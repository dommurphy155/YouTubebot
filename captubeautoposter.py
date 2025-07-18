import os
import json
import time
import asyncio
import random
import glob
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from moviepy.editor import VideoFileClip
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

UK_TZ = ZoneInfo("Europe/London")
CATEGORIES = [
    {"name": "funny", "min_sec": 5, "max_sec": 13},
    {"name": "motivational", "min_sec": 15, "max_sec": 30},
    {"name": "storytime", "min_sec": 20, "max_sec": 60},
    {"name": "trending1", "min_sec": 15, "max_sec": 30},
    {"name": "trending2", "min_sec": 15, "max_sec": 30},
]
POST_INTERVALS = [9 * 3600, 12 * 3600, 15 * 3600, 18 * 3600, 21 * 3600]
STATE_FILE = "poster_state.json"
TEMP_DIR = "/tmp"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_ADMIN_ID = int(os.environ.get("TELEGRAM_ADMIN_ID", "0"))

last_post_info = {"category": None, "timestamp": None}
def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump(last_post_info, f)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            last = json.load(f)
            last_post_info.update(last)

def cleanup_temp_files(age_seconds=86400):
    cutoff = time.time() - age_seconds
    for f in glob.glob(f"{TEMP_DIR}/video_*"):
        if os.path.getmtime(f) < cutoff:
            try:
                os.remove(f)
            except OSError:
                pass

def log(msg):
    ts = datetime.now(UK_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

async def with_retry(func, *args, retries=5, base_delay=2, **kwargs):
    for i in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            log(f"Retry {i+1}/{retries} for {func.__name__}: {e}")
            await asyncio.sleep(base_delay * (2 ** i))
    raise RuntimeError(f"{func.__name__} failed after {retries} retries")

def ai_optimize_script(category_name):
    text = f"Tune-in for next trending {category_name} clip!"
    return {"text": text, "use_tts": random.choice([True, False])}

async def generate_script(category):
    return ai_optimize_script(category["name"])

async def solve_captcha(page):
    log("🔐 CAPTCHA solving placeholder called")
    return False

async def click_fallback(page, selectors, **kwargs):
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            return await el.click(**kwargs)
    raise PlaywrightTimeout(f"No clickable element found in {selectors}")

async def fill_fallback(page, selectors, text, **kwargs):
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            return await el.fill(text, **kwargs)
    raise PlaywrightTimeout(f"No fillable element found in {selectors}")

async def capcut_create_video(page, script_data, category):
    try:
        log(f"Creating video: {category['name']}")
        await with_retry(page.goto, "https://www.capcut.com/", timeout=30000)
        await with_retry(page.wait_for_load_state, "networkidle", timeout=30000)

        await click_fallback(page, ["button:has-text('Login')", "role=button[name='Login']"])
        await fill_fallback(page, ["input[type=email]"], os.environ["CAPCUT_EMAIL"])
        await click_fallback(page, ["button:has-text('Next')"])
        await page.wait_for_timeout(1500)
        await fill_fallback(page, ["input[type=password]"], os.environ["CAPCUT_PASSWORD"])
        await click_fallback(page, ["button:has-text('Sign In')"])
        await with_retry(page.wait_for_selector, "button:has-text('Create Project')", timeout=30000)
        await click_fallback(page, ["button:has-text('Create Project')"])

        await page.wait_for_timeout(2000)
        await click_fallback(page, ["button#script-to-video-btn", "button:has-text('Script to Video')"])
        await fill_fallback(page, ["textarea#script-input"], script_data["text"])
        if script_data["use_tts"]:
            await click_fallback(page, ["button#tts-toggle", "button:has-text('TTS')"])
            await page.select_option("select#voice-select", "en-US-Natural")
        await click_fallback(page, ["button#generate-video", "button:has-text('Generate')"])
        await page.wait_for_timeout(10000)

        await click_fallback(page, ["button:has-text('Export')"])
        async with page.expect_download() as info:
            await click_fallback(page, ["button:has-text('Download')"])
        dl = await info.value
        path = f"{TEMP_DIR}/video_{category['name']}_{int(time.time())}.mp4"
        await dl.save_as(path)

        clip = VideoFileClip(path)
        if clip.duration > category["max_sec"]:
            trimmed = path.replace(".mp4", "_trimmed.mp4")
            clip.subclip(0, category["max_sec"]).write_videofile(trimmed)
            clip.close()
            log(f"Trimmed video to {category['max_sec']}s")
            return trimmed
        clip.close()
        return path
    except Exception:
        log(traceback.format_exc())
        return None

async def youtube_upload_video(page, video_path, category, title, description):
    try:
        await with_retry(page.goto, "https://www.youtube.com/upload", timeout=30000)
        if await page.query_selector("input[type=email]"):
            await fill_fallback(page, ["input[type=email]"], os.environ["YOUTUBE_EMAIL"])
            await click_fallback(page, ["button:has-text('Next')"])
            await asyncio.sleep(2)
            await fill_fallback(page, ["input[type=password]"], os.environ["YOUTUBE_PASSWORD"])
            await click_fallback(page, ["button:has-text('Next')"])
            await with_retry(page.wait_for_load_state, "networkidle")

            if await page.query_selector("img[alt='CAPTCHA']"):
                solved = await solve_captcha(page)
                if not solved:
                    Bot(TELEGRAM_TOKEN).send_message(TELEGRAM_ADMIN_ID, f"CAPTCHA on YouTube upload for {category['name']}")
                    return False

        input_file = await page.query_selector("input[type=file]")
        if not input_file:
            log("❌ No file input on YouTube upload")
            return False
        await input_file.set_input_files(video_path)

        await with_retry(page.wait_for_selector, "#textbox[aria-label='Title']", timeout=30000)
        await page.fill("#textbox[aria-label='Title']", title)
        await page.fill("#textbox[aria-label='Description']", description)

        await click_fallback(page, ["tp-yt-paper-radio-button[name='NOT_MADE_FOR_KIDS']"])
        for _ in range(3):
            await click_fallback(page, ["ytcp-button:has-text('Next')"])
            await asyncio.sleep(2)
        await click_fallback(page, ["tp-yt-paper-radio-button[name='PUBLIC']"])
        await click_fallback(page, ["ytcp-button:has-text('Publish')"])
        await with_retry(page.wait_for_selector, "text=Video published", timeout=60000)
        log("✅ Upload successful")
        return True
    except Exception:
        log(traceback.format_exc())
        return False

def generate_title_description(category, script_data):
    base = {
        "funny": "😂 Funny Clip",
        "motivational": "💪 Motivation Boost",
        "storytime": "📖 Story Time",
        "trending1": "🔥 Trend #1",
        "trending2": "🔥 Trend #2",
    }
    title = f"{base.get(category['name'], 'Short Video')} - {script_data['text'][:30].strip()}"
    return title, f"{title}\n\n#Shorts #AI"

async def post_one_video(playwright, category):
    cleanup_temp_files()
    browser = await playwright.chromium.launch(headless=True)
    ctx = await browser.new_context(accept_downloads=True)
    page = await ctx.new_page()
    try:
        script_data = await generate_script(category)
        video = await capcut_create_video(page, script_data, category)
        if not video:
            log("❌ Video creation failed")
            return False
        title, desc = generate_title_description(category, script_data)
        ok = await youtube_upload_video(page, video, category, title, desc)
        if ok:
            last_post_info.update({
                "category": category["name"],
                "timestamp": datetime.now(UK_TZ).isoformat()
            })
            save_state()
        return ok
    finally:
        await ctx.close()
        await browser.close()

async def scheduler():
    load_state()
    while True:
        now = datetime.now(UK_TZ)
        sec = now.hour * 3600 + now.minute * 60 + now.second
        idx = min(range(len(POST_INTERVALS)), key=lambda i: abs(POST_INTERVALS[i] - sec))
        cat = CATEGORIES[idx]
        log(f"Scheduled post: {cat['name']}")
        async with async_playwright() as pw:
            res = await post_one_video(pw, cat)
            log(f"Result: {res} for {cat['name']}")
        nxt = datetime.combine(now.date(), datetime.min.time(), tzinfo=UK_TZ) + timedelta(seconds=POST_INTERVALS[(idx + 1) % len(POST_INTERVALS)])
        if nxt <= now:
            nxt += timedelta(days=1)
        sleep = (nxt - now).total_seconds()
        log(f"Next run at {nxt.isoformat()}")
        await asyncio.sleep(sleep)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = last_post_info.get("category")
    ts = last_post_info.get("timestamp")
    text = "No videos posted yet." if not ts else f"Last: {cat} at {ts}"
    await update.message.reply_text(text)

async def postnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != TELEGRAM_ADMIN_ID:
        return await update.message.reply_text("❌ Unauthorized")
    idx = random.randrange(len(CATEGORIES))
    cat = CATEGORIES[idx]
    await update.message.reply_text(f"🔁 Manual trigger: {cat['name']}")
    async with async_playwright() as pw:
        ok = await post_one_video(pw, cat)
    await update.message.reply_text("✅ Success" if ok else "❌ Failed")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != TELEGRAM_ADMIN_ID:
        return await update.message.reply_text("❌ Unauthorized")
    log("Shutdown signal via Telegram")
    for t in asyncio.all_tasks():
        if t is not asyncio.current_task():
            t.cancel()
    await context.application.stop()

async def main():
    needed = ["CAPCUT_EMAIL", "CAPCUT_PASSWORD", "YOUTUBE_EMAIL", "YOUTUBE_PASSWORD", "TELEGRAM_TOKEN"]
    missing = [v for v in needed if not os.environ.get(v)]
    if missing:
        print("❗ Missing env:", ", ".join(missing))
        return
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("postnow", postnow))
    app.add_handler(CommandHandler("stop", stop_cmd))
    log("Bot starting, scheduler engaged")
    await asyncio.gather(app.run_polling(), scheduler())

if __name__ == "__main__":
    asyncio.run(main())

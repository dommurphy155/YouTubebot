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

POST_INTERVALS = [9 * 3600, 12 * 3600, 15 * 3600, 18 * 3600]

STATE_FILE = "poster_state.json"
TEMP_DIR = "/tmp"
USER_DATA_DIR = "./playwright_userdata"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_ADMIN_ID = int(os.environ.get("TELEGRAM_ADMIN_ID", "0"))

last_post_info = {"category": None, "timestamp": None}

STEALTH_JS = """
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'NVIDIA Corporation';
        if (parameter === 37446) return 'NVIDIA GeForce RTX 3080';
        return getParameter.call(this, parameter);
    };
}
"""

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/115.0.0.0 Safari/537.36"
)

VIEWPORT = {"width": 1366, "height": 768}

def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(last_post_info, f)
    except Exception as e:
        log(f"Failed to save state: {e}")

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                last_post_info.update(json.load(f))
        except Exception as e:
            log(f"Failed to load state: {e}")

def cleanup_temp_files(age_seconds=86400):
    cutoff = time.time() - age_seconds
    for f in glob.glob(f"{TEMP_DIR}/video_*"):
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
                log(f"Deleted temp file: {f}")
        except Exception:
            pass

def log(msg: str):
    ts = datetime.now(UK_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

async def with_retry(func, *args, retries=3, base_delay=1, **kwargs):
    for i in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            delay = base_delay * (2 ** i) + random.uniform(0, 0.5)
            log(f"Retry {i+1}/{retries} for {func.__name__}: {e}")
            await asyncio.sleep(delay)
    raise RuntimeError(f"{func.__name__} failed after {retries} retries")

def ai_optimize_script(name):
    return {"text": f"Check out this {name} clip!", "use_tts": random.choice([True, False])}

async def generate_script(category):
    return ai_optimize_script(category["name"])

async def solve_captcha(page):
    log("CAPTCHA solving not implemented")
    return False

async def click_fallback(page, selectors, **kwargs):
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            return await el.click(**kwargs)
    raise PlaywrightTimeout(f"No clickable element found for selectors: {selectors}")

async def fill_fallback(page, selectors, text, **kwargs):
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            return await el.fill(text, **kwargs)
    raise PlaywrightTimeout(f"No fillable element found for selectors: {selectors}")

async def capcut_create_video(page, script_data, category):
    try:
        log(f"Creating video for category: {category['name']}")
        await with_retry(page.goto, "https://www.capcut.com/", timeout=30000)
        await with_retry(page.wait_for_load_state, "networkidle", timeout=30000)

        login_btn = await page.query_selector("button:has-text('Login')")
        if login_btn:
            await click_fallback(page, ["button:has-text('Login')"])
            await fill_fallback(page, ["input[type=email]"], os.environ["CAPCUT_EMAIL"])
            await click_fallback(page, ["button:has-text('Next')"])
            await asyncio.sleep(1)
            await fill_fallback(page, ["input[type=password]"], os.environ["CAPCUT_PASSWORD"])
            await click_fallback(page, ["button:has-text('Sign In')"])
            await with_retry(page.wait_for_selector, "button:has-text('Create Project')", timeout=15000)

        await click_fallback(page, ["button:has-text('Create Project')"])
        await asyncio.sleep(1)

        await click_fallback(page, ["button#script-to-video-btn"])
        await fill_fallback(page, ["textarea#script-input"], script_data["text"])

        if script_data["use_tts"]:
            await click_fallback(page, ["button#tts-toggle"])
            await page.select_option("select#voice-select", "en-US-Natural")

        await click_fallback(page, ["button#generate-video"])
        await asyncio.sleep(7000)

        await click_fallback(page, ["button:has-text('Export')"])
        async with page.expect_download() as info:
            await click_fallback(page, ["button:has-text('Download')"])
        dl = await info.value
        path = f"{TEMP_DIR}/video_{category['name']}_{int(time.time())}.mp4"
        await dl.save_as(path)

        clip = VideoFileClip(path)
        if clip.duration > category["max_sec"]:
            trimmed = path.replace(".mp4", "_trimmed.mp4")
            clip.subclip(0, category["max_sec"]).write_videofile(trimmed, audio_codec="aac", logger=None)
            clip.close()
            log(f"Trimmed video to {category['max_sec']} seconds")
            return trimmed
        clip.close()
        return path
    except Exception:
        log(traceback.format_exc())
        return None

async def youtube_upload_video(page, video_path, category, title, description):
    try:
        log(f"Uploading video for category: {category['name']}")
        await with_retry(page.goto, "https://www.youtube.com/upload", timeout=30000)

        email_input = await page.query_selector("input[type=email]")
        if email_input:
            await fill_fallback(page, ["input[type=email]"], os.environ["YOUTUBE_EMAIL"])
            await click_fallback(page, ["button:has-text('Next')"])
            await asyncio.sleep(1.5)
            await fill_fallback(page, ["input[type=password]"], os.environ["YOUTUBE_PASSWORD"])
            await click_fallback(page, ["button:has-text('Next')"])
            await with_retry(page.wait_for_load_state, "networkidle", timeout=30000)

            captcha_img = await page.query_selector("img[alt='CAPTCHA']")
            if captcha_img and not await solve_captcha(page):
                Bot(TELEGRAM_TOKEN).send_message(TELEGRAM_ADMIN_ID, f"CAPTCHA on YouTube for {category['name']}")
                return False

        input_file = await page.query_selector("input[type=file]")
        if not input_file:
            log("No file input found for upload")
            return False

        await input_file.set_input_files(video_path)

        await with_retry(page.wait_for_selector, "#textbox[aria-label='Title']", timeout=30000)
        await page.fill("#textbox[aria-label='Title']", title)
        await page.fill("#textbox[aria-label='Description']", description)

        await click_fallback(page, ["tp-yt-paper-radio-button[name='NOT_MADE_FOR_KIDS']"])

        for _ in range(3):
            await click_fallback(page, ["ytcp-button:has-text('Next')"])
            await asyncio.sleep(1.5)

        await click_fallback(page, ["tp-yt-paper-radio-button[name='PUBLIC']"])
        await click_fallback(page, ["ytcp-button:has-text('Publish')"])

        await with_retry(page.wait_for_selector, "text=Video published", timeout=30000)
        log("Upload successful")
        return True
    except Exception:
        log(traceback.format_exc())
        return False

def generate_title_description(category, script_data):
    base_titles = {
        "funny": "Funny Clip",
        "motivational": "Motivation Boost",
        "storytime": "Story Time",
        "trending1": "Trend #1",
        "trending2": "Trend #2",
    }
    title = f"{base_titles.get(category['name'], 'Short')} - {script_data['text'][:30].strip()}"
    description = f"{title}\n\n#Shorts #AI"
    return title, description

async def post_one_video(playwright, category, headless=True):
    cleanup_temp_files()
    browser = await playwright.chromium.launch_persistent_context(
        USER_DATA_DIR,
        headless=headless,
        accept_downloads=True,
        viewport=VIEWPORT,
        user_agent=USER_AGENT,
        locale="en-US",
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-zygote",
            "--single-process",
            "--disable-gpu",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=site-per-process",  # minor perf gain
        ],
    )
    browser.add_init_script(STEALTH_JS)

    page = await browser.new_page()
    try:
        script_data = await generate_script(category)
        video_path = await capcut_create_video(page, script_data, category)
        if not video_path:
            log("Video creation failed")
            return False

        title, description = generate_title_description(category, script_data)
        success = await youtube_upload_video(page, video_path, category, title, description)
        if success:
            last_post_info.update({
                "category": category["name"],
                "timestamp": datetime.now(UK_TZ).isoformat()
            })
            save_state()
        return success
    finally:
        await browser.close()

async def scheduler():
    load_state()
    while True:
        now = datetime.now(UK_TZ)
        seconds_today = now.hour * 3600 + now.minute * 60 + now.second
        idx = min(range(len(POST_INTERVALS)), key=lambda i: abs(POST_INTERVALS[i] - seconds_today))
        category = CATEGORIES[idx]

        log(f"Scheduled post starting: {category['name']}")
        async with async_playwright() as pw:
            try:
                result = await post_one_video(pw, category, headless=True)
            except Exception:
                log(traceback.format_exc())
                result = False
        log(f"Scheduled post result: {'Success' if result else 'Fail'}")

        next_post_time = datetime.combine(now.date(), datetime.min.time(), tzinfo=UK_TZ) + timedelta(seconds=POST_INTERVALS[(idx + 1) % len(POST_INTERVALS)])
        if next_post_time <= now:
            next_post_time += timedelta(days=1)

        sleep_sec = (next_post_time - now).total_seconds()
        log(f"Sleeping {int(sleep_sec)} seconds until next scheduled post")
        await asyncio.sleep(sleep_sec)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not last_post_info.get("timestamp"):
        await update.message.reply_text("No videos posted yet.")
        return
    await update.message.reply_text(f"Last video posted:\nCategory: {last_post_info['category']}\nAt: {last_post_info['timestamp']}")

async def postnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != TELEGRAM_ADMIN_ID:
        await update.message.reply_text("Unauthorized")
        return
    category = random.choice(CATEGORIES)
    await update.message.reply_text(f"Manual post requested for category: {category['name']}")
    async with async_playwright() as pw:
        try:
            success = await post_one_video(pw, category, headless=False)
        except Exception:
            log(traceback.format_exc())
            success = False
    await update.message.reply_text("Success" if success else "Failed")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != TELEGRAM_ADMIN_ID:
        await update.message.reply_text("Unauthorized")
        return
    log("Shutdown command received")
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()
    await context.application.stop()

async def start_scheduler(app):
    app.create_task(scheduler())

def main():
    required_vars = ["CAPCUT_EMAIL", "CAPCUT_PASSWORD", "YOUTUBE_EMAIL", "YOUTUBE_PASSWORD", "TELEGRAM_TOKEN", "TELEGRAM_ADMIN_ID"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("postnow", postnow))
    app.add_handler(CommandHandler("stop", stop_cmd))

    async def on_startup(app):
        await start_scheduler(app)

    app.post_init = on_startup

    log("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()

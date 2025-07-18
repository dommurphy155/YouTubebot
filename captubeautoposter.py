import os
import json
import time
import asyncio
import random
import glob
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeAudioClip, CompositeVideoClip,
    TextClip, concatenate_videoclips
)
from moviepy.video.fx.resize import resize
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import pyttsx3
import tempfile
import shutil

UK_TZ = ZoneInfo("Europe/London")

CATEGORIES = [
    {"name": "funny", "min_sec": 15, "max_sec": 30},
    {"name": "motivational", "min_sec": 15, "max_sec": 30},
    {"name": "storytime", "min_sec": 15, "max_sec": 30},
    {"name": "trending1", "min_sec": 15, "max_sec": 30},
    {"name": "trending2", "min_sec": 15, "max_sec": 30},
]

POST_INTERVALS = [9 * 3600, 12 * 3600, 15 * 3600, 18 * 3600]

STATE_FILE = "poster_state.json"
TEMP_DIR = tempfile.gettempdir()
USER_DATA_DIR = "./playwright_userdata"
CLIPS_DIR = "./clips"
MUSIC_DIR = "./music"

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

def log(msg: str):
    ts = datetime.now(UK_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

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
    for f in glob.glob(f"{TEMP_DIR}/audio_*"):
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
                log(f"Deleted temp file: {f}")
        except Exception:
            pass

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
    base_phrases = {
        "funny": [
            "Here's a hilarious moment for you!",
            "Laugh out loud with this clip!",
            "Comedy time — enjoy!",
        ],
        "motivational": [
            "Boost your day with this!",
            "Stay motivated with this clip!",
            "Power through your day!",
        ],
        "storytime": [
            "Here's a quick story for you.",
            "Sit back and enjoy this tale.",
            "Storytime begins now!",
        ],
        "trending1": [
            "Check out this trending hit!",
            "What's hot right now!",
            "Trending vibes coming your way.",
        ],
        "trending2": [
            "Don't miss this trend!",
            "Latest trending clip!",
            "Catch this trend before anyone else!",
        ],
    }
    phrases = base_phrases.get(name, ["Enjoy this clip!"])
    text = random.choice(phrases)
    use_tts = True
    return {"text": text, "use_tts": use_tts}

async def generate_script(category):
    return ai_optimize_script(category["name"])

def select_random_clip(category):
    all_clips = glob.glob(os.path.join(CLIPS_DIR, "*.mp4"))
    if not all_clips:
        log("No clips found in clips directory.")
        return None
    random.shuffle(all_clips)
    for clip_path in all_clips:
        try:
            clip = VideoFileClip(clip_path)
            duration = clip.duration
            clip.close()
            if category["min_sec"] <= duration <= category["max_sec"]:
                return clip_path
        except Exception as e:
            log(f"Error reading clip {clip_path}: {e}")
    return random.choice(all_clips)

def select_random_music():
    all_music = glob.glob(os.path.join(MUSIC_DIR, "*.mp3")) + glob.glob(os.path.join(MUSIC_DIR, "*.wav"))
    if not all_music:
        log("No music tracks found in music directory.")
        return None
    return random.choice(all_music)

def generate_tts_audio(text, output_path):
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    engine.save_to_file(text, output_path)
    engine.runAndWait()

def compose_final_video(clip_path, tts_audio_path, bg_music_path, category):
    video_clip = VideoFileClip(clip_path)

    target_width, target_height = 1080, 1920
    video_clip = video_clip.resize(height=target_height)
    if video_clip.w > target_width:
        x1 = (video_clip.w - target_width) // 2
        video_clip = video_clip.crop(x1=x1, width=target_width)
    elif video_clip.w < target_width:
        video_clip = video_clip.margin(left=(target_width - video_clip.w)//2,
                                       right=(target_width - video_clip.w)//2,
                                       color=(0,0,0))

    if video_clip.duration > category["max_sec"]:
        video_clip = video_clip.subclip(0, category["max_sec"])
    elif video_clip.duration < category["min_sec"]:
        pad_duration = category["min_sec"] - video_clip.duration
        last_frame = video_clip.to_ImageClip(video_clip.duration-0.1).set_duration(pad_duration)
        video_clip = concatenate_videoclips([video_clip, last_frame])

    text_clip = TextClip(
        last_post_info.get("script_text", ""),
        fontsize=50,
        font='Arial-Bold',
        color='white',
        stroke_color='black',
        stroke_width=2,
        method='caption',
        size=(target_width - 100, None),
    ).set_duration(video_clip.duration).set_position(("center", "bottom")).margin(bottom=40, opacity=0)

    audio_clips = []

    if os.path.exists(tts_audio_path):
        tts_audio = AudioFileClip(tts_audio_path).volumex(1.0)
        audio_clips.append(tts_audio)

    if bg_music_path and os.path.exists(bg_music_path):
        bg_audio = AudioFileClip(bg_music_path).volumex(0.15)
        audio_clips.append(bg_audio)

    if audio_clips:
        composite_audio = CompositeAudioClip(audio_clips)
        composite_audio = composite_audio.set_duration(video_clip.duration)
    else:
        composite_audio = None

    video_with_text = CompositeVideoClip([video_clip, text_clip])
    if composite_audio:
        final_video = video_with_text.set_audio(composite_audio)
    else:
        final_video = video_with_text.set_audio(video_clip.audio)

    output_path = os.path.join(TEMP_DIR, f"video_{category['name']}_{int(time.time())}.mp4")
    final_video.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        preset="fast",
        ffmpeg_params=["-profile:v", "baseline", "-level", "3.0"],
        verbose=False,
        logger=None,
    )
    video_clip.close()
    video_with_text.close()
    final_video.close()
    for ac in audio_clips:
        ac.close()
    return output_path

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
            "--disable-features=site-per-process",
        ],
    )
    browser.add_init_script(STEALTH_JS)

    page = await browser.new_page()
    try:
        script_data = await generate_script(category)
        last_post_info["script_text"] = script_data["text"]

        clip_path = select_random_clip(category)
        if not clip_path:
            log("No suitable clip found, aborting post.")
            return False

        music_path = select_random_music()
        tts_audio_path = os.path.join(TEMP_DIR, f"audio_tts_{int(time.time())}.mp3")
        generate_tts_audio(script_data["text"], tts_audio_path)

        final_video_path = compose_final_video(clip_path, tts_audio_path, music_path, category)
        if not final_video_path or not os.path.exists(final_video_path):
            log("Final video composition failed.")
            return False

        title, description = generate_title_description(category, script_data)

        success = await youtube_upload_video(page, final_video_path, category, title, description)
        if success:
            last_post_info.update({
                "category": category["name"],
                "timestamp": datetime.now(UK_TZ).isoformat()
            })
            save_state()
        return success
    finally:
        await browser.close()
        try:
            if os.path.exists(tts_audio_path):
                os.remove(tts_audio_path)
            if os.path.exists(final_video_path):
                os.remove(final_video_path)
        except Exception:
            pass

async def youtube_upload_video(page, video_path, category, title, description):
    try:
        log(f"Uploading video for category: {category['name']}")
        await with_retry(page.goto, "https://www.youtube.com/upload", timeout=30000)

        # Skip login steps because we rely on persistent context logged in session

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
    missing = []
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_TOKEN")
    if not TELEGRAM_ADMIN_ID or TELEGRAM_ADMIN_ID == 0:
        missing.append("TELEGRAM_ADMIN_ID")
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

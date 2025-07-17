import os
import asyncio
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Constants and Configurations
CATEGORIES = [
    {"name": "funny", "min_sec": 5, "max_sec": 13},
    {"name": "motivational", "min_sec": 15, "max_sec": 30},
    {"name": "storytime", "min_sec": 20, "max_sec": 60},
    {"name": "trending1", "min_sec": 15, "max_sec": 30},
    {"name": "trending2", "min_sec": 15, "max_sec": 30},
]
POST_INTERVALS = [9*3600, 12*3600, 15*3600, 18*3600, 21*3600]  # seconds from midnight UTC

UK_TZ = ZoneInfo("Europe/London")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_ADMIN_ID = int(os.environ.get("TELEGRAM_ADMIN_ID", "0"))

# Bot state tracking
last_post_info = {"category": None, "timestamp": None}

def log(msg: str):
    now_uk = datetime.now(UK_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{now_uk}] {msg}")

async def generate_script(category):
    # Placeholder script generator - extend as needed
    if category["name"] == "funny":
        return "Why don't scientists trust atoms? Because they make up everything!"
    elif category["name"] == "motivational":
        return "Push yourself, because no one else is going to do it for you."
    elif category["name"] == "storytime":
        return "Once upon a time, in a land far away, a hero rose against all odds."
    else:
        return f"Check out this trending topic for {category['name']}!"

async def capcut_create_video(page, script_text, category):
    log(f"Starting CapCut video creation for category: {category['name']}")
    await page.goto("https://www.capcut.com/")
    await page.wait_for_load_state("networkidle")

    await page.click("text=Login")
    await page.wait_for_selector("input[type=email]")
    await page.fill("input[type=email]", os.environ["CAPCUT_EMAIL"])
    await page.click("button:has-text('Next')")
    await page.wait_for_timeout(1500)
    await page.fill("input[type=password]", os.environ["CAPCUT_PASSWORD"])
    await page.click("button:has-text('Sign In')")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector("text=Create Project", timeout=30000)

    await page.click("text=Create Project")
    await page.wait_for_timeout(2000)

    # TODO: Add video creation steps based on CapCut UI changes

    await page.click("text=Export")
    export_done = False
    for _ in range(60):
        if await page.query_selector("text=Download") is not None:
            export_done = True
            break
        await asyncio.sleep(2)
    if not export_done:
        log("Export timed out.")
        return None

    await page.click("text=Download")
    await page.wait_for_timeout(10000)

    downloaded_file_path = "/root/Downloads/latest_capcut_export.mp4"  # adjust as needed
    log(f"Video exported and downloaded at: {downloaded_file_path}")
    return downloaded_file_path

async def youtube_upload_video(page, video_path, category, title, description):
    log(f"Starting YouTube upload for category: {category['name']}")
    await page.goto("https://www.youtube.com/upload")
    await page.wait_for_load_state("networkidle")

    if await page.query_selector("input[type=email]") is not None:
        await page.fill("input[type=email]", os.environ["YOUTUBE_EMAIL"])
        await page.click("button:has-text('Next')")
        await page.wait_for_timeout(2000)
        await page.fill("input[type=password]", os.environ["YOUTUBE_PASSWORD"])
        await page.click("button:has-text('Next')")
        await page.wait_for_load_state("networkidle")

    input_file = await page.query_selector("input[type=file]")
    await input_file.set_input_files(video_path)
    await asyncio.sleep(5)

    title_input = await page.query_selector("#textbox[aria-label='Title']")
    if title_input:
        await title_input.fill(title)

    desc_input = await page.query_selector("#textbox[aria-label='Description']")
    if desc_input:
        await desc_input.fill(description)

    await page.click("tp-yt-paper-radio-button[name='NOT_MADE_FOR_KIDS']")
    for _ in range(3):
        await page.click("ytcp-button:has-text('Next')")
        await asyncio.sleep(2)

    await page.click("tp-yt-paper-radio-button[name='PUBLIC']")
    await page.click("ytcp-button:has-text('Publish')")
    await asyncio.sleep(5)

    log("Upload completed.")
    return True

def generate_title_description(category, script_text):
    base_title = {
        "funny": "😂 Hilarious Short Clip!",
        "motivational": "💪 Daily Motivation Boost",
        "storytime": "📖 Story Time: Listen Up!",
        "trending1": "🔥 Trending Now #1",
        "trending2": "🔥 Trending Now #2",
    }
    title = base_title.get(category["name"], "Awesome Short Video")
    snippet = script_text[:40].strip().replace("\n", " ")
    title += f" - {snippet}..."
    description = f"{title} \n\n#Shorts #Trending #AI"
    return title, description

async def post_one_video(playwright, category):
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(accept_downloads=True)
    page = await context.new_page()

    try:
        script_text = await generate_script(category)
        video_path = await capcut_create_video(page, script_text, category)
        if not video_path:
            log("Video creation failed.")
            return False

        title, description = generate_title_description(category, script_text)
        success = await youtube_upload_video(page, video_path, category, title, description)
        if success:
            last_post_info["category"] = category["name"]
            last_post_info["timestamp"] = datetime.now(tz=UK_TZ)
        return success
    finally:
        await context.close()
        await browser.close()

async def scheduler():
    log("Starting scheduler loop...")
    while True:
        now = datetime.utcnow().replace(tzinfo=timezone.utc).astimezone(UK_TZ)
        time_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
        next_index = min(range(len(POST_INTERVALS)), key=lambda i: abs(POST_INTERVALS[i] - time_since_midnight))
        category = CATEGORIES[next_index]

        async with async_playwright() as playwright:
            success = await post_one_video(playwright, category)
            if success:
                log(f"Posted {category['name']} video successfully.")
            else:
                log(f"Failed to post {category['name']} video.")

        next_post_time = datetime.combine(now.date(), datetime.min.time(), tzinfo=UK_TZ) + timedelta(seconds=POST_INTERVALS[(next_index + 1) % len(POST_INTERVALS)])
        sleep_seconds = (next_post_time - now).total_seconds()
        if sleep_seconds < 0:
            sleep_seconds += 86400
        log(f"Sleeping for {int(sleep_seconds)} seconds until next post.")
        await asyncio.sleep(sleep_seconds)

# Telegram Bot Handlers

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if last_post_info["timestamp"] is None:
        await update.message.reply_text("No videos posted yet.")
        return
    last_time_str = last_post_info["timestamp"].astimezone(UK_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    next_idx = (CATEGORIES.index({"name": last_post_info["category"], "min_sec":0, "max_sec":0}) + 1) % len(CATEGORIES) if last_post_info["category"] in [c["name"] for c in CATEGORIES] else 0
    next_post_time = datetime.now(tz=UK_TZ).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=POST_INTERVALS[next_idx])
    next_cat = CATEGORIES[next_idx]["name"]

    msg = (f"Last posted video: {last_post_info['category']}\n"
           f"Timestamp (UK time): {last_time_str}\n"
           f"Next scheduled post: {next_post_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
           f"Next category: {next_cat}")
    await update.message.reply_text(msg)

async def postnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if TELEGRAM_ADMIN_ID != 0 and user_id != TELEGRAM_ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return

    now = datetime.utcnow().replace(tzinfo=timezone.utc).astimezone(UK_TZ)
    time_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
    next_index = min(range(len(POST_INTERVALS)), key=lambda i: abs(POST_INTERVALS[i] - time_since_midnight))
    category = CATEGORIES[next_index]

    await update.message.reply_text(f"Starting immediate post for category: {category['name']}")
    async with async_playwright() as playwright:
        success = await post_one_video(playwright, category)
        if success:
            await update.message.reply_text(f"Posted {category['name']} video successfully.")
        else:
            await update.message.reply_text(f"Failed to post {category['name']} video.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if TELEGRAM_ADMIN_ID != 0 and user_id != TELEGRAM_ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text("Stopping bot gracefully...")
    log("Stop command received, exiting...")
    # Properly stop all asyncio tasks
    asyncio.get_event_loop().stop()

async def main():
    # Check env vars
    required_vars = ["CAPCUT_EMAIL", "CAPCUT_PASSWORD", "YOUTUBE_EMAIL", "YOUTUBE_PASSWORD", "TELEGRAM_TOKEN"]
    missing = [v for v in required_vars if v not in os.environ]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        return

    app = ApplicationBuilder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("status", status))
    app.add_handler
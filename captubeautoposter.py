import os
import asyncio
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from moviepy.editor import VideoFileClip
import traceback
from tenacity import retry, stop_after_attempt, wait_fixed
from loguru import logger

# --- Config ---
CATEGORIES = [
    {"name": "funny", "min_sec": 5, "max_sec": 13},
    {"name": "motivational", "min_sec": 7, "max_sec": 15},
    {"name": "trending1", "min_sec": 6, "max_sec": 10},
]

POST_INTERVAL_MINUTES = 15
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_ADMIN_ID = int(os.environ.get("TELEGRAM_ADMIN_ID", "0"))

# --- Scheduler State ---
last_post_time = datetime.now(tz=timezone.utc) - timedelta(minutes=POST_INTERVAL_MINUTES)

# --- Stealth JavaScript ---
STEALTH_JS = """
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'NVIDIA Corporation';
        if (parameter === 37446) return 'NVIDIA GeForce GTX 1050';
        return getParameter(parameter);
    };
}
"""

# --- Core Bot Logic ---

@retry(stop=stop_after_attempt(5), wait=wait_fixed(10))
async def create_video(category_name):
    logger.info(f"Creating video: {category_name}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox", "--disable-setuid-sandbox",
            "--disable-dev-shm-usage", "--disable-gpu"
        ])
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        await page.add_init_script(STEALTH_JS)
        await page.goto("https://www.capcut.com", wait_until="load", timeout=60000)
        await asyncio.sleep(5)

        # Simulate navigation to login and video creation steps
        # Add your CapCut login + upload flow here
        logger.info(f"[{category_name}] Reached CapCut homepage.")

        await browser.close()

# --- Telegram Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("YouTube Shorts Bot online.")

async def force_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_post_time
    if update.effective_user.id != TELEGRAM_ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return
    last_post_time = datetime.now(tz=timezone.utc) - timedelta(minutes=POST_INTERVAL_MINUTES)
    await update.message.reply_text("Next post triggered.")

# --- Scheduler ---

async def scheduler_loop():
    global last_post_time
    while True:
        now = datetime.now(tz=timezone.utc)
        if (now - last_post_time) >= timedelta(minutes=POST_INTERVAL_MINUTES):
            category = random.choice(CATEGORIES)
            try:
                await create_video(category["name"])
                last_post_time = now
            except Exception as e:
                logger.error(f"Scheduler error: {str(e)}\n{traceback.format_exc()}")
        await asyncio.sleep(60)

# --- Main Entrypoint ---

async def main():
    logger.info("Bot starting, scheduler engaged")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("post", force_post))
    asyncio.create_task(scheduler_loop())
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")

import asyncio
import logging
import signal
import sys
import os
import subprocess
import random

import scraper
import editor
import uploader
import status

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Logger setup
logger = logging.getLogger("TelegramVideoBot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Bot control
running = True

# Environment variables (injected via systemd)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.critical("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set in environment.")
    sys.exit(1)

# yt-dlp binary path (inside venv)
YTDLP_PATH = "/home/ubuntu/YouTubebot/venv/bin/yt-dlp"

def handle_shutdown(signum, frame):
    global running
    running = False
    logger.info("Shutdown signal received.")

def update_ytdlp():
    try:
        result = subprocess.run([YTDLP_PATH, "-U"], capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            logger.info("yt-dlp updated successfully.")
        else:
            logger.warning(f"yt-dlp update failed: {result.stderr.strip()}")
    except Exception as e:
        logger.error(f"yt-dlp update exception: {e}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != TELEGRAM_CHAT_ID:
        return
    try:
        downloaded, editing, ready = status.count_videos()
        msg = (
            f"📊 *Bot Status*\n"
            f"🕒 Uptime: `{status.get_uptime()}`\n"
            f"⚙️ CPU: `{status.get_cpu_usage()}` | RAM: `{status.get_ram_usage()}` | Disk: `{status.get_disk_usage()}`\n"
            f"📈 Load (1/5/15m): `{status.get_system_load()}`\n"
            f"📥 Downloaded: `{downloaded}` | 🛠️ Editing: `{editing}` | ✅ Ready: `{ready}`\n"
            f"🎬 Edit progress: `{status.get_edit_progress()}`\n"
            f"📤 Next video at: `{status.get_next_schedule()}` (UK)\n"
            f"🔖 Version: `{status.get_bot_version()}`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /status command: {e}")

async def start_telegram_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("status", status_command))
    await app.initialize()
    await app.start()
    logger.info("Telegram bot started.")
    return app

async def stop_telegram_bot(app):
    await app.stop()
    await app.shutdown()
    logger.info("Telegram bot stopped.")

async def main_loop():
    update_ytdlp()
    app = await start_telegram_bot()

    try:
        while running:
            try:
                success = False
                for attempt in range(3):
                    result = await scraper.scrape_video()
                    if result:
                        success = True
                        break
                    logger.info(f"No suitable video on attempt {attempt + 1}/3, retrying...")

                if not success:
                    logger.warning("Max retries reached without suitable videos. Skipping cycle.")
                    continue

                video_path, title = result

                # Sanity check: double check video suitability
                if not editor.is_video_suitable(video_path):
                    logger.info(f"Video {video_path} deemed unsuitable by editor. Cleaning up.")
                    scraper.cleanup_files([video_path])
                    continue

                edited_path = await editor.edit_video(video_path)
                await uploader.upload_video(edited_path)

                scraper.cleanup_files([video_path, edited_path])

                # Post-upload cooldown
                await asyncio.sleep(random.uniform(10, 30))

            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(10)
    finally:
        await stop_telegram_bot(app)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        asyncio.run(main_loop())
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        sys.exit(1)

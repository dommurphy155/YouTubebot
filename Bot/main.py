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

logger = logging.getLogger("TelegramVideoBot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

running = True

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

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
    update_ytdlp()  # Auto-update yt-dlp on startup

    app = await start_telegram_bot()
    try:
        while running:
            try:
                result = await scraper.scrape_video()
                if not result:
                    await asyncio.sleep(60 + random.uniform(5, 15))  # add jitter to reduce blocking
                    continue
                video_path, _title = result  # unpack tuple, discard title if unused

                edited_path = await editor.edit_video(video_path)
                await uploader.upload_video(edited_path)
                scraper.cleanup_files([video_path, edited_path])

                # Random delay 10-30 seconds to avoid triggering Reddit rate limits
                await asyncio.sleep(random.uniform(10, 30))
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(30)  # pause on error before retry
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

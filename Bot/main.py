import asyncio
import logging
import signal
import sys
import os
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

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.critical("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID in environment. Exiting.")
    sys.exit(1)


def handle_shutdown(signum, frame):
    global running
    running = False
    logger.info("Shutdown signal received.")


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
    app = await start_telegram_bot()
    backoff_seconds = 10  # Initial backoff on failure
    try:
        while running:
            try:
                result = await scraper.scrape_video()
                if not result:
                    logger.info("No suitable video found; sleeping longer before retry.")
                    await asyncio.sleep(60 + random.randint(5, 15))
                    continue

                video_path, title = result
                logger.info(f"Processing video: {video_path} - Title: {title}")

                edited_path = await editor.edit_video(video_path)
                if not edited_path:
                    logger.error("Video editing failed, deleting original video.")
                    scraper.cleanup_files([video_path])
                    await asyncio.sleep(backoff_seconds)
                    continue

                upload_success = await uploader.upload_video(edited_path)
                if not upload_success:
                    logger.error("Video upload failed, deleting files.")
                    scraper.cleanup_files([video_path, edited_path])
                    await asyncio.sleep(backoff_seconds)
                    continue

                scraper.cleanup_files([video_path, edited_path])
                backoff_seconds = 10  # reset backoff after success
                await asyncio.sleep(10 + random.randint(0, 10))  # jittered sleep to avoid pattern

            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 300)  # exponential backoff cap at 5 minutes
    finally:
        await stop_telegram_bot(app)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        asyncio.run(main_loop())
    except Exception as e:
        logger.error(f"Bot crashed: {e}", exc_info=True)
        sys.exit(1)

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

# Async shutdown event
shutdown_event = asyncio.Event()

# Environment variables (injected via systemd)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.critical("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set in environment.")
    sys.exit(1)

# yt-dlp binary path (inside venv)
YTDLP_PATH = "/home/ubuntu/YouTubebot/venv/bin/yt-dlp"


def handle_shutdown(signum, frame):
    logger.info(f"Shutdown signal ({signum}) received.")
    shutdown_event.set()


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
        while not shutdown_event.is_set():
            try:
                result = None
                attempt = 0

                while not result and not shutdown_event.is_set():
                    attempt += 1
                    result = await scraper.scrape_video()
                    if not result:
                        logger.warning(f"No suitable videos found. Attempt #{attempt}")
                        await asyncio.sleep(5)

                if shutdown_event.is_set():
                    logger.info("Shutdown requested before processing video.")
                    return

                video_path, title = result

                if not editor.is_video_suitable(video_path):
                    logger.info(f"Video {video_path} deemed unsuitable by editor. Cleaning up.")
                    scraper.cleanup_files([video_path])
                    continue

                edited_path = await editor.edit_video(video_path)
                await uploader.upload_video(edited_path)

                scraper.cleanup_files([video_path, edited_path])

                for _ in range(int(random.uniform(10, 30))):
                    if shutdown_event.is_set():
                        logger.info("Shutdown requested during cooldown. Exiting main loop.")
                        return
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Main loop error: {e}")
                for _ in range(10):
                    if shutdown_event.is_set():
                        logger.info("Shutdown requested during error sleep. Exiting.")
                        return
                    await asyncio.sleep(1)
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

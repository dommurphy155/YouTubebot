import asyncio
import logging
import signal
import sys
import os
import subprocess
import random
import traceback

import scraper
import editor
import uploader
import status

from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Logging ---
logger = logging.getLogger("TelegramVideoBot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

shutdown_event = asyncio.Event()

# --- Environment ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.critical("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set in environment.")
    sys.exit(1)

alert_bot = Bot(token=TELEGRAM_TOKEN)
YTDLP_PATH = "/home/ubuntu/YouTubebot/venv/bin/yt-dlp"

# --- Graceful Shutdown ---
def handle_shutdown(signum, frame):
    logger.info(f"Shutdown signal ({signum}) received.")
    shutdown_event.set()

# --- yt-dlp Updater ---
def update_ytdlp():
    try:
        result = subprocess.run([YTDLP_PATH, "-U"], capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            logger.info("yt-dlp updated successfully.")
        else:
            logger.warning(f"yt-dlp update failed: {result.stderr.strip()}")
    except Exception as e:
        logger.error(f"yt-dlp update exception: {e}")

# --- Telegram Alert Wrapper ---
async def send_alert_message(text: str):
    try:
        await alert_bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Failed to send alert message: {e}")

# --- Telegram Commands ---
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
        logger.error(f"/status error: {e}")

async def send_startup_alert():
    msg = (
        f"🚀 *Bot Startup Alert*\n\n"
        f"🕒 Uptime: `{status.get_uptime()}`\n"
        f"💻 CPU: `{status.get_cpu_usage()}`\n"
        f"🧠 RAM: `{status.get_ram_usage()}`\n"
        f"💾 Disk: `{status.get_disk_usage()}`\n"
        f"📉 Load: `{status.get_system_load()}`\n"
        f"📦 Version: `{status.get_bot_version()}`\n"
    )
    await send_alert_message(msg)

# --- Telegram Bot Lifecycle ---
async def start_telegram_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("status", status_command))
    await app.initialize()
    await app.start()
    logger.info("Telegram bot started.")
    await send_startup_alert()
    return app

async def stop_telegram_bot(app):
    await app.stop()
    await app.shutdown()
    logger.info("Telegram bot stopped.")

# --- Core Loop ---
async def main_loop():
    update_ytdlp()
    app = await start_telegram_bot()

    try:
        while not shutdown_event.is_set():
            try:
                result = None
                attempts = 0
                while not result and not shutdown_event.is_set():
                    attempts += 1
                    result = await scraper.scrape_video()
                    if not result:
                        logger.warning(f"No valid video found. Retry #{attempts}")
                        await asyncio.sleep(min(1 + attempts * 0.5, 10))

                if shutdown_event.is_set():
                    logger.info("Shutdown during scrape loop.")
                    return

                video_path, title = result

                if not editor.is_video_suitable(video_path):
                    logger.info(f"Video {video_path} unsuitable. Cleaning up.")
                    scraper.cleanup_files([video_path])
                    continue

                edited_path = None
                try:
                    edited_path = await editor.edit_video(video_path)
                except Exception as e:
                    tb = traceback.format_exc()
                    logger.error(f"Editing failed: {e}")
                    await send_alert_message(
                        f"❌ *Editing Error*\n"
                        f"Title: `{title}`\n"
                        f"```\n{tb[-3000:]}\n```"
                    )
                    scraper.cleanup_files([video_path])
                    continue

                # --- ✅ VALIDATE edited_path before uploading ---
                if not edited_path or not os.path.exists(edited_path):
                    logger.error(f"Invalid edited path: {edited_path}")
                    await send_alert_message(
                        f"❗ *Render Error*\n"
                        f"Output missing or failed.\n"
                        f"Title: `{title}`\n"
                        f"Input: `{video_path}`\n"
                        f"Output: `{edited_path}`"
                    )
                    scraper.cleanup_files([video_path])
                    continue

                await uploader.upload_video(edited_path)

                scraper.cleanup_files([video_path, edited_path])

                for _ in range(random.randint(10, 30)):
                    if shutdown_event.is_set():
                        return
                    await asyncio.sleep(1)

            except Exception as e:
                tb = traceback.format_exc()
                logger.error(f"Main loop error: {e}")
                await send_alert_message(
                    f"❗ *Critical Bot Failure*\n"
                    f"```\n{tb[-3000:]}\n```"
                )
                await asyncio.sleep(5)

    finally:
        await stop_telegram_bot(app)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    try:
        asyncio.run(main_loop())
    except Exception as e:
        tb = traceback.format_exc()
        logger.critical(f"Fatal bot error: {e}")

        async def crash_alert():
            try:
                await send_alert_message(
                    f"💥 *Bot Crash*\n"
                    f"```\n{tb[-3000:]}\n```"
                )
            except:
                pass

        asyncio.run(crash_alert())
        sys.exit(1)

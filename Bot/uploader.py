import logging
import os
import asyncio
from aiogram import Bot

logger = logging.getLogger("TelegramVideoBot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

from aiogram.types import DefaultBotProperties
bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))

async def upload_video(video_path: str):
    try:
        logger.info(f"Uploading video: {video_path}")
        async with bot:
            await bot.send_document(
                chat_id=TELEGRAM_CHAT_ID,
                document=open(video_path, "rb"),
                caption="🎬 New video",
                disable_notification=True,
            )
        logger.info("Upload successful")
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise

def cleanup_files(paths: list[str]):
    for path in paths:
        try:
            os.remove(path)
            logger.info(f"Deleted file: {path}")
        except Exception as e:
            logger.warning(f"Failed to delete {path}: {e}")

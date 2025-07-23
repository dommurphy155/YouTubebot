import logging
import os
from aiogram import Bot
from aiogram.types.input_file import BufferedInputFile
from typing import List

logger = logging.getLogger("TelegramVideoBot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

bot = Bot(token=TELEGRAM_TOKEN)

async def upload_video(video_path: str):
    try:
        logger.info(f"Uploading video: {video_path}")
        async with bot:
            with open(video_path, "rb") as f:
                file_data = f.read()
                input_file = BufferedInputFile(file_data, filename=os.path.basename(video_path))
                await bot.send_document(
                    chat_id=TELEGRAM_CHAT_ID,
                    document=input_file,
                    caption="🎬 New video\n#viral #funny #trending #shorts #mustwatch",
                    disable_notification=True,
                    parse_mode="HTML"
                )
        logger.info("Upload successful")
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise

def cleanup_files(paths: List[str]):
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Deleted file: {path}")
        except Exception as e:
            logger.warning(f"Failed to delete {path}: {e}")

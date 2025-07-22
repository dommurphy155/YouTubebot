import asyncio
from pathlib import Path
from bot.config import BOT_TOKEN, TELEGRAM_SEND_RETRIES, TELEGRAM_TIMEOUT_SECONDS
from bot.utils import logger
from telegram import Bot, TelegramError
from telegram.constants import ParseMode

bot = Bot(token=BOT_TOKEN)

async def send_video(chat_id: int, video_path: Path, caption: str = "") -> bool:
    """
    Sends video file to the specified Telegram chat_id.
    Retries up to TELEGRAM_SEND_RETRIES times on failure.
    """
    for attempt in range(1, TELEGRAM_SEND_RETRIES + 1):
        try:
            with video_path.open("rb") as video_file:
                await bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    supports_streaming=True,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    timeout=TELEGRAM_TIMEOUT_SECONDS,
                )
            logger.info(f"Sent video {video_path.name} to chat {chat_id}")
            return True
        except TelegramError as e:
            logger.error(f"Attempt {attempt}: Failed to send video - {e}")
            await asyncio.sleep(5 * attempt)  # exponential backoff

    logger.error(f"All {TELEGRAM_SEND_RETRIES} attempts to send video failed.")
    return False

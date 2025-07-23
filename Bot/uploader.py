import logging
import os
import subprocess
from typing import List
from telegram import Bot, InputFile

logger = logging.getLogger("TelegramVideoBot")
logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

bot = Bot(token=TELEGRAM_TOKEN)

def get_video_metadata(video_path: str):
    try:
        # Get duration using ffprobe
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        duration = float(result.stdout.strip()) if result.returncode == 0 else None

        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        return round(duration, 2) if duration else None, round(size_mb, 2)
    except Exception as e:
        logger.warning(f"Metadata fetch failed for {video_path}: {e}")
        return None, None

async def upload_video(video_path: str):
    try:
        if not os.path.exists(video_path):
            logger.error(f"File does not exist: {video_path}")
            return

        duration, size_mb = get_video_metadata(video_path)
        logger.info(f"Uploading video: {video_path} | Duration: {duration}s | Size: {size_mb}MB")

        with open(video_path, "rb") as f:
            input_file = InputFile(f, filename=os.path.basename(video_path))
            await bot.send_document(
                chat_id=TELEGRAM_CHAT_ID,
                document=input_file,
                caption="🎬 New video\n#viral #funny #trending #shorts #mustwatch",
                disable_notification=True,
                parse_mode="HTML",
                write_timeout=120,
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

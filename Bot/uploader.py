import logging
import os
import subprocess
from telegram import Bot, InputFile

# Setup logging
logger = logging.getLogger("TelegramVideoBot")
logging.basicConfig(level=logging.INFO)

# Read environment variables for Telegram credentials
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.critical("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set in environment.")
    raise EnvironmentError("Missing Telegram credentials in environment variables.")

TELEGRAM_CHAT_ID = int(TELEGRAM_CHAT_ID)

bot = Bot(token=TELEGRAM_TOKEN)


def get_video_metadata(video_path: str):
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10)
        duration = float(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        return (
            round(duration, 2) if duration is not None else None,
            round(size_mb, 2)
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to get metadata for {video_path}: {e}")
        return None, None


async def upload_video(video_path: str):
    if not video_path or not isinstance(video_path, (str, bytes, os.PathLike)):
        logger.error(f"❌ upload_video received invalid path type: {video_path}")
        return

    if not os.path.exists(video_path):
        logger.error(f"❌ upload_video: file does not exist — {video_path}")
        return

    duration, size_mb = get_video_metadata(video_path)
    logger.info(f"📤 Uploading: {video_path} | Duration: {duration}s | Size: {size_mb}MB")

    try:
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
        logger.info(f"✅ Upload succeeded: {os.path.basename(video_path)}")
    except Exception as e:
        logger.error(f"🚫 Telegram upload failed for {video_path}: {e}")
        raise


def cleanup_files(paths):
    for path in paths:
        if not path or not isinstance(path, (str, bytes, os.PathLike)):
            logger.warning(f"⚠️ cleanup_files: Skipping invalid path: {path}")
            continue

        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"🧹 Removed {path}")
        except Exception as e:
            logger.warning(f"⚠️ Could not delete {path}: {e}")

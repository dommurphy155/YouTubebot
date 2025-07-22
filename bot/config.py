import os
from dotenv import load_dotenv

load_dotenv()

# Environment variables and constants
BOT_TOKEN = os.getenv("BOT_TOKEN", None)
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables. Please export BOT_TOKEN.")

# Keywords rotation list
KEYWORDS = ["ASMR", "MrBeast", "song", "funny fails", "Minecraft"]

# Video processing constants
VIDEO_LENGTH_SECONDS = (20, 35)  # trim length range in seconds
VIDEO_RESOLUTION = "1080x1920"  # iPhone vertical size

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "..", "downloads")
EDITED_DIR = os.path.join(BASE_DIR, "..", "edited")

# Ensure directories exist
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(EDITED_DIR, exist_ok=True)

# Telegram retry and timeout config
TELEGRAM_SEND_RETRIES = 3
TELEGRAM_TIMEOUT_SECONDS = 60

# yt-dlp config
YTDLP_RETRIES = 10
YTDLP_FRAGMENT_RETRIES = 10
YTDLP_MAX_DURATION = 180  # max video length seconds to download

# Logging config
LOG_FILE = os.path.join(BASE_DIR, "..", "bot.log")

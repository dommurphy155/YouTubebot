import os
from datetime import timedelta

def require_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if value is None:
        raise EnvironmentError(f"Missing required environment variable: {var_name}")
    return value

# Telegram configuration
TELEGRAM_TOKEN = require_env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = require_env("TELEGRAM_CHAT_ID")

# Reddit API configuration
REDDIT_CLIENT_ID = require_env("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = require_env("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = require_env("REDDIT_USER_AGENT")
REDDIT_USERNAME = require_env("REDDIT_USERNAME")
REDDIT_PASSWORD = require_env("REDDIT_PASSWORD")

# Subreddits to scrape (no URLs — just slugs)
SOURCE_SUBREDDITS = [
    "PublicFreakout",
    "nextfuckinglevel",
    "Unexpected",
    "WatchPeopleDieInside",
    "instant_regret",
    "IdiotsInCars",
    "holdmyjuicebox",
    "blursedimages",
]

# Video filtering rules
MIN_DURATION_SECONDS = 20
MAX_DURATION_SECONDS = 60
MIN_SCORE = 5000
MIN_COMMENTS = 12000

# Scheduling & limits
MAX_VIDEOS_PER_RUN = 5
SCRAPE_INTERVAL = timedelta(hours=1)  # Used by scheduler (if needed)

# Paths
DOWNLOAD_DIR = "downloads"
EDITED_DIR = "edited"

# yt-dlp config
YTDLP_FORMAT = "bv*+ba/b"
YTDLP_RETRIES = 2
YTDLP_TIMEOUT = 30

# FFmpeg config
OUTPUT_RESOLUTION = "1080x1920"
CRF = 25
PRESET = "fast"

# Misc
USER_AGENT = REDDIT_USER_AGENT
VERSION = "1.0.0"

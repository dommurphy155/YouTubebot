import os
from datetime import timedelta

# ========== Environment Variables (Fail-safe Fallbacks) ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "TelegramVideoBot/1.0 by u/your_username")
REDDIT_USERNAME = os.environ.get("REDDIT_USERNAME", "")
REDDIT_PASSWORD = os.environ.get("REDDIT_PASSWORD", "")

# ========== Subreddit Sources ==========
SOURCE_SUBREDDITS = [
    "PublicFreakout",
    "Unexpected",
    "WatchPeopleDieInside",
    "NextFuckingLevel",
    "instant_regret",
    "holdmyjuicebox",
    "blursedimages",
    "IdiotsInCars",
    "youtubehaiku",
    "ContentCreators",
    "NewTubers",
    "AskReddit",
    "AITA",
    "nosleep",
]

# ========== Video Filtering ==========
MIN_DURATION_SECONDS = 20         # Skip anything shorter
MAX_DURATION_SECONDS = 60         # Skip anything longer
MIN_SCORE = 5000                  # Engagement threshold
MIN_COMMENTS = 12000              # Popularity filter

# ========== Processing Limits ==========
MAX_VIDEOS_PER_RUN = 5
SCRAPE_INTERVAL = timedelta(minutes=45)  # For external scheduler (optional)

# ========== Local Paths ==========
DOWNLOAD_DIR = "downloads"
EDITED_DIR = "edited"
LOG_DIR = "logs"

# ========== yt-dlp Settings ==========
YTDLP_FORMAT = "bv*+ba/b"     # Best video + audio combo fallback
YTDLP_RETRIES = 3
YTDLP_TIMEOUT = 30            # Seconds

# ========== FFmpeg Settings ==========
OUTPUT_RESOLUTION = "1080x1920"
CRF = 25
PRESET = "fast"

# ========== AI Render Preferences ==========
PRIMARY_RENDER = "shotstack"     # Options: shotstack, huggingface
FALLBACK_RENDER = "editor"       # Local fallback if APIs fail

# ========== Misc ==========
USER_AGENT = REDDIT_USER_AGENT
VERSION = "1.0.0"

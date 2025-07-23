import os
import logging
import random
from datetime import datetime, timedelta
import praw
import requests

logger = logging.getLogger("TelegramVideoBot")

DOWNLOAD_DIR = "/home/ubuntu/YouTubebot/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

REDDIT_SUBREDDITS = [
    "PublicFreakout",
    "Unexpected",
    "WatchPeopleDieInside",
    "NextFuckingLevel",
    "instant_regret",
    "holdmyjuicebox",
    "blursedimages",
    "IdiotsInCars"
]

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "RedditVideoScraperBot/1.0 by u/No_Education_9299")

reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT,
)

def fetch_reddit_videos(limit_per_sub=50):
    candidates = []
    for subreddit_name in REDDIT_SUBREDDITS:
        try:
            subreddit = reddit.subreddit(subreddit_name)
            for post in subreddit.top(time_filter="week", limit=limit_per_sub):
                if not post.is_video or not hasattr(post, "media"):
                    continue
                reddit_video = post.media.get("reddit_video", {})
                fallback_url = reddit_video.get("fallback_url")
                if fallback_url and post.score >= 5000 and post.num_comments >= 12000:
                    candidates.append((post.id, fallback_url))
        except Exception as e:
            logger.error(f"Error fetching from subreddit {subreddit_name}: {e}")
    return candidates

def download_video(url: str, filename: str) -> str | None:
    path = os.path.join(DOWNLOAD_DIR, filename)
    try:
        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code != 200:
            logger.error(f"Failed to download video: {resp.status_code}")
            return None
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return path
    except Exception as e:
        logger.error(f"Error downloading video from {url}: {e}")
        return None

import asyncio

async def has_audio_stream(filepath: str) -> bool:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0", filepath
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return bool(stdout.strip())

async def get_video_duration(filepath: str) -> float | None:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filepath
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.strip())
    except Exception:
        return None

async def get_video_resolution(filepath: str) -> tuple[int, int] | None:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", filepath
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    try:
        w, h = stdout.decode().strip().split('x')
        return int(w), int(h)
    except Exception:
        return None

async def is_video_suitable(filepath: str) -> bool:
    if not await has_audio_stream(filepath):
        logger.warning(f"No audio stream in {filepath}")
        return False

    duration = await get_video_duration(filepath)
    if duration is None or not (20 <= duration <= 60):
        logger.warning(f"Unsuitable duration: {filepath}")
        return False

    resolution = await get_video_resolution(filepath)
    if resolution is None:
        return False

    w, h = resolution
    if w > 3840 or h > 2160:
        logger.warning(f"Too high resolution: {w}x{h} in {filepath}")
        return False

    return True

async def scrape_video() -> str | None:
    videos = fetch_reddit_videos()
    if not videos:
        logger.warning("No suitable Reddit videos found.")
        return None

    random.shuffle(videos)
    for video_id, video_url in videos:
        filename = f"{video_id}.mp4"
        logger.info(f"Attempting download of {video_id} from {video_url}")
        video_path = download_video(video_url, filename)
        if video_path and await is_video_suitable(video_path):
            logger.info(f"Video ready: {video_path}")
            return video_path
        if video_path:
            try:
                os.remove(video_path)
                logger.info(f"Deleted unsuitable video: {video_path}")
            except Exception as e:
                logger.error(f"Failed to delete {video_path}: {e}")
    return None

def cleanup_files(paths: list[str]):
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Deleted file: {path}")
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")

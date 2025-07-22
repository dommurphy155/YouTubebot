import asyncio
import logging
import os
from yt_dlp import YoutubeDL
from pathlib import Path

logger = logging.getLogger("TelegramVideoBot")

DOWNLOAD_DIR = "/home/ubuntu/YouTubebot/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

YDL_OPTS = {
    "format": "best[ext=mp4]/best",
    "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "ignoreerrors": True,
    "nocheckcertificate": True,
    "continuedl": True,
    "retries": 3,
}

VIDEO_SOURCES = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Replace/add more valid, short-form URLs
]

_video_index = 0

def _get_next_url() -> str | None:
    global _video_index
    if _video_index >= len(VIDEO_SOURCES):
        return None
    url = VIDEO_SOURCES[_video_index]
    _video_index += 1
    return url

async def scrape_video() -> str | None:
    url = _get_next_url()
    if not url:
        logger.info("No more videos to scrape.")
        return None

    logger.info(f"Scraping video from URL: {url}")

    def download():
        with YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None
            filename = ydl.prepare_filename(info)
            if os.path.isfile(filename):
                return filename
            return None

    loop = asyncio.get_event_loop()
    video_path = await loop.run_in_executor(None, download)

    if video_path:
        logger.info(f"Downloaded video to {video_path}")
        return video_path
    else:
        logger.warning(f"Failed to download video from {url}")
        return None

def cleanup_files(paths: list[str]):
    for path in paths:
        try:
            os.remove(path)
            logger.info(f"Deleted file: {path}")
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")

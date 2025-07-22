import asyncio
import logging
import os
from yt_dlp import YoutubeDL

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

async def scrape_video(url: str) -> str | None:
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

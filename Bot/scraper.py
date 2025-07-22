import asyncio
import logging
import os
import aiohttp

logger = logging.getLogger("TelegramVideoBot")

DOWNLOAD_DIR = "/home/ubuntu/YouTubebot/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
if not PEXELS_API_KEY:
    raise RuntimeError("PEXELS_API_KEY environment variable not set")

HEADERS = {
    "Authorization": PEXELS_API_KEY,
}

PEXELS_API_URL = "https://api.pexels.com/videos/popular?per_page=10&page=1"

async def fetch_pexels_videos():
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(PEXELS_API_URL) as resp:
            if resp.status != 200:
                logger.error(f"Pexels API error: {resp.status}")
                return []
            data = await resp.json()
            return data.get("videos", [])

async def download_video(url: str, filename: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to download video: {resp.status}")
                    return None
                path = os.path.join(DOWNLOAD_DIR, filename)
                with open(path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(1024)
                        if not chunk:
                            break
                        f.write(chunk)
                return path
    except Exception as e:
        logger.error(f"Download exception: {e}")
        return None

async def scrape_video() -> str | None:
    videos = await fetch_pexels_videos()
    if not videos:
        logger.info("No videos fetched from Pexels")
        return None

    video = videos[0]
    video_files = video.get("video_files", [])
    if not video_files:
        logger.warning("No video files found for first Pexels video")
        return None

    mp4_files = [f for f in video_files if f.get("file_type") == "video/mp4"]
    if not mp4_files:
        logger.warning("No mp4 files found for first Pexels video")
        return None

    best_file = max(mp4_files, key=lambda x: x.get("width", 0))
    video_url = best_file.get("link")
    video_id = video.get("id")

    if not video_url or not video_id:
        logger.warning("Invalid video data from Pexels")
        return None

    filename = f"{video_id}.mp4"
    logger.info(f"Downloading Pexels video {video_id} from {video_url}")
    video_path = await download_video(video_url, filename)

    if video_path:
        logger.info(f"Downloaded video saved to {video_path}")
        return video_path
    else:
        logger.warning("Failed to download video from Pexels")
        return None

def cleanup_files(paths: list[str]):
    for path in paths:
        try:
            os.remove(path)
            logger.info(f"Deleted file: {path}")
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")

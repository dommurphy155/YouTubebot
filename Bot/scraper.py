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

PEXELS_API_URL = "https://api.pexels.com/videos/popular?per_page=5&page=1"  # reduced per_page for faster response

async def fetch_pexels_videos():
    timeout = aiohttp.ClientTimeout(total=10)  # limit total request time
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        try:
            async with session.get(PEXELS_API_URL) as resp:
                if resp.status != 200:
                    logger.error(f"Pexels API error: {resp.status}")
                    return []
                data = await resp.json()
                return data.get("videos", [])
        except asyncio.TimeoutError:
            logger.error("Pexels API request timed out")
            return []
        except Exception as e:
            logger.error(f"Pexels API request failed: {e}")
            return []

async def download_video(url: str, filename: str) -> str | None:
    path = os.path.join(DOWNLOAD_DIR, filename)
    try:
        timeout = aiohttp.ClientTimeout(total=60)  # 1 min max download time
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to download video: {resp.status}")
                    return None
                with open(path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(8192):  # bigger chunks, async iteration
                        f.write(chunk)
        return path
    except asyncio.TimeoutError:
        logger.error("Video download timed out")
        return None
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

    # Select best file balancing resolution and size
    def score(f):  # prioritize resolution but penalize large files for efficiency
        return f.get("width", 0) / (f.get("file_size", 1) / 1024 / 1024 + 1)
    best_file = max(mp4_files, key=score)

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
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Deleted file: {path}")
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")

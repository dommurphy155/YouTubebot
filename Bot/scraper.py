import asyncio
import logging
import os
import aiohttp
import random

logger = logging.getLogger("TelegramVideoBot")

DOWNLOAD_DIR = "/home/ubuntu/YouTubebot/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
if not PEXELS_API_KEY:
    raise RuntimeError("PEXELS_API_KEY environment variable not set")

HEADERS = {
    "Authorization": PEXELS_API_KEY,
}

PEXELS_SEARCH_QUERIES = [
    "funny animals",
    "pranks",
    "epic fails",
    "people reaction",
    "street interview",
    "dancing"
]

def build_search_url(query: str, per_page: int = 15, page: int = 1) -> str:
    q = query.replace(" ", "+")
    return f"https://api.pexels.com/videos/search?query={q}&per_page={per_page}&page={page}"

async def fetch_pexels_videos():
    query = random.choice(PEXELS_SEARCH_QUERIES)
    url = build_search_url(query)
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"Pexels API error: {resp.status} | Query: {query}")
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
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to download video: {resp.status}")
                    return None
                with open(path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)
        return path
    except asyncio.TimeoutError:
        logger.error("Video download timed out")
        return None
    except Exception as e:
        logger.error(f"Download exception: {e}")
        return None

async def has_audio_stream(filepath: str) -> bool:
    """Check if video file has an audio stream using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        filepath
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    has_audio = bool(stdout.strip())
    if not has_audio:
        logger.warning(f"No audio stream found in {filepath}")
    return has_audio

async def get_video_duration(filepath: str) -> float | None:
    """Get video duration in seconds."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filepath
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    try:
        duration = float(stdout.strip())
        return duration
    except (ValueError, TypeError):
        logger.warning(f"Failed to get duration for {filepath}")
        return None

async def get_video_resolution(filepath: str) -> tuple[int, int] | None:
    """Get video resolution (width, height)."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        filepath
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    try:
        w, h = stdout.decode().strip().split('x')
        return int(w), int(h)
    except Exception:
        logger.warning(f"Failed to get resolution for {filepath}")
        return None

async def is_video_suitable(filepath: str) -> bool:
    # Check audio presence
    if not await has_audio_stream(filepath):
        return False
    # Check duration limits (>=5s)
    duration = await get_video_duration(filepath)
    if duration is None or duration < 5:
        logger.warning(f"Video too short or duration unknown: {filepath}")
        return False
    # Check resolution cap (max 3840x2160 for 4K)
    resolution = await get_video_resolution(filepath)
    if resolution is None:
        return False
    width, height = resolution
    if width > 3840 or height > 2160:
        logger.warning(f"Video resolution too high: {width}x{height} in {filepath}")
        return False
    return True

async def scrape_video() -> str | None:
    videos = await fetch_pexels_videos()
    if not videos:
        logger.info("No videos fetched from Pexels")
        return None

    # Filter videos by duration 10–60s
    def is_suitable_duration(video):
        duration = video.get("duration", 0)
        return 10 <= duration <= 60

    candidates = list(filter(is_suitable_duration, videos))
    if not candidates:
        logger.warning("No suitable-duration videos found")
        return None

    # Pick random candidate and best quality mp4 file
    video = random.choice(candidates)
    video_files = video.get("video_files", [])
    if not video_files:
        logger.warning("No video files found for selected Pexels video")
        return None

    mp4_files = [f for f in video_files if f.get("file_type") == "video/mp4"]
    if not mp4_files:
        logger.warning("No mp4 files found for selected Pexels video")
        return None

    def score(f):
        size_mb = f.get("file_size", 1) / (1024 * 1024)
        return f.get("width", 0) / (size_mb + 1)

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
        # Check suitability before returning
        if await is_video_suitable(video_path):
            logger.info(f"Downloaded video suitable: {video_path}")
            return video_path
        else:
            logger.warning(f"Downloaded video not suitable, deleting: {video_path}")
            try:
                os.remove(video_path)
            except Exception as e:
                logger.error(f"Failed to delete unsuitable video {video_path}: {e}")
            return None
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

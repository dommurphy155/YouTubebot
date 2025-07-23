import asyncio
import logging
import os
import aiohttp
import random

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

PUSHSHIFT_API_URL = "https://api.pushshift.io/reddit/search/submission/"

async def fetch_reddit_videos(subreddit: str, limit: int = 50):
    params = {
        "subreddit": subreddit,
        "sort": "desc",
        "sort_type": "score",
        "after": "7d",
        "is_video": "true",
        "size": limit
    }
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(PUSHSHIFT_API_URL, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Pushshift API error: {resp.status} | Subreddit: {subreddit}")
                    return []
                data = await resp.json()
                return data.get("data", [])
        except asyncio.TimeoutError:
            logger.error(f"Pushshift API request timed out for subreddit {subreddit}")
            return []
        except Exception as e:
            logger.error(f"Pushshift API request failed for subreddit {subreddit}: {e}")
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
    if not await has_audio_stream(filepath):
        return False
    duration = await get_video_duration(filepath)
    if duration is None or not (20 <= duration <= 60):
        logger.warning(f"Video duration not in range 20-60s or unknown: {filepath}")
        return False
    resolution = await get_video_resolution(filepath)
    if resolution is None:
        return False
    width, height = resolution
    if width > 3840 or height > 2160:
        logger.warning(f"Video resolution too high: {width}x{height} in {filepath}")
        return False
    return True

async def scrape_video() -> str | None:
    # Aggregate videos from all subreddits
    all_videos = []
    for subreddit in REDDIT_SUBREDDITS:
        vids = await fetch_reddit_videos(subreddit)
        all_videos.extend(vids)

    if not all_videos:
        logger.info("No videos fetched from Reddit")
        return None

    # Filter by score and comments thresholds
    def is_viral(video):
        score = video.get("score", 0)
        comments = video.get("num_comments", 0)
        is_vid = video.get("is_video", False)
        return is_vid and score >= 12000 and comments >= 5000

    viral_videos = list(filter(is_viral, all_videos))
    if not viral_videos:
        logger.warning("No viral videos found based on score/comments")
        return None

    # Pick a random viral video with Reddit native video url
    candidates = []
    for video in viral_videos:
        media = video.get("media")
        if not media:
            continue
        reddit_video = media.get("reddit_video")
        if reddit_video:
            fallback_url = reddit_video.get("fallback_url")
            if fallback_url:
                candidates.append((video, fallback_url))

    if not candidates:
        logger.warning("No Reddit native video URLs found")
        return None

    video, video_url = random.choice(candidates)
    video_id = video.get("id") or video.get("name") or str(random.randint(1000000, 9999999))
    filename = f"{video_id}.mp4"

    logger.info(f"Downloading Reddit video {video_id} from {video_url}")
    video_path = await download_video(video_url, filename)

    if video_path:
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
        logger.warning("Failed to download video from Reddit")
        return None

def cleanup_files(paths: list[str]):
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Deleted file: {path}")
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")

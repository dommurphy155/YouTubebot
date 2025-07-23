import os
import asyncio
import aiohttp
import logging
import random
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Tuple, List

import praw
import subprocess

logger = logging.getLogger("TelegramVideoBot")
logging.basicConfig(level=logging.INFO)

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

# Dynamic thresholds per subreddit, can be tuned over time
SUBREDDIT_THRESHOLDS = {
    "PublicFreakout": {"score": 5000, "comments": 12000},
    "Unexpected": {"score": 3000, "comments": 8000},
    # Default threshold for others
}

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.environ["REDDIT_USER_AGENT"]

# Maintain set of seen video hashes and IDs for deduplication
seen_hashes = set()
seen_post_ids = set()
blacklist_urls = set()

def get_reddit_instance():
    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT
    )

def run_ffprobe_cmd(cmd: List[str]) -> Optional[str]:
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return None
    except Exception:
        return None

def get_video_bitrate(filepath: str) -> Optional[int]:
    output = run_ffprobe_cmd([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=bit_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filepath
    ])
    if output:
        try:
            return int(output)
        except ValueError:
            return None
    return None

def get_video_codec(filepath: str) -> Optional[str]:
    output = run_ffprobe_cmd([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filepath
    ])
    return output

def get_audio_channels(filepath: str) -> Optional[int]:
    output = run_ffprobe_cmd([
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=channels",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filepath
    ])
    if output:
        try:
            return int(output)
        except ValueError:
            return None
    return None

def get_video_fps(filepath: str) -> Optional[float]:
    output = run_ffprobe_cmd([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filepath
    ])
    if output and '/' in output:
        num, den = output.split('/')
        try:
            fps = float(num) / float(den)
            return fps
        except Exception:
            return None
    else:
        try:
            return float(output)
        except Exception:
            return None

def get_video_orientation(filepath: str) -> Optional[str]:
    res = get_video_resolution(filepath)
    if not res:
        return None
    w, h = res
    if h > w:
        return "vertical"
    else:
        return "horizontal"

def get_video_resolution(filepath: str) -> Optional[Tuple[int, int]]:
    output = run_ffprobe_cmd([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", filepath
    ])
    if output:
        try:
            w, h = output.split('x')
            return int(w), int(h)
        except Exception:
            return None
    return None

def calculate_file_hash(filepath: str, chunk_size=8192) -> str:
    hash_md5 = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        logger.error(f"Failed to hash file {filepath}: {e}")
        return ""

async def download_file(url: str, filename: str) -> Optional[str]:
    if url in blacklist_urls:
        logger.info(f"URL blacklisted, skipping: {url}")
        return None
    path = os.path.join(DOWNLOAD_DIR, filename)
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to download file: {resp.status} from {url}")
                    blacklist_urls.add(url)
                    return None
                with open(path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)
        return path
    except Exception as e:
        logger.error(f"Error downloading file from {url}: {e}")
        blacklist_urls.add(url)
        return None

async def download_and_merge(video_url: str, audio_url: str, output_path: str) -> Optional[str]:
    video_path = output_path + "_video.mp4"
    audio_path = output_path + "_audio.mp4"

    video_dl = await download_file(video_url, os.path.basename(video_path))
    if not video_dl:
        return None
    audio_dl = await download_file(audio_url, os.path.basename(audio_path))
    if not audio_dl:
        # If no audio, delete video and return None
        try:
            os.remove(video_path)
        except Exception:
            pass
        return None

    # Merge video + audio
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-strict", "experimental",
        output_path
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(f"FFmpeg merge failed: {stderr.decode()}")
        try:
            os.remove(video_path)
        except Exception:
            pass
        try:
            os.remove(audio_path)
        except Exception:
            pass
        return None

    # Cleanup separate files
    try:
        os.remove(video_path)
    except Exception:
        pass
    try:
        os.remove(audio_path)
    except Exception:
        pass
    return output_path

async def is_video_suitable(filepath: str) -> bool:
    # Check deduplication
    file_hash = calculate_file_hash(filepath)
    if file_hash in seen_hashes:
        logger.info(f"Duplicate video detected, skipping {filepath}")
        return False
    seen_hashes.add(file_hash)

    # Check audio channels (skip if none or less than 1 channel)
    audio_ch = get_audio_channels(filepath)
    if audio_ch is None or audio_ch < 1:
        logger.warning(f"No or invalid audio channels in {filepath}")
        return False

    # Duration check (20-60s)
    duration = await get_video_duration(filepath)
    if duration is None or not (20 <= duration <= 60):
        logger.warning(f"Unsuitable duration: {duration} seconds in {filepath}")
        return False

    # Resolution check
    resolution = get_video_resolution(filepath)
    if resolution is None:
        logger.warning(f"Cannot get resolution for {filepath}")
        return False
    w, h = resolution
    if w > 3840 or h > 2160:
        logger.warning(f"Too high resolution: {w}x{h} in {filepath}")
        return False

    # Orientation check: prefer vertical videos only
    orientation = get_video_orientation(filepath)
    if orientation != "vertical":
        logger.info(f"Skipping non-vertical video: {filepath} orientation={orientation}")
        return False

    # Codec check (only accept h264 or vp9)
    codec = get_video_codec(filepath)
    if codec not in ("h264", "vp9"):
        logger.info(f"Skipping unsupported codec {codec} in {filepath}")
        return False

    # Bitrate check (reject very low bitrate below 500kbps)
    bitrate = get_video_bitrate(filepath)
    if bitrate is not None and bitrate < 500_000:
        logger.info(f"Skipping low bitrate {bitrate} in {filepath}")
        return False

    # FPS check (min 24)
    fps = get_video_fps(filepath)
    if fps is not None and fps < 24:
        logger.info(f"Skipping low FPS {fps} in {filepath}")
        return False

    return True

async def fetch_reddit_videos(limit_per_sub=50) -> List[Tuple[str, str, str, str]]:
    reddit = get_reddit_instance()
    candidates = []

    for subreddit_name in REDDIT_SUBREDDITS:
        try:
            subreddit = reddit.subreddit(subreddit_name)
            thresh = SUBREDDIT_THRESHOLDS.get(subreddit_name, {"score": 2000, "comments": 5000})
            count = 0

            for post in subreddit.top(time_filter="week", limit=limit_per_sub):
                if count >= limit_per_sub:
                    break
                if not post.is_video or not hasattr(post, "media"):
                    continue
                reddit_video = post.media.get("reddit_video", {})
                fallback_url = reddit_video.get("fallback_url")
                dash_url = reddit_video.get("dash_url")

                if not fallback_url or not dash_url or fallback_url in blacklist_urls:
                    continue
                if post.score < thresh["score"] or post.num_comments < thresh["comments"]:
                    continue
                if post.id in seen_post_ids:
                    continue

                # Audio URL from dash_url (replace last segment with DASH_audio.mp4)
                audio_url = dash_url.rsplit('/', 1)[0] + "/DASH_audio.mp4"
                candidates.append((post.id, fallback_url, audio_url, post.title))
                seen_post_ids.add(post.id)
                count += 1
        except Exception as e:
            logger.error(f"Error fetching from subreddit {subreddit_name}: {e}")

    return candidates

async def scrape_video() -> Optional[Tuple[str, str]]:
    videos = await fetch_reddit_videos()
    if not videos:
        logger.warning("No suitable Reddit videos found.")
        return None

    random.shuffle(videos)
    for video_id, video_url, audio_url, title in videos:
        filename = f"{video_id}.mp4"
        output_path = os.path.join(DOWNLOAD_DIR, filename)
        logger.info(f"Attempting download+merge of {video_id} from {video_url} and audio {audio_url}")
        merged_path = await download_and_merge(video_url, audio_url, output_path)
        if merged_path and await is_video_suitable(merged_path):
            logger.info(f"Video ready: {merged_path}")
            return merged_path, title
        if merged_path:
            try:
                os.remove(merged_path)
                logger.info(f"Deleted unsuitable video: {merged_path}")
            except Exception as e:
                logger.error(f"Failed to delete {merged_path}: {e}")
    return None

def cleanup_files(paths: List[str]):
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Deleted file: {path}")
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")

async def get_video_duration(filepath: str) -> Optional[float]:
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

import os
import asyncio
import logging
import random
import hashlib
from typing import Optional, Tuple, List

import praw
import shlex
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

SUBREDDIT_THRESHOLDS = {
    "PublicFreakout": {"score": 5000, "comments": 12000},
    "Unexpected": {"score": 3000, "comments": 8000},
}

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.environ["REDDIT_USER_AGENT"]

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
    return "vertical" if h > w else "horizontal"


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


async def is_video_suitable(filepath: str) -> bool:
    file_hash = calculate_file_hash(filepath)
    if file_hash in seen_hashes:
        logger.info(f"Duplicate video detected, skipping {filepath}")
        return False
    seen_hashes.add(file_hash)

    audio_ch = get_audio_channels(filepath)
    if audio_ch is None or audio_ch < 1:
        logger.warning(f"No or invalid audio channels in {filepath}")
        return False

    duration = await get_video_duration(filepath)
    if duration is None or not (20 <= duration <= 60):
        logger.warning(f"Unsuitable duration: {duration} seconds in {filepath}")
        return False

    resolution = get_video_resolution(filepath)
    if resolution is None:
        logger.warning(f"Cannot get resolution for {filepath}")
        return False
    w, h = resolution
    if w > 3840 or h > 2160:
        logger.warning(f"Too high resolution: {w}x{h} in {filepath}")
        return False

    orientation = get_video_orientation(filepath)
    if orientation != "vertical":
        logger.info(f"Skipping non-vertical video: {filepath} orientation={orientation}")
        return False

    codec = get_video_codec(filepath)
    if codec not in ("h264", "vp9"):
        logger.info(f"Skipping unsupported codec {codec} in {filepath}")
        return False

    bitrate = get_video_bitrate(filepath)
    if bitrate is not None and bitrate < 500_000:
        logger.info(f"Skipping low bitrate {bitrate} in {filepath}")
        return False

    fps = get_video_fps(filepath)
    if fps is not None and fps < 24:
        logger.info(f"Skipping low FPS {fps} in {filepath}")
        return False

    return True


async def async_subreddit_top(subreddit, limit):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: list(subreddit.top(time_filter="week", limit=limit)))


async def fetch_reddit_videos(limit_per_sub=50) -> List[Tuple[str, str]]:
    reddit = get_reddit_instance()
    candidates = []

    for subreddit_name in REDDIT_SUBREDDITS:
        try:
            subreddit = reddit.subreddit(subreddit_name)
            thresh = SUBREDDIT_THRESHOLDS.get(subreddit_name, {"score": 2000, "comments": 5000})
            count = 0

            posts = await async_subreddit_top(subreddit, limit_per_sub)
            for post in posts:
                if count >= limit_per_sub:
                    break
                if not post.is_video or not hasattr(post, "media"):
                    continue
                reddit_video = post.media.get("reddit_video", {})
                fallback_url = reddit_video.get("fallback_url")
                if not fallback_url or fallback_url in blacklist_urls:
                    continue
                if post.score < thresh["score"] or post.num_comments < thresh["comments"]:
                    continue
                if post.id in seen_post_ids:
                    continue

                candidates.append((post.id, post.title))
                seen_post_ids.add(post.id)
                count += 1
        except Exception as e:
            logger.error(f"Error fetching from subreddit {subreddit_name}: {e}")

    return candidates


async def download_reddit_video_with_ytdlp(post_url: str, output_dir: str) -> Optional[str]:
    filename_template = "%(id)s.%(ext)s"
    output_template = os.path.join(output_dir, filename_template)
    cmd = f"yt-dlp --quiet --no-warnings --merge-output-format mp4 -o {shlex.quote(output_template)} {shlex.quote(post_url)}"
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(f"yt-dlp failed: {stderr.decode().strip()}")
        return None

    id_ = post_url.rstrip('/').split("/")[-1]
    candidate_path = os.path.join(output_dir, f"{id_}.mp4")
    if os.path.exists(candidate_path):
        return candidate_path
    logger.error(f"Downloaded file not found: {candidate_path}")
    return None


async def scrape_video() -> Optional[Tuple[str, str]]:
    videos = await fetch_reddit_videos()
    if not videos:
        logger.warning("No suitable Reddit videos found.")
        return None

    random.shuffle(videos)
    for video_id, title in videos:
        reddit_url = f"https://redd.it/{video_id}"
        logger.info(f"Downloading video via yt-dlp from Reddit post {reddit_url}")
        video_path = await download_reddit_video_with_ytdlp(reddit_url, DOWNLOAD_DIR)
        if video_path and await is_video_suitable(video_path):
            logger.info(f"Video ready: {video_path}")
            return video_path, title
        if video_path:
            try:
                os.remove(video_path)
                logger.info(f"Deleted unsuitable video: {video_path}")
            except Exception as e:
                logger.error(f"Failed to delete {video_path}: {e}")
    return None


def cleanup_files(paths: List[str]):
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Deleted file: {path}")
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")

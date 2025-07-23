import os
import asyncio
import logging
import random
import hashlib
from typing import Optional, Tuple, List

import praw
import shlex
import subprocess
import aiohttp
import requests

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
download_failures = set()

YTDLP_PATH = "/home/ubuntu/YouTubebot/venv/bin/yt-dlp"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
]

def get_reddit_instance():
    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT
    )

def run_ffprobe_cmd(cmd: List[str]) -> Optional[str]:
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None

def get_video_bitrate(filepath: str) -> Optional[int]:
    out = run_ffprobe_cmd([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=bit_rate", "-of", "default=noprint_wrappers=1:nokey=1", filepath
    ])
    try: return int(out) if out else None
    except: return None

def get_video_codec(filepath: str) -> Optional[str]:
    return run_ffprobe_cmd([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", filepath
    ])

def get_audio_channels(filepath: str) -> Optional[int]:
    out = run_ffprobe_cmd([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=channels", "-of", "default=noprint_wrappers=1:nokey=1", filepath
    ])
    try: return int(out) if out else None
    except: return None

def get_video_fps(filepath: str) -> Optional[float]:
    out = run_ffprobe_cmd([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1", filepath
    ])
    try:
        if '/' in out:
            num, den = out.split('/')
            return float(num) / float(den)
        return float(out)
    except: return None

def get_video_resolution(filepath: str) -> Optional[Tuple[int, int]]:
    out = run_ffprobe_cmd([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", filepath
    ])
    try:
        w, h = out.split('x')
        return int(w), int(h)
    except: return None

def get_video_orientation(filepath: str) -> Optional[str]:
    res = get_video_resolution(filepath)
    if not res: return None
    w, h = res
    return "vertical" if h > w else "horizontal"

def calculate_file_hash(filepath: str, chunk_size=8192) -> str:
    h = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""): h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.error(f"Hashing failed: {filepath}: {e}")
        return ""

async def get_video_duration(filepath: str) -> Optional[float]:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filepath]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, _ = await proc.communicate()
    try: return float(stdout.strip())
    except: return None

async def is_video_suitable(filepath: str) -> bool:
    file_hash = calculate_file_hash(filepath)
    if file_hash in seen_hashes:
        logger.info(f"Duplicate: {filepath}")
        return False
    seen_hashes.add(file_hash)

    duration = await get_video_duration(filepath)
    if duration is None or not (20 <= duration <= 60):
        logger.info(f"Bad duration: {duration} in {filepath}")
        return False

    audio = get_audio_channels(filepath)
    if audio is None or audio < 1:
        logger.info(f"No audio: {filepath}")
        return False

    res = get_video_resolution(filepath)
    if not res: return False
    w, h = res
    if w > 3840 or h > 2160:
        logger.info(f"Too large: {w}x{h} in {filepath}")
        return False

    if get_video_orientation(filepath) != "vertical":
        logger.info(f"Not vertical: {filepath}")
        return False

    codec = get_video_codec(filepath)
    if codec not in ("h264", "vp9"):
        logger.info(f"Bad codec {codec} in {filepath}")
        return False

    bitrate = get_video_bitrate(filepath)
    if bitrate and bitrate < 500_000:
        logger.info(f"Low bitrate {bitrate} in {filepath}")
        return False

    fps = get_video_fps(filepath)
    if fps and fps < 24:
        logger.info(f"Low FPS {fps} in {filepath}")
        return False

    return True

async def async_subreddit_top(subreddit, limit):
    return await asyncio.get_event_loop().run_in_executor(None, lambda: list(subreddit.top(time_filter="week", limit=limit)))

async def head_check_url(url: str, timeout=10) -> Optional[int]:
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://www.reddit.com/",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, headers=headers, timeout=timeout) as resp:
                if resp.status == 200:
                    sz = resp.headers.get("Content-Length")
                    return int(sz) if sz and sz.isdigit() else None
                else:
                    logger.warning(f"HEAD {resp.status}: {url}")
                    return None
    except Exception as e:
        logger.warning(f"HEAD failed {url}: {e}")
        return None

def resolve_reddit_url(short_url: str) -> str:
    try:
        resp = requests.head(short_url, allow_redirects=True, timeout=5)
        return resp.url
    except Exception as e:
        logger.warning(f"Failed to resolve {short_url}: {e}")
        return short_url

async def fetch_reddit_videos(limit_per_sub=50) -> List[Tuple[str, str]]:
    reddit = get_reddit_instance()
    results = []

    for sub in REDDIT_SUBREDDITS:
        try:
            posts = await async_subreddit_top(reddit.subreddit(sub), limit_per_sub)
            thresh = SUBREDDIT_THRESHOLDS.get(sub, {"score": 2000, "comments": 5000})

            for post in posts:
                if not post.is_video or not hasattr(post, "media"): continue
                vid = post.media.get("reddit_video", {})
                url = vid.get("fallback_url")
                if not url or url in blacklist_urls or url in download_failures:
                    continue

                size = await head_check_url(url)
                if size is None or size > 100_000_000:
                    continue

                if post.score < thresh["score"] or post.num_comments < thresh["comments"]:
                    continue
                if post.id in seen_post_ids:
                    continue

                seen_post_ids.add(post.id)
                results.append((post.id, post.title))
        except Exception as e:
            logger.error(f"{sub} fetch error: {e}")
    return results

async def download_reddit_video_with_ytdlp(post_url: str, output_dir: str) -> Optional[str]:
    post_url = resolve_reddit_url(post_url)
    id_ = post_url.rstrip('/').split("/")[-1].split("?")[0]
    output_path = os.path.join(output_dir, f"{id_}.mp4")

    user_agent = random.choice(USER_AGENTS)
    post_url += f"?x={''.join(random.choices('abcdef1234567890', k=6))}"

    cmd = (
        f"{YTDLP_PATH} --quiet --no-warnings --merge-output-format mp4 "
        f"--sleep-interval 5 --max-sleep-interval 15 --retries 5 "
        f"--add-header 'User-Agent: {user_agent}' "
        f"--add-header 'Referer: https://www.reddit.com/' "
        f"-o {shlex.quote(output_path)} {shlex.quote(post_url)}"
    )

    proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"yt-dlp failed: {stderr.decode().strip()}")
        download_failures.add(post_url)
        return None

    return output_path if os.path.exists(output_path) else None

async def scrape_video() -> Optional[Tuple[str, str]]:
    vids = await fetch_reddit_videos()
    if not vids:
        logger.warning("No Reddit videos available.")
        return None

    random.shuffle(vids)
    for vid_id, title in vids:
        url = f"https://redd.it/{vid_id}"
        logger.info(f"Trying video: {url}")
        await asyncio.sleep(random.uniform(5, 15))

        path = await download_reddit_video_with_ytdlp(url, DOWNLOAD_DIR)
        if path and await is_video_suitable(path):
            return path, title
        if path:
            try:
                os.remove(path)
                logger.info(f"Deleted: {path}")
            except Exception as e:
                logger.error(f"Cleanup failed: {e}")
    return None

def cleanup_files(paths: List[str]):
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
                logger.info(f"Deleted file: {p}")
        except Exception as e:
            logger.error(f"Delete failed: {e}")

async def check_ip_reputation():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://ipinfo.io/json") as resp:
                if resp.status != 200:
                    logger.warning("IP info unavailable")
                    return False
                ip = (await resp.json()).get("ip")
                logger.info(f"External IP: {ip}")
                return True
    except Exception as e:
        logger.warning(f"IP check failed: {e}")
        return False

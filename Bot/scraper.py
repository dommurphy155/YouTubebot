import os
import asyncio
import logging
import random
import json
from typing import Optional, Tuple, List

import praw
import aiohttp

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

DEFAULT_THRESHOLDS = {"score": 3000, "comments": 8000}

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.environ["REDDIT_USER_AGENT"]

STATE_FILE = os.path.join(DOWNLOAD_DIR, "scraper_state.json")

seen_post_ids = set()
blacklist_urls = set()
download_failures = set()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
]

def load_state():
    global seen_post_ids, blacklist_urls, download_failures
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            seen_post_ids = set(data.get("seen_post_ids", []))
            blacklist_urls = set(data.get("blacklist_urls", []))
            download_failures = set(data.get("download_failures", []))
            logger.info("Loaded scraper state from file.")
        except Exception as e:
            logger.warning(f"Failed to load scraper state: {e}")

def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "seen_post_ids": list(seen_post_ids),
                "blacklist_urls": list(blacklist_urls),
                "download_failures": list(download_failures)
            }, f)
        logger.info("Saved scraper state to file.")
    except Exception as e:
        logger.error(f"Failed to save scraper state: {e}")

def get_reddit_instance():
    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT
    )

async def async_subreddit_top(subreddit, limit):
    return await asyncio.get_event_loop().run_in_executor(
        None, lambda: list(subreddit.top(time_filter="week", limit=limit))
    )

async def fetch_reddit_videos(limit_per_sub=50) -> List[Tuple[str, str, str]]:
    reddit = get_reddit_instance()
    results = []

    for sub in REDDIT_SUBREDDITS:
        try:
            posts = await async_subreddit_top(reddit.subreddit(sub), limit_per_sub)
            thresh = SUBREDDIT_THRESHOLDS.get(sub, DEFAULT_THRESHOLDS)

            for post in posts:
                if not post.is_video or not hasattr(post, "media"):
                    continue

                vid = post.media.get("reddit_video", {})
                url = vid.get("fallback_url")
                if not url or url in blacklist_urls or url in download_failures:
                    continue
                if not url.endswith(".mp4"):
                    continue

                duration = vid.get("duration")
                if duration is None or not (15 <= duration <= 90):
                    continue

                if not vid.get("has_audio", False):
                    continue

                if post.score < thresh["score"] or post.num_comments < thresh["comments"]:
                    continue

                if post.id in seen_post_ids:
                    continue

                seen_post_ids.add(post.id)
                save_state()
                results.append((post.id, post.title, url))

        except Exception as e:
            logger.error(f"Error fetching from subreddit {sub}: {e}")

    return results

async def download_file(url: str, output_path: str, max_retries=3) -> Optional[str]:
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://www.reddit.com/",
        "Accept-Language": "en-US,en;q=0.9"
    }

    for attempt in range(1, max_retries + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=60) as resp:
                    if resp.status != 200:
                        logger.warning(f"[{resp.status}] {url}")
                        await asyncio.sleep(1)
                        continue

                    with open(output_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(65536):
                            f.write(chunk)

                    logger.info(f"Downloaded: {output_path}")
                    return output_path
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed for {url}: {e}")
            await asyncio.sleep(2 ** attempt)

    download_failures.add(url)
    save_state()
    logger.error(f"Max retries reached. Failed to download: {url}")
    return None

# Critical logic call to suitability filter
from editor import is_video_suitable

async def scrape_video() -> Optional[Tuple[str, str]]:
    attempt = 0
    while True:
        videos = await fetch_reddit_videos()
        if not videos:
            attempt += 1
            logger.warning(f"No suitable videos found. Retry attempt #{attempt}")
            continue

        random.shuffle(videos)

        for vid_id, title, url in videos:
            logger.info(f"Checking: https://redd.it/{vid_id}")
            output_path = os.path.join(DOWNLOAD_DIR, f"{vid_id}.mp4")
            await asyncio.sleep(random.uniform(2.5, 6.5))  # Humanlike

            path = await download_file(url, output_path)
            if path and is_video_suitable(path):
                return path, title

            if path:
                try:
                    os.remove(path)
                    logger.info(f"Deleted unsuitable file: {path}")
                except Exception as e:
                    logger.error(f"Delete failed: {e}")

        logger.info("Finished current batch. Instantly retrying...")

def cleanup_files(paths: List[str]):
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
                logger.info(f"Deleted file: {p}")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

async def check_ip_reputation():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://ipinfo.io/json") as resp:
                if resp.status != 200:
                    logger.warning("IP info fetch failed.")
                    return False
                ip = (await resp.json()).get("ip")
                logger.info(f"Current external IP: {ip}")
                return True
    except Exception as e:
        logger.warning(f"IP check error: {e}")
        return False

# Initialize state on module load
load_state()

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
    "PublicFreakout": {"score": 3000, "comments": 5000},  # loosened thresholds
    "Unexpected": {"score": 2000, "comments": 4000},
}

DEFAULT_THRESHOLDS = {"score": 1500, "comments": 3000}  # overall lowered thresholds

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.environ["REDDIT_USER_AGENT"]
HUGGINGFACE_API_KEY = os.environ.get("HUGGINGFACE_API_KEY")

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

async def huggingface_filter(text: str) -> bool:
    if not HUGGINGFACE_API_KEY:
        logger.warning("Hugging Face API key not set, skipping HF filter.")
        return True  # allow all if no key

    url = "https://api-inference.huggingface.co/models/facebook/bart-large-mnli"
    headers = {
        "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "inputs": text,
        "parameters": {"candidate_labels": ["funny", "viral", "fail", "epic", "crazy", "shocking", "wow", "fun", "interesting"]},
        "options": {"wait_for_model": True}
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, json=data, timeout=20) as resp:
                if resp.status != 200:
                    logger.warning(f"Hugging Face API error {resp.status}")
                    return True  # fallback: accept if API fails
                result = await resp.json()
                scores = result.get("scores", [])
                if not scores:
                    return True  # fallback allow if no scores
                if max(scores) > 0.5:  # lower threshold to allow more through
                    return True
                return False
        except Exception as e:
            logger.error(f"Hugging Face filter exception: {e}")
            return True  # fallback allow on error

async def fetch_reddit_videos(limit_per_sub=75) -> List[Tuple[str, str, str]]:
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
                # Loosen duration constraint, allow more videos
                if duration is None or not (10 <= duration <= 120):
                    continue

                # Allow videos without audio but mark for possible skipping later
                # Remove strict has_audio check to increase throughput
                # if not vid.get("has_audio", False):
                #     continue

                if post.score < thresh["score"] or post.num_comments < thresh["comments"]:
                    continue

                if post.id in seen_post_ids:
                    continue

                # Hugging Face AI filter on post title
                is_trending = await huggingface_filter(post.title)
                if not is_trending:
                    logger.info(f"Post {post.id} filtered out by HF AI filter.")
                    continue

                seen_post_ids.add(post.id)
                save_state()
                results.append((post.id, post.title, url))

        except Exception as e:
            logger.error(f"Error fetching from subreddit {sub}: {e}")

    return results

async def download_file(url: str, output_path: str, max_retries=5) -> Optional[str]:
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://www.reddit.com/",
        "Accept-Language": "en-US,en;q=0.9"
    }

    for attempt in range(1, max_retries + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=90) as resp:
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

# Import your updated is_video_suitable from editor.py
from editor import is_video_suitable

async def scrape_video() -> Optional[Tuple[str, str]]:
    while True:
        videos = await fetch_reddit_videos()
        if not videos:
            logger.warning("No suitable posts found, retrying immediately.")
            continue

        random.shuffle(videos)
        for vid_id, title, url in videos:
            logger.info(f"Checking: https://redd.it/{vid_id}")
            output_path = os.path.join(DOWNLOAD_DIR, f"{vid_id}.mp4")
            await asyncio.sleep(random.uniform(1, 2))  # reduced sleep for speed

            path = await download_file(url, output_path)
            if path and is_video_suitable(path):
                return path, title

            if path:
                try:
                    os.remove(path)
                    logger.info(f"Deleted unsuitable file: {path}")
                except Exception as e:
                    logger.error(f"Delete failed: {e}")

        logger.info("No usable videos from this batch. Looping again...")

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

# Load scraper state on boot
load_state()

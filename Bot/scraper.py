import os
import asyncio
import logging
import random
import json
from typing import Optional, Tuple, List

import praw
import aiohttp
from prawcore import ServerError, RequestException, ResponseException

logger = logging.getLogger("TelegramVideoBot")
logging.basicConfig(level=logging.INFO)

DOWNLOAD_DIR = "/home/ubuntu/YouTubebot/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

REDDIT_SUBREDDITS = [
    "PublicFreakout", "Unexpected", "WatchPeopleDieInside", "NextFuckingLevel",
    "instant_regret", "holdmyjuicebox", "blursedimages", "IdiotsInCars",
    "youtubehaiku", "ContentCreators", "NewTubers", "AskReddit", "AITA", "nosleep"
]

SUBREDDIT_THRESHOLDS = {
    "PublicFreakout": {"score": 3000, "comments": 5000},
    "Unexpected": {"score": 2000, "comments": 4000},
}
DEFAULT_THRESHOLDS = {"score": 1000, "comments": 1000}

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.environ["REDDIT_USER_AGENT"]

STATE_FILE = os.path.join(DOWNLOAD_DIR, "scraper_state.json")
seen_post_ids = set()
blacklist_urls = set()
download_failures = set()

VIDEO_EXTENSIONS = [".mp4", ".mov"]
EXCLUDED_EXTENSIONS = [
    ".gif", ".gifv", ".jpg", ".jpeg", ".png", ".webp",
    ".webm", ".tiff", ".tif", ".m3u8"
]
MIN_DURATION = 20
MAX_DURATION = 60

def load_state():
    global seen_post_ids, blacklist_urls, download_failures
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
                seen_post_ids.update(data.get("seen_post_ids", []))
                blacklist_urls.update(data.get("blacklist_urls", []))
                download_failures.update(data.get("download_failures", []))
                logger.info(f"Loaded state from {STATE_FILE}")
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")

def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "seen_post_ids": list(seen_post_ids),
                "blacklist_urls": list(blacklist_urls),
                "download_failures": list(download_failures)
            }, f)
    except Exception as e:
        logger.error(f"Error saving state: {e}")

def get_reddit():
    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT
    )

def is_valid_video_post(post) -> bool:
    if getattr(post, "is_gallery", False) or not getattr(post, "is_video", True):
        return False

    url = post.url.lower()
    if any(url.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
        return False

    try:
        if post.media and "reddit_video" in post.media:
            duration = post.media["reddit_video"].get("duration", 0)
        elif post.media and "reddit_video_preview" in post.media:
            duration = post.media["reddit_video_preview"].get("duration", 0)
        else:
            return False
    except Exception as e:
        logger.warning(f"Error extracting video duration: {e}")
        return False

    if not (MIN_DURATION <= duration <= MAX_DURATION):
        return False

    return True

async def fetch_candidates(limit=100) -> List[Tuple[str, str, str]]:
    reddit = get_reddit()
    results = []
    random.shuffle(REDDIT_SUBREDDITS)

    for sub in REDDIT_SUBREDDITS:
        for sort in ["hot", "new"]:
            retries = 0
            while retries < 3:
                try:
                    posts = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: list(getattr(reddit.subreddit(sub), sort)(limit=limit))
                    )
                    thresh = SUBREDDIT_THRESHOLDS.get(sub, DEFAULT_THRESHOLDS)

                    for post in posts:
                        if post.id in seen_post_ids or post.url in blacklist_urls:
                            continue
                        if post.score < thresh["score"] and post.num_comments < thresh["comments"]:
                            continue
                        if not is_valid_video_post(post):
                            continue

                        logger.info(f"Found candidate: {post.title} ({post.url})")
                        seen_post_ids.add(post.id)
                        results.append((post.url, post.title, post.id))
                        if len(results) >= 1:
                            return results
                    break
                except (ServerError, RequestException, ResponseException) as e:
                    retries += 1
                    logger.warning(f"Reddit API error on /r/{sub} ({sort}): {e}, retrying...")
                    await asyncio.sleep(1 + retries)
                except Exception as e:
                    logger.error(f"Unexpected error scraping /r/{sub}: {e}")
                    break
    return results

async def scrape_video() -> Optional[Tuple[str, str]]:
    while True:
        candidates = await fetch_candidates()
        if candidates:
            url, title, pid = candidates[0]
            logger.info(f"📥 Scrape picked: {pid} | {url}")
            return url, title
        logger.info("No candidates found, retrying...")
        await asyncio.sleep(0.5)

def cleanup_files(paths: List[str]):
    for p in paths:
        try:
            os.remove(p)
        except Exception:
            pass

load_state()

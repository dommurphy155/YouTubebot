import os
import asyncio
import logging
import random
import json
from typing import Optional, Tuple, List

import praw
import aiohttp
from prawcore import ServerError, RequestException

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
    "IdiotsInCars",
    "youtubehaiku",
	"ContentCreators",
	"NewTubers", 
	"AskReddit",
	"AITA",
	"nosleep",
]

SUBREDDIT_THRESHOLDS = {
    "PublicFreakout": {"score": 3000, "comments": 5000},
    "Unexpected": {"score": 2000, "comments": 4000},
}
DEFAULT_THRESHOLDS = {"score": 1000, "comments": 1000}  # Loosened

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.environ["REDDIT_USER_AGENT"]

STATE_FILE = os.path.join(DOWNLOAD_DIR, "scraper_state.json")
seen_post_ids = set()
blacklist_urls = set()
download_failures = set()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5)...",
    "Mozilla/5.0 (X11; Linux x86_64)...",
]

def load_state():
    global seen_post_ids, blacklist_urls, download_failures
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
                seen_post_ids.update(data.get("seen_post_ids", []))
                blacklist_urls.update(data.get("blacklist_urls", []))
                download_failures.update(data.get("download_failures", []))
                logger.info(f"Loaded state file: {STATE_FILE}")
        except Exception as e:
            logger.warning(f"Error loading state: {e}")

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

async def fetch_candidates(limit=100):
    reddit = get_reddit()
    results = []
    for sub in REDDIT_SUBREDDITS:
        retries = 0
        while retries < 3:
            try:
                posts = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: list(reddit.subreddit(sub).hot(limit=limit))
                )
                thresh = SUBREDDIT_THRESHOLDS.get(sub, DEFAULT_THRESHOLDS)
                for post in posts:
                    if post.id in seen_post_ids or post.url in blacklist_urls:
                        continue
                    if not hasattr(post, "is_video"):
                        continue
                    if not post.is_video and not any(
                        post.url.startswith(p) for p in ("https://v.redd.it", "https://i.redd.it", "https://youtube.com", "https://youtu.be")
                    ):
                        continue
                    if post.score < thresh["score"] and post.num_comments < thresh["comments"]:
                        continue
                    results.append((post.id, post.title, post.url))
                break  # success, exit retry loop
            except (ServerError, RequestException) as e:
                retries += 1
                wait = 2 ** retries
                logger.warning(f"Fetch error from /r/{sub}: {e} – retrying in {wait}s (attempt {retries}/3)")
                await asyncio.sleep(wait)
            except Exception as e:
                logger.error(f"Unexpected error scraping /r/{sub}: {e}")
                break  # stop retrying on unknown errors
        else:
            logger.error(f"Skipping /r/{sub} after 3 failed retries.")
    random.shuffle(results)
    return results

async def download_file(url: str, path: str, retries: int = 5) -> Optional[str]:
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=60) as resp:
                    if resp.status != 200:
                        continue
                    with open(path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 64):
                            f.write(chunk)
                    return path
        except Exception:
            await asyncio.sleep(2 ** attempt)
    return None

from editor import is_video_suitable

async def scrape_video() -> Optional[Tuple[str, str]]:
    while True:
        candidates = await fetch_candidates()
        if not candidates:
            logger.warning("No suitable posts found, retrying immediately.")
            continue  # Don't sleep — retry aggressively
        for pid, title, url in candidates:
            logger.info(f"Trying post {pid}: {url}")
            seen_post_ids.add(pid)
            save_state()
            out_path = os.path.join(DOWNLOAD_DIR, f"{pid}.mp4")
            if not await download_file(url, out_path):
                logger.warning(f"Download failed: {url}")
                download_failures.add(url)
                continue
            if is_video_suitable(out_path):
                return out_path, title
            os.remove(out_path)  # Not suitable
            logger.info(f"Rejected: {pid} — unsuitable")
        await asyncio.sleep(0.5)  # minimal backoff between rounds

def cleanup_files(paths: List[str]):
    for p in paths:
        try:
            os.remove(p)
        except:
            pass

load_state()

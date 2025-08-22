WORKING TIKTOK SCRAPER

!/usr/bin/env python3
import json
import asyncio
import time
import random
import subprocess
import os
import signal
import atexit
import shutil
import re
from collections import deque

# ensure headless to work on VPS / micro VM
os.environ["DISPLAY"] = ":99"

try:
    import psutil  # optional; used for RAM/Firefox leak control
except Exception:
    psutil = None

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
import telegram  # Import telegram to check version

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TIKTOK_COOKIES_FILE,
    OUTPUT_PATH,
    TIKTOK_HOMEPAGE,
    log,
)

log(f"Using python-telegram-bot version: {telegram.__version__}")

# ------------------- Tunables (bloat + RAM control) -------------------
NETSCAPE_COOKIES_FILE = "tiktok_cookies.txt"

PRELOAD_TARGET = 3
VIDEO_QUEUE = deque(maxlen=PRELOAD_TARGET)  # holds URLs to download
VIDEO_CACHE = deque(maxlen=3)  # holds downloaded file paths ready to play (keeps one ahead)
HISTORY_MAX = 3
SEEN_URLS_MAX = 250
SCROLL_SLEEP_RANGE = (1.0, 1.6)

OUTPUT_DISK_QUOTA_MB = int(os.getenv("OUTPUT_DISK_QUOTA_MB", "1024"))
OUTPUT_DISK_RESERVE_MB = int(os.getenv("OUTPUT_DISK_RESERVE_MB", "2048"))

JANITOR_INTERVAL_SEC = 180
BROWSER_RESTART_PRELOADS = 200
MEM_SOFT_LIMIT_MB = int(os.getenv("MEM_SOFT_LIMIT_MB", "1200"))

# ------------------- Globals -------------------
BROWSER_DRIVER = None
PRELOADING_LOCK = asyncio.Lock()
PRELOADED_VIDEOS = set()
SEEN_URLS = deque()
PLAYED_VIDEOS = []  # file paths already played (history)
CURRENT_INDEX = -1
PRELOAD_COUNTER = 0

# metadata storage: video_path -> metadata dict (duration, caption, hashtags)
METADATA_BY_PATH = {}

# pending post flows keyed by chat_id
PENDING_POSTS = {}  # chat_id -> dict {stage:int, video_path:str, comment:str, hashtags:str, prompt_msg_ids:[]}

# ------------------- Utils -------------------
def safe_delete(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
            log(f"Deleted file: {path}")
    except Exception as e:
        log(f"[WARNING] Failed to delete {path}: {e}")


def _keep_set():
    return set(PLAYED_VIDEOS) | set(VIDEO_CACHE)


def cleanup_files():
    try:
        keep = _keep_set()
        if not os.path.isdir(OUTPUT_PATH):
            return
        for name in os.listdir(OUTPUT_PATH):
            if not name.lower().endswith(".mp4"):
                continue
            candidate = os.path.join(OUTPUT_PATH, name)
            if candidate not in keep:
                safe_delete(candidate)
    except Exception as e:
        log(f"[WARNING] cleanup_files failed: {e}")


def prune_seen_urls_if_needed():
    while len(SEEN_URLS) > SEEN_URLS_MAX:
        oldest = SEEN_URLS.popleft()
        PRELOADED_VIDEOS.discard(oldest)


def add_seen_url(href: str):
    if href in PRELOADED_VIDEOS:
        return
    if len(SEEN_URLS) >= SEEN_URLS_MAX:
        oldest = SEEN_URLS.popleft()
        PRELOADED_VIDEOS.discard(oldest)
    PRELOADED_VIDEOS.add(href)
    SEEN_URLS.append(href)


def push_played_video(path: str, update_index=True):
    """Add a video to played history and keep index sane."""
    global CURRENT_INDEX
    PLAYED_VIDEOS.append(path)
    if len(PLAYED_VIDEOS) > HISTORY_MAX:
        evicted = PLAYED_VIDEOS.pop(0)
        if evicted != path:
            safe_delete(evicted)
        if CURRENT_INDEX > 0:
            CURRENT_INDEX -= 1
    if update_index:
        CURRENT_INDEX = len(PLAYED_VIDEOS) - 1
    cleanup_files()


def folder_size_bytes(folder: str) -> int:
    total = 0
    try:
        for entry in os.scandir(folder):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
    except Exception:
        pass
    return total


def enforce_disk_budget():
    try:
        if not os.path.isdir(OUTPUT_PATH):
            return
        cleanup_files()
        quota_bytes = OUTPUT_DISK_QUOTA_MB * 1024 * 1024
        reserve_bytes = OUTPUT_DISK_RESERVE_MB * 1024 * 1024
        folder_bytes = folder_size_bytes(OUTPUT_PATH)

        def constraints_ok() -> bool:
            u = shutil.disk_usage(OUTPUT_PATH)
            return (folder_bytes <= quota_bytes) and (u.free >= reserve_bytes)

        safety_counter = 0
        while not constraints_ok():
            safety_counter += 1
            if safety_counter > 100:
                log("[WARNING] Disk janitor safety stop hit.")
                break
            if len(PLAYED_VIDEOS) > 0:
                current_path = (
                    PLAYED_VIDEOS[CURRENT_INDEX]
                    if 0 <= CURRENT_INDEX < len(PLAYED_VIDEOS)
                    else None
                )
                did_delete = False
                while len(PLAYED_VIDEOS) > 0:
                    oldest = PLAYED_VIDEOS[0]
                    if oldest == current_path and len(PLAYED_VIDEOS) == 1:
                        break
                    if oldest == current_path:
                        if len(PLAYED_VIDEOS) >= 2:
                            second = PLAYED_VIDEOS[1]
                            PLAYED_VIDEOS.pop(1)
                            safe_delete(second)
                            did_delete = True
                            break
                        else:
                            break
                    else:
                        PLAYED_VIDEOS.pop(0)
                        safe_delete(oldest)
                        if CURRENT_INDEX > 0:
                            CURRENT_INDEX -= 1
                        did_delete = True
                        break
                if did_delete:
                    continue
            if len(VIDEO_CACHE) > 0:
                old_file = VIDEO_CACHE.popleft()
                protect = set(PLAYED_VIDEOS)
                if old_file not in protect:
                    safe_delete(old_file)
                continue
            keep = _keep_set()
            candidates = []
            for name in os.listdir(OUTPUT_PATH):
                if name.lower().endswith(".mp4"):
                    p = os.path.join(OUTPUT_PATH, name)
                    if p not in keep:
                        candidates.append(p)
            if candidates:
                candidates.sort(key=lambda p: os.stat(p).st_mtime)
                safe_delete(candidates[0])
            else:
                break
    except Exception as e:
        log(f"[WARNING] enforce_disk_budget failed: {e}")


def current_process_rss_mb() -> int:
    if not psutil:
        return -1
    try:
        p = psutil.Process(os.getpid())
        return int(p.memory_info().rss / (1024 * 1024))
    except Exception:
        return -1


# ------------------- TikTok Scraper -------------------
def convert_json_to_netscape(json_file, txt_file):
    log(f"Converting JSON cookies {json_file} to Netscape format {txt_file}...")
    with open(json_file, "r") as f:
        cookies = json.load(f)
    with open(txt_file, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for c in cookies:
            domain = c.get("domain", ".tiktok.com")
            include_subdomains = "TRUE"
            path = c.get("path", "/")
            secure = "TRUE" if c.get("secure", False) else "FALSE"
            expiration = str(int(c.get("expiry", 2147483647)))
            name = c["name"]
            value = c["value"]
            f.write(
                "\t".join([domain, include_subdomains, path, secure, expiration, name, value]) + "\n"
            )
    log("Cookie conversion completed.")


def load_cookies():
    log("Loading cookies from file...")
    with open(TIKTOK_COOKIES_FILE, "r") as f:
        cookies = json.load(f)
    log(f"Loaded {len(cookies)} cookies")
    return cookies


def setup_browser():
    """Start Firefox WebDriver in headless mode."""
    firefox_options = Options()
    firefox_options.add_argument("--no-sandbox")
    firefox_options.add_argument("--disable-dev-shm-usage")
    # prefer explicit width/height args for older geckodriver compatibility
    firefox_options.add_argument("--width=1200")
    firefox_options.add_argument("--height=900")
    firefox_options.headless = False
    try:
        driver = webdriver.Firefox(service=Service("/usr/bin/geckodriver"), options=firefox_options)
        log("Firefox WebDriver started")
        return driver
    except WebDriverException as e:
        log(f"[ERROR] Failed to start Firefox WebDriver: {e}")
        raise


def apply_cookies(driver, cookies, url=TIKTOK_HOMEPAGE):
    """
    Apply cookies directly by navigating to `url` and calling add_cookie() for each cookie.
    This function will be called once on startup (per user's request).
    """
    driver.get(url)
    for cookie in cookies:
        cookie_dict = {
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": cookie.get("domain", "https://www.tiktok.com/?lang=en-GB"),
            "path": cookie.get("path", "/"),
            "secure": cookie.get("secure", True),
            "httpOnly": cookie.get("httpOnly", False),
        }
        try:
            driver.add_cookie(cookie_dict)
        except Exception as e:
            log(f"[ERROR] Failed to add cookie {cookie.get('name', '<unknown>')}: {e}")
    driver.refresh()
    log("All cookies applied.")


def get_fresh_video_link(driver, retries=5, scroll=True):
    """
    Keep legacy behavior for finding links via Selenium, but note:
    you can replace this with a yt-dlp based scraper later if you prefer.
    """
    global PRELOAD_COUNTER
    for attempt in range(retries):
        try:
            if scroll:
                driver.execute_script(f"window.scrollBy(0, {random.randint(400, 1200)});")
                time.sleep(random.uniform(*SCROLL_SLEEP_RANGE))
            videos = driver.find_elements(By.XPATH, "//a[contains(@href, '/video/')]")
            random.shuffle(videos)
            for video_link in videos:
                href = video_link.get_attribute("href")
                if href and href not in PRELOADED_VIDEOS:
                    add_seen_url(href)
                    log(f"Found video link: {href}")
                    prune_seen_urls_if_needed()
                    PRELOAD_COUNTER += 1
                    return href
        except TimeoutException:
            log(f"[WARNING] Attempt {attempt + 1} failed to find video link.")
        if attempt % 2 == 0:
            driver.refresh()
            time.sleep(1.2)
    raise Exception("Failed to locate unique video link after retries")


def extract_video_metadata(video_url, timeout_sec=15):
    """
    Extract metadata using yt-dlp --dump-json.
    Return a dict with keys: duration (float), caption (str), hashtags (list[str]).
    If extraction fails, return None.
    """
    try:
        cmd = ["yt-dlp", "--dump-json", "--cookies", NETSCAPE_COOKIES_FILE, video_url]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout_sec)
        metadata = json.loads(result.stdout)
        duration = float(metadata.get("duration", 0) or 0)
        description = metadata.get("description", "") or ""
        tags = metadata.get("tags", []) or []
        description_hashtags = re.findall(r"#\w+", description)
        tags_hash = [t for t in tags if isinstance(t, str) and t.startswith("#")]
        hashtags = list(dict.fromkeys(description_hashtags + tags_hash))
        return {"duration": duration, "caption": description.strip(), "hashtags": hashtags}
    except subprocess.TimeoutExpired:
        log(f"[ERROR] yt-dlp timed out extracting metadata for {video_url}")
        return None
    except subprocess.CalledProcessError as cpe:
        log(f"[ERROR] yt-dlp returned non-zero for metadata {video_url}: {cpe}")
        return None
    except Exception as e:
        log(f"[ERROR] Failed to extract metadata for {video_url}: {e}")
        return None


def download_video(video_url, output_folder):
    """
    Downloads video using yt-dlp and attempts to extract metadata.
    Returns a tuple (output_path, metadata_dict_or_None) on success, or None on failure.
    Important: will not abort just because metadata extraction fails.
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    # ensure cache churn
    if len(VIDEO_CACHE) == VIDEO_CACHE.maxlen:
        old_file = VIDEO_CACHE.popleft()
        safe_delete(old_file)
        METADATA_BY_PATH.pop(old_file, None)

    # attempt to get metadata (non-blocking failure tolerated)
    metadata = extract_video_metadata(video_url, timeout_sec=12)

    # If metadata exists and duration is outside bounds, skip
    if metadata and not (5 <= metadata.get("duration", 0) <= 50):
        log(f"[INFO] Skipping {video_url}: Duration {metadata.get('duration', 0):.1f}s not in 5-50s")
        return None

    video_id = video_url.rstrip("/").split("/")[-1]
    output_path = os.path.join(output_folder, f"{video_id}.mp4")
    cmd = [
        "yt-dlp",
        "--no-part",
        "--no-mtime",
        "--cookies",
        NETSCAPE_COOKIES_FILE,
        "-o",
        output_path,
        video_url,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=180)
        file_size = os.path.getsize(output_path) / (1024 * 1024)
        log(f"Video downloaded successfully to {output_path} ({file_size:.2f} MB)")
        if file_size > 50:
            log(f"[WARNING] Large video file ({file_size:.2f} MB) may slow Telegram upload")
    except subprocess.TimeoutExpired:
        log(f"[ERROR] yt-dlp timed out downloading {video_url}")
        return None
    except subprocess.CalledProcessError as cpe:
        log(f"[ERROR] yt-dlp returned error downloading {video_url}: {cpe}")
        return None
    except Exception as e:
        log(f"[ERROR] Failed to download video {video_url}: {e}")
        return None

    # store metadata for this path (may be None)
    METADATA_BY_PATH[output_path] = metadata or {"duration": None, "caption": "", "hashtags": []}
    # append to ready cache (this keeps "one ahead")
    VIDEO_CACHE.append(output_path)
    cleanup_files()
    enforce_disk_budget()
    return output_path, METADATA_BY_PATH[output_path]


# ------------------- Preload Videos -------------------
async def _recycle_browser_if_needed():
    global PRELOAD_COUNTER, BROWSER_DRIVER
    try:
        rss_mb = current_process_rss_mb() if psutil else -1
        need_restart = False
        if BROWSER_RESTART_PRELOADS > 0 and PRELOAD_COUNTER >= BROWSER_RESTART_PRELOADS:
            need_restart = True
            log(f"[INFO] Recycling Firefox after {PRELOAD_COUNTER} preloads")
        if rss_mb > 0 and rss_mb >= MEM_SOFT_LIMIT_MB:
            need_restart = True
            log(f"[INFO] Recycling Firefox due to RSS {rss_mb} MB >= {MEM_SOFT_LIMIT_MB} MB")
        if need_restart:
            _shutdown_driver()
            await asyncio.sleep(0.5)
            BROWSER_DRIVER = setup_browser()
            cookies = load_cookies()
            apply_cookies(BROWSER_DRIVER, cookies, TIKTOK_HOMEPAGE)
            PRELOAD_COUNTER = 0
    except Exception as e:
        log(f"[WARNING] Browser recycle failed: {e}")


async def init_browser_and_queue(n=PRELOAD_TARGET):
    """
    Startup sequence:
      - launch browser
      - load cookies and apply them once
      - convert json cookies to netscape file once (after cookies applied)
      - fill VIDEO_QUEUE with n URLs using Selenium scraping (legacy behaviour)
    """
    global BROWSER_DRIVER
    BROWSER_DRIVER = setup_browser()
    cookies = load_cookies()
    apply_cookies(BROWSER_DRIVER, cookies, TIKTOK_HOMEPAGE)
    # convert only once after cookies applied
    convert_json_to_netscape(TIKTOK_COOKIES_FILE, NETSCAPE_COOKIES_FILE)

    # find URLs with Selenium (keeps your original behaviour)
    while len(VIDEO_QUEUE) < n:
        video_url = get_fresh_video_link(BROWSER_DRIVER)
        VIDEO_QUEUE.append(video_url)
    log(f"Preloaded {len(VIDEO_QUEUE)} videos.")


async def preload_one_video_async():
    async with PRELOADING_LOCK:
        global BROWSER_DRIVER
        if BROWSER_DRIVER is None:
            BROWSER_DRIVER = setup_browser()
            cookies = load_cookies()
            apply_cookies(BROWSER_DRIVER, cookies, TIKTOK_HOMEPAGE)
        await _recycle_browser_if_needed()
        # always try to keep at least one downloaded ready
        if VIDEO_QUEUE:
            video_url = VIDEO_QUEUE.popleft()
            res = download_video(video_url, OUTPUT_PATH)
            if res:
                path, meta = res
                log("Added new video to ready cache")
        # ensure there are always URLs queued for future downloads
        while len(VIDEO_QUEUE) < 1:
            next_url = get_fresh_video_link(BROWSER_DRIVER)
            VIDEO_QUEUE.append(next_url)
            log("Added new video URL to queue")


async def pre_download_task():
    """
    Always keep one downloaded video ready in VIDEO_CACHE.
    When VIDEO_CACHE length drops below 1, download the next URL.
    """
    while True:
        try:
            async with PRELOADING_LOCK:
                # ensure at least one ready download exists
                if len(VIDEO_CACHE) < 1 and VIDEO_QUEUE:
                    next_video_url = VIDEO_QUEUE.popleft()
                    res = download_video(next_video_url, OUTPUT_PATH)
                    if res:
                        path, meta = res
                        log(f"Pre-downloaded next video: {path}")
                # ensure VIDEO_QUEUE is replenished
                while len(VIDEO_QUEUE) < PRELOAD_TARGET:
                    # find more URLs from the browser
                    candidate = get_fresh_video_link(BROWSER_DRIVER)
                    VIDEO_QUEUE.append(candidate)
                    log("Added new video URL to queue")
            await asyncio.sleep(1.0)
        except Exception as e:
            log(f"[WARNING] pre_download_task failed: {e}")
            await asyncio.sleep(5.0)


# ------------------- Posting helper (Selenium) -------------------
def blocking_post_video(driver, video_path, caption, hashtags):
    """
    Blocking function that uses Selenium to post to TikTok.
    Designed to be executed in a thread via asyncio.to_thread.
    """
    try:
        driver.get(TIKTOK_HOMEPAGE)
        wait = WebDriverWait(driver, 15)
        time.sleep(random.uniform(1, 2))

        # file input
        file_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]')))
        file_input.send_keys(video_path)
        time.sleep(random.uniform(2, 4))

        # caption (contenteditable)
        caption_elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[contenteditable="true"]')))
        full_caption = (caption or "") + " " + " ".join(hashtags or [])
        # type humanly
        for ch in full_caption:
            caption_elem.send_keys(ch)
            time.sleep(random.uniform(0.02, 0.08))

        time.sleep(random.uniform(1, 3))
        post_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "Post")]')))
        post_button.click()
        time.sleep(5)
        log(f"Posted video {video_path} via Selenium.")
        return True
    except Exception as e:
        log(f"[ERROR] blocking_post_video failed: {e}")
        return False


# ------------------- Telegram Bot -------------------
async def send_video(bot, chat_id, video_path, index, caption=None):
    """
    Send a video over Telegram. Include metadata caption and hashtags if available.
    Add Next / Previous / Post buttons.
    """
    start_time = time.time()
    if not os.path.exists(video_path):
        log(f"[ERROR] Video file {video_path} does not exist")
        return None

    # pull metadata if we stored it during download; otherwise attempt a best-effort extract
    metadata = METADATA_BY_PATH.get(video_path)
    if not metadata:
        # best-effort try to derive URL and extract (fast)
        video_id = os.path.basename(video_path).replace(".mp4", "")
        video_url = f"https://www.tiktok.com/video/{video_id}"
        metadata = extract_video_metadata(video_url, timeout_sec=8) or {"caption": "", "hashtags": []}
        METADATA_BY_PATH[video_path] = metadata

    caption_text_parts = []
    if caption:
        caption_text_parts.append(caption)
    if metadata and metadata.get("caption"):
        caption_text_parts.append(f"Original Caption: {metadata.get('caption')}")
    if metadata and metadata.get("hashtags"):
        caption_text_parts.append(f"Hashtags: {' '.join(metadata.get('hashtags'))}")
    caption_text = "\n\n".join(caption_text_parts) if caption_text_parts else None

    buttons_row = []
    if index > 0:
        buttons_row.append(InlineKeyboardButton("◀️ Previous", callback_data="prev_video"))
    buttons_row.append(InlineKeyboardButton("Post ⬆️", callback_data="post_video"))
    buttons_row.append(InlineKeyboardButton("Next ▶️", callback_data="next_video"))
    markup = InlineKeyboardMarkup([buttons_row])

    for attempt in range(3):  # Up to 3 attempts
        try:
            log(f"Opening file {video_path} (attempt {attempt + 1})...")
            with open(video_path, "rb") as f:
                log(f"File opened in {time.time() - start_time:.2f} seconds")
                msg = await bot.send_video(chat_id=chat_id, video=f, reply_markup=markup, caption=caption_text)
            log(f"Sent video {video_path} in {time.time() - start_time:.2f} seconds")
            return msg.message_id
        except Exception as e:
            log(f"[ERROR] Failed to send video {video_path} (attempt {attempt + 1}): {e}")
            if attempt < 2:
                log("Retrying send_video...")
                await asyncio.sleep(1.0)
            continue
    log(f"[ERROR] Failed to send video {video_path} after 3 attempts")
    return None


async def _handle_next_action(bot):
    """
    Internal helper to perform the 'next' action: move next file from VIDEO_CACHE into PLAYED_VIDEOS
    and send it to Telegram.
    """
    global CURRENT_INDEX
    if len(VIDEO_CACHE) > 0:
        next_path = VIDEO_CACHE.popleft()
        push_played_video(next_path, update_index=True)
        log(f"Moved ready video to played: {next_path}")
    else:
        if VIDEO_QUEUE:
            next_url = VIDEO_QUEUE.popleft()
            res = download_video(next_url, OUTPUT_PATH)
            if res:
                path, _meta = res
                push_played_video(path, update_index=True)
                log(f"Downloaded and moved to played for Next: {path}")
            else:
                log("[WARNING] Failed to download fallback next video")
                return
        else:
            log("[WARNING] No URL in queue for Next")
            return

    if 0 <= CURRENT_INDEX < len(PLAYED_VIDEOS):
        await send_video(bot, TELEGRAM_CHAT_ID, PLAYED_VIDEOS[CURRENT_INDEX], CURRENT_INDEX)


async def navigation_callback(update, context):
    """
    Handle Next/Previous/Post/Post-Next button presses.
    """
    global CURRENT_INDEX
    start_time = time.time()
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    # For navigation and post actions we delete the invoking message (video or processing)
    try:
        await query.message.delete()
    except Exception:
        log(f"[WARNING] Failed to delete invoking message")

    # NEXT
    if query.data == "next_video":
        await _handle_next_action(context.bot)
        log(f"Navigation completed in {time.time() - start_time:.2f} seconds")
        return

    # PREVIOUS
    if query.data == "prev_video":
        if CURRENT_INDEX > 0:
            CURRENT_INDEX -= 1
            log(f"Moving to previous video at index {CURRENT_INDEX}")
            if 0 <= CURRENT_INDEX < len(PLAYED_VIDEOS):
                await send_video(context.bot, TELEGRAM_CHAT_ID, PLAYED_VIDEOS[CURRENT_INDEX], CURRENT_INDEX)
        else:
            log("[WARNING] Already at the first video")
        return

    # POST: start the post conversation
    if query.data == "post_video":
        # delete the video message already attempted above
        # Validate current index
        if 0 <= CURRENT_INDEX < len(PLAYED_VIDEOS):
            video_path = PLAYED_VIDEOS[CURRENT_INDEX]
            # initialize pending flow for this chat
            chat_id = query.message.chat.id if query.message and query.message.chat else TELEGRAM_CHAT_ID
            PENDING_POSTS[chat_id] = {
                "stage": 1,
                "video_path": video_path,
                "comment": None,
                "hashtags": None,
                "prompt_msg_ids": [],
            }
            # ask first question
            msg = await context.bot.send_message(chat_id=chat_id, text="What would you like to comment?")
            PENDING_POSTS[chat_id]["prompt_msg_ids"].append(msg.message_id)
        else:
            log("[WARNING] No current video to post")
        return

    # POST_NEXT: delete processing message (the query.message) and then send next video
    if query.data == "post_next":
        # query.message already deleted above
        await _handle_next_action(context.bot)
        return


async def text_message_handler(update, context):
    """
    Handle user replies to the post flow prompts.
    """
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = chat.id
    if chat_id not in PENDING_POSTS:
        return  # ignore unrelated messages

    flow = PENDING_POSTS[chat_id]
    stage = flow.get("stage", 1)

    # Stage 1: receive comment
    if stage == 1:
        # store comment
        flow["comment"] = update.message.text or ""
        # delete the prompt message(s)
        for mid in flow.get("prompt_msg_ids", []):
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass
        flow["prompt_msg_ids"] = []
        # ask for hashtags
        msg = await context.bot.send_message(chat_id=chat_id, text="What would you like as your #?")
        flow["prompt_msg_ids"].append(msg.message_id)
        flow["stage"] = 2
        return

    # Stage 2: receive hashtags
    if stage == 2:
        flow["hashtags"] = update.message.text or ""
        # delete the prompt message(s)
        for mid in flow.get("prompt_msg_ids", []):
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass
        flow["prompt_msg_ids"] = []
        flow["stage"] = 3

        # send processing message with inline Next button
        next_button = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Next ▶️", callback_data="post_next")]]
        )
        processing_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="Your post is now processing. Please check your TikTok shortly to confirm.",
            reply_markup=next_button,
        )
        # store processing message id in case we need to delete later (post_next will delete it)
        flow["processing_msg_id"] = processing_msg.message_id

        # in background, perform actual post via Selenium (non-blocking)
        video_path = flow.get("video_path")
        comment = flow.get("comment") or ""
        hashtags_raw = flow.get("hashtags") or ""
        # derive hashtag list (split by spaces, keep tokens starting with #, or send whole string)
        hashtags_list = [t for t in re.split(r"\s+", hashtags_raw) if t]
        # fire-and-forget background post
        async def do_post():
            try:
                # run blocking selenium post in a thread
                ok = await asyncio.to_thread(blocking_post_video, BROWSER_DRIVER, video_path, comment, hashtags_list)
                if ok:
                    log(f"[INFO] Background post succeeded for {video_path}")
                else:
                    log(f"[WARNING] Background post failed for {video_path}")
            except Exception as e:
                log(f"[ERROR] do_post background raised: {e}")

        asyncio.create_task(do_post())

        # clear PENDING_POSTS only when user clicks Next (handled in post_next)
        return

    # Stage 3: waiting for user to click Next — ignore textual messages
    return


# ------------------- Janitor Task -------------------
async def janitor_task():
    while True:
        try:
            cleanup_files()
            enforce_disk_budget()
            prune_seen_urls_if_needed()
            await _recycle_browser_if_needed()
        except Exception as e:
            log(f"[WARNING] janitor_task failed: {e}")
        await asyncio.sleep(JANITOR_INTERVAL_SEC)


# ------------------- Graceful shutdown -------------------
def _shutdown_driver():
    global BROWSER_DRIVER
    try:
        if BROWSER_DRIVER is not None:
            BROWSER_DRIVER.quit()
            BROWSER_DRIVER = None
            log("Firefox WebDriver closed")
    except Exception as e:
        log(f"[WARNING] Failed to close WebDriver: {e}")


def _handle_exit(*_args):
    try:
        cleanup_files()
    finally:
        _shutdown_driver()


atexit.register(_handle_exit)
signal.signal(signal.SIGINT, _handle_exit)
signal.signal(signal.SIGTERM, _handle_exit)


# ------------------- Main -------------------
def main():
    global CURRENT_INDEX
    log("Starting TikTok downloader with Telegram bot...")
    loop = asyncio.get_event_loop()
    # init browser, apply cookies once, convert cookies once, and preload URLs
    loop.run_until_complete(init_browser_and_queue(PRELOAD_TARGET))

    # After init, download first two items so we have immediate send + one ready
    if len(VIDEO_QUEUE) >= 1:
        first_url = VIDEO_QUEUE.popleft()
        res1 = download_video(first_url, OUTPUT_PATH)
        if res1:
            first_path, _meta1 = res1
            push_played_video(first_path, update_index=True)
        else:
            log("[ERROR] Failed to download first video at startup")
            return
    else:
        log("[ERROR] No videos queued at startup (first)")
        return

    if len(VIDEO_QUEUE) >= 1:
        second_url = VIDEO_QUEUE.popleft()
        res2 = download_video(second_url, OUTPUT_PATH)
        if res2:
            second_path, _meta2 = res2
            # keep second video in VIDEO_CACHE ready (do NOT push to played)
            log("Second video downloaded and kept ready for immediate 'Next'")
        else:
            log("[WARNING] Failed to download second startup video")
    else:
        log("[WARNING] Not enough preloaded URLs to download second startup video")

    # ensure a third url is queued/downloaded by pre_download_task to maintain pipeline
    while len(VIDEO_QUEUE) < 1:
        # refill URLs if necessary
        try:
            candidate = get_fresh_video_link(BROWSER_DRIVER)
            VIDEO_QUEUE.append(candidate)
        except Exception:
            break

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    # handle nav + post callbacks
    app.add_handler(
        CallbackQueryHandler(
            navigation_callback, pattern="^(next_video|prev_video|post_video|post_next)$"
        )
    )
    # message handler for collecting post comments/hashtags
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_message_handler))

    # schedule background tasks
    loop.create_task(pre_download_task())
    loop.create_task(janitor_task())

    # send first video on startup if available
    if 0 <= CURRENT_INDEX < len(PLAYED_VIDEOS):
        startup_message = (
            "Welcome to your TikTok Video Scraper! 🎉 "
            "Enjoy seamless browsing of fresh TikTok content with our intuitive 'Next' and 'Previous' buttons. "
            "Please note that video sending may take up to 10 seconds due to Telegram's processing."
        )
        loop.create_task(send_video(app.bot, TELEGRAM_CHAT_ID, PLAYED_VIDEOS[CURRENT_INDEX], CURRENT_INDEX, caption=startup_message))
    else:
        log("[ERROR] No first video to send at startup")

    cleanup_files()
    enforce_disk_budget()
    app.run_polling()
    _handle_exit()


if __name__ == "__main__":
    main()

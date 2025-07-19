import os
import asyncio
import subprocess
import random
import signal
import sys
import json
import shutil
from pathlib import Path
import pyttsx3
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from concurrent.futures import ThreadPoolExecutor
import logging

# --- CONFIGURABLE PARAMETERS via ENV VARS ---
MAX_VIDEO_DOWNLOADS = int(os.getenv("MAX_VIDEO_DOWNLOADS", "50"))
MAX_MUSIC_DOWNLOADS = int(os.getenv("MAX_MUSIC_DOWNLOADS", "30"))
MAX_VOICEOVERS = int(os.getenv("MAX_VOICEOVERS", "30"))
MIN_VIDEO_DURATION = int(os.getenv("MIN_VIDEO_DURATION", "1"))
MAX_VIDEO_DURATION = int(os.getenv("MAX_VIDEO_DURATION", "60"))
CONCURRENT_DOWNLOADS = int(os.getenv("CONCURRENT_DOWNLOADS", "3"))
MIN_DELAY_BETWEEN_DOWNLOADS = float(os.getenv("MIN_DELAY_BETWEEN_DOWNLOADS", "1.0"))
MAX_DELAY_BETWEEN_DOWNLOADS = float(os.getenv("MAX_DELAY_BETWEEN_DOWNLOADS", "5.0"))
MIN_FREE_DISK_GB = float(os.getenv("MIN_FREE_DISK_GB", "1.0"))  # abort if free disk below this

# --- PATHS ---
CLIPS_DIR = Path("clips")
MUSIC_DIR = Path("music")
VOICE_DIR = Path("voiceovers")
STATE_FILE = Path("download_state.json")

CLIPS_DIR.mkdir(exist_ok=True)
MUSIC_DIR.mkdir(exist_ok=True)
VOICE_DIR.mkdir(exist_ok=True)

# --- CONSTANTS ---
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
)

ROYALTY_FREE_CLIP_PLAYLISTS = [
    "https://www.youtube.com/playlist?list=PLrEnWoR732-BHrPp_Pm8_VleD68f9s14-",
]

ROYALTY_FREE_MUSIC_PLAYLISTS = [
    "https://www.youtube.com/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj",
]

# --- SETUP LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s %(message)s",
    handlers=[
        logging.FileHandler("download_assets.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

# --- GLOBALS ---
shutdown_requested = False
download_semaphore = asyncio.Semaphore(CONCURRENT_DOWNLOADS)


def save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
        logging.info("Saved state file.")
    except Exception as e:
        logging.error(f"Failed to save state: {e}")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            logging.info("Loaded existing state file.")
            return state
        except Exception as e:
            logging.error(f"Failed to load state file: {e}")
    return {"videos": [], "music": [], "voiceovers": []}


def check_disk_space(path: Path) -> bool:
    total, used, free = shutil.disk_usage(str(path))
    free_gb = free / (1024**3)
    if free_gb < MIN_FREE_DISK_GB:
        logging.error(f"Low disk space: {free_gb:.2f} GB free, required {MIN_FREE_DISK_GB} GB minimum.")
        return False
    return True


def cleanup_partial_file(filepath: Path):
    # Remove if file exists but is <100KB (likely partial/corrupt)
    if filepath.exists() and filepath.stat().st_size < 100 * 1024:
        try:
            filepath.unlink()
            logging.info(f"Removed partial/corrupt file {filepath}")
        except Exception as e:
            logging.error(f"Failed to remove partial file {filepath}: {e}")


def verify_media_file(filepath: Path) -> bool:
    if not filepath.exists():
        return False
    try:
        # Use ffprobe to check media file integrity; must be installed on system
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(filepath),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        duration = float(result.stdout.strip())
        if duration > 0:
            return True
        else:
            logging.warning(f"ffprobe reported zero duration for {filepath}")
            return False
    except Exception as e:
        logging.warning(f"Media file verification failed for {filepath}: {e}")
        return False


# Custom exception to retry on
class YtDlpTransientError(Exception):
    pass


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(YtDlpTransientError),
    reraise=True,
)
async def run_yt_dlp_cmd(args: list[str]) -> str:
    if not check_disk_space(CLIPS_DIR):
        raise RuntimeError("Disk space below threshold, aborting yt-dlp run.")
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logging.warning(f"yt-dlp command timed out: {' '.join(args)}")
        raise YtDlpTransientError("Timeout during yt-dlp execution")

    if proc.returncode != 0:
        err_str = stderr.decode().strip()
        logging.warning(f"yt-dlp error ({proc.returncode}): {err_str}")
        transient_keywords = [
            "sign in", "captcha", "login", "cookie", "blocked",
            "forbidden", "error 429", "temporarily unavailable",
            "network error", "timed out", "connection reset"
        ]
        if any(keyword in err_str.lower() for keyword in transient_keywords):
            raise YtDlpTransientError(err_str)
        raise RuntimeError(f"yt-dlp failed: {err_str}")
    return stdout.decode()


async def fetch_playlist_videos(playlist_url: str) -> list[dict]:
    try:
        output = await run_yt_dlp_cmd(
            [
                "--flat-playlist",
                "-j",
                playlist_url,
                "--user-agent",
                USER_AGENT,
                "--no-check-certificate",
                "--skip-download",
            ]
        )
        videos = []
        for line in output.splitlines():
            try:
                videos.append(json.loads(line))
            except Exception:
                continue
        return videos
    except Exception as e:
        logging.error(f"Failed to fetch playlist {playlist_url}: {e}")
        return []


async def fetch_video_metadata(video_url: str) -> dict | None:
    try:
        output = await run_yt_dlp_cmd(
            [
                "-j",
                video_url,
                "--user-agent",
                USER_AGENT,
                "--no-check-certificate",
                "--skip-download",
            ]
        )
        meta = json.loads(output)
        if meta.get("is_private") or meta.get("is_unavailable") or meta.get("age_limit", 0) > 18:
            return None
        if meta.get("requested_formats") is None and meta.get("formats") is None:
            return None
        return meta
    except YtDlpTransientError:
        raise
    except Exception as e:
        logging.warning(f"Failed to fetch metadata for {video_url}: {e}")
        return None


async def download_video(video_url: str, filename: Path) -> None:
    async with download_semaphore:
        cleanup_partial_file(filename)
        args = [
            "-f",
            "mp4",
            "-o",
            str(filename),
            video_url,
            "--user-agent",
            USER_AGENT,
            "--no-check-certificate",
            "--write-info-json",
            "--write-sub",
            "--write-auto-sub",
            "--embed-subs",
            "--embed-thumbnail",
            "--write-thumbnail",
            "--continue",
        ]
        await run_yt_dlp_cmd(args)

        if not verify_media_file(filename):
            logging.warning(f"File verification failed after download: {filename}")
            filename.unlink(missing_ok=True)
            raise YtDlpTransientError("Corrupt or incomplete video file")


async def download_audio(audio_url: str, filename: Path) -> None:
    async with download_semaphore:
        cleanup_partial_file(filename)
        args = [
            "-x",
            "--audio-format",
            "mp3",
            "-o",
            str(filename),
            audio_url,
            "--user-agent",
            USER_AGENT,
            "--no-check-certificate",
            "--continue",
        ]
        await run_yt_dlp_cmd(args)

        if not verify_media_file(filename):
            logging.warning(f"File verification failed after download: {filename}")
            filename.unlink(missing_ok=True)
            raise YtDlpTransientError("Corrupt or incomplete audio file")


def generate_voiceover_file(quote: str, filename: Path) -> None:
    engine = pyttsx3.init()
    engine.setProperty("rate", 150)
    voices = engine.getProperty("voices")
    if voices:
        engine.setProperty("voice", voices[0].id)
    engine.save_to_file(quote, str(filename))
    engine.runAndWait()


async def download_videos(
    output_dir: Path, playlists: list[str], count: int, min_duration=1, max_duration=60
) -> None:
    logging.info(f"Starting download of up to {count} shorts into {output_dir}...")
    state = load_state()
    downloaded = 0
    failed = []

    for playlist_url in playlists:
        if shutdown_requested or downloaded >= count:
            break
        videos_info = await fetch_playlist_videos(playlist_url)
        random.shuffle(videos_info)

        for video in videos_info:
            if shutdown_requested or downloaded >= count:
                break
            vid_id = video.get("id")
            if not vid_id or vid_id in state["videos"]:
                continue
            vid_url = f"https://www.youtube.com/shorts/{vid_id}"
            filename = output_dir / f"{vid_id}.mp4"

            if filename.exists() and verify_media_file(filename):
                logging.info(f"[SKIP] Video already downloaded & valid: {filename}")
                state["videos"].append(vid_id)
                downloaded += 1
                continue

            try:
                meta = await fetch_video_metadata(vid_url)
                if meta is None:
                    logging.info(f"[SKIP] Video {vid_url} metadata indicates skip.")
                    continue
                duration = meta.get("duration", 0)
                if not (min_duration <= duration <= max_duration):
                    logging.info(f"[SKIP] Video {vid_url} duration {duration}s out of range.")
                    continue
                logging.info(f"Downloading video {vid_url} ({duration}s)...")
                await download_video(vid_url, filename)
                logging.info(f"[SUCCESS] Downloaded video {vid_url}")
                state["videos"].append(vid_id)
                downloaded += 1
                save_state(state)
                await asyncio.sleep(random.uniform(MIN_DELAY_BETWEEN_DOWNLOADS, MAX_DELAY_BETWEEN_DOWNLOADS))
            except YtDlpTransientError as e:
                logging.warning(f"[RETRY LATER] Transient error downloading {vid_url}: {e}")
                failed.append((vid_url, filename))
            except Exception as e:
                logging.error(f"[FAIL] Failed to download video {vid_url}: {e}")

    # Retry failed downloads with backoff
    for vid_url, filename in failed:
        if shutdown_requested:
            break
        logging.info(f"Retrying failed video download {vid_url} after delay...")
        await asyncio.sleep(10)
        try:
            await download_video(vid_url, filename)
            logging.info(f"[SUCCESS] Retried download succeeded: {vid_url}")
            vid_id = Path(filename).stem
            state["videos"].append(vid_id)
            save_state(state)
            downloaded += 1
        except Exception as e:
            logging.error(f"[FAIL] Retried download failed: {vid_url}: {e}")

    logging.info(f"Downloaded {downloaded} shorts into {output_dir}")


async def download_music(output_dir: Path, playlists: list[str], count: int) -> None:
    logging.info(f"Starting download of up to {count} music tracks into {output_dir}...")
    state = load_state()
    downloaded = 0
    failed = []

    for playlist_url in playlists:
        if shutdown_requested or downloaded >= count:
            break
        tracks_info = await fetch_playlist_videos(playlist_url)
        random.shuffle(tracks_info)

        for track in tracks_info:
            if shutdown_requested or downloaded >= count:
                break
            track_id = track.get("id")
            if not track_id or track_id in state["music"]:
                continue
            track_url = f"https://www.youtube.com/watch?v={track_id}"
            filename = output_dir / f"{track_id}.mp3"

            if filename.exists() and verify_media_file(filename):
                logging.info(f"[SKIP] Music track already downloaded & valid: {filename}")
                state["music"].append(track_id)
                downloaded += 1
                continue

            try:
                meta = await fetch_video_metadata(track_url)
                if meta is None:
                    logging.info(f"[SKIP] Music track {track_url} metadata indicates skip.")
                    continue
                logging.info(f"Downloading music track {track_url}...")
                await download_audio(track_url, filename)
                logging.info(f"[SUCCESS] Downloaded music track {track_url}")
                state["music"].append(track_id)
                downloaded += 1
                save_state(state)
                await asyncio.sleep(random.uniform(MIN_DELAY_BETWEEN_DOWNLOADS, MAX_DELAY_BETWEEN_DOWNLOADS))
            except YtDlpTransientError as e:
                logging.warning(f"[RETRY LATER] Transient error downloading music {track_url}: {e}")
                failed.append((track_url, filename))
            except Exception as e:
                logging.error(f"[FAIL] Failed to download music track {track_url}: {e}")

    for track_url, filename in failed:
        if shutdown_requested:
            break
        logging.info(f"Retrying failed music download {track_url} after delay...")
        await asyncio.sleep(10)
        try:
            await download_audio(track_url, filename)
            logging.info(f"[SUCCESS] Retried music download succeeded: {track_url}")
            track_id = Path(filename).stem
            state["music"].append(track_id)
            save_state(state)
            downloaded += 1
        except Exception as e:
            logging.error(f"[FAIL] Retried music download failed: {track_url}: {e}")

    logging.info(f"Downloaded {downloaded} music tracks into {output_dir}")


async def generate_dynamic_voiceovers(output_dir: Path, count: int) -> None:
    logging.info(f"Generating {count} dynamic voiceovers into {output_dir}...")
    state = load_state()
    quotes = [
        "Believe you can and you're halfway there.",
        "Stay positive, work hard, make it happen.",
        "The only limit to our realization of tomorrow is our doubts of today.",
        "Dream big and dare to fail.",
        "Keep going, you're getting there.",
    ]
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=2)
    generated = 0

    for i in range(count):
        if shutdown_requested:
            break
        filename = output_dir / f"voiceover_{i+1}.mp3"
        if filename.exists():
            logging.info(f"[SKIP] Voiceover already exists: {filename}")
            if i+1 not in state["voiceovers"]:
                state["voiceovers"].append(i+1)
            generated += 1
            continue
        quote = random.choice(quotes)
        try:
            await loop.run_in_executor(executor, generate_voiceover_file, quote, filename)
            logging.info(f"[SUCCESS] Generated voiceover: {filename}")
            state["voiceovers"].append(i+1)
            generated += 1
            save_state(state)
            await asyncio.sleep(random.uniform(MIN_DELAY_BETWEEN_DOWNLOADS, MAX_DELAY_BETWEEN_DOWNLOADS))
        except Exception as e:
            logging.error(f"[FAIL] Failed to generate voiceover {filename}: {e}")
    logging.info(f"Generated {generated} voiceovers in {output_dir}")


def shutdown_handler(signum, frame):
    global shutdown_requested
    logging.info(f"Shutdown signal ({signum}) received, preparing to exit gracefully...")
    shutdown_requested = True


async def run_all() -> None:
    await download_videos(CLIPS_DIR, ROYALTY_FREE_CLIP_PLAYLISTS, MAX_VIDEO_DOWNLOADS, MIN_VIDEO_DURATION, MAX_VIDEO_DURATION)
    if shutdown_requested:
        logging.info("Shutdown requested, skipping further downloads.")
        return
    await download_music(MUSIC_DIR, ROYALTY_FREE_MUSIC_PLAYLISTS, MAX_MUSIC_DOWNLOADS)
    if shutdown_requested:
        logging.info("Shutdown requested, skipping voiceover generation.")
        return
    await generate_dynamic_voiceovers(VOICE_DIR, MAX_VOICEOVERS)


if __name__ == "__main__":
    # Register graceful shutdown signals
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        asyncio.run(run_all())
    except Exception as e:
        logging.error(f"Fatal error during run_all: {e}")
    finally:
        # Save state one last time on exit
        save_state(load_state())
        logging.info("Exiting download_assets.py")
    

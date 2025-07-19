import os
import asyncio
import subprocess
import random
from pathlib import Path
import pyttsx3
import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from concurrent.futures import ThreadPoolExecutor
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s %(message)s",
    handlers=[
        logging.FileHandler("download_assets.log"),
        logging.StreamHandler()
    ],
)

CLIPS_DIR = Path("clips")
MUSIC_DIR = Path("music")
VOICE_DIR = Path("voiceovers")

CLIPS_DIR.mkdir(exist_ok=True)
MUSIC_DIR.mkdir(exist_ok=True)
VOICE_DIR.mkdir(exist_ok=True)

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
    """Run yt-dlp with retry on transient errors, timeout after 2 minutes."""
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
        # Retry on transient errors, fail otherwise
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
        "--continue",  # resume partial downloads
    ]
    await run_yt_dlp_cmd(args)


async def download_audio(audio_url: str, filename: Path) -> None:
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
        "--continue",  # resume partial downloads
    ]
    await run_yt_dlp_cmd(args)


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
    downloaded = 0
    failed = []

    for playlist_url in playlists:
        if downloaded >= count:
            break
        videos_info = await fetch_playlist_videos(playlist_url)
        random.shuffle(videos_info)

        for video in videos_info:
            if downloaded >= count:
                break
            vid_id = video.get("id")
            if not vid_id:
                continue
            vid_url = f"https://www.youtube.com/shorts/{vid_id}"
            filename = output_dir / f"{vid_id}.mp4"
            if filename.exists():
                logging.info(f"[SKIP] Video already exists: {filename}")
                downloaded += 1
                continue
            try:
                meta = await fetch_video_metadata(vid_url)
                if meta is None:
                    logging.info(f"[SKIP] Video {vid_url} metadata indicates it should be skipped.")
                    continue
                duration = meta.get("duration", 0)
                if not (min_duration <= duration <= max_duration):
                    logging.info(f"[SKIP] Video {vid_url} duration {duration}s out of range.")
                    continue
                logging.info(f"Downloading video {vid_url} ({duration}s)...")
                await download_video(vid_url, filename)
                logging.info(f"[SUCCESS] Downloaded video {vid_url}")
                downloaded += 1
            except YtDlpTransientError as e:
                logging.warning(f"[RETRY LATER] Transient error downloading {vid_url}: {e}")
                failed.append((vid_url, filename))
            except Exception as e:
                logging.error(f"[FAIL] Failed to download video {vid_url}: {e}")

    # Retry failed downloads with backoff
    for vid_url, filename in failed:
        logging.info(f"Retrying failed video download {vid_url} after delay...")
        await asyncio.sleep(10)
        try:
            await download_video(vid_url, filename)
            logging.info(f"[SUCCESS] Retried download succeeded: {vid_url}")
            downloaded += 1
        except Exception as e:
            logging.error(f"[FAIL] Retried download failed: {vid_url}: {e}")

    logging.info(f"Downloaded {downloaded} shorts into {output_dir}")


async def download_music(output_dir: Path, playlists: list[str], count: int) -> None:
    logging.info(f"Starting download of up to {count} music tracks into {output_dir}...")
    downloaded = 0
    failed = []

    for playlist_url in playlists:
        if downloaded >= count:
            break
        tracks_info = await fetch_playlist_videos(playlist_url)
        random.shuffle(tracks_info)

        for track in tracks_info:
            if downloaded >= count:
                break
            track_id = track.get("id")
            if not track_id:
                continue
            track_url = f"https://www.youtube.com/watch?v={track_id}"
            filename = output_dir / f"{track_id}.mp3"
            if filename.exists():
                logging.info(f"[SKIP] Music track already exists: {filename}")
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
                downloaded += 1
            except YtDlpTransientError as e:
                logging.warning(f"[RETRY LATER] Transient error downloading music {track_url}: {e}")
                failed.append((track_url, filename))
            except Exception as e:
                logging.error(f"[FAIL] Failed to download music track {track_url}: {e}")

    for track_url, filename in failed:
        logging.info(f"Retrying failed music download {track_url} after delay...")
        await asyncio.sleep(10)
        try:
            await download_audio(track_url, filename)
            logging.info(f"[SUCCESS] Retried music download succeeded: {track_url}")
            downloaded += 1
        except Exception as e:
            logging.error(f"[FAIL] Retried music download failed: {track_url}: {e}")

    logging.info(f"Downloaded {downloaded} music tracks into {output_dir}")


async def generate_dynamic_voiceovers(output_dir: Path, count: int) -> None:
    logging.info(f"Generating {count} dynamic voiceovers into {output_dir}...")
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
        filename = output_dir / f"voiceover_{i+1}.mp3"
        if filename.exists():
            logging.info(f"[SKIP] Voiceover already exists: {filename}")
            generated += 1
            continue
        quote = random.choice(quotes)
        try:
            await loop.run_in_executor(executor, generate_voiceover_file, quote, filename)
            logging.info(f"[SUCCESS] Generated voiceover: {filename}")
            generated += 1
        except Exception as e:
            logging.error(f"[FAIL] Failed to generate voiceover {filename}: {e}")
    logging.info(f"Generated {generated} voiceovers in {output_dir}")


async def run_all() -> None:
    await download_videos(CLIPS_DIR, ROYALTY_FREE_CLIP_PLAYLISTS, 50, 1, 60)
    await download_music(MUSIC_DIR, ROYALTY_FREE_MUSIC_PLAYLISTS, 30)
    await generate_dynamic_voiceovers(VOICE_DIR, 30)


if __name__ == "__main__":
    asyncio.run(run_all())

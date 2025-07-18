import os
import asyncio
import subprocess
import random
from pathlib import Path
import pyttsx3
import json
from tenacity import retry, stop_after_attempt, wait_fixed
from concurrent.futures import ThreadPoolExecutor

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


@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def run_yt_dlp_cmd(args: list[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err_str = stderr.decode().strip()
        if any(keyword in err_str.lower() for keyword in ["sign in", "captcha", "login", "cookie", "blocked", "forbidden", "error 429"]):
            raise RuntimeError(f"yt-dlp blocked by YouTube restrictions: {err_str}")
        raise RuntimeError(f"yt-dlp failed: {err_str}")
    return stdout.decode()


async def fetch_playlist_videos(playlist_url: str) -> list[dict]:
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
    except RuntimeError:
        return None
    except Exception:
        return None


async def download_video(video_url: str, filename: Path) -> None:
    await run_yt_dlp_cmd(
        [
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
        ]
    )


async def download_audio(audio_url: str, filename: Path) -> None:
    await run_yt_dlp_cmd(
        [
            "-x",
            "--audio-format",
            "mp3",
            "-o",
            str(filename),
            audio_url,
            "--user-agent",
            USER_AGENT,
            "--no-check-certificate",
        ]
    )


def generate_voiceover_file(quote: str, filename: Path) -> None:
    engine = pyttsx3.init()
    engine.setProperty("rate", 150)
    voices = engine.getProperty("voices")
    if voices:
        engine.setProperty("voice", voices[0].id)
    engine.save_to_file(quote, str(filename))
    engine.runAndWait()


async def download_videos(
    output_dir: Path, playlists: list[str], count: int, min_duration=15, max_duration=30
) -> None:
    print(f"[INFO] Starting download of up to {count} videos into {output_dir}...")
    downloaded = 0
    for playlist_url in playlists:
        if downloaded >= count:
            break
        try:
            videos_info = await fetch_playlist_videos(playlist_url)
            random.shuffle(videos_info)
        except Exception as e:
            print(f"[WARN] Failed to fetch playlist {playlist_url}: {e}")
            continue

        for video in videos_info:
            if downloaded >= count:
                break
            vid_id = video.get("id")
            if not vid_id:
                continue
            vid_url = f"https://www.youtube.com/watch?v={vid_id}"
            filename = output_dir / f"{vid_id}.mp4"
            if filename.exists():
                print(f"[SKIP] Video already exists: {filename}")
                downloaded += 1
                continue
            try:
                meta = await fetch_video_metadata(vid_url)
                if meta is None:
                    print(f"[SKIP] Video {vid_url} metadata indicates it should be skipped (likely login/restriction).")
                    continue
                duration = meta.get("duration", 0)
                if not (min_duration <= duration <= max_duration):
                    print(f"[SKIP] Video {vid_url} duration {duration}s out of range ({min_duration}-{max_duration}s)")
                    continue
            except Exception as e:
                print(f"[WARN] Failed to fetch metadata for video {vid_url}: {e}")
                continue
            try:
                print(f"[INFO] Downloading video {vid_url} ({duration}s)...")
                await download_video(vid_url, filename)
                print(f"[SUCCESS] Downloaded video {vid_url}")
                downloaded += 1
            except Exception as e:
                print(f"[FAIL] Failed to download video {vid_url}: {e}")
                continue
    print(f"[INFO] Downloaded {downloaded} videos into {output_dir}")


async def download_music(output_dir: Path, playlists: list[str], count: int) -> None:
    print(f"[INFO] Starting download of up to {count} music tracks into {output_dir}...")
    downloaded = 0
    for playlist_url in playlists:
        if downloaded >= count:
            break
        try:
            tracks_info = await fetch_playlist_videos(playlist_url)
            random.shuffle(tracks_info)
        except Exception as e:
            print(f"[WARN] Failed to fetch music playlist {playlist_url}: {e}")
            continue

        for track in tracks_info:
            if downloaded >= count:
                break
            track_id = track.get("id")
            if not track_id:
                continue
            track_url = f"https://www.youtube.com/watch?v={track_id}"
            filename = output_dir / f"{track_id}.mp3"
            if filename.exists():
                print(f"[SKIP] Music track already exists: {filename}")
                downloaded += 1
                continue
            try:
                meta = await fetch_video_metadata(track_url)
                if meta is None:
                    print(f"[SKIP] Music track {track_url} metadata indicates it should be skipped (likely login/restriction).")
                    continue
                print(f"[INFO] Downloading music track {track_url}...")
                await download_audio(track_url, filename)
                print(f"[SUCCESS] Downloaded music track {track_url}")
                downloaded += 1
            except Exception as e:
                print(f"[FAIL] Failed to download music track {track_url}: {e}")
                continue
    print(f"[INFO] Downloaded {downloaded} music tracks into {output_dir}")


async def generate_dynamic_voiceovers(output_dir: Path, count: int) -> None:
    print(f"[INFO] Generating {count} dynamic voiceovers into {output_dir}...")
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
            print(f"[SKIP] Voiceover already exists: {filename}")
            generated += 1
            continue
        quote = random.choice(quotes)
        try:
            await loop.run_in_executor(executor, generate_voiceover_file, quote, filename)
            print(f"[SUCCESS] Generated voiceover: {filename}")
            generated += 1
        except Exception as e:
            print(f"[FAIL] Failed to generate voiceover {filename}: {e}")
    print(f"[INFO] Generated {generated} voiceovers in {output_dir}")


async def run_all() -> None:
    await download_videos(CLIPS_DIR, ROYALTY_FREE_CLIP_PLAYLISTS, 50, 15, 30)
    await download_music(MUSIC_DIR, ROYALTY_FREE_MUSIC_PLAYLISTS, 30)
    await generate_dynamic_voiceovers(VOICE_DIR, 30)


if __name__ == "__main__":
    asyncio.run(run_all())

import os
import asyncio
import subprocess
import random
import shutil
from pathlib import Path
import pyttsx3

CLIPS_DIR = Path("clips")
MUSIC_DIR = Path("music")
VOICE_DIR = Path("voiceovers")

CLIPS_DIR.mkdir(exist_ok=True)
MUSIC_DIR.mkdir(exist_ok=True)
VOICE_DIR.mkdir(exist_ok=True)

# YouTube playlists or channels with royalty-free clips/music (example placeholders)
ROYALTY_FREE_CLIP_PLAYLISTS = [
    "https://www.youtube.com/playlist?list=PLrEnWoR732-BHrPp_Pm8_VleD68f9s14-",
    # Add more legit royalty-free clip playlists
]

ROYALTY_FREE_MUSIC_PLAYLISTS = [
    "https://www.youtube.com/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj",
    # Add more legit royalty-free music playlists
]

async def download_videos(output_dir: Path, playlists: list[str], count: int, min_duration=15, max_duration=30):
    """
    Use yt-dlp to download count number of random videos from given playlists.
    Filters videos by duration (seconds).
    """
    print(f"Starting download of {count} videos into {output_dir}...")

    downloaded = 0
    for playlist_url in playlists:
        if downloaded >= count:
            break

        # Download metadata only, to filter by duration
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--flat-playlist",
            "-j",
            playlist_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        videos_info = [json.loads(line) for line in stdout.decode().splitlines()]
        random.shuffle(videos_info)

        for video in videos_info:
            if downloaded >= count:
                break
            vid_url = f"https://www.youtube.com/watch?v={video['id']}"

            # Fetch duration metadata of video before downloading (to filter)
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "-j",
                vid_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            meta = json.loads(out.decode())
            duration = meta.get("duration", 0)
            if not (min_duration <= duration <= max_duration):
                continue

            # Download video
            filename = output_dir / f"{video['id']}.mp4"
            if filename.exists():
                downloaded += 1
                continue  # already downloaded

            print(f"Downloading video {vid_url} ({duration}s)...")
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "-f", "mp4",
                "-o", str(filename),
                vid_url,
            )
            await proc.communicate()
            downloaded += 1

    print(f"Downloaded {downloaded} videos into {output_dir}")

async def download_music(output_dir: Path, playlists: list[str], count: int):
    """
    Download audio files only from music playlists using yt-dlp.
    """
    print(f"Starting download of {count} music tracks into {output_dir}...")

    downloaded = 0
    for playlist_url in playlists:
        if downloaded >= count:
            break

        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--flat-playlist",
            "-j",
            playlist_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        tracks_info = [json.loads(line) for line in stdout.decode().splitlines()]
        random.shuffle(tracks_info)

        for track in tracks_info:
            if downloaded >= count:
                break
            track_url = f"https://www.youtube.com/watch?v={track['id']}"
            filename = output_dir / f"{track['id']}.mp3"
            if filename.exists():
                downloaded += 1
                continue

            print(f"Downloading music track {track_url} ...")
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "-x", "--audio-format", "mp3",
                "-o", str(filename),
                track_url,
            )
            await proc.communicate()
            downloaded += 1

    print(f"Downloaded {downloaded} music tracks into {output_dir}")

async def generate_dynamic_voiceovers(output_dir: Path, count: int):
    """
    Generate voiceover audio files from a list of motivational/funny quotes using pyttsx3 TTS locally.
    """
    print(f"Generating {count} dynamic voiceovers into {output_dir}...")

    quotes = [
        "Believe you can and you're halfway there.",
        "Stay positive, work hard, make it happen.",
        "The only limit to our realization of tomorrow is our doubts of today.",
        "Dream big and dare to fail.",
        "Keep going, you're getting there.",
        # Add 30-50 more or pull dynamically from local file
    ]

    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    voices = engine.getProperty('voices')
    if voices:
        engine.setProperty('voice', voices[0].id)

    for i in range(count):
        quote = random.choice(quotes)
        filename = output_dir / f"voiceover_{i+1}.mp3"
        if filename.exists():
            continue
        engine.save_to_file(quote, str(filename))
        engine.runAndWait()
        print(f"Generated voiceover: {filename}")

    print(f"Generated {count} voiceovers in {output_dir}")

async def run_all():
    await download_videos(CLIPS_DIR, ROYALTY_FREE_CLIP_PLAYLISTS, 50, 15, 30)
    await download_music(MUSIC_DIR, ROYALTY_FREE_MUSIC_PLAYLISTS, 30)
    await generate_dynamic_voiceovers(VOICE_DIR, 30)

if __name__ == "__main__":
    import json
    asyncio.run(run_all())

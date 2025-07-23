import os
import json
import subprocess
import asyncio
import logging
import logging.handlers
import signal
from typing import List

OUTPUT_DIR = os.path.join(os.getcwd(), "processed")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# === LOGGING SETUP ===
logger = logging.getLogger("TelegramVideoBot")
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
file_handler = logging.handlers.RotatingFileHandler(
    "editor.log", maxBytes=5 * 1024 * 1024, backupCount=2
)
formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s')

console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

# === FFMPEG CHECK ===
FFMPEG_OK = subprocess.run(
    ["ffmpeg", "-version"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
).returncode == 0

if not FFMPEG_OK:
    logger.critical("FFmpeg is not installed or not in PATH. Exiting.")
    raise SystemExit(1)

# === SHUTDOWN HANDLING ===
shutdown_event = asyncio.Event()

def _handle_shutdown():
    logger.info("Shutdown signal received. Cleaning up...")
    shutdown_event.set()

for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: _handle_shutdown())

# === ASYNC FFMPEG WRAPPER ===
_ffmpeg_semaphore = asyncio.Semaphore(1)

async def run_ffmpeg_async(cmd: List[str]) -> None:
    async with _ffmpeg_semaphore:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {stderr.decode().strip()}")

# === VIDEO SEGMENT ANALYSIS ===
def detect_best_segment(video_path: str, max_duration: int = 45) -> float:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        total_duration = float(result.stdout.strip())
        return max(0.0, round((total_duration - max_duration) / 2, 2)) if total_duration > max_duration else 0.0
    except Exception as e:
        logger.warning(f"Failed to detect segment: {e}")
        return 0.0

def has_audio_stream(video_path: str) -> bool:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "json",
            video_path
        ], capture_output=True, text=True, check=True)
        return bool(json.loads(result.stdout).get("streams"))
    except:
        return False

# === MAIN EDIT FUNCTION ===
async def edit_video(input_path: str) -> str:
    output_path = os.path.join(OUTPUT_DIR, os.path.basename(input_path))
    start_time = detect_best_segment(input_path)

    logger.info(f"Editing video: {input_path} (start={start_time}s)")

    common_vfilters = (
        "scale=1080:-1,"
        "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2,"
        "eq=contrast=1.1:brightness=0.05,"
        "unsharp=5:5:1.0,"
        "fade=t=in:st=0:d=1,fade=t=out:st=44:d=1,"
        "minterpolate='fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1'"
    )

    has_audio = has_audio_stream(input_path)
    if has_audio:
        filters = (
            f"[0:v]{common_vfilters}[v];"
            f"[0:a]silenceremove=start_periods=1:start_silence=0.1:start_threshold=-50dB:"
            f"stop_periods=-1:stop_silence=0.1:stop_threshold=-50dB[aout]"
        )
        maps = ["-map", "[v]", "-map", "[aout]"]
    else:
        filters = f"[0:v]{common_vfilters}[v]"
        maps = ["-map", "[v]"]

    ffmpeg_cmd = [
        "ffmpeg", "-ss", str(start_time), "-i", input_path,
        "-filter_complex", filters,
        *maps,
        "-t", "45",
        "-vcodec", "libx264",
        "-preset", "fast",
        "-crf", "25",
        "-acodec", "aac" if has_audio else "-an",
        "-b:a", "128k" if has_audio else None,
        "-pix_fmt", "yuv420p",
        "-movflags", "faststart",
        "-threads", "2",
        "-y", output_path
    ]
    ffmpeg_cmd = [x for x in ffmpeg_cmd if x is not None]

    try:
        await asyncio.wait_for(run_ffmpeg_async(ffmpeg_cmd), timeout=120)
        logger.info(f"Edited video saved to: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Edit failed: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
            logger.info(f"Deleted incomplete file: {output_path}")
        raise

# === SANITY CHECK ===
def is_video_suitable(path: str) -> bool:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration",
            "-of", "json", path
        ], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)["streams"][0]
        width, height = int(data["width"]), int(data["height"])
        duration = float(data["duration"])
        return 15 <= duration <= 90 and width >= 640 and height >= 360
    except Exception as e:
        logger.warning(f"Video check failed: {e}")
        return False

# === OPTIONAL: SHUTDOWN AWAITER FOR CLEAN EXITS ===
async def await_shutdown():
    await shutdown_event.wait()
    logger.info("Exiting editor module cleanly.")

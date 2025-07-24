import os
import json
import subprocess
import asyncio
import logging
import logging.handlers
import signal
import datetime
from typing import List

OUTPUT_DIR = os.path.join(os.getcwd(), "processed")
os.makedirs(OUTPUT_DIR, exist_ok=True)

LOGS_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

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

# === ASYNC FFMPEG WRAPPER (IMPROVED TO PROPAGATE STDERR) ===
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
            err_text = stderr.decode().strip()
            logger.error("FFmpeg stderr:\n" + err_text)
            raise RuntimeError(f"ffmpeg failed with exit code {proc.returncode}\n{err_text}")

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

def is_video_corrupted(video_path: str) -> bool:
    cmd = [
        "ffmpeg", "-v", "error", "-i", video_path,
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return bool(result.stderr.strip())

def get_video_duration(video_path: str) -> float:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"Failed to get video duration: {e}")
        return 0.0

def get_video_fps(video_path: str) -> float:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        fps_str = result.stdout.strip()
        # r_frame_rate comes as a fraction, e.g. "30/1"
        num, den = fps_str.split('/')
        return float(num) / float(den)
    except Exception as e:
        logger.warning(f"Failed to get video fps: {e}")
        return 30.0  # fallback

# === MAIN EDIT FUNCTION WITH UPGRADES ===
async def edit_video(input_path: str) -> str:
    output_path = os.path.join(OUTPUT_DIR, os.path.basename(input_path))
    total_duration = get_video_duration(input_path)
    start_time = detect_best_segment(input_path)
    fps = get_video_fps(input_path)
    
    logger.info(f"Editing video: {input_path} (start={start_time}s, total_duration={total_duration}s, fps={fps})")

    min_duration = 15
    max_duration = 45
    target_duration = min(max_duration, max(min_duration, total_duration))
    ffmpeg_extra = []
    if total_duration < min_duration:
        loop_count = int(min_duration // total_duration) + 1
        ffmpeg_extra.extend([
            "-stream_loop", str(loop_count - 1)
        ])
        target_duration = min_duration

    has_audio = has_audio_stream(input_path)

    # Filters setup:
    # Scale width to 1080, height automatic -2 to keep aspect ratio and divisible by 2
    # If after scale height < 1920, pad to 1080x1920 centered
    # Else crop center 1080x1920
    # Add eq, unsharp, fade (fade out dynamically), minterpolate if fps < 30, format=yuv420p
    filters_list = []
    filters_list.append("scale=w=1080:h=-2:flags=lanczos")

    # Will need to check input height after scale:
    # Use ffprobe to get input width/height for logic below
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "default=noprint_wrappers=1",
            input_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        lines = result.stdout.strip().split('\n')
        width, height = None, None
        for line in lines:
            if line.startswith("width="):
                width = int(line.split("=")[1])
            if line.startswith("height="):
                height = int(line.split("=")[1])
    except Exception:
        width, height = 1280, 720  # fallback

    # After scaling width to 1080, compute estimated scaled height
    scaled_height = int(height * 1080 / width) if width and height else 1920

    if scaled_height < 1920:
        # Pad vertically centered
        filters_list.append(f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
    else:
        # Crop center 1080x1920
        filters_list.append(f"crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2")

    filters_list.append("eq=contrast=1.1:brightness=0.05")
    filters_list.append("unsharp=5:5:1.0")

    fade_out_start = max(target_duration - 1, 1)
    filters_list.append(f"fade=t=in:st=0:d=1,fade=t=out:st={fade_out_start}:d=1")

    if fps < 30:
        filters_list.append("minterpolate='fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1'")

    filters_list.append("format=yuv420p")

    video_filter = ",".join(filters_list)

    if has_audio:
        # Normalize volume and trim audio to target_duration exactly
        audio_filter = (
            f"volume=1.0,atrim=0:{target_duration},asetpts=N/SR/TB"
        )
        filters = f"[0:v]{video_filter}[v];[0:a]{audio_filter}[aout]"
        maps = ["-map", "[v]", "-map", "[aout]"]
        acodec = "aac"
        audio_bitrate = "128k"
    else:
        filters = f"[0:v]{video_filter}[v]"
        maps = ["-map", "[v]"]
        acodec = None
        audio_bitrate = None

    ffmpeg_cmd = [
        "ffmpeg",
        *ffmpeg_extra,
        "-ss", str(start_time),
        "-i", input_path,
        "-filter_complex", filters,
        *maps,
        "-t", str(target_duration),
        "-vcodec", "libx264",
        "-preset", "veryfast",  # faster encode
        "-crf", "25",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-threads", "0",  # auto threads
        "-y", output_path
    ]
    if has_audio:
        ffmpeg_cmd += ["-acodec", acodec, "-b:a", audio_bitrate]
    else:
        ffmpeg_cmd += ["-an"]

    ffmpeg_cmd = [x for x in ffmpeg_cmd if x is not None]

    try:
        if is_video_corrupted(input_path):
            raise RuntimeError("Input video is corrupted or unreadable")

        await asyncio.wait_for(run_ffmpeg_async(ffmpeg_cmd), timeout=150)
        logger.info(f"Edited video saved to: {output_path}")
        return output_path

    except Exception as e:
        # Save ffmpeg stderr and error info to a timestamped file
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        error_log_path = os.path.join(LOGS_DIR, f"ffmpeg_error_{timestamp}.log")

        error_text = str(e)
        with open(error_log_path, "w") as f:
            f.write(f"Edit failed for video: {input_path}\n")
            f.write(error_text)

        logger.error(f"Edit failed: {error_text}")
        logger.info(f"FFmpeg error log saved to {error_log_path}")
        print(f"FFmpeg error log saved to {error_log_path}")

        if os.path.exists(output_path):
            os.remove(output_path)
            logger.info(f"Deleted incomplete file: {output_path}")

        raise

# === RELAXED SANITY CHECK ===
def is_video_suitable(path: str) -> bool:
    try:
        if is_video_corrupted(path):
            logger.warning("Video rejected: corrupted")
            return False

        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration",
            "-of", "json", path
        ], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)["streams"][0]
        width, height = int(data["width"]), int(data["height"])
        duration = float(data["duration"])

        if duration < 1:
            logger.warning(f"Video rejected: duration too short {duration}s")
            return False

        if duration > 90:
            logger.info(f"Video accepted but will be trimmed: duration {duration}s")
        
        return True
    except Exception as e:
        logger.warning(f"Video suitability check failed: {e}")
        return False

# === SHUTDOWN HANDLER ===
async def await_shutdown():
    await shutdown_event.wait()
    logger.info("Exiting editor module cleanly.")

import os
import json
import subprocess
import asyncio
import logging
import datetime
import signal
from typing import List

OUTPUT_DIR = os.path.join(os.getcwd(), "processed")
os.makedirs(OUTPUT_DIR, exist_ok=True)

LOGS_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

logger = logging.getLogger("TelegramVideoBot")
logger.setLevel(logging.INFO)

console = logging.StreamHandler()
formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s')
console.setFormatter(formatter)
logger.addHandler(console)

# FFmpeg availability check
if subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
    logger.critical("FFmpeg not found. Exiting.")
    raise SystemExit(1)

shutdown_event = asyncio.Event()

def _handle_shutdown(sig, frame):
    logger.warning(f"Received signal {sig.name}, shutting down gracefully.")
    shutdown_event.set()

signal.signal(signal.SIGINT, _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)

_ffmpeg_semaphore = asyncio.Semaphore(1)

async def run_ffmpeg_async(cmd: List[str]):
    async with _ffmpeg_semaphore:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode().strip()
            logger.error("FFmpeg error: " + err)
            raise RuntimeError(err)

def get_probe(field: str, path: str) -> str:
    resp = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0" if field != "duration" else "a:0",
        "-show_entries", f"format={field}" if field == "duration" else f"stream={field}",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return resp.stdout.strip()

def get_video_stats(path: str):
    dur = float(get_probe("duration", path))
    sizes = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "json", path
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    data = json.loads(sizes)["streams"][0]
    w, h = int(data["width"]), int(data["height"])
    num, den = map(int, data["r_frame_rate"].split("/"))
    fps = num / den if den else 30.0
    return dur, w, h, fps

def is_video_corrupted(path: str) -> bool:
    rez = subprocess.run([
        "ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    return bool(rez.stderr)

def is_video_suitable(path: str) -> bool:
    try:
        dur, w, h, _ = get_video_stats(path)
        return dur >= 1 and w >= 320 and h >= 320
    except Exception as e:
        logger.warning(f"Video suitability check failed: {e}")
        return False

async def edit_video(input_path: str) -> str:
    dur, w, h, fps = get_video_stats(input_path)
    start = max(0, round((dur - 45) / 2, 2))
    target = dur if dur <= 45 else 45

    if dur < 15:
        loop = int(15 // dur) + 1
        loop_args = ["-stream_loop", str(loop - 1)]
        target = 15
    else:
        loop_args = []

    filters = [
        "scale=1080:-2:flags=lanczos"
    ]
    scaled_h = int(h * 1080 / w)
    if scaled_h < 1920:
        filters.append("pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
    else:
        filters.append("crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2")
    filters += [
        "eq=contrast=1.1:brightness=0.05",
        "unsharp=5:5:1.0",
        f"fade=t=in:st=0:d=1,fade=t=out:st={target-1}:d=1"
    ]
    if fps < 30:
        filters.append("minterpolate='fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1'")
    filters.append("format=yuv420p")
    vf = ",".join(filters)

    has_audio = not is_video_corrupted(input_path) and bool(get_probe("duration", input_path))
    if has_audio:
        af = f"volume=1.0,atrim=0:{target},asetpts=N/SR/TB"
        filter_complex = f"[0:v]{vf}[v];[0:a]{af}[a]"
        maps = ["-map", "[v]", "-map", "[a]"]
        acodec = ["-acodec", "aac", "-b:a", "128k"]
    else:
        filter_complex = f"[0:v]{vf}[v]"
        maps = ["-map", "[v]"]
        acodec = ["-an"]

    out = os.path.join(OUTPUT_DIR, os.path.basename(input_path))
    cmd = [
        "ffmpeg", *loop_args,
        "-ss", str(start), "-i", input_path,
        "-filter_complex", filter_complex,
        *maps,
        "-t", str(target),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-threads", "0", "-y", out,
        *acodec
    ]

    try:
        if is_video_corrupted(input_path):
            raise RuntimeError("Corrupted input")
        await asyncio.wait_for(run_ffmpeg_async(cmd), timeout=120)
        return out
    except Exception as e:
        log = os.path.join(LOGS_DIR, f"ffmpeg_error_{datetime.datetime.now():%Y%m%d%H%M%S}.log")
        with open(log, "w") as f:
            f.write(str(e))
        logger.error(f"Edit failed, log: {log}")
        if os.path.exists(out):
            os.remove(out)
        raise

async def await_shutdown():
    await shutdown_event.wait()

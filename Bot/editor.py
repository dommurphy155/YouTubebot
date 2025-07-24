import os
import logging
import ffmpeg
import random
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] editor.py: %(message)s",
    handlers=[logging.StreamHandler()]
)

INPUT_DIR = "downloads"
OUTPUT_DIR = "ready"

# Loosened constraints
MIN_DURATION = 15
MAX_DURATION = 90
TARGET_RESOLUTION = (1080, 1920)
CRF = 28

def get_video_duration(input_path):
    try:
        probe = ffmpeg.probe(input_path)
        return float(probe['format']['duration'])
    except Exception as e:
        logging.warning(f"⚠️ Could not probe duration: {e} — proceeding anyway")
        return None

def is_video_suitable(file_path: str) -> bool:
    """Used by scraper.py to prefilter videos."""
    try:
        probe = ffmpeg.probe(file_path)
        duration = float(probe['format']['duration'])
        width = int(probe['streams'][0]['width'])
        height = int(probe['streams'][0]['height'])
        if duration < MIN_DURATION or duration > MAX_DURATION:
            return False
        if width < 640 or height < 360:
            return False
        return True
    except Exception as e:
        logging.warning(f"⚠️ is_video_suitable failed: {e} — allowing video")
        return True  # Let it through instead of rejecting

def get_best_subclip(duration, min_duration, max_duration) -> tuple:
    if not duration or duration <= min_duration:
        return 0, min(max_duration, duration or max_duration)
    if duration <= max_duration:
        return 0, duration
    window = random.randint(min_duration, max_duration)
    mid = duration / 2
    start = max(0, mid - window / 2 + random.uniform(-5, 5))
    end = start + window
    return round(start, 2), round(min(end, duration), 2)

def apply_ffmpeg_filters(input_path, output_path, start_time, end_time):
    try:
        logging.info("🎞️ Applying main filters...")
        (
            ffmpeg
            .input(input_path, ss=start_time, to=end_time)
            .filter('scale', -1, TARGET_RESOLUTION[1])
            .filter('crop', TARGET_RESOLUTION[0], TARGET_RESOLUTION[1])
            .filter('eq', contrast=1.05, brightness=0.02, saturation=1.1)
            .filter('unsharp', 3, 3, 0.7, 3, 3, 0.0)
            .output(
                output_path,
                vcodec='libx264',
                acodec='aac',
                crf=CRF,
                preset='fast',
                movflags='+faststart'
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        logging.info(f"✅ Rendered successfully to: {output_path}")
        return True
    except ffmpeg.Error as e:
        logging.warning("⚠️ FFmpeg failed, attempting fallback...")
        logging.warning(e.stderr.decode())
        try:
            (
                ffmpeg
                .input(input_path, ss=start_time, to=end_time)
                .output(
                    output_path,
                    vcodec='libx264',
                    acodec='aac',
                    crf=30,
                    preset='veryfast',
                    movflags='+faststart'
                )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            logging.info(f"✅ Fallback render successful: {output_path}")
            return True
        except Exception as e2:
            logging.error(f"❌ Fallback failed: {e2}")
            return False

def process_video(file_path):
    try:
        filename = os.path.basename(file_path)
        name, _ = os.path.splitext(filename)
        output_path = os.path.join(OUTPUT_DIR, f"{name}_edited.mp4")

        duration = get_video_duration(file_path) or MAX_DURATION
        start, end = get_best_subclip(duration, MIN_DURATION, MAX_DURATION)

        logging.info(f"✂️ Trimming: {start}s to {end}s (of {duration}s)")
        success = apply_ffmpeg_filters(file_path, output_path, start, end)

        if not success:
            raise RuntimeError("FFmpeg failed.")

        return output_path
    except Exception as e:
        logging.error(f"❌ process_video error: {str(e)}")
        return None

async def edit_video(file_path: str) -> str:
    """Async-compatible wrapper so main.py can call edit_video(...)"""
    logging.info(f"🧠 Launching async edit_video for: {file_path}")
    output = await asyncio.to_thread(process_video, file_path)
    if output:
        logging.info(f"📤 edit_video done: {output}")
    else:
        logging.warning(f"⚠️ edit_video failed for: {file_path}")
    return output

def main():
    logging.info("🚀 Starting editor.py...")
    for file in os.listdir(INPUT_DIR):
        if not file.endswith(".mp4"):
            continue
        input_path = os.path.join(INPUT_DIR, file)
        output_path = process_video(input_path)
        if output_path:
            logging.info(f"📦 Final video ready: {output_path}")
        else:
            logging.warning(f"⚠️ Skipped: {file}")

if __name__ == "__main__":
    main()

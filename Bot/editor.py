import os
import logging
import ffmpeg
import random

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] editor.py: %(message)s",
    handlers=[logging.StreamHandler()]
)

INPUT_DIR = "downloads"
OUTPUT_DIR = "ready"

MIN_DURATION = 20
MAX_DURATION = 60
TARGET_RESOLUTION = (1080, 1920)  # vertical
CRF = 25

def get_video_duration(input_path):
    try:
        probe = ffmpeg.probe(input_path)
        duration = float(probe['format']['duration'])
        return duration
    except Exception as e:
        logging.error(f"Error probing video duration: {e}")
        return None

def get_best_subclip(duration, min_duration: int, max_duration: int) -> tuple:
    """Find the best 20–60s subclip, ideally centered on the most active segment (smart fallback)."""
    if duration is None:
        return 0, 0
    if duration <= max_duration:
        return 0, duration

    window = random.randint(min_duration, max_duration)
    mid = duration / 2
    start = max(0, mid - window / 2 + random.uniform(-3, 3))
    end = start + window
    return round(start, 2), round(min(end, duration), 2)

def apply_ffmpeg_filters(input_path, output_path, start_time, end_time):
    try:
        logging.info("Starting ffmpeg filters...")
        (
            ffmpeg
            .input(input_path, ss=start_time, to=end_time)
            .filter('scale', TARGET_RESOLUTION[0], -1)
            .filter('crop', TARGET_RESOLUTION[0], TARGET_RESOLUTION[1])
            .filter('eq', contrast=1.1, brightness=0.05, saturation=1.2)  # AI-inspired enhancements
            .filter('unsharp', 5, 5, 1.0, 5, 5, 0.0)  # Sharpening
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
        logging.info(f"Rendered successfully to {output_path}")
        return True
    except ffmpeg.Error as e:
        logging.error("FFmpeg error:")
        logging.error(e.stderr.decode())
        return False

def process_video(file_path):
    try:
        filename = os.path.basename(file_path)
        name, _ = os.path.splitext(filename)
        output_path = os.path.join(OUTPUT_DIR, f"{name}_edited.mp4")

        duration = get_video_duration(file_path)
        if duration is None or duration == 0:
            logging.error(f"Could not get duration for {file_path}")
            return None

        start, end = get_best_subclip(duration, MIN_DURATION, MAX_DURATION)
        logging.info(f"Selected subclip: {start}s to {end}s (original: {duration}s)")

        success = apply_ffmpeg_filters(file_path, output_path, start, end)

        if not success:
            raise RuntimeError("FFmpeg failed to render.")

        return output_path
    except Exception as e:
        logging.error(f"Error processing {file_path}: {str(e)}")
        return None

def main():
    logging.info("Starting editor.py")
    for file in os.listdir(INPUT_DIR):
        if not file.endswith(".mp4"):
            continue
        input_path = os.path.join(INPUT_DIR, file)
        output_path = process_video(input_path)
        if output_path:
            logging.info(f"✅ Final video saved: {output_path}")
        else:
            logging.warning(f"⚠️ Failed to process {file}")

if __name__ == "__main__":
    main()

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

# Loosen duration requirements to allow more videos through
MIN_DURATION = 15  # lowered from 20
MAX_DURATION = 90  # raised from 60
TARGET_RESOLUTION = (1080, 1920)  # vertical
CRF = 28  # slightly higher CRF to allow faster encoding if needed

def get_video_duration(input_path):
    try:
        probe = ffmpeg.probe(input_path)
        duration = float(probe['format']['duration'])
        return duration
    except Exception as e:
        logging.warning(f"Warning: Could not probe video duration: {e}. Processing anyway.")
        return None  # allow video even if duration probe fails

def get_best_subclip(duration, min_duration: int, max_duration: int) -> tuple:
    if duration is None or duration <= min_duration:
        # No duration or too short, just take first max_duration seconds or full clip
        return 0, max_duration
    if duration <= max_duration:
        return 0, duration

    window = random.randint(min_duration, max_duration)
    mid = duration / 2
    start = max(0, mid - window / 2 + random.uniform(-5, 5))  # add more randomness to subclip selection
    end = start + window
    return round(start, 2), round(min(end, duration), 2)

def apply_ffmpeg_filters(input_path, output_path, start_time, end_time):
    try:
        logging.info("Starting ffmpeg filters...")
        (
            ffmpeg
            .input(input_path, ss=start_time, to=end_time)
            # Scale by height to maintain aspect ratio better, then crop to target resolution
            .filter('scale', -1, TARGET_RESOLUTION[1])
            .filter('crop', TARGET_RESOLUTION[0], TARGET_RESOLUTION[1])
            .filter('eq', contrast=1.05, brightness=0.02, saturation=1.1)  # softer enhancements
            .filter('unsharp', 3, 3, 0.7, 3, 3, 0.0)  # less aggressive sharpening
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
        logging.warning("FFmpeg error, retrying with minimal filters...")
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
            logging.info(f"Rendered fallback successfully to {output_path}")
            return True
        except Exception as e2:
            logging.error(f"Fallback ffmpeg render failed: {e2}")
            return False

def process_video(file_path):
    try:
        filename = os.path.basename(file_path)
        name, _ = os.path.splitext(filename)
        output_path = os.path.join(OUTPUT_DIR, f"{name}_edited.mp4")

        duration = get_video_duration(file_path)
        if duration is None:
            logging.warning(f"Unknown duration for {file_path}, proceeding with default max duration.")
            duration = MAX_DURATION

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

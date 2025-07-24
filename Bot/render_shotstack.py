import os
import asyncio
import logging
import aiohttp
import json
from typing import Optional, Dict

logger = logging.getLogger("TelegramVideoBot.render_shotstack")
logging.basicConfig(level=logging.INFO)

SHOTSTACK_API_KEY = os.environ.get("SHOTSTACK_API_KEY")
SHOTSTACK_API_URL = "https://api.shotstack.io/stage/render"

HEADERS = {
    "x-api-key": SHOTSTACK_API_KEY,
    "Content-Type": "application/json"
}

async def submit_render_job(payload: Dict) -> Optional[str]:
    """
    Submit the video editing JSON payload to Shotstack API.
    Returns render job ID or None on failure.
    """
    if not SHOTSTACK_API_KEY:
        logger.error("SHOTSTACK_API_KEY not set in environment.")
        return None

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(SHOTSTACK_API_URL, json=payload, headers=HEADERS, timeout=60) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Shotstack API error {resp.status}: {text}")
                    return None
                data = await resp.json()
                job_id = data.get("response", {}).get("id")
                if not job_id:
                    logger.error(f"No job ID returned from Shotstack API: {data}")
                    return None
                logger.info(f"Shotstack job submitted, ID: {job_id}")
                return job_id
        except Exception as e:
            logger.error(f"Shotstack submission exception: {e}")
            return None

async def get_render_status(job_id: str) -> Optional[Dict]:
    """
    Poll Shotstack API for render job status.
    Returns job status dict or None on failure.
    """
    url = f"{SHOTSTACK_API_URL}/{job_id}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=HEADERS, timeout=30) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Shotstack status error {resp.status}: {text}")
                    return None
                return await resp.json()
        except Exception as e:
            logger.error(f"Shotstack status fetch exception: {e}")
            return None

async def download_rendered_video(url: str, output_path: str) -> bool:
    """
    Download rendered video from Shotstack URL to local path.
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=120) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to download rendered video: HTTP {resp.status}")
                    return False
                with open(output_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(65536):
                        f.write(chunk)
            logger.info(f"Downloaded rendered video to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Exception downloading rendered video: {e}")
            return False

async def render_video_shotstack(input_video_path: str, output_path: str, metadata: Optional[Dict] = None) -> Optional[str]:
    """
    Main Shotstack render orchestrator.
    - input_video_path: local raw video path
    - output_path: local path for final video
    - metadata: dict containing overlays, text, transitions etc (optional)
    
    Returns output_path on success or None.
    """
    if not os.path.isfile(input_video_path):
        logger.error(f"Input video does not exist: {input_video_path}")
        return None

    # Build Shotstack JSON payload
    video_url = f"file://{os.path.abspath(input_video_path)}"  # For local files, may require uploading or static hosting
    # Note: Shotstack requires URL-accessible video files — you must upload input_video_path somewhere accessible or
    # modify to first upload to S3 or similar. This example assumes video_url is accessible.

    # Minimal example JSON; user should replace metadata for viral editing:
    payload = {
        "timeline": {
            "background": "#000000",
            "tracks": [
                {
                    "clips": [
                        {
                            "asset": {
                                "type": "video",
                                "src": video_url,
                                "trim": {
                                    "start": 0,
                                    "length": 30
                                }
                            },
                            "start": 0,
                            "length": 30,
                            "transition": {
                                "in": "fade",
                                "out": "fade"
                            }
                        }
                    ]
                }
            ]
        },
        "output": {
            "format": "mp4",
            "resolution": "sd"
        }
    }

    # If metadata supplied, merge or replace accordingly here

    job_id = await submit_render_job(payload)
    if not job_id:
        logger.error("Shotstack render job submission failed.")
        return None

    # Poll status until done or error
    for _ in range(60):  # Poll max 10 minutes (60 * 10 sec)
        status_resp = await get_render_status(job_id)
        if not status_resp:
            logger.error("Failed to get Shotstack job status.")
            return None

        status = status_resp.get("response", {}).get("status")
        logger.info(f"Shotstack job {job_id} status: {status}")

        if status == "done":
            video_url = status_resp.get("response", {}).get("url")
            if not video_url:
                logger.error("Shotstack job finished but no video URL provided.")
                return None
            success = await download_rendered_video(video_url, output_path)
            return output_path if success else None

        elif status == "error":
            logger.error(f"Shotstack job {job_id} failed with error.")
            return None

        await asyncio.sleep(10)

    logger.error("Shotstack job timeout.")
    return None

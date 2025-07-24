import os
import asyncio
import logging
import aiohttp
from typing import Optional, Dict, List

logger = logging.getLogger("TelegramVideoBot.render_hf")
logging.basicConfig(level=logging.INFO)

HUGGINGFACE_API_KEY = os.environ.get("HUGGINGFACE_API_KEY")
HF_ZERO_SHOT_MODEL = "facebook/bart-large-mnli"

HEADERS = {
    "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
    "Content-Type": "application/json"
}

async def zero_shot_classify(text: str, candidate_labels: List[str]) -> Optional[Dict]:
    """
    Run zero-shot classification on text with candidate labels.
    Returns dict of labels and scores or None.
    """
    if not HUGGINGFACE_API_KEY:
        logger.error("Hugging Face API key missing.")
        return None

    url = f"https://api-inference.huggingface.co/models/{HF_ZERO_SHOT_MODEL}"
    payload = {
        "inputs": text,
        "parameters": {"candidate_labels": candidate_labels},
        "options": {"wait_for_model": True}
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=HEADERS, json=payload, timeout=20) as resp:
                if resp.status != 200:
                    logger.error(f"HF zero-shot classification failed with status {resp.status}")
                    return None
                data = await resp.json()
                return data
        except Exception as e:
            logger.error(f"Exception during HF zero-shot call: {e}")
            return None

async def generate_edit_metadata(title: str, duration: float) -> Dict:
    """
    Generate Shotstack-compatible metadata based on AI analysis of title and duration.
    Example outputs: text overlays, animations, transition timings, etc.
    """
    candidate_labels = ["funny", "fail", "viral", "epic", "shocking", "wow", "crazy", "interesting", "fail", "wow"]
    classification = await zero_shot_classify(title, candidate_labels)
    overlay_text = title if classification else ""

    # Simple logic: if viral/funny/shocking score high, add flashy transitions, else keep minimal
    style = "minimal"
    if classification:
        labels = classification.get("labels", [])
        scores = classification.get("scores", [])
        # Pick highest label score
        max_score = max(scores) if scores else 0
        max_label = labels[scores.index(max_score)] if scores else ""
        if max_label in ("viral", "funny", "shocking", "epic") and max_score > 0.5:
            style = "flashy"

    # Construct metadata JSON snippet for Shotstack
    metadata = {
        "timeline": {
            "background": "#000000",
            "tracks": [
                {
                    "clips": [
                        {
                            "asset": {
                                "type": "video",
                                "src": "",  # Input video URL to be set by caller
                                "trim": {"start": 0, "length": duration}
                            },
                            "start": 0,
                            "length": duration,
                            "transition": {"in": "fade", "out": "fade"}
                        },
                        {
                            "asset": {
                                "type": "title",
                                "text": overlay_text,
                                "style": "minimal" if style == "minimal" else "dynamic",
                                "position": "top",
                                "size": "large",
                                "color": "#FFFFFF"
                            },
                            "start": 0,
                            "length": min(5, duration / 3),
                            "transition": {"in": "fade", "out": "fade"}
                        }
                    ]
                }
            ]
        },
        "output": {
            "format": "mp4",
            "resolution": "hd"
        }
    }
    return metadata

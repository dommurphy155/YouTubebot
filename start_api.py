import uvicorn
from fastapi import FastAPI
from psutil import cpu_percent, virtual_memory, disk_usage
import platform
import logging

logger = logging.getLogger("TelegramVideoBot")

app = FastAPI()

@app.get("/status")
def get_status():
    try:
        return {
            "system": platform.system(),
            "release": platform.release(),
            "cpu_percent": cpu_percent(interval=1),
            "ram_percent": virtual_memory().percent,
            "disk_percent": disk_usage("/").percent,
        }
    except Exception as e:
        logger.error(f"Error in /status endpoint: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)

import json
import os
from threading import Lock

class RotationManager:
    def __init__(self, keywords, state_file):
        self.keywords = keywords
        self.state_file = state_file
        self.lock = Lock()
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "index" in data:
                        idx = data["index"]
                        if 0 <= idx < len(self.keywords):
                            return data
            except Exception:
                pass
        return {"index": 0}

    def _save_state(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f)

    def next_keyword(self):
        with self.lock:
            keyword = self.keywords[self.state["index"]]
            self.state["index"] = (self.state["index"] + 1) % len(self.keywords)
            self._save_state()
            return keyword

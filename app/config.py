import json
import os
import sys


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "BiliDownloader")


class Config:
    DEFAULTS = {
        "output_dir": os.path.join(os.path.expanduser("~"), "Downloads", "BiliDownloader"),
        "quality_qn": 0,
        "codec": "auto",
        "concurrent": 2,
        "threads": 4,
        "template": "{quality}_{title}{p2}",
        "cookie": "",
        "ffmpeg_path": "",
    }

    def __init__(self):
        self.path = os.path.join(app_dir(), "config.json")
        self.data = dict(self.DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data.update(json.load(f))
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def __getitem__(self, key):
        return self.data.get(key, self.DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value
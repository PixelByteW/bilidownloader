from dataclasses import dataclass


@dataclass
class Task:
    bvid: str = ""
    page: int = 1
    part_title: str = ""
    video_title: str = ""
    duration: int = 0
    url: str = ""
    selected: bool = True
    status: str = "等待"
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    size: str = ""
    filename: str = ""
    error: str = ""
    index: int = 0
    total: int = 1
    quality_qn: int = 0
    _actual_height: int = 0


class FormatInfo:
    def __init__(self):
        self.qns = []
        self.codecs = set()
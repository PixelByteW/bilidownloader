import os
import queue
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.bili_api import BiliClient
from app.config import Config
from app.downloader import Downloader


def main():
    cfg = Config()
    cfg["output_dir"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_out")
    cfg["template"] = "batch_{title}_{n}"
    cfg["quality_qn"] = 64
    cfg["codec"] = "avc"
    cfg["concurrent"] = 2

    client = BiliClient()
    tasks = client.resolve("https://www.bilibili.com/video/BV1HpuR6EE7V")
    tasks = tasks + client.resolve("https://www.bilibili.com/video/BV1ucb96VEXk?p=1")
    for i, t in enumerate(tasks):
        t.index = i

    evq = queue.Queue()
    dl = Downloader(cfg, evq)
    dl.start(tasks)
    done = False
    while not done:
        try:
            while True:
                kind, payload, extra = evq.get_nowait()
                if kind == "task":
                    t = payload
                    print("  [{}] {:.0f}% {} {}".format(t.video_title[:12], t.progress, t.status, t.speed))
                elif kind == "log":
                    print("[log]", payload)
                elif kind == "all_done":
                    done = True
        except queue.Empty:
            pass
        time.sleep(0.2)

    ok = all(t.status == "完成" for t in tasks)
    for t in tasks:
        print("任务:", t.video_title[:20], "->", t.status, t.filename, t.size)
    assert ok, "存在失败任务"
    print("OK: 批量并发下载全部完成")


if __name__ == "__main__":
    main()
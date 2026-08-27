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
    cfg["template"] = "{title}_{p}"
    cfg["quality_qn"] = 16
    cfg["codec"] = "auto"
    cfg["concurrent"] = 2

    client = BiliClient()
    tasks = client.resolve("https://www.bilibili.com/video/BV1HpuR6EE7V")
    tasks = tasks[:1]

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
                    print("{:.0f}% {} {} {}".format(t.progress, t.status, t.speed, t.eta))
                elif kind == "log":
                    print("[log]", payload)
                elif kind == "all_done":
                    done = True
        except queue.Empty:
            pass
        time.sleep(0.2)

    t = tasks[0]
    print("最终状态:", t.status, "文件:", t.filename, "大小:", t.size)
    assert t.status == "完成", "下载失败"
    f = os.path.join(cfg["output_dir"], t.filename)
    assert os.path.isfile(f) and os.path.getsize(f) > 1000, "文件异常"
    print("OK: 文件存在于", f)


if __name__ == "__main__":
    main()
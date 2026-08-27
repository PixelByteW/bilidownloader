import os
import queue
import sys
import time

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def run_cli(argv):
    from app.bili_api import BiliClient
    from app.config import Config
    from app.downloader import Downloader

    url = argv[0]
    outdir = argv[1] if len(argv) > 1 else "."
    qn = int(argv[2]) if len(argv) > 2 else 0
    codec = argv[3] if len(argv) > 3 else "auto"
    cfg = Config()
    cfg["output_dir"] = outdir
    cfg["quality_qn"] = qn
    cfg["codec"] = codec
    cfg["concurrent"] = 1
    cfg["template"] = "{quality}_{title}{p2}"
    client = BiliClient(cfg["cookie"])
    tasks = client.resolve(url, include_parts=False)
    if not tasks:
        print("无任务")
        return 1
    evq = queue.Queue()
    dl = Downloader(cfg, evq)
    dl.start(tasks[:1])
    while True:
        try:
            while True:
                kind, payload, extra = evq.get_nowait()
                if kind == "task":
                    t = payload
                    print("{} {:.0f}%".format(t.status, t.progress))
                elif kind == "log":
                    print("[log]", payload)
                elif kind == "all_done":
                    t = tasks[0]
                    print("RESULT {} {}".format(t.status, t.filename or ""))
                    return 0 if t.status == "完成" else 1
        except queue.Empty:
            pass
        time.sleep(0.2)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        sys.exit(run_cli(sys.argv[2:]))
    if getattr(sys, "frozen", False):
        _install_error_log()
    from app.ui import App

    app = App()
    app.mainloop()


def _install_error_log():
    import traceback

    log_path = os.path.join(os.path.dirname(sys.executable), "error.log")

    def hook(t, v, tb):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("=" * 30 + "\n")
                traceback.print_exception(t, v, tb, file=f)
        except Exception:
            pass

    sys.excepthook = hook


if __name__ == "__main__":
    main()
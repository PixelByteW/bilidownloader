import os
import queue
import re
import sys
import threading

import yt_dlp

from .bili_api import QN_HEIGHT, QN_LABEL, write_cookies_file


def height_to_label(height):
    if not height:
        return ""
    if height >= 2160:
        return "4K"
    if height >= 1440:
        return "2K"
    if height >= 1080:
        return "1080P"
    if height >= 720:
        return "720P"
    if height >= 480:
        return "480P"
    if height >= 360:
        return "360P"
    return "{}P".format(height)


def format_size(n):
    if not n:
        return ""
    n = float(n)
    units = ["B", "KB", "MB", "GB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return "{:.1f}{}".format(n, units[i])


def format_speed(bps):
    if not bps:
        return ""
    return format_size(bps) + "/s"


def format_eta(sec):
    if not sec:
        return ""
    sec = int(sec)
    if sec < 60:
        return "{}s".format(sec)
    return "{}m{:02d}s".format(sec // 60, sec % 60)


RESERVED = {"CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}


def sanitize_filename(name, max_len=80):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if name.upper() in RESERVED:
        name = "_" + name
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
    return name or "video"


def build_format(height, codec):
    base = "bv*[height<={}]+ba".format(height)
    if codec == "auto":
        return base + "/b"
    re_map = {"avc": r"^avc", "hevc": r"^(hev|hvc)", "av1": r"^av01"}
    c = re_map.get(codec)
    if not c:
        return base + "/b"
    return ("bv*[height<={}][vcodec~='{}']+ba/{}/b"
            .format(height, c, base))


class _Logger:
    def __init__(self, evq):
        self.evq = evq

    def debug(self, msg):
        pass

    def info(self, msg):
        self.evq.put(("log", msg, None))

    def warning(self, msg):
        self.evq.put(("log", msg, None))

    def error(self, msg):
        self.evq.put(("log", msg, None))


class Downloader:
    def __init__(self, config, evq):
        self.config = config
        self.evq = evq
        self.q = queue.Queue()
        self.workers = []
        self.active = 0
        self.stop_flag = threading.Event()

    def start(self, tasks):
        self.stop_flag.clear()
        for t in tasks:
            if t.selected and t.status not in ("完成", "下载中"):
                t.status = "等待"
                self.q.put(t)
        self.workers = [w for w in self.workers if w.is_alive()]
        n = int(self.config["concurrent"] or 2)
        while len(self.workers) < n:
            w = threading.Thread(target=self._worker, daemon=True)
            w.start()
            self.workers.append(w)

    def stop(self):
        self.stop_flag.set()
        while True:
            try:
                t = self.q.get_nowait()
                t.status = "已停止"
                self.evq.put(("task", t, None))
            except queue.Empty:
                break

    def _worker(self):
        while True:
            if self.stop_flag.is_set():
                break
            try:
                t = self.q.get(timeout=1)
            except queue.Empty:
                if self.stop_flag.is_set():
                    break
                continue
            self.active += 1
            try:
                self._run_with_retry(t)
                t.status = "完成"
                t.progress = 100
            except Exception as e:
                t.status = "失败"
                t.error = str(e)
                self.evq.put(("log", "[跳过] {} P{}: {}，已跳过该编号，继续下一个"
                              .format(t.video_title, t.page, e), None))
            finally:
                self.active -= 1
                self.q.task_done()
                self.evq.put(("task", t, None))
                if self.q.empty() and self.active == 0:
                    self.evq.put(("all_done", None, None))

    def _run_with_retry(self, t):
        last = None
        for attempt in range(2):
            try:
                self._run(t)
                return
            except Exception as e:
                last = e
                if attempt == 0:
                    self.evq.put(("log", "[重试] {} P{}: {}，自动重试一次"
                                  .format(t.video_title, t.page, e), None))
        raise last

    def _run(self, t):
        t.status = "下载中"
        t.progress = 0
        t.speed = ""
        t.eta = ""
        self.evq.put(("task", t, None))
        outdir = self.config["output_dir"]
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as e:
            raise RuntimeError("无法创建输出目录: {}".format(e))
        template = self.config["template"] or "{title}"
        qn = int(t.quality_qn or self.config["quality_qn"] or 0)
        name = self._render_name(t, template, qn=qn)
        outtmpl = os.path.join(outdir, name + ".%(ext)s")
        codec = self.config["codec"] or "auto"
        height = QN_HEIGHT.get(qn, 100000) if qn else 100000
        ff = self._find_ffmpeg()
        fmt = build_format(height, codec)
        opts = {
            "outtmpl": outtmpl,
            "format": fmt,
            "noprogress": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 5,
            "fragment_retries": 5,
            "merge_output_format": "mp4",
            "concurrent_fragment_downloads": int(self.config["threads"] or 4),
            "downloader": "curl_cffi",
            "progress_hooks": [lambda d: self._hook(t, d)],
            "logger": _Logger(self.evq),
            "socket_timeout": 30,
        }
        if ff:
            opts["ffmpeg_location"] = os.path.dirname(ff)
        else:
            self.evq.put(("log", "[提示] {}: 未找到 ffmpeg，将优先单文件格式".format(
                t.video_title), None))
        cookie = self.config["cookie"]
        if cookie:
            cf = write_cookies_file(cookie)
            if cf:
                opts["cookiefile"] = cf
        with yt_dlp.YoutubeDL(opts) as ydl:
            code = ydl.download([t.url])
        if code:
            raise RuntimeError("下载返回错误码 {}".format(code))
        cand = [os.path.join(outdir, f) for f in os.listdir(outdir)
                if f.startswith(name + ".")]
        if cand:
            newest = max(cand, key=os.path.getmtime)
            t.size = format_size(os.path.getsize(newest))
            t.filename = os.path.basename(newest)
            actual = height_to_label(getattr(t, "_actual_height", 0))
            want = QN_LABEL.get(qn, "自动") if qn else "自动"
            if actual and actual != want and "{quality}" in template:
                new = self._render_name(t, template, qn=qn,
                                        quality_override=actual)
                if new != name:
                    old_p = newest
                    new_p = os.path.join(outdir, new + os.path.splitext(newest)[1])
                    try:
                        os.rename(old_p, new_p)
                        t.filename = os.path.basename(new_p)
                        self.evq.put(("log", "[提示] {}: 实际画质 {}，文件已按实际画质重命名"
                                      .format(t.video_title, actual), None))
                    except OSError:
                        pass
            elif actual:
                self.evq.put(("log", "[提示] {}: 实际画质 {}".format(
                    t.video_title, actual), None))
        t.progress = 100

    def _render_name(self, t, template, qn=None, quality_override=None):
        title = t.part_title or t.video_title
        if qn is None:
            qn = int(t.quality_qn or self.config["quality_qn"] or 0)
        quality = quality_override or QN_LABEL.get(qn, str(qn) if qn else "自动")
        codec = self.config["codec"] or "auto"
        if codec == "auto":
            codec = "自动"
        try:
            name = template.format(
                title=title, video=t.video_title, bvid=t.bvid,
                p=str(t.page), p2="" if t.total <= 1 else "_{:02d}".format(t.page),
                n="{:03d}".format(t.index + 1),
                quality=quality, codec=codec)
        except (KeyError, IndexError, ValueError):
            name = template
        return sanitize_filename(name)

    def _hook(self, t, d):
        st = d.get("status")
        if st == "downloading":
            info = d.get("info_dict") or {}
            h = info.get("height") or 0
            if h and h > getattr(t, "_actual_height", 0):
                t._actual_height = h
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            t.progress = (got / total * 100) if total else 0
            t.speed = format_speed(d.get("speed"))
            t.eta = format_eta(d.get("eta"))
            self.evq.put(("task", t, None))
        elif st == "finished":
            t.progress = 100

    def _find_ffmpeg(self):
        cfg = self.config["ffmpeg_path"]
        if cfg and os.path.isfile(cfg):
            return cfg
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
            exe_dir = os.path.dirname(sys.executable)
            dirs = [base, exe_dir, os.path.join(exe_dir, "ffmpeg")]
        else:
            dirs = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
        for d in dirs:
            for cand in [os.path.join(d, "ffmpeg.exe"),
                         os.path.join(d, "ffmpeg", "ffmpeg.exe")]:
                if os.path.isfile(cand):
                    return cand
        for d in os.environ.get("PATH", "").split(os.pathsep):
            p = os.path.join(d, "ffmpeg.exe")
            if os.path.isfile(p):
                return p
        return ""
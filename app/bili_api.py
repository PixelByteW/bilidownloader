import json
import os
import re
import tempfile
import time

import requests

from .models import FormatInfo, Task

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
API = "https://api.bilibili.com"
QN_HEIGHT = {127: 2160, 126: 2160, 125: 2160, 120: 2160, 116: 1080,
             112: 1080, 80: 1080, 74: 720, 64: 720, 32: 480, 16: 360, 6: 240}
QN_LABEL = {127: "8K", 126: "杜比视界", 125: "杜比全景声", 120: "4K", 116: "1080P60",
            112: "1080P+", 80: "1080P", 74: "720P60", 64: "720P", 32: "480P",
            16: "360P", 6: "240P"}
BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")


class BiliError(Exception):
    pass


def parse_input(text):
    text = text.strip()
    sid = re.search(r"[?&]sid=(\d+)", text)
    series_id = re.search(r"[?&]series_id=(\d+)", text)
    fid = re.search(r"[?&](?:fid|media_id)=(\d+)", text)
    bv = BV_RE.search(text)
    m_sd = re.search(r"channel/seriesdetail\?[^ ]*?sid=(\d+)", text)
    m_list = re.search(r"(?:www\.)?bilibili\.com/list/(\d+)(?:\?[^ ]*?sid=(\d+))?", text)
    m_lists = re.search(r"space\.bilibili\.com/(\d+)/lists/(\d+)", text)
    if m_sd:
        return "series", (None, int(m_sd.group(1)))
    if m_list:
        return "series", (int(m_list.group(1)), int(m_list.group(2) or 0))
    if m_lists:
        mid, lsid = int(m_lists.group(1)), int(m_lists.group(2))
        if re.search(r"type=season", text):
            return "collection", lsid
        return "series", (mid, lsid)
    if sid:
        return "collection", int(sid.group(1))
    if fid:
        return "favorites", int(fid.group(1))
    if bv:
        p = 1
        pm = re.search(r"[?&]p=(\d+)", text)
        if pm:
            p = int(pm.group(1))
        s = int(series_id.group(1)) if series_id else None
        return "video", (bv.group(0), p, s)
    if re.match(r"https?://", text):
        try:
            r = requests.get(text, headers={"User-Agent": UA}, timeout=10,
                             allow_redirects=True)
            final = r.url
            sid = re.search(r"[?&]sid=(\d+)", final)
            bv = BV_RE.search(final)
            if sid:
                return "collection", int(sid.group(1))
            if bv:
                return "video", (bv.group(0), 1, None)
        except requests.RequestException:
            pass
    raise BiliError("无法识别的链接，请粘贴 B 站视频页/合集/收藏夹链接")


class BiliClient:
    def __init__(self, cookie=""):
        self.cookie = cookie
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
        })
        if cookie:
            self.s.headers["Cookie"] = cookie
        self._view_cache = {}

    def _get(self, path, params=None, referer=None, allow_codes=()):
        headers = {}
        if referer:
            headers["Referer"] = referer
        last_err = None
        for i in range(3):
            try:
                r = self.s.get(API + path, params=params, headers=headers,
                               timeout=15)
                j = r.json()
                code = j.get("code")
                if code == 0 or code in allow_codes:
                    return j.get("data")
                msg = j.get("message") or j.get("code")
                if code == -101:
                    raise BiliError("账号未登录或 Cookie 已失效（{}）".format(msg))
                raise BiliError("接口 {} 错误: {}".format(path, msg))
            except requests.RequestException as e:
                last_err = e
                time.sleep(0.8)
        raise BiliError("网络请求失败: {}".format(last_err))

    def nav(self):
        try:
            return self._get("/x/web-interface/nav", allow_codes=(-101,))
        except BiliError:
            return None

    def video_info(self, bvid):
        if bvid in self._view_cache:
            return self._view_cache[bvid]
        d = self._get("/x/web-interface/view", {"bvid": bvid})
        pages = [{
            "cid": p.get("cid", 0),
            "page": p.get("page", 1),
            "part": p.get("part") or "第{}P".format(p.get("page", 1)),
            "duration": p.get("duration", 0),
        } for p in d.get("pages") or []]
        ug = d.get("ugc_season") or {}
        info = {
            "title": d.get("title") or bvid,
            "pages": pages,
            "owner": (d.get("owner") or {}).get("name", ""),
            "season_id": ug.get("id"),
            "season_title": ug.get("title"),
        }
        self._view_cache[bvid] = info
        return info

    def playurl(self, bvid, cid):
        return self._get("/x/player/playurl", {
            "bvid": bvid, "cid": cid, "qn": 127, "fnval": 4048,
            "fnver": 0, "fourk": 1,
        }, referer="https://www.bilibili.com/video/" + bvid)

    def summarize_formats(self, bvid, cid):
        d = self.playurl(bvid, cid)
        accept = list(zip(d.get("accept_quality") or [],
                          d.get("accept_description") or []))
        codecs = set()
        has60 = False
        for v in (d.get("dash") or {}).get("video") or []:
            c = v.get("codecs") or ""
            if c.startswith("avc1"):
                codecs.add("avc")
            elif c.startswith("hev") or c.startswith("hvc"):
                codecs.add("hevc")
            elif c.startswith("av01"):
                codecs.add("av1")
            fr = str(v.get("frameRate") or "")
            if fr:
                try:
                    if "/" in fr:
                        num, den = fr.split("/")
                        fps = int(num) / int(den)
                    else:
                        fps = float(fr)
                    if fps > 50:
                        has60 = True
                except (ValueError, ZeroDivisionError):
                    pass
        return accept, codecs, has60

    def series_meta(self, sid):
        d = self._get("/x/series/series", {"series_id": sid}) or {}
        meta = d.get("meta") or {}
        return {
            "mid": meta.get("mid"),
            "title": meta.get("name") or "",
        }

    def series_archives(self, sid, mid=None):
        if not mid:
            meta = self.series_meta(sid)
            mid = meta.get("mid")
            if not mid:
                raise BiliError("无法获取合集信息（series_id={}）".format(sid))
        out = []
        pn = 1
        while True:
            d = self._get("/x/series/archives", {
                "mid": mid, "series_id": sid, "pn": pn, "ps": 30,
            })
            for a in d.get("archives") or []:
                out.append({
                    "bvid": a["bvid"],
                    "title": a.get("title") or a["bvid"],
                    "duration": a.get("duration", 0),
                })
            total = (d.get("page") or {}).get("total", 0)
            if not d.get("archives") or len(out) >= total:
                break
            pn += 1
            time.sleep(0.2)
        return out

    def _page_collection_id(self, bvid):
        try:
            r = self.s.get("https://www.bilibili.com/video/" + bvid,
                           headers={"User-Agent": UA,
                                    "Referer": "https://www.bilibili.com/"},
                           timeout=15)
            html = r.text
            m = re.search(r'__INITIAL_STATE__\s*=\s*\{', html)
            if m:
                start = m.end() - 1
                depth = 0
                i = start
                while i < len(html):
                    ch = html[i]
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                raw = html[start:i + 1]
                m2 = re.search(r'"series_id"\s*:\s*([1-9]\d*)', raw)
                if m2:
                    return "series", int(m2.group(1))
                m2 = re.search(r'"videoData"\s*:\s*\{', raw)
                if m2:
                    vd_start = m2.end() - 1
                    depth = 0
                    i = vd_start
                    while i < len(raw):
                        ch = raw[i]
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                break
                        i += 1
                    vd = raw[vd_start:i + 1]
                    m3 = re.search(r'"season_id"\s*:\s*(\d+)', vd)
                    if m3 and int(m3.group(1)) not in (0, 102):
                        return "collection", int(m3.group(1))
            m3 = re.search(r'"seriesList"\s*:\s*\[', html)
            if m3:
                depth = 0
                i = m3.end()
                while i < len(html):
                    ch = html[i]
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                sl = json.loads(html[m3.end():i + 1])
                for s in sl or []:
                    if s.get("series_id"):
                        return "series", int(s["series_id"])
        except Exception:
            return None
        return None

    def collection_archives(self, sid):
        out = []
        pn = 1
        while True:
            d = self._get("/x/polymer/web-space/seasons_archives_list", {
                "season_id": sid, "page_num": pn, "page_size": 30,
            })
            for a in d.get("archives") or []:
                out.append({
                    "bvid": a["bvid"],
                    "title": a.get("title") or a["bvid"],
                    "duration": a.get("duration", 0),
                })
            total = (d.get("page") or {}).get("total", 0)
            if not d.get("archives") or len(out) >= total:
                break
            pn += 1
            time.sleep(0.2)
        return out

    def fav_archives(self, media_id):
        out = []
        pn = 1
        while True:
            d = self._get("/x/v3/fav/resource/list", {
                "media_id": media_id, "pn": pn, "ps": 20, "platform": "web",
            })
            for m in d.get("medias") or []:
                out.append({
                    "bvid": m["bvid"],
                    "title": m.get("title") or m["bvid"],
                    "duration": m.get("duration", 0),
                })
            if not d.get("has_more"):
                break
            pn += 1
            time.sleep(0.2)
        return out

    def _task(self, bvid, info, pg, total=1):
        return Task(
            bvid=bvid,
            page=pg.get("page", 1),
            part_title=pg.get("part") or info.get("title") or bvid,
            video_title=info.get("title") or bvid,
            duration=pg.get("duration", 0),
            url="https://www.bilibili.com/video/{bvid}?p={p}".format(
                bvid=bvid, p=pg.get("page", 1)),
            total=total,
        )

    def _tasks_from_archives(self, archives, include_parts):
        tasks = []
        for a in archives:
            try:
                info = self.video_info(a["bvid"])
                pages = info["pages"] if include_parts else [info["pages"][0]]
                for pg in pages:
                    tasks.append(self._task(a["bvid"], info, pg,
                                            total=len(pages)))
                time.sleep(0.12)
            except BiliError:
                tasks.append(self._task(a["bvid"], {"title": a["title"]}, {
                    "cid": 0, "page": 1, "part": a["title"],
                    "duration": a.get("duration", 0)}, total=1))
        return tasks

    def resolve(self, text, include_parts=True):
        mode, param = parse_input(text)
        tasks = []
        if mode == "video":
            bvid, p, series_id = param
            info = self.video_info(bvid)
            pages = info["pages"]
            if 1 < p <= len(pages):
                pages = [pages[p - 1]]
                for pg in pages:
                    tasks.append(self._task(bvid, info, pg, total=1))
            elif series_id is not None:
                tasks = self._tasks_from_archives(
                    self.series_archives(series_id), include_parts)
            elif info.get("season_id"):
                tasks = self._tasks_from_archives(
                    self.collection_archives(info["season_id"]),
                    include_parts)
            else:
                found = self._page_collection_id(bvid)
                if found:
                    kind, cid = found
                    if kind == "series":
                        tasks = self._tasks_from_archives(
                            self.series_archives(cid), include_parts)
                    else:
                        tasks = self._tasks_from_archives(
                            self.collection_archives(cid), include_parts)
                else:
                    for pg in pages:
                        tasks.append(self._task(bvid, info, pg,
                                                total=len(pages)))
        else:
            if mode == "collection":
                archives = self.collection_archives(param)
            elif mode == "series":
                mid, sid = param
                archives = self.series_archives(sid, mid)
            else:
                archives = self.fav_archives(param)
            if not archives:
                raise BiliError("未获取到视频列表（收藏夹需要登录 Cookie）")
            tasks = self._tasks_from_archives(archives, include_parts)
        if not tasks:
            raise BiliError("未解析到任何视频")
        self._fill_formats(tasks)
        return tasks

    def _fill_formats(self, tasks):
        fi = FormatInfo()
        seen = set()
        for t in tasks:
            if t.bvid in seen or len(seen) >= 5:
                continue
            seen.add(t.bvid)
            try:
                info = self.video_info(t.bvid)
                cid = info["pages"][0]["cid"]
                accept, codecs, has60 = self.summarize_formats(t.bvid, cid)
                for qn, desc in accept:
                    if not any(x[0] == qn for x in fi.qns):
                        if has60 and qn in (116, 120, 125, 126, 127) and "60" not in desc:
                            desc = desc + " 60帧"
                        fi.qns.append((qn, desc))
                fi.codecs |= codecs
            except BiliError:
                continue
        fi.qns.sort(key=lambda x: -x[0])
        for t in tasks:
            t.formats = fi


def write_cookies_file(cookie_str):
    if not cookie_str:
        return ""
    path = os.path.join(tempfile.gettempdir(), "bili_cookies.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            if cookie_str in f.read():
                return path
    except OSError:
        pass
    lines = ["# Netscape HTTP Cookie File"]
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k or not v:
            continue
        pref = "#HttpOnly_" if k in ("SESSDATA", "bili_jct") else ""
        lines.append("{}.bilibili.com\tTRUE\t/\tTRUE\t0\t{}\t{}".format(pref, k, v))
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        return ""
    return path
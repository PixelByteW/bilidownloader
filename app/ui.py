import os
import queue
import threading
import tkinter as tk

import ttkbootstrap as ttkb

from .bili_api import BiliClient, BiliError, QN_LABEL
from .config import Config
from .downloader import Downloader, format_eta, format_size, format_speed

DISCLAIMER_TEXT = """本软件《B站视频下载器》为个人学习交流项目。

使用前请仔细阅读并同意以下条款：

1. 本工具仅支持下载您本人账号有权访问的视频与清晰度，
   不包含任何形式的会员权益破解、付费内容绕过或权限提升。

2. 您应对下载内容的版权负全部责任。请勿下载、传播或用于
   商业用途任何未经授权的内容。

3. 请遵守哔哩哔哩《用户协议》及适用法律法规。因不当使用
   产生的一切后果由使用者自行承担。

4. 本工具仅用于个人学习、备份与离线观看。请在下载后合理
   时间内删除受版权保护的内容。

5. 本软件按“现状”提供，作者不对因使用本软件造成的任何
   直接或间接损失承担责任。

继续使用即代表您已阅读并同意上述条款。
"""

CODE_MAP = {"自动": "auto", "H.264 (AVC)": "avc",
            "H.265 (HEVC)": "hevc", "AV1": "av1"}


def fmt_dur(sec):
    if not sec:
        return ""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return "{}:{:02d}:{:02d}".format(h, m, s)
    return "{:02d}:{:02d}".format(m, s)


class App(ttkb.Window):
    def __init__(self):
        super().__init__(themename="cosmo")
        self.title("B站视频下载器")
        self.geometry("1080x780")
        self.minsize(900, 650)
        self.cfg = Config()
        self.evq = queue.Queue()
        self.client = BiliClient(self.cfg["cookie"])
        self.tasks = []
        self.formats = None
        self.qn_map = {}
        self.dl = Downloader(self.cfg, self.evq)
        self.running = False
        self._vars()
        self._menu()
        self._ui()
        self._restore_settings()
        self.after(100, self._poll)
        self.after(300, self._first_run)
        self.after(500, self._refresh_login)
        self.after(80, self._fit_height)

    def _fit_height(self):
        self.update_idletasks()
        w = self.winfo_width() or 1080
        need = self.winfo_reqheight()
        if need > self.winfo_height():
            self.geometry("{}x{}".format(w, need + 28))

    def _vars(self):
        self.out_var = tk.StringVar()
        self.quality_var = tk.StringVar(value="自动(最高)")
        self.codec_var = tk.StringVar(value="自动")
        self.conc_var = tk.StringVar(value=str(self.cfg["concurrent"]))
        self.thread_var = tk.StringVar(value=str(self.cfg["threads"]))
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar()
        self.template_var = tk.StringVar(value=self.cfg["template"])
        self.multi_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="就绪")
        self.login_var = tk.StringVar(value="登录状态检测中…")

    def _menu(self):
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="导入 Cookie…", command=self._cookie_dialog)
        fm.add_command(label="打开输出目录", command=self._open_outdir)
        fm.add_separator()
        fm.add_command(label="退出", command=self._quit)
        m.add_cascade(label="文件", menu=fm)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="免责声明", command=self._show_disclaimer)
        hm.add_command(label="关于", command=self._about)
        m.add_cascade(label="帮助", menu=hm)
        self.config(menu=m)

    def _ui(self):
        top = ttkb.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)
        ttkb.Label(top, text="视频链接:").grid(row=0, column=0, sticky="w")
        self.url_text = ttkb.ScrolledText(top, height=2, wrap="none",
                                          font=("Microsoft YaHei UI", 10))
        self.url_text.grid(row=0, column=1, sticky="ew", padx=6)
        self.url_text.bind("<Control-Return>", lambda e: self._parse())
        self.parse_btn = ttkb.Button(top, text="解析", bootstyle="primary",
                                     command=self._parse)
        self.parse_btn.grid(row=0, column=2, sticky="e")

        opt = ttkb.Labelframe(self, text="下载设置（对所有任务生效）",
                              padding=(8, 6))
        opt.pack(fill="x", padx=10, pady=(4, 0))
        ttkb.Label(opt, text="画质:").grid(row=0, column=0, padx=(4, 2), pady=3)
        self.quality_cb = ttkb.Combobox(opt, textvariable=self.quality_var,
                                        state="readonly", width=18)
        self.quality_cb.grid(row=0, column=1, padx=(0, 10))
        self.quality_cb.bind("<<ComboboxSelected>>",
                             lambda e: self._refresh_table())
        ttkb.Label(opt, text="编码:").grid(row=0, column=2, padx=(4, 2))
        self.codec_cb = ttkb.Combobox(opt, textvariable=self.codec_var,
                                      state="readonly", width=12,
                                      values=list(CODE_MAP))
        self.codec_cb.grid(row=0, column=3, padx=(0, 10))
        ttkb.Label(opt, text="并发:").grid(row=0, column=4, padx=(4, 2))
        self.conc_sp = ttkb.Spinbox(opt, from_=1, to=8, width=4,
                                    textvariable=self.conc_var)
        self.conc_sp.grid(row=0, column=5, padx=(0, 10))
        ttkb.Label(opt, text="线程:").grid(row=0, column=6, padx=(4, 2))
        self.thread_sp = ttkb.Spinbox(opt, from_=1, to=16, width=4,
                                      textvariable=self.thread_var)
        self.thread_sp.grid(row=0, column=7, padx=(0, 10))
        ttkb.Label(opt, text="输出目录:").grid(row=0, column=8, padx=(4, 2))
        ttkb.Entry(opt, textvariable=self.out_var).grid(row=0, column=9,
                                                        sticky="ew")
        ttkb.Button(opt, text="浏览…", command=self._pick_dir).grid(
            row=0, column=10, padx=(4, 2))
        ttkb.Checkbutton(opt, text="合集/收藏展开全部分P", bootstyle="round-toggle",
                         variable=self.multi_var).grid(row=0, column=11,
                                                       padx=(10, 0))
        opt.columnconfigure(9, weight=1)

        nm = ttkb.Labelframe(self, text="批量命名模板", padding=(8, 6))
        nm.pack(fill="x", padx=10, pady=(4, 0))
        self.template_entry = ttkb.Entry(nm, textvariable=self.template_var)
        self.template_entry.pack(side="left", fill="x", expand=True)
        ttkb.Button(nm, text="恢复默认", bootstyle="secondary",
                    command=lambda: self.template_var.set("{quality}_{title}{p2}")
                    ).pack(side="left", padx=(6, 0))
        presets = ttkb.Combobox(nm, state="readonly", width=18,
                                values=["画质+视频名(默认)", "纯视频名", "视频名+分P",
                                        "序号_画质_标题", "序号_视频名", "主标题_分P"],
                                font=("Microsoft YaHei UI", 9))
        presets.set("常用预设")
        presets.pack(side="left", padx=(6, 0))
        preset_map = {"画质+视频名(默认)": "{quality}_{title}{p2}",
                      "纯视频名": "{title}",
                      "视频名+分P": "{title}{p2}",
                      "序号_画质_标题": "{n}_{quality}_{title}{p2}",
                      "序号_视频名": "{n}_{title}",
                      "主标题_分P": "{video}{p2}"}

        def on_preset(e):
            self.template_var.set(preset_map.get(presets.get(), self.template_var.get()))

        presets.bind("<<ComboboxSelected>>", on_preset)
        trow = ttkb.Frame(nm)
        trow.pack(fill="x", pady=(6, 0))
        for tok, tip in (("{title}", "分P标题"), ("{video}", "主标题"),
                         ("{p}", "分P序号"), ("{p2}", "分P序号(单P为空)"),
                         ("{quality}", "画质"), ("{codec}", "编码"),
                         ("{bvid}", "BV号"), ("{n}", "导入顺序号(01起)")):
            ttkb.Button(trow, text=tok, bootstyle="outline-secondary",
                        command=lambda t=tok: self._tpl_insert(t)).pack(
                side="left", padx=(0, 4))

        mid = ttkb.Frame(self, padding=(10, 6))
        mid.pack(fill="both", expand=True)
        frow = ttkb.Frame(mid)
        frow.pack(fill="x", pady=(0, 4))
        ttkb.Label(frow, text="搜索:").pack(side="left")
        self.search_entry = ttkb.Entry(frow, textvariable=self.search_var,
                                       width=26)
        self.search_entry.pack(side="left", padx=6)
        self.search_entry.bind("<KeyRelease>",
                               lambda e: self._refresh_table())
        ttkb.Button(frow, text="清除", bootstyle="secondary",
                    command=lambda: (self.search_var.set(""),
                                     self._refresh_table())).pack(
            side="left", padx=(0, 6))
        ttkb.Label(frow, textvariable=self.filter_var,
                   bootstyle="secondary").pack(side="right")
        cols = ("sel", "title", "q", "bvid", "page", "dur", "size", "status", "progress")
        self.tree = ttkb.Treeview(mid, columns=cols, show="headings",
                                  selectmode="extended")
        heads = {"sel": "选", "title": "标题", "q": "画质",
                 "bvid": "BVID", "page": "分P", "dur": "时长", "size": "大小",
                 "status": "状态", "progress": "进度"}
        widths = {"sel": 42, "title": 368, "q": 78, "bvid": 118, "page": 46,
                  "dur": 62, "size": 76, "status": 72, "progress": 150}
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="center",
                             stretch=(c in ("title", "progress")))
        ys = ttkb.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tree.tag_configure("done", foreground="#2e7d32")
        self.tree.tag_configure("error", foreground="#c62828")
        self.tree.tag_configure("run", foreground="#1565c0")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-1>", self._on_tree_dblclick)

        btns = ttkb.Frame(self, padding=(10, 4))
        btns.pack(fill="x")
        for text, cmd in (("全选", self._select_all),
                          ("反选", self._invert),
                          ("移除选中", self._remove_selected),
                          ("清空列表", self._clear_all)):
            ttkb.Button(btns, text=text, bootstyle="secondary",
                        command=cmd).pack(side="left", padx=(0, 6))
        ttkb.Button(btns, text="清空日志", bootstyle="secondary",
                    command=lambda: self.log_text.delete("1.0", "end")).pack(
            side="left", padx=(0, 6))
        self.start_btn = ttkb.Button(btns, text="开始下载", bootstyle="success",
                                     command=self._start)
        self.start_btn.pack(side="right", padx=(6, 0))
        ttkb.Button(btns, text="停止", bootstyle="danger",
                    command=self._stop).pack(side="right", padx=(0, 6))

        bot = ttkb.Frame(self, padding=(10, 6))
        bot.pack(fill="x")
        self.global_bar = ttkb.Progressbar(bot, maximum=100, value=0,
                                           bootstyle="success-striped")
        self.global_bar.pack(fill="x")
        self.log_text = ttkb.ScrolledText(bot, height=7, wrap="word",
                                          state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="x", pady=(4, 0))

        sb = ttkb.Frame(self, padding=(10, 4))
        sb.pack(fill="x")
        self.login_lbl = ttkb.Label(sb, textvariable=self.login_var,
                                    bootstyle="secondary")
        self.login_lbl.pack(side="left")
        ttkb.Label(sb, textvariable=self.status_var,
                   bootstyle="secondary").pack(side="right")

    def _restore_settings(self):
        self.out_var.set(self.cfg["output_dir"])
        codec = self.cfg["codec"]
        for k, v in CODE_MAP.items():
            if v == codec:
                self.codec_var.set(k)
        self._apply_formats(None)

    def _apply_formats(self, fi):
        self.formats = fi
        vals = ["自动(最高)"]
        self.qn_map = {"自动(最高)": 0}
        if fi and fi.qns:
            for qn, desc in fi.qns:
                self.qn_map[desc] = qn
                vals.append(desc)
        self.quality_cb.configure(values=vals)
        cur = self.quality_var.get()
        if cur not in vals:
            self.quality_var.set("自动(最高)")
        self._refresh_table()

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        if int(float(self.log_text.index("end-1c").split(".")[0])) > 2500:
            self.log_text.delete("1.0", "500.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _parse(self):
        raw = self.url_text.get("1.0", "end")
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            messagebox_show("提示", "请先粘贴 B 站链接，每行一个，支持批量")
            return
        inc = bool(self.multi_var.get())
        self.parse_btn.configure(state="disabled")
        self.url_text.configure(state="disabled")
        self.status_var.set("正在解析 {} 个链接…".format(len(lines)))
        threading.Thread(target=self._parse_worker, args=(lines, inc),
                         daemon=True).start()

    def _parse_worker(self, texts, inc):
        tasks = []
        errors = []
        for i, text in enumerate(texts, 1):
            try:
                ts = self.client.resolve(text, include_parts=inc)
                tasks.extend(ts)
            except BiliError as e:
                errors.append("第 {} 行: {}".format(i, e))
            except Exception as e:
                errors.append("第 {} 行: 解析异常 {}".format(i, e))
        self.evq.put(("parse_ok", (tasks, errors), None))

    def _parse_ok(self, payload):
        tasks, errors = payload
        self.parse_btn.configure(state="normal")
        self.url_text.configure(state="normal")
        base = len(self.tasks)
        for i, t in enumerate(tasks):
            t.index = base + i
            self.tasks.append(t)
        if tasks:
            self._apply_formats(tasks[0].formats)
        self._refresh_table()
        for e in errors:
            self._log("[已跳过] " + e)
        if tasks:
            self.status_var.set("解析完成，共 {} 个分P任务".format(len(tasks)))
            self._log("解析完成: {} 个任务（{} 行失败已跳过，序号按导入顺序排列）"
                      .format(len(tasks), len(errors)))
        elif errors:
            self.status_var.set("解析失败：全部 {} 行均无法识别".format(len(errors)))
            self._log("[解析失败] 全部链接无法解析")
            messagebox_show("解析失败",
                            "全部链接解析失败，详见日志。\n" + errors[0])

    def _parse_err(self, msg):
        self.parse_btn.configure(state="normal")
        self.url_text.configure(state="normal")
        self.status_var.set("解析失败")
        self._log("[解析失败] " + msg)
        messagebox_show("解析失败", msg)

    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        kw = self.search_var.get().strip().lower()
        n = 0
        for t in self.tasks:
            if kw and kw not in t.part_title.lower() and \
                    kw not in t.video_title.lower() and \
                    kw not in t.bvid.lower():
                continue
            self._insert_row(t)
            n += 1
        if kw:
            self.filter_var.set("筛选出 {}/{} 条".format(n, len(self.tasks)))
        else:
            self.filter_var.set("共 {} 条".format(len(self.tasks)))

    def _q_text(self, t):
        if t.quality_qn:
            label = QN_LABEL.get(t.quality_qn, str(t.quality_qn))
            return "★" + label
        gqn = self.qn_map.get(self.quality_var.get(), 0)
        return QN_LABEL.get(gqn, "自动") if gqn else "自动"

    def _insert_row(self, t):
        iid = "t{}".format(t.index)
        tag = "run" if t.status in ("下载中", "等待") else (
            "done" if t.status == "完成" else (
                "error" if t.status in ("失败", "已停止") else ""))
        self.tree.insert("", "end", iid=iid, tags=(tag,),
                         values=(self._sel_text(t), t.part_title, self._q_text(t),
                                 t.bvid, "P{}".format(t.page), fmt_dur(t.duration),
                                 t.size, t.status, self._prog_text(t)))

    def _sel_text(self, t):
        return "√" if t.selected else ""

    def _prog_text(self, t):
        if t.status == "下载中":
            return "{:.0f}% {}{}".format(t.progress, t.speed, t.eta)
        if t.status == "完成":
            return "100%"
        return ""

    def _update_row(self, t):
        iid = "t{}".format(t.index)
        if not self.tree.exists(iid):
            return
        tag = "run" if t.status in ("下载中", "等待") else (
            "done" if t.status == "完成" else (
                "error" if t.status in ("失败", "已停止") else ""))
        self.tree.item(iid, tags=(tag,), values=(
            self._sel_text(t), t.part_title, self._q_text(t),
            t.bvid, "P{}".format(t.page), fmt_dur(t.duration),
            t.size, t.status, self._prog_text(t)))

    def _on_tree_click(self, e):
        if self.tree.identify("region", e.x, e.y) != "cell":
            return
        if self.tree.identify_column(e.x) != "#1":
            return
        iid = self.tree.identify_row(e.y)
        if not iid:
            return
        t = self.tasks[int(iid[1:])]
        t.selected = not t.selected
        self._update_row(t)

    def _on_tree_dblclick(self, e):
        if self.tree.identify("region", e.x, e.y) != "cell":
            return
        iid = self.tree.identify_row(e.y)
        if not iid:
            return
        t = self.tasks[int(iid[1:])]
        self._quality_dialog(t)

    def _quality_dialog(self, t):
        dlg = ttkb.Toplevel(self)
        dlg.title("设置画质")
        dlg.transient(self)
        dlg.grab_set()
        ttkb.Label(dlg, text="为任务单独设置画质（双击行可修改）",
                   bootstyle="secondary").pack(padx=12, pady=(10, 2))
        var = tk.StringVar()
        opts = ["继承全局设置"]
        qn_map = {"继承全局设置": 0}
        if getattr(t, "formats", None) and t.formats.qns:
            for qn, desc in t.formats.qns:
                opts.append(desc)
                qn_map[desc] = qn
        else:
            opts.append("自动(最高)")
            qn_map["自动(最高)"] = 0
        cb = ttkb.Combobox(dlg, textvariable=var, state="readonly",
                           values=opts, width=28)
        cb.set("继承全局设置")
        cb.pack(pady=8)
        var.trace_add("write", lambda *a: None)

        def apply():
            t.quality_qn = qn_map.get(var.get(), 0)
            dlg.destroy()
            self._update_row(t)
            self._log("已设置画质: {} -> {}".format(
                t.part_title[:20], var.get()))

        row = ttkb.Frame(dlg)
        row.pack(pady=8)
        ttkb.Button(row, text="确定", bootstyle="success",
                    command=apply).pack(side="left", padx=6)
        ttkb.Button(row, text="取消", bootstyle="secondary",
                    command=dlg.destroy).pack(side="left", padx=6)
        cb.focus_set()
        dlg.update_idletasks()
        dlg.geometry("{}x{}".format(dlg.winfo_reqwidth(), dlg.winfo_reqheight()))

    def _select_all(self):
        for t in self.tasks:
            t.selected = True
        self._refresh_table()

    def _invert(self):
        for t in self.tasks:
            t.selected = not t.selected
        self._refresh_table()

    def _remove_selected(self):
        self.tasks = [t for t in self.tasks if not t.selected]
        self._refresh_table()

    def _clear_all(self):
        self.tasks = []
        self._refresh_table()

    def _pick_dir(self):
        d = filedialog_askdirectory(initialdir=self.out_var.get() or None)
        if d:
            self.out_var.set(d)

    def _open_outdir(self):
        d = self.out_var.get()
        if not d:
            return
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)
        except OSError:
            pass

    def _tpl_insert(self, tok):
        e = self.template_entry
        try:
            pos = e.index("insert")
        except tk.TclError:
            pos = len(self.template_var.get())
        s = self.template_var.get()
        self.template_var.set(s[:pos] + tok + s[pos:])
        try:
            e.icursor(pos + len(tok))
            e.focus_set()
        except tk.TclError:
            pass

    def _save_settings(self):
        self.cfg["output_dir"] = self.out_var.get().strip() or self.cfg["output_dir"]
        self.cfg["quality_qn"] = self.qn_map.get(self.quality_var.get(), 0)
        self.cfg["codec"] = CODE_MAP.get(self.codec_var.get(), "auto")
        try:
            self.cfg["concurrent"] = max(1, min(8, int(self.conc_var.get())))
        except ValueError:
            pass
        try:
            self.cfg["threads"] = max(1, min(16, int(self.thread_var.get())))
        except ValueError:
            pass
        self.cfg["template"] = self.template_var.get().strip() or "{quality}_{title}{p2}"
        self.cfg.save()

    def _start(self):
        sel = [t for t in self.tasks
               if t.selected and t.status not in ("完成", "下载中")]
        if not sel:
            messagebox_show("提示", "没有可下载的任务，请先在列表中勾选")
            return
        self._save_settings()
        self.out_var.set(self.cfg["output_dir"])
        if not self.dl._find_ffmpeg():
            self._log("[提示] 未找到 ffmpeg：高画质（需音视频合并）可能失败，"
                      "可将 ffmpeg.exe 放到程序目录")
        self.running = True
        self.start_btn.configure(state="disabled")
        self.dl.start(sel)
        self.status_var.set("下载中…")
        self._log("开始下载 {} 个任务，输出到: {}".format(len(sel),
                                                     self.cfg["output_dir"]))

    def _stop(self):
        self.dl.stop()
        self.status_var.set("已请求停止")
        self._log("已请求停止，当前任务结束后停止")

    def _poll(self):
        try:
            while True:
                kind, payload, extra = self.evq.get_nowait()
                if kind == "task":
                    self._update_row(payload)
                elif kind == "log":
                    self._log(payload)
                elif kind == "all_done":
                    if self.running:
                        self.running = False
                        self.start_btn.configure(state="normal")
                        self.status_var.set("全部任务完成")
                        self._log("全部任务完成")
                elif kind == "parse_ok":
                    self._parse_ok(payload)
                elif kind == "parse_err":
                    self._parse_err(payload)
                elif kind == "login":
                    self.login_var.set(payload)
        except queue.Empty:
            pass
        self._update_global_bar()
        self.after(100, self._poll)

    def _update_global_bar(self):
        vals = [t.progress for t in self.tasks if t.selected]
        self.global_bar["value"] = sum(vals) / len(vals) if vals else 0

    def _first_run(self):
        self._show_disclaimer(blocking=True)

    def _show_disclaimer(self, blocking=False):
        dlg = ttkb.Toplevel(self)
        dlg.title("免责声明")
        dlg.minsize(560, 420)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        ttkb.Label(dlg, text="免责声明", font=("Microsoft YaHei UI", 14, "bold")
                   ).pack(pady=(12, 4))
        txt = ttkb.ScrolledText(dlg, height=14, wrap="word",
                                font=("Microsoft YaHei UI", 10))
        txt.pack(fill="both", expand=True, padx=14, pady=4)
        txt.insert("1.0", DISCLAIMER_TEXT)
        txt.configure(state="disabled")
        agree = tk.BooleanVar(value=False)
        ttkb.Checkbutton(dlg, text="我已阅读并同意上述声明",
                         variable=agree).pack(pady=(6, 2))

        def ok():
            if not agree.get():
                messagebox_show("提示", "请先勾选“我已阅读并同意上述声明”",
                                parent=dlg)
                return
            dlg.destroy()

        def quit_app():
            dlg.destroy()
            self._quit()

        row = ttkb.Frame(dlg)
        row.pack(pady=(4, 12))
        ttkb.Button(row, text="同意并继续", bootstyle="success",
                    command=ok).pack(side="left", padx=8)
        ttkb.Button(row, text="退出", bootstyle="secondary",
                    command=quit_app).pack(side="left", padx=8)
        dlg.protocol("WM_DELETE_WINDOW", quit_app)
        dlg.update_idletasks()
        dlg.geometry("680x{}".format(dlg.winfo_reqheight()))

    def _cookie_dialog(self):
        dlg = ttkb.Toplevel(self)
        dlg.title("导入 Cookie")
        dlg.minsize(560, 320)
        dlg.resizable(True, True)
        dlg.transient(self)
        dlg.grab_set()
        ttkb.Label(dlg, text=(
            "粘贴 B 站登录后的 Cookie 请求头，用于下载有权限访问的画质/收藏夹。\n"
            "获取方式: 浏览器登录 bilibili.com → F12 → 网络 → 任意请求 → "
            "请求头 → 复制 Cookie 整段"),
            bootstyle="secondary", justify="left", wraplength=580).pack(
            fill="x", padx=12, pady=(10, 4))
        txt = ttkb.ScrolledText(dlg, height=12, font=("Consolas", 9))
        row = ttkb.Frame(dlg)
        row.pack(side="bottom", fill="x", padx=12, pady=(0, 10))

        def save():
            c = txt.get("1.0", "end").strip()
            self.cfg["cookie"] = c
            self.cfg.save()
            self.client = BiliClient(c)
            dlg.destroy()
            self._refresh_login()
            self._log("Cookie 已保存" if c else "Cookie 已清空")

        def clear():
            txt.delete("1.0", "end")

        ttkb.Button(row, text="保存", bootstyle="success",
                    command=save).pack(side="left", padx=6)
        ttkb.Button(row, text="清空", bootstyle="secondary",
                    command=clear).pack(side="left", padx=6)
        ttkb.Button(row, text="取消", bootstyle="secondary",
                    command=dlg.destroy).pack(side="left", padx=6)
        txt.pack(fill="both", expand=True, padx=12)
        txt.insert("1.0", self.cfg["cookie"])
        dlg.update_idletasks()
        dlg.geometry("620x{}".format(dlg.winfo_reqheight()))

    def _refresh_login(self):
        def w():
            try:
                d = self.client.nav()
                if d and d.get("isLogin"):
                    name = d.get("uname") or ""
                    vip = d.get("vipStatus") or 0
                    self.evq.put(("login", "已登录: {} {}".format(
                        name, "大会员" if vip else ""), None))
                else:
                    self.evq.put(("login", "未登录（仅公开画质）", None))
            except Exception:
                self.evq.put(("login", "登录状态未知", None))
        threading.Thread(target=w, daemon=True).start()

    def _about(self):
        ff = "已就绪" if self.dl._find_ffmpeg() else "未找到"
        msg = ("B站视频下载器 v1.0\n\n"
               "技术栈: Python + yt-dlp + ttkbootstrap\n"
               "ffmpeg: {}\n"
               "仅下载你有权访问的视频与清晰度，请遵守版权法规。").format(ff)
        messagebox_show("关于", msg)

    def _quit(self):
        self._save_settings()
        self.destroy()


def messagebox_show(title, msg, parent=None):
    import tkinter.messagebox as mb
    mb.showinfo(title, msg, parent=parent)


def filedialog_askdirectory(initialdir=None):
    import tkinter.filedialog as fd
    return fd.askdirectory(initialdir=initialdir)
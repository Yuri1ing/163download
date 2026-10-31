# -*- coding: utf-8 -*-
"""图形界面（tkinter / 深色主题）。"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import time
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List

from .api import LEVELS, NeteaseAPI, fee_label, track_from_song
from .core import APP_NAME, DownloadEngine, Settings, parse_inputs, sanitize, render_name

# ------------------------------------------------------------------ 配色
BG = "#191920"
PANEL = "#23232c"
PANEL2 = "#2b2b36"
FG = "#e6e6f0"
FG_DIM = "#9a9aae"
ACCENT = "#e8443a"
ACCENT_HOVER = "#ff5749"
OK = "#3ddc84"
WARN = "#ffc857"
ERR = "#ff5c5c"
BORDER = "#3a3a47"

FONT = ("Microsoft YaHei UI", 9)
FONT_B = ("Microsoft YaHei UI", 9, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 15, "bold")

LEVEL_LABELS = {v["label"]: k for k, v in LEVELS.items()}
LEVEL_LABELS_ORDER = [LEVELS[k]["label"] for k in ("standard", "higher", "exhigh", "lossless")]


def fmt_dur(ms: int) -> str:
    if not ms:
        return "--:--"
    s = int(ms // 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v1.0")
        self.configure(bg=BG)
        self.settings = Settings.load()
        self.api = NeteaseAPI(cookie=self.settings.cookie)
        self.tracks: List[dict] = []
        self.checked: set = set()
        self.uid = 0
        self.evq: "queue.Queue[tuple]" = queue.Queue()
        self.engine: DownloadEngine | None = None
        self.group_name = ""
        self._busy_parse = False

        self._init_style()
        self._build()
        self._fit_window()
        self.after(120, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.log(f"就绪 · 音质默认 {LEVELS[self.settings.level]['label']} · "
                 f"保存到 {self.settings.save_dir}")

    # ------------------------------------------------------------ 样式
    def _fit_window(self):
        """按实际内容请求尺寸开窗，避免高 DPI(125%/150%) 下底部控件被裁掉。"""
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(max(self.winfo_reqwidth(), 900), int(sw * 0.94))
        h = min(max(self.winfo_reqheight(), 620), int(sh * 0.90))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 4)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(min(w, 880), min(h, 560))

    def _init_style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL2,
                     bordercolor=BORDER, lightcolor=PANEL2, darkcolor=PANEL2,
                     font=FONT)
        st.configure("TFrame", background=BG)
        st.configure("Panel.TFrame", background=PANEL)
        st.configure("TLabel", background=BG, foreground=FG)
        st.configure("Dim.TLabel", background=BG, foreground=FG_DIM)
        st.configure("Panel.TLabel", background=PANEL, foreground=FG)
        st.configure("Title.TLabel", background=BG, foreground=FG, font=FONT_TITLE)
        st.configure("TButton", background=PANEL2, foreground=FG, borderwidth=0,
                     focusthickness=0, padding=(14, 6))
        st.map("TButton",
               background=[("active", "#3a3a48"), ("disabled", "#25252e")],
               foreground=[("disabled", "#5d5d6d")])
        st.configure("Accent.TButton", background=ACCENT, foreground="white",
                     font=FONT_B, padding=(18, 7))
        st.map("Accent.TButton", background=[("active", ACCENT_HOVER),
                                             ("disabled", "#5a2b28")])
        st.configure("TEntry", fieldbackground=PANEL2, foreground=FG,
                     insertcolor=FG, borderwidth=0, padding=5)
        st.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2,
                     foreground=FG, arrowcolor=FG, borderwidth=0, padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL2)])
        st.configure("TCheckbutton", background=BG, foreground=FG)
        st.map("TCheckbutton", background=[("active", BG)])
        st.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                     foreground=FG, rowheight=27, borderwidth=0, font=FONT)
        st.configure("Treeview.Heading", background=PANEL2, foreground=FG_DIM,
                     borderwidth=0, font=FONT_B, padding=(6, 6))
        st.map("Treeview.Heading", background=[("active", PANEL2)])
        st.map("Treeview", background=[("selected", "#3d2b2a")],
               foreground=[("selected", "#ffffff")])
        st.configure("TProgressbar", background=ACCENT, troughcolor=PANEL2,
                     borderwidth=0, thickness=8)
        st.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=PANEL,
                     borderwidth=0, arrowcolor=FG_DIM)
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # ------------------------------------------------------------ 布局
    def _build(self):
        root = ttk.Frame(self, padding=(14, 12, 14, 10))
        root.pack(fill="both", expand=True)

        # 顶栏
        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="♪ 网易云音乐下载器", style="Title.TLabel").pack(side="left")
        self.lbl_status = ttk.Label(top, text="未登录（匿名模式）", style="Dim.TLabel")
        self.lbl_status.pack(side="left", padx=14)
        ttk.Button(top, text="打开目录", command=self.open_dir).pack(side="right")
        ttk.Button(top, text="设置", command=self.open_settings).pack(side="right", padx=8)

        # 输入区
        box = tk.Frame(root, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        box.pack(fill="x")
        inner = tk.Frame(box, bg=PANEL, padx=12, pady=10)
        inner.pack(fill="x")
        tk.Label(inner, text="粘贴 歌曲 / 歌单 / 专辑 / 歌手 链接或 ID，每行一个；也可直接输入关键词搜索",
                 bg=PANEL, fg=FG_DIM, font=FONT).pack(anchor="w")
        self.txt = tk.Text(inner, height=4, bg=PANEL2, fg=FG, insertbackground=FG,
                           relief="flat", font=("Consolas", 10), padx=8, pady=6,
                           highlightthickness=0, wrap="none")
        self.txt.pack(fill="x", pady=(6, 8))
        self.txt.insert("1.0", "https://music.163.com/playlist?id=3778678")

        bar = tk.Frame(inner, bg=PANEL)
        bar.pack(fill="x")
        self.btn_parse = tk.Button(bar, text="解析 / 搜索", command=self.do_parse,
                                   bg=ACCENT, fg="white", activebackground=ACCENT_HOVER,
                                   activeforeground="white", relief="flat", font=FONT_B,
                                   padx=16, pady=6, cursor="hand2", borderwidth=0)
        self.btn_parse.pack(side="left")
        tk.Label(bar, text="音质", bg=PANEL, fg=FG_DIM, font=FONT).pack(side="left", padx=(16, 6))
        self.var_level = tk.StringVar(value=LEVELS[self.settings.level]["label"])
        cb = ttk.Combobox(bar, textvariable=self.var_level, values=LEVEL_LABELS_ORDER,
                          width=14, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", self._on_level)
        self.var_fallback = tk.BooleanVar(value=self.settings.fallback_enabled)
        ttk.Checkbutton(bar, text="音源兜底（无版权/VIP 时自动换源）",
                        variable=self.var_fallback).pack(side="left", padx=16)
        self.lbl_count = tk.Label(bar, text="共 0 首 · 已选 0 首", bg=PANEL, fg=FG_DIM, font=FONT)
        self.lbl_count.pack(side="right")

        # 列表
        mid = ttk.Frame(root)
        mid.pack(fill="both", expand=True, pady=10)
        cols = ("sel", "idx", "title", "artist", "album", "dur", "fee", "status")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
        heads = {"sel": ("", 34), "idx": ("#", 44), "title": ("歌名", 300),
                 "artist": ("歌手", 170), "album": ("专辑", 190),
                 "dur": ("时长", 62), "fee": ("权限", 66), "status": ("状态", 190)}
        for c in cols:
            text, w = heads[c]
            anchor = "center" if c in ("sel", "idx", "dur", "fee") else "w"
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor=anchor,
                             stretch=(c in ("title", "artist", "status")))
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#20202a")
        self.tree.tag_configure("ok", foreground=OK)
        self.tree.tag_configure("fail", foreground=ERR)
        self.tree.tag_configure("skip", foreground=WARN)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-1>", self._on_tree_dbl)

        # 操作条
        ops = ttk.Frame(root)
        ops.pack(fill="x")
        for text, cmd in (("全选", lambda: self._check_all(True)),
                          ("取消全选", lambda: self._check_all(False)),
                          ("反选", self._check_invert),
                          ("移除选中", self._remove_selected),
                          ("清空列表", self._clear)):
            ttk.Button(ops, text=text, command=cmd).pack(side="left", padx=(0, 6))
        self.btn_start = tk.Button(ops, text="开始下载", command=self.do_download,
                                   bg=ACCENT, fg="white", activebackground=ACCENT_HOVER,
                                   activeforeground="white", relief="flat", font=FONT_B,
                                   padx=22, pady=6, cursor="hand2", borderwidth=0)
        self.btn_start.pack(side="right")
        self.btn_stop = ttk.Button(ops, text="停止", command=self.do_stop)
        self.btn_stop.pack(side="right", padx=8)
        self.btn_stop.state(["disabled"])

        # 进度
        pf = ttk.Frame(root)
        pf.pack(fill="x", pady=(10, 6))
        self.pb = ttk.Progressbar(pf, mode="determinate", maximum=100)
        self.pb.pack(side="left", fill="x", expand=True)
        self.lbl_prog = ttk.Label(pf, text="0 / 0", style="Dim.TLabel", width=18,
                                  anchor="e")
        self.lbl_prog.pack(side="left", padx=10)
        self.lbl_speed = ttk.Label(pf, text="", style="Dim.TLabel", width=14, anchor="e")
        self.lbl_speed.pack(side="left")

        # 日志
        lg = tk.Frame(root, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        lg.pack(fill="x", pady=(4, 0))
        self.logbox = tk.Text(lg, height=6, bg=PANEL, fg=FG_DIM, relief="flat",
                              font=("Consolas", 9), padx=10, pady=6, wrap="word",
                              highlightthickness=0, state="disabled")
        self.logbox.pack(fill="both", expand=True)
        self.logbox.tag_configure("ok", foreground=OK)
        self.logbox.tag_configure("err", foreground=ERR)
        self.logbox.tag_configure("warn", foreground=WARN)
        self.logbox.tag_configure("dim", foreground=FG_DIM)

    # ------------------------------------------------------------ 工具
    def log(self, msg: str, tag: str = "dim"):
        ts = time.strftime("%H:%M:%S")
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"[{ts}] {msg}\n", tag)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def open_dir(self):
        path = self.settings.save_dir
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)  # noqa: S606
        except Exception:  # noqa: BLE001
            subprocess.Popen(["explorer", path])

    def _on_level(self, _evt=None):
        self.settings.level = LEVEL_LABELS.get(self.var_level.get(), "exhigh")
        self.settings.save()
        self.log(f"音质切换为 {self.var_level.get()}")

    def _new_track(self, t: dict) -> dict:
        self.uid += 1
        t["uid"] = self.uid
        t["_index"] = len(self.tracks) + 1
        t["status"] = "等待"
        self.tracks.append(t)
        self.checked.add(self.uid)
        return t

    def _row_values(self, t: dict) -> tuple:
        return ("☑" if t["uid"] in self.checked else "☐",
                t["_index"], t["title"], t["artist_str"], t["album"],
                fmt_dur(t["duration"]), fee_label(t["fee"]), t["status"])

    def _refresh_row(self, t: dict):
        iid = str(t["uid"])
        if self.tree.exists(iid):
            self.tree.item(iid, values=self._row_values(t))

    def _refresh_count(self):
        self.lbl_count.configure(
            text=f"共 {len(self.tracks)} 首 · 已选 {len(self.checked)} 首")

    # ------------------------------------------------------------ 解析
    def do_parse(self):
        if self._busy_parse:
            return
        text = self.txt.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo(APP_NAME, "先粘贴链接或输入关键词")
            return
        items = parse_inputs(text)
        if not items:
            messagebox.showinfo(APP_NAME, "没识别到有效内容")
            return
        self._busy_parse = True
        self.btn_parse.configure(state="disabled", text="解析中…")
        threading.Thread(target=self._parse_worker, args=(items,), daemon=True).start()

    def _parse_worker(self, items: List[dict]):
        added = 0
        try:
            for it in items:
                kind = it["kind"]
                try:
                    if kind == "song":
                        songs = self.api.song_detail([it["id"]])
                        for s in songs:
                            self.post("add", track_from_song(s))
                            added += 1
                        self.group_name = ""
                    elif kind == "playlist":
                        pl, songs = self.api.playlist_tracks(it["id"])
                        self.group_name = pl.get("name", "")
                        for s in songs:
                            self.post("add", track_from_song(s))
                            added += 1
                        self.log(f"歌单《{self.group_name}》解析到 {len(songs)} 首")
                    elif kind == "album":
                        al, songs = self.api.album_tracks(it["id"])
                        self.group_name = al.get("name", "")
                        for s in songs:
                            self.post("add", track_from_song(s))
                            added += 1
                        self.log(f"专辑《{self.group_name}》解析到 {len(songs)} 首")
                    elif kind == "artist":
                        ar, songs = self.api.artist_top(it["id"])
                        self.group_name = ar.get("name", "")
                        for s in songs:
                            self.post("add", track_from_song(s))
                            added += 1
                        self.log(f"歌手「{self.group_name}」热门 50 首解析到 {len(songs)} 首")
                    elif kind == "search":
                        res = self.api.search(it["keyword"], "song", 30)
                        ids = [r["id"] for r in res]
                        if ids:
                            for s in self.api.song_detail(ids):
                                self.post("add", track_from_song(s))
                                added += 1
                        self.log(f"搜索「{it['keyword']}」命中 {len(ids)} 首")
                except Exception as exc:  # noqa: BLE001
                    self.post("log", ("解析失败: " + repr(exc), "err"))
            self.post("parse_done", added)
        finally:
            self.post("parse_unlock", None)

    # ------------------------------------------------------------ 下载
    def _selected_tracks(self) -> List[dict]:
        sel = [t for t in self.tracks if t["uid"] in self.checked]
        if sel:
            return sel
        idx = self.tree.selection()
        if idx:
            want = {int(i) for i in idx}
            return [t for t in self.tracks if t["uid"] in want]
        return []

    def do_download(self):
        if self.engine and self.engine.running:
            return
        tracks = self._selected_tracks()
        if not tracks:
            messagebox.showinfo(APP_NAME, "没有选中任何歌曲")
            return
        self.settings.fallback_enabled = self.var_fallback.get()
        self.settings.save()
        os.makedirs(self.settings.save_dir, exist_ok=True)

        self.engine = DownloadEngine(self.settings, on_event=self.post)
        for t in tracks:
            t["status"] = "等待中"
            self._refresh_row(t)
        self.pb.configure(value=0, maximum=len(tracks))
        self.lbl_prog.configure(text=f"0 / {len(tracks)}")
        self.btn_start.configure(state="disabled", text="下载中…")
        self.btn_stop.state(["!disabled"])
        self.log(f"开始下载 {len(tracks)} 首 · 并发 {self.settings.concurrency} · "
                 f"音质 {LEVELS[self.settings.level]['label']}")
        self.engine.start(tracks, self.group_name)

    def do_stop(self):
        if self.engine:
            self.engine.stop()
            self.log("已发送停止信号…", "warn")

    # ------------------------------------------------------------ 事件泵
    def post(self, kind: str, payload):
        self.evq.put((kind, payload))

    def _pump(self):
        try:
            while True:
                kind, payload = self.evq.get_nowait()
                self._dispatch(kind, payload)
        except queue.Empty:
            pass
        if self.engine and self.engine.running:
            self.lbl_speed.configure(text=fmt_size(self.engine.speed()) + "/s")
        self.after(120, self._pump)

    def _dispatch(self, kind: str, payload):
        if kind == "add":
            t = self._new_track(payload)
            self.tree.insert("", "end", iid=str(t["uid"]),
                             values=self._row_values(t),
                             tags=("odd",) if len(self.tracks) % 2 else ())
            self._refresh_count()
        elif kind == "parse_done":
            self.log(f"解析完成，新增 {payload} 首", "ok")
        elif kind == "parse_unlock":
            self._busy_parse = False
            self.btn_parse.configure(state="normal", text="解析 / 搜索")
        elif kind == "log":
            self.log(*payload)
        elif kind == "login":
            if payload:
                self.lbl_status.configure(text=f"已登录：{payload}", foreground=OK)
                self.log(f"Cookie 有效，登录账号：{payload}", "ok")
            else:
                self.lbl_status.configure(text="未登录（匿名模式）")
                self.log("Cookie 无效或已过期，仍可用匿名模式", "warn")
        elif kind == "start":
            t = payload["track"]
            t["status"] = "连接中…"
            self._refresh_row(t)
        elif kind == "notice":
            t = payload["track"]
            t["status"] = payload["text"]
            self._refresh_row(t)
        elif kind == "progress":
            t = payload["track"]
            done, total = payload["done"], payload["total"]
            pct = (done / total * 100) if total else 0
            t["status"] = f"下载 {pct:4.1f}%  {fmt_size(done)}"
            self._refresh_row(t)
        elif kind == "done":
            t = payload["track"]
            t["status"] = f"✔ 完成 · {payload['src']}"
            self._refresh_row(t)
            self.tree.item(str(t["uid"]), tags=("ok",))
            self.log(f"完成：{t['title']} → {payload['path']}", "ok")
            self._bump_progress()
        elif kind == "skipped":
            t = payload["track"]
            t["status"] = "已存在，跳过"
            self._refresh_row(t)
            self.tree.item(str(t["uid"]), tags=("skip",))
            self.log(f"跳过（已存在）：{t['title']}", "warn")
            self._bump_progress()
        elif kind == "failed":
            t = payload["track"]
            t["status"] = "✘ 失败"
            self._refresh_row(t)
            self.tree.item(str(t["uid"]), tags=("fail",))
            self.log(f"失败：{t['title']} — {payload['error']}", "err")
            self._bump_progress()
        elif kind == "finished":
            st = payload
            self.lbl_prog.configure(
                text=f"{st['done'] + st['failed'] + st['skipped']} / {st['total']}")
            self.lbl_speed.configure(text="")
            self.btn_start.configure(state="normal", text="开始下载")
            self.btn_stop.state(["disabled"])
            self.log(f"全部结束：成功 {st['done']} · 跳过 {st['skipped']} · 失败 {st['failed']}",
                     "ok" if st["failed"] == 0 else "warn")

    def _bump_progress(self):
        if not self.engine:
            return
        st = self.engine.stats
        finished = st["done"] + st["failed"] + st["skipped"]
        self.pb.configure(value=finished, maximum=max(st["total"], 1))
        self.lbl_prog.configure(text=f"{finished} / {st['total']}")

    # ------------------------------------------------------------ 列表交互
    def _on_tree_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        uid = int(iid)
        if uid in self.checked:
            self.checked.discard(uid)
        else:
            self.checked.add(uid)
        t = next((x for x in self.tracks if x["uid"] == uid), None)
        if t:
            self._refresh_row(t)
        self._refresh_count()
        return "break"

    def _on_tree_dbl(self, event):
        iid = self.tree.identify_row(event.y)
        t = next((x for x in self.tracks if str(x["uid"]) == iid), None)
        if not t:
            return
        if t.get("_path") and os.path.exists(t["_path"]):
            try:
                os.startfile(os.path.dirname(t["_path"]))  # noqa: S606
            except Exception:  # noqa: BLE001
                pass
        else:
            self.goto_song(t)

    def _check_all(self, on: bool):
        self.checked = {t["uid"] for t in self.tracks} if on else set()
        for t in self.tracks:
            self._refresh_row(t)
        self._refresh_count()

    def _check_invert(self):
        allids = {t["uid"] for t in self.tracks}
        self.checked = allids - self.checked
        for t in self.tracks:
            self._refresh_row(t)
        self._refresh_count()

    def _remove_selected(self):
        ids = set(self.tree.selection())
        if not ids:
            ids = {str(u) for u in self.checked}
        keep = []
        for t in self.tracks:
            if str(t["uid"]) in ids:
                self.tree.delete(str(t["uid"]))
                self.checked.discard(t["uid"])
            else:
                keep.append(t)
        self.tracks = keep
        for i, t in enumerate(self.tracks, 1):
            t["_index"] = i
            self._refresh_row(t)
        self._refresh_count()

    def _clear(self):
        self.tree.delete(*self.tree.get_children())
        self.tracks.clear()
        self.checked.clear()
        self._refresh_count()

    def goto_song(self, t: dict):
        try:
            os.startfile(f"https://music.163.com/song?id={t['id']}")  # noqa: S606
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 设置窗口
    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("设置")
        win.configure(bg=BG)
        win.geometry("620x460")
        win.transient(self)
        win.grab_set()

        pad = {"padx": 18, "pady": 6}
        tk.Label(win, text="下载设置", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(16, 4), padx=18)

        def row(label, widget_builder):
            f = tk.Frame(win, bg=BG)
            f.pack(fill="x", **pad)
            tk.Label(f, text=label, bg=BG, fg=FG_DIM, width=12, anchor="w").pack(side="left")
            w = widget_builder(f)
            w.pack(side="left", fill="x", expand=True)
            return w

        var_dir = tk.StringVar(value=self.settings.save_dir)
        f = tk.Frame(win, bg=BG)
        f.pack(fill="x", **pad)
        tk.Label(f, text="保存目录", bg=BG, fg=FG_DIM, width=12, anchor="w").pack(side="left")
        e = tk.Entry(f, textvariable=var_dir, bg=PANEL2, fg=FG, relief="flat",
                     insertbackground=FG)
        e.pack(side="left", fill="x", expand=True, ipady=4)

        def pick():
            d = filedialog.askdirectory(initialdir=var_dir.get() or os.path.expanduser("~"))
            if d:
                var_dir.set(d)
        tk.Button(f, text="浏览", command=pick, bg=PANEL2, fg=FG, relief="flat",
                  padx=10, borderwidth=0).pack(side="left", padx=6)

        var_tpl = row("文件名模板", lambda p: tk.Entry(p, bg=PANEL2, fg=FG, relief="flat",
                                                       insertbackground=FG))
        var_tpl.insert(0, self.settings.template)
        tk.Label(win, text="可用变量：{artist} {title} {album} {index} {track} {year} {id}",
                 bg=BG, fg=FG_DIM, font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=90)

        var_conc = tk.IntVar(value=self.settings.concurrency)
        sp = row("并发线程", lambda p: tk.Spinbox(p, from_=1, to=8, textvariable=var_conc,
                                                  width=6, bg=PANEL2, fg=FG, relief="flat"))
        sp.configure(buttonbackground=PANEL2)

        v_cover = tk.BooleanVar(value=self.settings.write_cover)
        v_lyric = tk.BooleanVar(value=self.settings.write_lyric)
        v_skip = tk.BooleanVar(value=self.settings.skip_existing)
        v_org = tk.BooleanVar(value=self.settings.organize)
        v_fb = tk.BooleanVar(value=self.settings.fallback_enabled)
        for text, var in (("写入封面（专辑图）", v_cover),
                          ("写入歌词（内嵌 LRC）", v_lyric),
                          ("跳过已存在的文件", v_skip),
                          ("按歌单建子文件夹", v_org),
                          ("启用音源兜底（无版权时自动换源）", v_fb)):
            cb = tk.Checkbutton(win, text=text, variable=var, bg=BG, fg=FG,
                                selectcolor=PANEL2, activebackground=BG,
                                activeforeground=FG, anchor="w",
                                font=("Microsoft YaHei UI", 9))
            cb.pack(anchor="w", padx=18, pady=2)

        tk.Label(win, text="账号 Cookie（可选，填了能下 VIP 自购/会员曲目的合法音质）",
                 bg=BG, fg=FG_DIM, font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=18, pady=(10, 2))
        var_ck = tk.Text(win, height=3, bg=PANEL2, fg=FG, relief="flat",
                         insertbackground=FG, font=("Consolas", 8), padx=6, pady=4)
        var_ck.pack(fill="x", padx=18)
        var_ck.insert("1.0", self.settings.cookie)

        def save():
            self.settings.save_dir = var_dir.get().strip() or self.settings.save_dir
            self.settings.template = var_tpl.get().strip() or "{artist} - {title}"
            self.settings.concurrency = max(1, min(int(var_conc.get() or 3), 8))
            self.settings.write_cover = v_cover.get()
            self.settings.write_lyric = v_lyric.get()
            self.settings.skip_existing = v_skip.get()
            self.settings.organize = v_org.get()
            self.settings.fallback_enabled = v_fb.get()
            self.settings.cookie = var_ck.get("1.0", "end").strip()
            self.settings.save()
            self.api = NeteaseAPI(cookie=self.settings.cookie)
            os.makedirs(self.settings.save_dir, exist_ok=True)
            if self.settings.cookie:
                threading.Thread(target=self._check_login, daemon=True).start()
            self.log("设置已保存")
            win.destroy()

        bf = tk.Frame(win, bg=BG)
        bf.pack(fill="x", side="bottom", pady=14, padx=18)
        tk.Button(bf, text="保存", command=save, bg=ACCENT, fg="white", relief="flat",
                  font=FONT_B, padx=22, pady=6, borderwidth=0,
                  activebackground=ACCENT_HOVER, activeforeground="white").pack(side="right")
        tk.Button(bf, text="取消", command=win.destroy, bg=PANEL2, fg=FG, relief="flat",
                  padx=18, pady=6, borderwidth=0).pack(side="right", padx=8)

    def _check_login(self):
        try:
            prof = self.api.check_cookie()
            if prof:
                self.post("login", prof.get("nickname", "已登录"))
            else:
                self.post("login", "")
        except Exception:  # noqa: BLE001
            self.post("login", "")

    def _on_close(self):
        try:
            if self.engine:
                self.engine.stop()
            self.settings.save()
        finally:
            self.destroy()


def main():
    app = App()
    app.mainloop()

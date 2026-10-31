# -*- coding: utf-8 -*-
"""本地 Web 后端：给前端页面提供 JSON 接口 + SSE 事件流。

前端是 ncm/web 下的静态页面，在 Edge 的「应用模式」窗口里打开（无地址栏，跟原生窗口一样）。
之所以不用 pywebview/pythonnet：在 Python 3.14 上它和 .NET 的 COM 交互会疯狂报错并吃光内存，
而「本地 HTTP + Edge --app」渲染内核同样是 WebView2，但没有任何原生依赖，打包也更稳。
"""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import socket
import socketserver
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Dict, List, Optional

from .api import NeteaseAPI, track_from_song
from .core import APP_NAME, DownloadEngine, Settings, parse_inputs

VERSION = "2.0"
BATCH = 40          # 每次推给前端的歌曲条数（大歌单避免刷爆前端）

SETTING_FIELDS = (
    "level", "save_dir", "template", "concurrency", "write_cover", "write_lyric",
    "skip_existing", "organize", "cookie", "fallback_enabled", "strict_mp3",
)


def web_dir() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "ncm", "web")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


# ------------------------------------------------------------------ 后端
class Backend:
    """界面能调用的全部动作。方法都返回 dict，异常由 HTTP 层兜住。"""

    def __init__(self) -> None:
        self.settings = Settings.load()
        self.tracks: Dict[int, dict] = {}
        self.uid = 0
        self.engine: Optional[DownloadEngine] = None
        self.group = ""
        self._subs: List["queue.Queue[dict]"] = []
        self._lock = threading.Lock()

    # ---------------------------------------------------------- 事件
    def subscribe(self) -> "queue.Queue[dict]":
        q: "queue.Queue[dict]" = queue.Queue(maxsize=2000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[dict]") -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def emit(self, payload: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass

    def log(self, msg: str, kind: str = "") -> None:
        self.emit({"type": "log", "msg": msg, "kind": kind})

    # ---------------------------------------------------------- 设置
    def ready(self) -> dict:
        return self.settings.to_dict()

    def set_setting(self, key: str, value) -> dict:
        if key in SETTING_FIELDS and hasattr(self.settings, key):
            setattr(self.settings, key, value)
            self.settings.save()
        return self.settings.to_dict()

    def save_settings(self, patch: dict) -> dict:
        for k, v in (patch or {}).items():
            if k in SETTING_FIELDS and hasattr(self.settings, k):
                setattr(self.settings, k, v)
        self.settings.save()
        self.log(f"设置已保存 · 线程 {self.settings.concurrency} · 保存到 {self.settings.save_dir}")
        return self.settings.to_dict()

    # ---------------------------------------------------------- Cookie 校验
    def check_cookie(self, cookie: str = "") -> dict:
        """校验 Cookie 是否有效：返回昵称/UID/VIP 等级，失败给出原因。"""
        raw = (cookie if cookie is not None else self.settings.cookie or "").strip()
        if not raw:
            return {"ok": False, "reason": "empty", "message": "还没填 Cookie"}
        from .api import NeteaseAPI  # 局部导入，避免循环依赖

        try:
            prof = NeteaseAPI(cookie=raw).check_cookie()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": "error", "message": f"检测出错：{exc}"}
        if not prof:
            return {"ok": False, "reason": "invalid",
                    "message": "Cookie 无效或已过期（请重新登录网易云复制）"}
        vip = int(prof.get("vipType") or 0)
        return {
            "ok": True,
            "message": "Cookie 有效",
            "nickname": prof.get("nickname") or "(未命名)",
            "userId": prof.get("userId"),
            "vipType": vip,
            "vipLabel": {0: "普通账号", 10: "黑胶VIP", 11: "黑胶VIP"}.get(vip, f"VIP{vip}"),
            "avatar": prof.get("avatarUrl") or "",
            "level": prof.get("level"),
        }

    # ---------------------------------------------------------- 解析
    def parse(self, text: str) -> dict:
        items = parse_inputs(text or "")
        if not items:
            self.emit({"type": "toast", "msg": "没识别到有效内容", "kind": "warn"})
            return {"ok": False}
        self.emit({"type": "parse_start"})
        threading.Thread(target=self._parse_worker, args=(items,), daemon=True).start()
        return {"ok": True}

    def _add(self, songs: List[dict]) -> None:
        buf = []
        for s in songs:
            self.uid += 1
            t = track_from_song(s)
            t["uid"] = self.uid
            t["artist"] = t.get("artist_str", "")
            self.tracks[self.uid] = t
            buf.append({k: t.get(k) for k in
                        ("uid", "id", "title", "artist", "album", "duration", "cover", "fee")})
            if len(buf) >= BATCH:
                self.emit({"type": "tracks", "list": buf})
                buf = []
        if buf:
            self.emit({"type": "tracks", "list": buf})

    def _parse_worker(self, items: List[dict]) -> None:
        api = NeteaseAPI(cookie=self.settings.cookie)
        added = 0
        try:
            for it in items:
                kind = it["kind"]
                try:
                    if kind == "song":
                        songs = api.song_detail([it["id"]])
                        self.group = ""
                        self._add(songs)
                        added += len(songs)
                        self.log(f"单曲解析 {len(songs)} 首")
                    elif kind == "playlist":
                        pl, songs = api.playlist_tracks(it["id"])
                        self.group = pl.get("name", "")
                        self._add(songs)
                        added += len(songs)
                        self.log(f"歌单《{self.group}》解析到 {len(songs)} 首")
                        if not songs:
                            self.log(
                                f"歌单 {it['id']} 没读到任何歌曲：多半是「私密歌单」，"
                                f"匿名接口读不了。请到设置里填入你自己的网易云 Cookie 再解析。",
                                "warn")
                            self.emit({"type": "toast",
                                       "msg": "私密歌单需要登录 Cookie，去设置里填一下",
                                       "kind": "warn"})
                    elif kind == "album":
                        al, songs = api.album_tracks(it["id"])
                        self.group = al.get("name", "")
                        self._add(songs)
                        added += len(songs)
                        self.log(f"专辑《{self.group}》解析到 {len(songs)} 首")
                    elif kind == "artist":
                        ar, songs = api.artist_top(it["id"])
                        self.group = ar.get("name", "")
                        self._add(songs)
                        added += len(songs)
                        self.log(f"歌手「{self.group}」解析到 {len(songs)} 首")
                    elif kind == "search":
                        res = api.search(it["keyword"], "song", 30)
                        ids = [r["id"] for r in res]
                        if ids:
                            songs = api.song_detail(ids)
                            self._add(songs)
                            added += len(songs)
                        self.log(f"搜索「{it['keyword']}」命中 {len(ids)} 首")
                except Exception as exc:  # noqa: BLE001
                    self.log(f"解析失败: {exc!r}", "err")
        finally:
            self.emit({"type": "parse_done", "added": added})

    # ---------------------------------------------------------- 下载
    def download(self, uids: List[int]) -> dict:
        if self.engine and self.engine.running:
            return {"ok": False}
        sel = [self.tracks[u] for u in uids if u in self.tracks]
        if not sel:
            return {"ok": False}
        for i, t in enumerate(sel):
            t["_index"] = i + 1
        self.engine = DownloadEngine(self.settings, on_event=self._on_engine_event)
        self.emit({"type": "progress", "done": 0, "failed": 0, "skipped": 0,
                   "total": len(sel), "speed": 0})
        self.engine.start(sel, self.group)
        threading.Thread(target=self._ticker, daemon=True).start()
        return {"ok": True}

    def stop(self) -> dict:
        if self.engine:
            self.engine.stop()
        return {"ok": True}

    def _on_engine_event(self, kind: str, payload: dict) -> None:
        if kind == "bytes":
            return  # 字节级进度只用于内部测速，进度条按「首」计算
        if kind in ("finished", "progress"):
            self.emit({"type": kind, **payload})
            return
        track = payload.get("track") or {}
        uid = track.get("uid")
        if kind == "start":
            self.emit({"type": "start", "uid": uid})
        elif kind == "done":
            fmt = (track.get("_fmt") or "mp3").upper()
            self.emit({"type": "done", "uid": uid, "size": payload.get("size"),
                       "src": payload.get("src"), "fmt": fmt,
                       "path": payload.get("path")})
            self.log(f"✔ {track.get('artist_str','')} - {track.get('title','')}"
                     f"（{payload.get('src')} · {fmt}）", "ok")
        elif kind == "skipped":
            self.emit({"type": "skipped", "uid": uid})
            self.log(f"跳过已存在：{track.get('title','')}", "warn")
        elif kind == "failed":
            self.emit({"type": "failed", "uid": uid})
            self.log(f"✘ {track.get('title','')}：{payload.get('error','')}", "err")
        elif kind == "notice":
            self.emit({"type": "notice", "uid": uid, "text": payload.get("text", "")})

    def _ticker(self) -> None:
        eng = self.engine
        if not eng:
            return
        while eng.running:
            st = dict(eng.stats)
            self.emit({"type": "progress", "done": st["done"], "failed": st["failed"],
                       "skipped": st["skipped"], "total": st["total"], "speed": eng.speed()})
            time.sleep(0.6)
        st = dict(eng.stats)
        self.emit({"type": "progress", "done": st["done"], "failed": st["failed"],
                   "skipped": st["skipped"], "total": st["total"], "speed": 0})

    # ---------------------------------------------------------- 杂项
    def open_dir(self) -> dict:
        path = self.settings.save_dir
        try:
            os.makedirs(path, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            self.emit({"type": "toast", "msg": f"打不开目录: {exc}", "kind": "err"})
            return {"ok": False}

    def open_url(self, url: str) -> dict:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True}

    def win(self, action: str = "") -> dict:
        """自绘标题栏用：最小化 / 关闭 / 最大化切换。

        优先用外壳注册的句柄（pywebview 窗口对象），没有就走 Win32。
        """
        try:
            handler = WIN_HANDLER
            if handler is not None and handler(action):
                return {"ok": True}
        except Exception:  # noqa: BLE001
            pass
        try:
            from .core import APP_NAME
            from .shell import win32_action
            return {"ok": bool(win32_action(APP_NAME, action))}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": repr(exc)}

    def pick_dir(self) -> dict:
        """调系统文件夹选择框（tkinter 只用来弹这一个对话框）。"""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(parent=root, initialdir=self.settings.save_dir)
            root.destroy()
            if path:
                self.settings.save_dir = path
                self.settings.save()
                return {"path": path}
        except Exception:  # noqa: BLE001
            pass
        return {"path": ""}


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = f"NCM/{VERSION}"
    backend: Backend = None      # 由 make_server 注入
    token: str = ""

    def log_message(self, fmt, *args):  # 静音
        pass

    # ---------------------------------------------------------- 工具
    def _json(self, obj, status=HTTPStatus.OK) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _ok(self) -> bool:
        if not self.token:
            return True
        if self.headers.get("X-Token", "") == self.token:
            return True
        # EventSource 没法加请求头，允许查询串带 token
        if "?" in self.path:
            from urllib.parse import parse_qs
            q = parse_qs(self.path.split("?", 1)[1])
            return (q.get("t") or [""])[0] == self.token
        return False

    def _file(self, rel: str) -> None:
        path = os.path.normpath(os.path.join(web_dir(), rel))
        if not path.startswith(os.path.normpath(web_dir())) or not os.path.isfile(path):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ---------------------------------------------------------- GET
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._file("index.html")
            return
        if path == "/api/events":
            if not self._ok():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            self._sse()
            return
        if path.startswith("/api/"):
            if not self._ok():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            name = path[5:]
            fn = getattr(self.backend, name, None)
            if not callable(fn):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                self._json(fn())
            except Exception as exc:  # noqa: BLE001
                self._json({"error": repr(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._file(path.lstrip("/"))

    # ---------------------------------------------------------- POST
    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if not path.startswith("/api/") or not self._ok():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        name = path[5:]
        fn = getattr(self.backend, name, None)
        if not callable(fn):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            body = {}
        try:
            if isinstance(body, dict):
                self._json(fn(**body))
            elif isinstance(body, list):
                self._json(fn(*body))
            else:
                self._json(fn(body))
        except TypeError as exc:
            self._json({"error": f"参数不对: {exc}"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": repr(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    # ---------------------------------------------------------- SSE
    def _sse(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.backend.subscribe()
        STATE["clients"] += 1
        STATE["ever"] = True
        try:
            self.wfile.write(b"retry: 1000\n\n")
            self.wfile.flush()
            while True:
                try:
                    payload = q.get(timeout=15.0)
                    data = json.dumps(payload, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass
        finally:
            STATE["clients"] -= 1
            self.backend.unsubscribe(q)


STATE = {"clients": 0, "ever": False}

# 外壳（shell.py）启动窗口后会把「窗口操作」挂到这里：minimize / close / toggle_max
WIN_HANDLER = None


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(token: str = "") -> tuple:
    backend = Backend()
    Handler.backend = backend
    Handler.token = token
    httpd = Server(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    return httpd, backend, port


def _free_port_ok(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False

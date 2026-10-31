# -*- coding: utf-8 -*-
"""输入解析、设置持久化、多线程下载引擎。"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import requests

from . import tagger
from .api import LEVELS, NeteaseAPI, level_ext, level_want, normalize_level, track_from_song
from .fallback import KuwoSource

APP_NAME = "网易云音乐下载器"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "NCMD")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Music", "网易云下载")

ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


# ---------------------------------------------------------------------- 格式校验
def sniff_audio(path: str) -> Optional[str]:
    """读文件头判断真实音频格式：mp3 / flac / m4a / wav / ogg，认不出返回 None。

    接口返回的 `type`/URL 后缀并不可靠（常见：老接口回落成 FLAC、m4a），
    所以落盘后一律按**字节**认定，避免「扩展名 mp3、内容其实是 flac」。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return None
    if len(head) < 4:
        return None
    if head[:4] == b"fLaC":
        return "flac"
    if head[:3] == b"ID3":
        return "mp3"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"RIFF":
        return "wav"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:      # MPEG 帧同步
        return "mp3"
    return None


FORMAT_EXT = {"mp3": ".mp3", "flac": ".flac", "m4a": ".m4a", "wav": ".wav", "ogg": ".ogg"}


# ---------------------------------------------------------------------- 设置
@dataclass
class Settings:
    save_dir: str = DEFAULT_DIR
    level: str = "exhigh"
    template: str = "{artist} - {title}"
    concurrency: int = 3
    write_cover: bool = True
    write_lyric: bool = True
    fallback_enabled: bool = True
    skip_existing: bool = True
    organize: bool = False          # 按歌单/专辑名建子文件夹
    strict_mp3: bool = True         # 校验落盘文件真实格式必须是 MP3，不符则换源重下
    cookie: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        except Exception:  # noqa: BLE001
            pass
        # 老配置里的「无损 / Hi-Res」档位统一折算成 320k MP3
        s.level = normalize_level(getattr(s, "level", "exhigh"))
        return s

    def save(self) -> None:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------- 解析
_URL_RULES = [
    (re.compile(r"music\.163\.com/(?:#/)?(song|playlist|album|artist)\?id=(\d+)", re.I), None),
    (re.compile(r"music\.163\.com/(?:#/)?(song|playlist|album|artist)/(\d+)", re.I), None),
    (re.compile(r"^\s*(song|playlist|album|artist)\s*[:：]\s*(\d+)\s*$", re.I), None),
]
_BARE_ID = re.compile(r"^\s*(\d{3,})\s*$")


def parse_inputs(text: str) -> List[Dict]:
    """把一坨链接/ID/关键词拆成 [{kind, id 或 keyword}]，按出现顺序去重。"""
    items: List[Dict] = []
    seen = set()

    def push(item):
        key = (item["kind"], item.get("id") or item.get("keyword"))
        if key in seen:
            return
        seen.add(key)
        items.append(item)

    for raw in text.replace("，", ",").splitlines():
        line = raw.strip()
        if not line:
            continue
        # 一行里可能塞了多个链接（分享文案）
        urls = re.findall(r"music\.163\.com/[^\s\"'<>]+", line, re.I)
        matched = False
        for blob in urls or []:
            m = (re.search(r"/(song|playlist|album|artist)\?id=(\d+)", blob, re.I)
                 or re.search(r"/(song|playlist|album|artist)/(\d+)", blob, re.I))
            if m:
                push({"kind": m.group(1).lower(), "id": int(m.group(2))})
                matched = True
        if matched:
            continue
        m = re.match(r"^\s*(song|playlist|album|artist)\s*[:：]\s*(\d+)\s*$", line, re.I)
        if m:
            push({"kind": m.group(1).lower(), "id": int(m.group(2))})
            continue
        m = _BARE_ID.match(line)
        if m:
            push({"kind": "song", "id": int(m.group(1))})
            continue
        push({"kind": "search", "keyword": line})
    return items


def sanitize(name: str, max_len: int = 120) -> str:
    name = ILLEGAL.sub("_", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:max_len].rstrip(". ") or "未命名"


def render_name(template: str, track: dict, index: int) -> str:
    mapping = {
        "artist": track.get("artist_str", ""),
        "title": track.get("title", ""),
        "album": track.get("album", ""),
        "index": f"{index:02d}",
        "track": f"{track.get('track_no') or 0:02d}",
        "year": time.strftime("%Y", time.localtime(track["publish"] / 1000)) if track.get("publish") else "",
        "id": str(track.get("id", "")),
    }
    try:
        out = template.format(**mapping)
    except Exception:  # noqa: BLE001
        out = f"{mapping['artist']} - {mapping['title']}"
    return sanitize(out)


# ---------------------------------------------------------------------- 下载
class DownloadEngine:
    """线程池下载器。所有状态变化通过 on_event(kind, payload) 回调抛出。"""

    def __init__(self, settings: Settings,
                 on_event: Optional[Callable[[str, dict], None]] = None):
        self.settings = settings
        self.on_event = on_event or (lambda k, p: None)
        self.api = NeteaseAPI(cookie=settings.cookie)
        self.kuwo = KuwoSource()
        self._q: "queue.Queue[dict]" = queue.Queue()
        self._threads: List[threading.Thread] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.stats = {"done": 0, "failed": 0, "skipped": 0, "total": 0}
        self._bytes = 0
        self._t0 = 0.0

    # ------------------------------------------------------------ 生命周期
    def start(self, tracks: List[dict], group_name: str = "") -> None:
        self._stop.clear()
        self.stats = {"done": 0, "failed": 0, "skipped": 0, "total": len(tracks)}
        self._bytes = 0
        self._t0 = time.time()
        for t in tracks:
            self._q.put(t)
        n = max(1, min(int(self.settings.concurrency), 8))
        self._threads = []
        for i in range(n):
            th = threading.Thread(target=self._worker, args=(i, group_name), daemon=True)
            th.start()
            self._threads.append(th)
        threading.Thread(target=self._watcher, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def _watcher(self) -> None:
        for th in self._threads:
            th.join()
        self.on_event("finished", dict(self.stats))

    def speed(self) -> float:
        dt = max(time.time() - self._t0, 0.001)
        return self._bytes / dt

    # ------------------------------------------------------------ 工作线程
    def _worker(self, wid: int, group_name: str) -> None:
        while not self._stop.is_set():
            try:
                track = self._q.get_nowait()
            except queue.Empty:
                return
            try:
                self._handle(track, group_name)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.stats["failed"] += 1
                self.on_event("failed", {"track": track, "error": repr(exc)})
            finally:
                self._q.task_done()

    def _handle(self, track: dict, group_name: str) -> None:
        s = self.settings
        base_dir = s.save_dir
        if s.organize and group_name:
            base_dir = os.path.join(base_dir, sanitize(group_name, 80))
        os.makedirs(base_dir, exist_ok=True)

        index = track.get("_index", 0)
        stem = render_name(s.template, track, index)

        self.on_event("start", {"track": track})

        # ---------- 1. 取直链（网易云）—— 只要 MP3
        level = normalize_level(s.level)
        url, src = None, "网易云"
        item = self.api.song_url(track["id"], level)
        if item and item.get("url"):
            url = item["url"]
            track["_br"] = item.get("br")
            track["_api_type"] = (item.get("type") or "").lower()

        # ---------- 2. 下载（扩展名先按 mp3 落盘，实际格式由第 3 步按字节认定）
        got, final_path = 0, ""
        if url:
            final_path = os.path.join(base_dir, stem + level_ext(s.level))
            if s.skip_existing and os.path.exists(final_path) and os.path.getsize(final_path) > 10240:
                self._skip(track, final_path)
                return
            got = self._download(url, final_path, track, src)
            want = level_want(s.level)
            if got:
                real = sniff_audio(final_path)
                if real and real != want:
                    if want == "flac":
                        # 无损/Hi-Res 需要会员权限：平台只给 MP3 时按降级处理（不反复换源）
                        fixed = os.path.join(base_dir, stem + FORMAT_EXT.get(real, "." + real))
                        try:
                            os.replace(final_path, fixed)
                            final_path = fixed
                        except OSError:
                            pass
                        label = "无损/Hi-Res 需要会员权限"
                        self.on_event("notice", {
                            "track": track,
                            "text": f"{label}，已自动降级为 {real.upper()}（{track.get('name','')}）"})
                    elif s.strict_mp3:
                        # 选了 MP3 档却给了 FLAC/M4A：换源重取，避免扩展名说谎
                        self.on_event("notice", {
                            "track": track,
                            "text": (f"接口给的是 {real.upper()}，与所选音质要求的 "
                                     f"{want.upper()} 不符，换源重取…")})
                        try:
                            os.remove(final_path)
                        except OSError:
                            pass
                        got = 0
                    else:
                        fixed = os.path.join(base_dir, stem + FORMAT_EXT.get(real, "." + real))
                        try:
                            os.replace(final_path, fixed)
                            final_path = fixed
                        except OSError:
                            pass
                track["_fmt"] = real or want

        # ---------- 3. 校验：试听片段 / 下载失败 -> 兜底音源
        if got:
            dur = self._duration(final_path)
            expect = (track.get("duration") or 0) / 1000.0
            if expect > 25 and dur and dur < expect * 0.9:
                self.on_event("notice", {"track": track,
                                         "text": f"仅 {dur:.0f}s 试听片段，换源重下…"})
                try:
                    os.remove(final_path + ".part")
                except OSError:
                    pass
                got = 0
        if not got:
            if not s.fallback_enabled:
                with self._lock:
                    self.stats["failed"] += 1
                self.on_event("failed", {"track": track,
                                         "error": "网易云无可用直链/VIP限制（音源兜底未开启）"})
                return
            if not url:
                self.on_event("notice", {"track": track, "text": "网易云无直链，切换兜底音源…"})
            cands = self.kuwo.rank(track.get("title", ""), track.get("artist_str", ""),
                                   track.get("album", ""), track.get("duration", 0), limit=3)
            expect = (track.get("duration") or 0) / 1000.0
            for cand in cands:
                u2 = self.kuwo.get_url(cand["rid"], prefer_flac=False)
                if not u2:
                    continue
                ext2 = ".flac" if ".flac" in u2 else ".mp3"
                p2 = os.path.join(base_dir, stem + ext2)
                got = self._download(u2, p2, track, cand["source"])
                if not got:
                    continue
                dur2 = self._duration(p2)
                if expect > 25 and dur2 and dur2 < expect * 0.9:
                    self.on_event("notice", {"track": track,
                                             "text": f"兜底音源《{cand['title']}》也是 {dur2:.0f}s 试听，换下一个候选…"})
                    for junk in (p2, p2 + ".part"):
                        try:
                            os.remove(junk)
                        except OSError:
                            pass
                    got = 0
                    continue
                src, final_path = cand["source"], p2
                track["_br"] = 320000
                real2 = sniff_audio(p2)
                if s.strict_mp3 and real2 and real2 != level_want(s.level):
                    self.on_event("notice", {
                        "track": track,
                        "text": f"兜底音源给的也是 {real2.upper()}，换下一个候选…"})
                    try:
                        os.remove(p2)
                    except OSError:
                        pass
                    got = 0
                    continue
                track["_fmt"] = real2 or "mp3"
                break
            if not got:
                with self._lock:
                    self.stats["failed"] += 1
                self.on_event("failed", {"track": track,
                                         "error": "VIP/版权受限：网易云与所有兜底音源都只给试听或拿不到（该曲在各平台均为付费曲）"})
                return

        # ---------- 4. 写标签（按文件真实格式选写入器，MP3 优先）
        fmt = track.get("_fmt") or sniff_audio(final_path) or "mp3"
        track["_fmt"] = fmt
        tmp_path = final_path + ".part"
        cover = None
        if s.write_cover and track.get("cover"):
            try:
                cr = requests.get(track["cover"],
                                  headers={"User-Agent": "Mozilla/5.0",
                                           "Referer": "https://music.163.com/"}, timeout=15)
                if cr.status_code == 200 and len(cr.content) > 1024:
                    cover = cr.content
            except Exception:  # noqa: BLE001
                cover = None
        lyric = ""
        if s.write_lyric:
            try:
                lyric = self.api.lyric(track["id"]) or ""
            except Exception:  # noqa: BLE001
                lyric = ""

        meta = {
            "title": track.get("title", ""),
            "artists": track.get("artists") or [track.get("artist_str", "")],
            "album": track.get("album", ""),
            "track_no": track.get("track_no") or 0,
            "publish": track.get("publish") or 0,
        }
        if fmt == "flac":
            tagger.write_flac(tmp_path, meta, cover, lyric)
        else:
            tagger.write_mp3(tmp_path, meta, cover, lyric)
        try:
            os.replace(tmp_path, final_path)
        except OSError:
            try:
                os.remove(final_path)
                os.replace(tmp_path, final_path)
            except OSError:
                pass

        track["_path"] = final_path
        track["_src"] = src
        with self._lock:
            self.stats["done"] += 1
        self.on_event("done", {"track": track, "path": final_path,
                               "src": src, "size": got})

    # ------------------------------------------------------------ 内部
    def _skip(self, track: dict, path: str) -> None:
        with self._lock:
            self.stats["skipped"] += 1
        track["_path"] = path
        self.on_event("skipped", {"track": track, "path": path})

    def _download(self, url: str, final_path: str, track: dict, src: str) -> int:
        """流式下载到 <final>.part，返回字节数（0 表示失败）。"""
        tmp_path = final_path + ".part"
        got = 0
        total = 0
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(64 * 1024):
                        if self._stop.is_set():
                            raise RuntimeError("用户停止")
                        if not chunk:
                            continue
                        f.write(chunk)
                        got += len(chunk)
                        with self._lock:
                            self._bytes += len(chunk)
                        self.on_event("bytes", {"track": track, "got": got,
                                                "total": total, "src": src})
        except Exception as exc:  # noqa: BLE001
            self.on_event("notice", {"track": track, "text": f"下载中断：{exc}"})
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return 0
        if got < 10240:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return 0
        return got

    @staticmethod
    def _duration(path: str) -> float:
        p = path + ".part"
        if not os.path.exists(p):
            return 0.0
        try:
            from mutagen.mp3 import MP3
            from mutagen.flac import FLAC
            if p.lower().endswith(".flac"):
                return FLAC(p).info.length
            return MP3(p).info.length
        except Exception:  # noqa: BLE001
            return 0.0

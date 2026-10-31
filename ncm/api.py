# -*- coding: utf-8 -*-
"""网易云音乐接口封装。

要点：
1. 接口走 eapi 加密（AES-128-ECB + MD5 签字），匿名即可拿到非 VIP 歌曲直链；
2. 服务器有 WAF，缺 X-Real-IP 或 os=pc cookie 会回 {"msg":"参数错误","code":400}，
   所以每个请求都带随机国内 IP 头 + 客户端 cookie；
3. 全局限速，避免被风控（实测连续打会被临时封）。
"""
from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

EAPI_KEY = b"e82ckenh8dichen8"
EAPI_SEP = "-36cd479b6b5-"

PC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
MOBILE_UA = ("NeteaseMusic/9.1.65.240927161425(9001065);Dalvik/2.1.0 "
             "(Linux; U; Android 14; Pixel 8)")

# 国内 IP 池，随机伪造 X-Real-IP，绕开「参数错误」风控
IP_POOL = [
    "116.25.146.177", "117.136.0.10", "120.229.12.34", "183.14.30.118",
    "221.192.7.66", "111.202.98.20", "101.226.4.55", "124.90.16.8",
    "223.104.3.11", "39.144.22.7", "112.17.245.9", "115.236.88.3",
]

# 音质档位 -> (中文名, encodeType, 期望码率)
LEVELS: Dict[str, Dict[str, Any]] = {
    "standard": {"label": "标准 128kbps", "encode": "mp3", "br": 128000, "kbps": 128, "ext": ".mp3"},
    "higher":   {"label": "较高 192kbps", "encode": "mp3", "br": 192000, "kbps": 192, "ext": ".mp3"},
    "exhigh":   {"label": "极高 320kbps", "encode": "mp3", "br": 320000, "kbps": 320, "ext": ".mp3"},
    "lossless": {"label": "无损 FLAC", "encode": "flac", "br": 999000, "kbps": 1000, "ext": ".flac"},
    "hires":    {"label": "Hi-Res", "encode": "flac", "br": 1900000, "kbps": 1900, "ext": ".flac"},
}

# 只做兜底：真的不认识的档位才退回 320k MP3
LEGACY_LEVELS: Dict[str, str] = {}


def normalize_level(level: str) -> str:
    """非法/未知档位退回 exhigh；无损与 Hi-Res 都是一等公民。"""
    if level in LEVELS:
        return level
    return LEGACY_LEVELS.get(level or "", "exhigh")


def level_ext(level: str) -> str:
    """该档位期望的落盘扩展名（.mp3 / .flac）。"""
    return LEVELS[normalize_level(level)]["ext"]


def level_want(level: str) -> str:
    """该档位期望的真实格式（mp3 / flac），用于文件头校验。"""
    return LEVELS[normalize_level(level)]["encode"]

SEARCH_TYPES = {"song": 1, "album": 10, "artist": 100, "playlist": 1000}


def _eapi_params(path: str, payload: Dict[str, Any]) -> str:
    text = json.dumps(payload, separators=(",", ":"))
    message = f"nobody{path}use{text}md5forencrypt"
    digest = hashlib.md5(message.encode()).hexdigest()
    plain = f"{path}{EAPI_SEP}{text}{EAPI_SEP}{digest}"
    cipher = AES.new(EAPI_KEY, AES.MODE_ECB)
    return cipher.encrypt(pad(plain.encode(), 16)).hex().upper()


class RateLimiter:
    """简单令牌桶：同一时刻只允许一个请求，间隔不小于 min_interval 秒。"""

    def __init__(self, min_interval: float = 0.55):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.monotonic()


class NeteaseAPI:
    def __init__(self, cookie: str = "", min_interval: float = 0.55, timeout: int = 20):
        self.cookie = (cookie or "").strip()
        self.timeout = timeout
        self.limiter = RateLimiter(min_interval)
        self._local = threading.local()

    # ------------------------------------------------------------------ 底层
    def _session(self) -> requests.Session:
        s = getattr(self._local, "s", None)
        if s is None:
            s = requests.Session()
            s.headers.update({
                "User-Agent": PC_UA,
                "Referer": "https://music.163.com/",
                "Origin": "https://music.163.com",
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            s.cookies.set("os", "pc")
            s.cookies.set("appver", "8.9.70")
            s.cookies.set("osver", "Microsoft-Windows-10-Professional-build-19045-64bit")
            s.cookies.set("channel", "netease")
            if self.cookie:
                self._load_cookie(s, self.cookie)
            self._local.s = s
        return s

    @staticmethod
    def _load_cookie(s: requests.Session, raw: str) -> None:
        for part in raw.replace(";", "\n").splitlines():
            part = part.strip()
            if not part or "=" not in part:
                continue
            k, _, v = part.partition("=")
            s.cookies.set(k.strip(), v.strip(), domain=".music.163.com")

    def _get(self, url: str, params: Optional[dict] = None, retries: int = 3) -> Optional[dict]:
        last_err = None
        for attempt in range(retries):
            self.limiter.wait()
            headers = {"X-Real-IP": random.choice(IP_POOL),
                       "X-Forwarded-For": random.choice(IP_POOL)}
            try:
                r = self._session().get(url, params=params, headers=headers,
                                        timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
                last_err = f"HTTP {r.status_code}"
            except Exception as exc:  # noqa: BLE001
                last_err = repr(exc)
            time.sleep(1.2 + attempt * 1.5)
        return {"code": -1, "msg": f"请求失败: {last_err}"}

    def _eapi(self, path: str, payload: Dict[str, Any], retries: int = 4) -> Optional[dict]:
        """path 形如 /api/song/enhance/player/url/v1（内部自动转 /eapi/...）"""
        api_path = path if path.startswith("/api/") else "/api" + path
        last = None
        for attempt in range(retries):
            self.limiter.wait()
            ip = random.choice(IP_POOL)
            headers = {"X-Real-IP": ip, "X-Forwarded-For": ip}
            body = {"params": _eapi_params(api_path, payload)}
            try:
                r = self._session().post("https://music.163.com/eapi" + api_path[4:],
                                         data=body, headers=headers, timeout=self.timeout)
                txt = r.text.strip()
                # 风控会返回两段拼接的 {"msg":"参数错误"...}
                if txt.startswith("{") and txt.count('"code"') > 1 and "参数错误" in txt:
                    last = "WAF 拦截"
                    time.sleep(2.0 + attempt * 2.0)
                    continue
                data = r.json()
                if data.get("code") == 400 and "参数错误" in str(data.get("msg", "")):
                    last = "WAF 拦截"
                    time.sleep(2.0 + attempt * 2.0)
                    continue
                return data
            except Exception as exc:  # noqa: BLE001
                last = repr(exc)
                time.sleep(1.2 + attempt * 1.5)
        return {"code": -1, "msg": f"eapi 失败: {last}"}

    # ------------------------------------------------------------------ 检索
    def search(self, keyword: str, kind: str = "song", limit: int = 30) -> List[dict]:
        stype = SEARCH_TYPES.get(kind, 1)
        data = self._get("https://music.163.com/api/search/get/web",
                         {"s": keyword, "type": stype, "limit": limit, "offset": 0})
        result = (data or {}).get("result") or {}
        if kind == "song":
            return result.get("songs") or []
        if kind == "album":
            return result.get("albums") or []
        if kind == "artist":
            return result.get("artists") or []
        return result.get("playlists") or []

    def song_detail(self, ids: Iterable[int]) -> List[dict]:
        ids = [int(i) for i in ids]
        out: List[dict] = []
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            c = json.dumps([{"id": x} for x in chunk], separators=(",", ":"))
            data = self._eapi("/api/v3/song/detail", {"c": c})
            out.extend((data or {}).get("songs") or [])
            if len(ids) > 200:
                time.sleep(0.3)
        return out

    def playlist(self, pid: int) -> dict:
        data = self._get("https://music.163.com/api/v6/playlist/detail",
                         {"id": int(pid), "n": 1000})
        return (data or {}).get("playlist") or {}

    def playlist_tracks(self, pid: int) -> tuple[dict, List[dict]]:
        pl = self.playlist(pid)
        if not pl:
            return {}, []
        ids = [t["id"] for t in (pl.get("trackIds") or [])]
        if not ids:
            ids = [t["id"] for t in (pl.get("tracks") or []) if t.get("id")]
        return pl, self.song_detail(ids)

    def album(self, aid: int) -> dict:
        return self._get(f"https://music.163.com/api/v1/album/{int(aid)}") or {}

    def album_tracks(self, aid: int) -> tuple[dict, List[dict]]:
        data = self.album(aid)
        return data.get("album") or {}, data.get("songs") or []

    def artist_hot(self, aid: int) -> dict:
        return self._get(f"https://music.163.com/api/v1/artist/{int(aid)}") or {}

    def artist_top(self, aid: int, limit: int = 200) -> tuple[dict, List[dict]]:
        data = self.artist_hot(aid)
        return data.get("artist") or {}, (data.get("hotSongs") or [])[:limit]

    def lyric(self, sid: int) -> str:
        data = self._get("https://music.163.com/api/song/lyric",
                         {"id": int(sid), "lv": -1, "kv": -1, "tv": -1})
        return ((data or {}).get("lrc") or {}).get("lyric") or ""

    def song_url(self, sid: int, level: str = "exhigh") -> Optional[dict]:
        level = normalize_level(level)
        lv = LEVELS.get(level, LEVELS["exhigh"])
        data = self._eapi("/api/song/enhance/player/url/v1",
                          {"ids": json.dumps([int(sid)]),
                           "level": level, "encodeType": lv["encode"]})
        for item in (data or {}).get("data") or []:
            if item.get("url"):
                return item
        return None

    def check_cookie(self) -> Optional[dict]:
        data = self._get("https://music.163.com/api/nuser/account/get")
        profile = (data or {}).get("profile")
        return profile


# ---------------------------------------------------------------------- 归一化
def track_from_song(song: dict) -> dict:
    """把各种接口返回的歌曲对象归一成统一结构。"""
    al = song.get("al") or song.get("album") or {}
    ar = song.get("ar") or song.get("artists") or []
    artists = [a.get("name", "") for a in ar if a.get("name")]
    cover = al.get("picUrl") or ""
    if cover and "?" not in cover:
        cover += "?param=640y640"
    return {
        "id": int(song.get("id") or 0),
        "title": song.get("name") or "",
        "artists": artists,
        "artist_str": " / ".join(artists) if artists else "未知歌手",
        "album": al.get("name") or "",
        "album_id": int(al.get("id") or 0),
        "cover": cover,
        "duration": int(song.get("dt") or song.get("duration") or 0),
        "fee": int(song.get("fee") or 0),
        "track_no": int(song.get("no") or 0),
        "publish": int(al.get("publishTime") or 0),
    }


def fee_label(fee: int) -> str:
    return {0: "免费", 8: "免费", 1: "VIP", 4: "付费专辑", 16: "试听"}.get(fee, f"fee={fee}")

# -*- coding: utf-8 -*-
"""兜底音源：网易云因为版权/VIP 拿不到直链时，去酷我音乐取同一首歌的音频。

只做一件事——拿到音频流，标签(歌名/歌手/专辑/封面/歌词)依然用网易云的元数据写，
所以下下来的文件信息与网易云客户端一致。
"""
from __future__ import annotations

import ast
import html
import json
import re
import unicodedata
from typing import Dict, List, Optional

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_BRACKET = re.compile(r"[\(（\[【].*?[\)）\]】]")


def _norm(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = _BRACKET.sub("", text)
    text = re.sub(r"[\s\-_·.,、'\"!！?？/\\&+]", "", text)
    return text.lower().strip()


def _similar(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(len(sa | sb), 1)


class KuwoSource:
    name = "酷我音乐"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.headers = {"User-Agent": UA, "Referer": "http://www.kuwo.cn/"}

    # ------------------------------------------------------------------ 搜索
    def search(self, keyword: str, limit: int = 12) -> List[Dict]:
        params = {
            "all": keyword, "ft": "music", "itemset": "web_2013", "client": "kt",
            "pn": 0, "rn": limit, "rformat": "json", "encoding": "utf8",
            "vipver": 1, "show_copyright_off": 1,
        }
        try:
            r = requests.get("http://search.kuwo.cn/r.s", params=params,
                             headers=self.headers, timeout=self.timeout)
            text = r.text.strip()
            data = None
            try:
                data = json.loads(text)
            except Exception:  # noqa: BLE001
                # 酷我老接口返回的是单引号 JS 对象，用 literal_eval 兜底
                data = ast.literal_eval(text)
            if not isinstance(data, dict):
                return []
        except Exception:  # noqa: BLE001
            return []
        songs = data.get("abslist") or []
        out = []
        for s in songs:
            rid = s.get("DC_TARGETID") or s.get("MUSICRID") or ""
            rid = str(rid).replace("MUSIC_", "")
            out.append({
                "rid": rid,
                "title": html.unescape(s.get("SONGNAME") or ""),
                "artist": html.unescape(s.get("ARTIST") or ""),
                "album": html.unescape(s.get("ALBUM") or ""),
                "duration": int(s.get("DURATION") or 0),
                "formats": html.unescape(s.get("FORMATS") or ""),
            })
        return out

    # ------------------------------------------------------------------ 直链
    def get_url(self, rid: str, prefer_flac: bool = False) -> Optional[str]:
        tries = []
        if prefer_flac:
            tries.append({"type": "convert_url", "format": "flac", "response": "url", "rid": f"MUSIC_{rid}"})
        tries.append({"type": "convert_url", "format": "mp3", "br": "320kmp3",
                      "response": "url", "rid": f"MUSIC_{rid}"})
        tries.append({"type": "convert_url", "format": "mp3", "response": "url",
                      "rid": f"MUSIC_{rid}"})
        for params in tries:
            try:
                r = requests.get("http://antiserver.kuwo.cn/anti.s", params=params,
                                 headers=self.headers, timeout=self.timeout)
                url = r.text.strip()
                if url.startswith("http") and ("mp3" in url or "flac" in url):
                    return url
            except Exception:  # noqa: BLE001
                continue
        return None

    # ------------------------------------------------------------------ 匹配
    def rank(self, title: str, artist: str, album: str = "",
             duration_ms: int = 0, limit: int = 3) -> List[Dict]:
        """按「歌名 + 歌手 + 时长」给候选排序，返回前 limit 个（不含直链）。

        交给调用方逐个试：有些歌酷我给的也是试听片段，需要按实际时长回退到下一个候选。
        """
        queries = []
        if artist:
            queries.append(f"{title} {artist}")
        queries.append(title)
        seen = set()
        scored = []
        for kw in queries:
            for cand in self.search(kw):
                if cand["rid"] in seen:
                    continue
                seen.add(cand["rid"])
                score = _similar(title, cand["title"]) * 0.65
                score += _similar(artist, cand["artist"]) * 0.35
                if duration_ms and cand["duration"]:
                    diff = abs(cand["duration"] * 1000 - duration_ms) / 1000.0
                    if diff <= 4:
                        score += 0.12
                    elif diff > 25:
                        score -= 0.25
                cand = dict(cand)
                cand["score"] = round(score, 3)
                cand["source"] = self.name
                scored.append((score, cand))
        ranked = [c for sc, c in sorted(scored, key=lambda x: -x[0]) if sc > 0.45]
        return ranked[:max(1, limit)]

    def resolve(self, title: str, artist: str, album: str = "",
                duration_ms: int = 0, prefer_flac: bool = False) -> Optional[Dict]:
        """兼容接口：返回排名第一且有直链的候选。"""
        for best in self.rank(title, artist, album, duration_ms, limit=3):
            url = self.get_url(best["rid"], prefer_flac=prefer_flac)
            if not url:
                continue
            best = dict(best)
            best["url"] = url
            best["source"] = self.name
            return best
        return None

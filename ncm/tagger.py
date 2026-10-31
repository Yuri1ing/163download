# -*- coding: utf-8 -*-
"""把元数据写进音频文件：歌名、歌手、专辑、音轨号、年份、封面、歌词。"""
from __future__ import annotations

import io
import os
from typing import List, Optional

from mutagen.flac import FLAC, Picture
from mutagen.id3 import (APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2,
                         TPOS, TRCK, USLT, ID3NoHeaderError)
from mutagen.mp3 import MP3

GENRE_GUESS = {
    "pop": "Pop", "rock": "Rock", "民谣": "Folk", "电子": "Electronic",
    "说唱": "Hip-Hop", "嘻哈": "Hip-Hop", "古风": "Chinese Style",
    "爵士": "Jazz", "古典": "Classical", "摇滚": "Rock",
}


def _sniff_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _year_of(ts_ms: int) -> str:
    if not ts_ms:
        return ""
    import datetime
    try:
        return str(datetime.datetime.fromtimestamp(ts_ms / 1000).year)
    except Exception:  # noqa: BLE001
        return ""


def write_mp3(path: str, meta: dict, cover: Optional[bytes] = None,
              lyric: str = "") -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("TIT2")
    tags.add(TIT2(encoding=3, text=meta.get("title", "")))
    if meta.get("artists"):
        tags.delall("TPE1")
        tags.add(TPE1(encoding=3, text=meta["artists"]))
        tags.delall("TPE2")
        tags.add(TPE2(encoding=3, text=meta["artists"][0]))
    if meta.get("album"):
        tags.delall("TALB")
        tags.add(TALB(encoding=3, text=meta["album"]))
    if meta.get("track_no"):
        total = meta.get("track_total") or 0
        tags.delall("TRCK")
        tags.add(TRCK(encoding=3, text=f"{meta['track_no']}/{total}" if total else str(meta["track_no"])))
    if meta.get("disc_no"):
        tags.delall("TPOS")
        tags.add(TPOS(encoding=3, text=str(meta["disc_no"])))
    year = meta.get("year") or _year_of(meta.get("publish", 0))
    if year:
        tags.delall("TDRC")
        tags.add(TDRC(encoding=3, text=str(year)))
    if meta.get("genre"):
        tags.delall("TCON")
        tags.add(TCON(encoding=3, text=meta["genre"]))
    if cover:
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=_sniff_mime(cover), type=3,
                      desc="Cover", data=cover))
    if lyric:
        tags.delall("USLT")
        tags.add(USLT(encoding=3, lang="chi", desc="", text=lyric))
    tags.save(path, v2_version=3)


def write_flac(path: str, meta: dict, cover: Optional[bytes] = None,
               lyric: str = "") -> None:
    audio = FLAC(path)
    audio.delete()
    audio["title"] = meta.get("title", "")
    if meta.get("artists"):
        audio["artist"] = meta["artists"]
        audio["albumartist"] = meta["artists"][0]
    if meta.get("album"):
        audio["album"] = meta["album"]
    if meta.get("track_no"):
        audio["tracknumber"] = str(meta["track_no"])
    year = meta.get("year") or _year_of(meta.get("publish", 0))
    if year:
        audio["date"] = year
    if meta.get("genre"):
        audio["genre"] = meta["genre"]
    if lyric:
        audio["lyrics"] = lyric
    audio.clear_pictures()
    if cover:
        pic = Picture()
        pic.type = 3
        pic.mime = _sniff_mime(cover)
        pic.desc = "Cover"
        pic.data = cover
        audio.add_picture(pic)
    audio.save()


def write_tags(path: str, meta: dict, cover: Optional[bytes] = None,
               lyric: str = "") -> bool:
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".flac":
            write_flac(path, meta, cover, lyric)
        elif ext in (".mp3", ".m4a"):
            write_mp3(path, meta, cover, lyric)
        else:
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


def read_tags(path: str) -> dict:
    """读回标签，用于下载后自检。"""
    ext = os.path.splitext(path)[1].lower()
    info = {}
    try:
        if ext == ".flac":
            a = FLAC(path)
            info["title"] = (a.get("title") or [""])[0]
            info["artist"] = " / ".join(a.get("artist") or [])
            info["album"] = (a.get("album") or [""])[0]
            info["pictures"] = len(a.pictures)
            info["duration"] = round(a.info.length, 1)
        else:
            a = MP3(path)
            info["title"] = str(a.tags.get("TIT2", "")) if a.tags else ""
            info["artist"] = str(a.tags.get("TPE1", "")) if a.tags else ""
            info["album"] = str(a.tags.get("TALB", "")) if a.tags else ""
            info["pictures"] = len(a.tags.getall("APIC")) if a.tags else 0
            info["duration"] = round(a.info.length, 1)
    except Exception as exc:  # noqa: BLE001
        info["error"] = repr(exc)
    return info

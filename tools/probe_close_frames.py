# -*- coding: utf-8 -*-
"""在真实窗口上触发系统关窗动画，并在动画进行中截屏，验证是否真的淡出。

用法：先启动 dist\\网易云音乐下载器.exe，再运行本脚本。
"""
import ctypes
import os
import struct
import sys
import threading
import time
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ncm.shell import APP_NAME, find_window_by_title, native_close, window_rect  # noqa: E402

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32
u32.SetProcessDPIAware()

OUT = os.path.join(ROOT, "shots")
PNG_SIG = bytes([137, 80, 78, 71, 13, 10, 26, 10])


class BIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


def chunk(tag, data):
    body = tag + data
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)


def grab(rect, path):
    x, y, w, h = rect
    screen = u32.GetDC(0)
    mem = g32.CreateCompatibleDC(screen)
    bmp = g32.CreateCompatibleBitmap(screen, w, h)
    g32.SelectObject(mem, bmp)
    g32.BitBlt(mem, 0, 0, w, h, screen, x, y, 0x00CC0020)

    bi = BIH()
    bi.biSize = ctypes.sizeof(BIH)
    bi.biWidth, bi.biHeight = w, -h
    bi.biPlanes, bi.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mem)
    u32.ReleaseDC(0, screen)

    data = buf.raw
    stride = w * 4
    out = bytearray()
    for r in range(h):
        out.append(0)                                  # PNG 行过滤器 None
        row = bytearray(data[r * stride:(r + 1) * stride])
        row[0::4], row[2::4] = row[2::4], row[0::4]     # BGR -> RGB
        for i in range(3, len(row), 4):
            row[i] = 255                               # alpha
        out += row

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    png = PNG_SIG + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(out), 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def main():
    hwnd = find_window_by_title(APP_NAME)
    if not hwnd:
        print("窗口没开，先启动 exe")
        return 1
    rect = window_rect(hwnd)
    print("窗口:", hwnd, rect)

    threading.Thread(target=lambda: (time.sleep(0.02), native_close(hwnd)), daemon=True).start()
    shots = [60, 100, 140, 180]
    t0 = time.perf_counter()
    for i, ms in enumerate(shots):
        while (time.perf_counter() - t0) * 1000 < ms:
            time.sleep(0.002)
        grab(rect, os.path.join(OUT, "anim-%d-%dms.png" % (i, ms)))
        print("抓帧", ms, "ms")
    time.sleep(0.6)
    print("窗口还在:", bool(find_window_by_title(APP_NAME)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

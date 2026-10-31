# -*- coding: utf-8 -*-
"""抓关闭过程帧：验证 Windows 原生 AnimateWindow 淡出的实际观感。"""
import ctypes
import os
import time

from PIL import ImageGrab  # noqa: F401  (若无 PIL 则下面用 win32 抓屏)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
u32 = ctypes.windll.user32
u32.SetProcessDPIAware()


class RECT(ctypes.Structure):
    _fields_ = [("L", ctypes.c_long), ("T", ctypes.c_long),
                ("R", ctypes.c_long), ("B", ctypes.c_long)]


def grab(rect):
    from PIL import ImageGrab as IG
    return IG.grab((rect.L, rect.T, rect.R, rect.B))


def main():
    hwnd = u32.FindWindowW(None, "网易云音乐下载器")
    if not hwnd:
        raise SystemExit("找不到窗口")
    r = RECT()
    u32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
    print("窗口:", r.L, r.T, r.R - r.L, r.B - r.T)

    u32.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)  # WM_CLOSE
    t0 = time.perf_counter()
    for ms in (30, 70, 110, 150, 190, 240):
        while (time.perf_counter() - t0) * 1000 < ms:
            time.sleep(0.004)
        img = grab(r)
        out = os.path.join(HERE, "shots", f"nc-{ms:03d}ms.png")
        img.save(out)
        print(f"[+] {ms}ms ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

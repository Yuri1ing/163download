# -*- coding: utf-8 -*-
"""测 pywebview(WebView2) 无边框窗口在本机 Python 3.14 上能不能跑，以及客户区是否等于页面视口。

    python tools/probe_pywebview.py
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ncm.server import make_server      # noqa: E402

SHOT = os.path.join(ROOT, "shots", "pywebview-probe.png")
CLASSES = ("Chrome_WidgetWin_0", "Chrome_WidgetWin_1", "WinForms10Lib")


def windows_of_pid(pid):
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        pid_out = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_out))
        if pid_out.value == pid:
            buf = ctypes.create_unicode_buffer(256)
            u.GetClassNameW(hwnd, buf, 256)
            if u.IsWindowVisible(hwnd):
                found.append((hwnd, buf.value))
        return True

    u.EnumWindows(cb, 0)
    return found



def main() -> int:
    import webview

    httpd, backend, port = make_server("pw")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/?t=pw"

    win = webview.create_window(
        "网易云音乐下载器", url,
        width=1280, height=880, frameless=True, easy_drag=True,
        background_color="#08090d",
    )

    def inspect():
        time.sleep(8)
        pid = os.getpid()
        wins = windows_of_pid(pid)
        print("[窗口]", [(h, c) for h, c in wins])
        u = ctypes.windll.user32
        for h, cls in wins:
            cr, wr = wintypes.RECT(), wintypes.RECT()
            u.GetClientRect(hwnd := h, ctypes.byref(cr))
            u.GetWindowRect(h, ctypes.byref(wr))
            print(f"[{cls}] client {cr.right}x{cr.bottom} window "
                  f"{wr.right - wr.left}x{wr.bottom - wr.top}")
            try:
                r = win.evaluate_js("JSON.stringify({iw:innerWidth, ih:innerHeight})")
                print("[页面]", r)
            except Exception as exc:  # noqa: BLE001
                print("[页面] 取值失败", repr(exc))
        try:
            win.destroy()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=inspect, daemon=True).start()
    t0 = time.time()
    webview.start(gui="edgechromium") if False else webview.start()
    print("[退出] 耗时", round(time.time() - t0, 1), "s")
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

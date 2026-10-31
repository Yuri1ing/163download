# -*- coding: utf-8 -*-
"""试各种 Chromium 特性开关，找出「剥掉 WS_CAPTION 后不画出浏览器自绘标题栏」的那个。

判定方法：客户区高度 - innerHeight ≈ 0 → 客户区里没有 28px 的自绘标题栏。

    python tools/probe_flags.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import ctypes                                     # noqa: E402
from ctypes import wintypes                       # noqa: E402

from ncm.server import make_server                # noqa: E402
from ncm.shell import find_edge, make_frameless, _hwnd  # noqa: E402
from drive_shot import CDP, wait                  # noqa: E402

TITLE = "网易云音乐下载器"
CANDIDATES = [
    ("baseline", []),
    ("no-WebAppFrameToolbar", ["--disable-features=WebAppFrameToolbar"]),
    ("no-WindowsCustomTitleBar", ["--disable-features=WindowsCustomTitleBar"]),
    ("no-Windows11CustomTitleBar", ["--disable-features=Windows11CustomTitleBar"]),
    ("no-CustomFrameView", ["--disable-features=CustomFrameView"]),
    ("no-DesktopPWAsAdditionalWindowingControls",
     ["--disable-features=DesktopPWAsAdditionalWindowingControls"]),
    ("no-WebAppWindowControlsOverlay",
     ["--disable-features=WebAppWindowControlsOverlay"]),
    ("combo-all",
     ["--disable-features=WebAppFrameToolbar,WindowsCustomTitleBar,"
      "Windows11CustomTitleBar,CustomFrameView,WebAppWindowControlsOverlay"]),
]


def measure(flags, idx, port):
    prof = os.path.join(tempfile.gettempdir(), f"ncm-flag-{idx}")
    url = f"http://127.0.0.1:{port}/?t=f{idx}"
    proc = subprocess.Popen([
        find_edge(), f"--app={url}", "--window-size=1280,900",
        f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
        f"--remote-debugging-port={9300 + idx}", "--remote-allow-origins=*",
    ] + flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    target = {}

    def find():
        try:
            data = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{9300 + idx}/json", timeout=2).read().decode())
            for t in data:
                if t.get("type") == "page" and f":{port}" in t.get("url", ""):
                    target["ws"] = t["webSocketDebuggerUrl"]
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    if not wait(find, 30, "cdp"):
        return None
    cdp = CDP(target["ws"])
    cdp.send("Page.enable")
    cdp.send("Runtime.enable")
    wait(lambda: cdp.js("!!document.body"), 15, "页面")
    time.sleep(1.2)
    make_frameless(TITLE)
    time.sleep(1.6)

    h = _hwnd(TITLE)
    u = ctypes.WinDLL("user32")
    u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    cr = wintypes.RECT()
    u.GetClientRect(h, ctypes.byref(cr))
    ih = cdp.js("innerHeight")
    cdp.close()
    proc.terminate()
    time.sleep(0.8)
    return cr.bottom - ih if ih else None


def main() -> int:
    httpd, backend, port = make_server("flags")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    results = []
    for i, (name, flags) in enumerate(CANDIDATES):
        try:
            diff = measure(flags, i, port)
        except Exception as exc:  # noqa: BLE001
            diff = f"err {exc!r}"
        results.append((name, diff))
        print(f"{name:45s} 客户区-innerHeight = {diff}")
    httpd.shutdown()
    print("\n结论：差值 ≤ 2 的候选可用 ->",
          [n for n, d in results if isinstance(d, int) and d <= 2])
    return 0


if __name__ == "__main__":
    sys.exit(main())

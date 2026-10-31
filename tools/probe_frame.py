# -*- coding: utf-8 -*-
"""诊断：Edge --app 窗口去掉 WS_CAPTION 后，客户区里还有没有 Chromium 自己画的标题栏。

    python tools/probe_frame.py
输出 innerHeight / client 高度对比结论，并留下窗口句柄给后续截图用。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from ncm.server import make_server                    # noqa: E402
from ncm.shell import find_edge, make_frameless, _hwnd  # noqa: E402
from drive_shot import CDP, wait                      # noqa: E402

TITLE = "网易云音乐下载器"
PORT = 9391


def main() -> int:
    import threading
    httpd, backend, port = make_server("probe")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/?t=probe"
    prof = os.path.join(tempfile.gettempdir(), "ncm-probe")
    proc = subprocess.Popen([
        find_edge(), f"--app={url}", "--window-size=1280,900",
        f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
        f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    target = {}

    def find():
        try:
            data = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/json", timeout=2).read().decode())
            for t in data:
                if t.get("type") == "page" and f":{port}" in t.get("url", ""):
                    target["ws"] = t["webSocketDebuggerUrl"]
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    if not wait(find, 40, "cdp"):
        return 1
    cdp = CDP(target["ws"])
    cdp.send("Page.enable")
    cdp.send("Runtime.enable")
    wait(lambda: cdp.js("!!document.getElementById('btnParse')"), 20, "页面")
    time.sleep(1.0)

    print("剥标题栏:", make_frameless(TITLE))
    time.sleep(1.5)
    h = _hwnd(TITLE)
    print("hwnd:", h)

    js = cdp.js("JSON.stringify({iw: innerWidth, ih: innerHeight, "
                "ow: outerWidth, oh: outerHeight, sy: screenY, sx: screenX})")
    print("页面测量:", js)

    # 用 Win32 读客户区尺寸做对比（ctypes）
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32")
    u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    cr, wr = wintypes.RECT(), wintypes.RECT()
    u.GetClientRect(h, ctypes.byref(cr))
    u.GetWindowRect(h, ctypes.byref(wr))
    print(f"客户区 {cr.right}x{cr.bottom}  窗口 {wr.right - wr.left}x{wr.bottom - wr.top}")

    data = json.loads(js)
    diff = cr.bottom - data["ih"]
    print(f"客户区高度 - innerHeight = {diff}  ({'客户区里有浏览器自绘标题栏' if diff > 12 else '没有自绘标题栏'})")

    with open(os.path.join(tempfile.gettempdir(), "ncm-probe-hwnd.txt"), "w") as fh:
        fh.write(str(h))
    cdp.close()
    httpd.shutdown()
    print("Edge 未关闭，hwnd 留给截图用；用完执行 taskkill")
    return 0


if __name__ == "__main__":
    sys.exit(main())

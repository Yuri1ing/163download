# -*- coding: utf-8 -*-
"""端到端验证关窗淡出：用 CDP 点真实界面的 × 按钮，同时在屏幕上连拍几帧。

用法：先启动 exe（带 remote-debugging 端口），再跑本脚本。
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drive_shot import CDP, wait                     # noqa: E402
from ncm.shell import APP_NAME, find_window_by_title, window_rect  # noqa: E402
from probe_fade import grab                          # noqa: E402

PORT = 9361
OUT = os.path.join(ROOT, "shots")


def find_ws():
    try:
        data = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/json", timeout=2).read().decode())
        for t in data:
            if t.get("type") == "page":
                return t["webSocketDebuggerUrl"]
    except Exception:  # noqa: BLE001
        pass
    return None


def main():
    exe = os.path.join(ROOT, "dist", "网易云音乐下载器.exe")
    env = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f"--remote-debugging-port={PORT}")
    proc = subprocess.Popen([exe], env=env)
    box = {}

    def _find():
        u = find_ws()
        if u:
            box["ws"] = u
            return True
        return False

    wait(_find, 60, "CDP 端口")
    cdp = CDP(box["ws"])
    cdp.send("Runtime.enable")
    wait(lambda: cdp.js("!!document.getElementById('btnClose')"), 40, "页面就绪")
    time.sleep(1.0)

    hwnd = find_window_by_title(APP_NAME)
    rect = window_rect(hwnd)
    print("窗口", hwnd, rect)

    cdp.js("document.getElementById('btnClose').click()")
    t0 = time.perf_counter()
    for i, ms in enumerate([40, 120, 200, 260]):
        while (time.perf_counter() - t0) * 1000 < ms:
            time.sleep(0.002)
        grab(rect, os.path.join(OUT, f"real-close-{i}-{ms}ms.png"))
    print("抓帧完成")
    try:
        cdp.close()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(2.5)
    print("进程退出码:", proc.poll())
    return 0


if __name__ == "__main__":
    sys.exit(main())

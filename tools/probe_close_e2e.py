# -*- coding: utf-8 -*-
"""端到端验证：点界面上的「×」后，窗口是否按系统动画关闭、进程是否退出。

做法：带 WebView2 远程调试参数启动 exe -> CDP 点 #btnClose -> 记录窗口/进程消失耗时。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ncm.shell import find_window_by_title, APP_NAME  # noqa: E402

EXE = os.path.join(ROOT, "dist", "网易云音乐下载器.exe")
PORT = 9361


def cdp_targets():
    try:
        return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=1).read())
    except Exception:
        return []


def main():
    env = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f"--remote-debugging-port={PORT}")
    p = subprocess.Popen([EXE], env=env)
    print("启动 exe pid", p.pid)

    ws = None
    t0 = time.time()
    while time.time() - t0 < 40 and not ws:
        for t in cdp_targets():
            if t.get("type") == "page":
                ws = t["webSocketDebuggerUrl"]
        time.sleep(0.4)
    if not ws:
        print("拿不到 CDP，跳过")
        p.kill()
        return 1
    print("CDP ok，等界面就绪")
    time.sleep(4)

    from tools.drive_shot import CDP
    c = CDP(ws)
    c.send("Runtime.enable")
    for _ in range(40):
        if c.js("!!document.getElementById('btnClose')"):
            break
        time.sleep(0.3)

    hwnd_before = find_window_by_title(APP_NAME)
    print("窗口句柄", hwnd_before)

    mode = sys.argv[1] if len(sys.argv) > 1 else "close"
    if mode == "min":
        import ctypes
        c.js("document.getElementById('btnMin').click()")
        time.sleep(0.5)
        print("IsIconic（已最小化）:", bool(ctypes.windll.user32.IsIconic(hwnd_before)))
        ctypes.windll.user32.ShowWindow(hwnd_before, 9)
        time.sleep(0.6)
        c.js("document.getElementById('btnClose').click()")
        time.sleep(2.5)
        p.kill()
        print("最小化链路 OK")
        return 0

    c.js("document.getElementById('btnClose').click()")
    t_click = time.perf_counter()
    gone_at, exit_at = None, None
    for _ in range(200):
        time.sleep(0.02)
        ms = (time.perf_counter() - t_click) * 1000
        if gone_at is None and not find_window_by_title(APP_NAME):
            gone_at = ms
        if p.poll() is not None:
            exit_at = ms
            break
    print(f"窗口消失于 {gone_at and round(gone_at)} ms，进程退出于 {exit_at and round(exit_at)} ms")
    try:
        c.close()
    except Exception:
        pass
    if p.poll() is None:
        print("！！进程没退出，强制结束")
        p.kill()
        return 2
    print("关窗链路 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

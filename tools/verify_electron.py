# -*- coding: utf-8 -*-
"""打包后 Electron 版验证：截图 + 点关闭并采样窗口 alpha，证明淡出是真的。"""
import base64
import ctypes
import json
import os
import sys
import threading
import time
import urllib.request

import websocket

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("NCM_DEBUG_PORT", "9335"))

u32 = ctypes.windll.user32


def page_ws():
    data = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{PORT}/json", timeout=3).read().decode())
    for t in data:
        if t.get("type") == "page" and "127.0.0.1" in t.get("url", ""):
            return t["webSocketDebuggerUrl"]
    raise SystemExit("没有页面")


class CDP:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=40)
        self.i = 0

    def send(self, method, **params):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.i:
                return m.get("result", {})

    def js(self, expr):
        r = self.send("Runtime.evaluate", expression=expr, returnByValue=True)
        return r.get("result", {}).get("value")

    def shot(self, path):
        r = self.send("Page.captureScreenshot", format="png")
        open(path, "wb").write(base64.b64decode(r["data"]))
        print("[+]", path)


def alpha_samples(hwnd, stop_evt, out):
    for _ in range(14):
        if stop_evt.is_set():
            break
        key = ctypes.c_int(0)
        alpha = ctypes.c_ubyte(255)
        flags = ctypes.c_int(0)
        ok = u32.GetLayeredWindowAttributes(ctypes.c_void_p(hwnd), ctypes.byref(key),
                                            ctypes.byref(alpha), ctypes.byref(flags))
        out.append((ok, alpha.value))
        time.sleep(0.045)


def main():
    cdp = CDP(page_ws())
    cdp.send("Page.enable")
    cdp.send("Runtime.enable")
    time.sleep(1.0)
    cdp.shot(os.path.join(HERE, "shots", "el-packaged.png"))
    print("[*] 标题:", cdp.js("document.title"),
          "| ncmWin:", cdp.js("!!window.ncmWin"),
          "| 列表行:", cdp.js("document.querySelectorAll('#list .row').length"))

    hwnd = u32.FindWindowW(None, "网易云音乐下载器")
    print("[*] hwnd =", hwnd)

    samples = []
    stop = threading.Event()
    th = threading.Thread(target=alpha_samples, args=(hwnd, stop, samples))
    th.start()
    time.sleep(0.03)
    cdp.js("window.ncmWin.close()")
    th.join(timeout=3)
    stop.set()
    seq = [a for ok, a in samples if ok]
    print("[*] 关闭淡出 alpha 采样:", seq if seq else "（读取不到分层属性）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

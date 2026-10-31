# -*- coding: utf-8 -*-
"""开发用：用 DevTools 协议驱动界面并截图（验证样式 / 走通解析流程）。

    python tools/drive_shot.py            # 默认截 3 张到 shots/
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

from ncm.server import make_server          # noqa: E402
from ncm.shell import find_edge             # noqa: E402

PORT_CDP = 9371


class CDP:
    def __init__(self, ws_url: str):
        from websocket import create_connection   # type: ignore
        self.ws = create_connection(ws_url, timeout=30)
        self.i = 0

    def send(self, method: str, **params):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.i:
                return msg.get("result", {})

    def js(self, expr: str):
        r = self.send("Runtime.evaluate", expression=expr, returnByValue=True,
                      awaitPromise=True)
        return r.get("result", {}).get("value")

    def shot(self, path: str):
        r = self.send("Page.captureScreenshot", format="png",
                      captureBeyondViewport=False)
        import base64
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(r["data"]))
        print(f"[+] {path}")

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def wait(fn, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if fn():
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.35)
    print(f"[!] 超时：{what}")
    return False


def main() -> int:
    shots = os.path.join(ROOT, "shots")
    os.makedirs(shots, exist_ok=True)

    httpd, backend, port = make_server("devtok")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/?t=devtok"

    prof = os.path.join(tempfile.gettempdir(), "ncm-cdp-shots")
    proc = subprocess.Popen([
        find_edge(), f"--app={url}", "--window-size=1280,880",
        f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
        f"--remote-debugging-port={PORT_CDP}", "--remote-allow-origins=*",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    target = {}

    def find():
        try:
            data = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{PORT_CDP}/json", timeout=2).read().decode())
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
    # 固定视口 + 1 倍缩放，保证截图尺寸就是真实布局尺寸
    try:
        cdp.send("Emulation.setDeviceMetricsOverride", width=1280, height=880,
                 deviceScaleFactor=1, mobile=False)
    except Exception:  # noqa: BLE001
        pass
    wait(lambda: cdp.js("!!document.getElementById('btnParse')"), 20, "页面加载")
    time.sleep(0.8)
    cdp.shot(os.path.join(shots, "01-empty.png"))

    # 解析歌单
    cdp.js("""(() => {
      document.getElementById('input').value = 'https://music.163.com/playlist?id=3778678';
      document.getElementById('btnParse').click();
    })()""")
    wait(lambda: (cdp.js("document.querySelectorAll('#list .row').length") or 0) > 10, 90, "解析")
    time.sleep(0.6)
    cdp.shot(os.path.join(shots, "02-list.png"))

    # 设置抽屉
    cdp.js("document.getElementById('btnSettings').click()")
    time.sleep(0.2)
    cdp.js("document.getAnimations().forEach(a => { try { a.finish(); } catch (e) {} })")
    time.sleep(0.4)
    cdp.shot(os.path.join(shots, "03-settings.png"))
    cdp.js("document.getElementById('drawerClose').click()")
    time.sleep(0.4)

    # 日志面板
    cdp.js("document.getElementById('btnLog').click()")
    time.sleep(0.2)
    cdp.js("document.getAnimations().forEach(a => { try { a.finish(); } catch (e) {} })")
    time.sleep(0.4)
    cdp.shot(os.path.join(shots, "04-log.png"))

    print("[+] 行数:", cdp.js("document.querySelectorAll('#list .row').length"))
    cdp.close()
    proc.terminate()
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Electron 版 UI 驱动：走 CDP 点按钮、截图，验证功能与外观。"""
import base64
import json
import os
import sys
import time
import urllib.request

import websocket

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("NCM_DEBUG_PORT", "9333"))


def find_page():
    for _ in range(40):
        try:
            data = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/json", timeout=2).read().decode())
            for t in data:
                if t.get("type") == "page" and "127.0.0.1" in t.get("url", ""):
                    return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    raise SystemExit("没找到 Electron 页面")


class CDP:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=40)
        self.i = 0

    def send(self, method, **params):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.i:
                return msg.get("result", {})

    def js(self, expr):
        r = self.send("Runtime.evaluate", expression=expr, returnByValue=True,
                      awaitPromise=True)
        return r.get("result", {}).get("value")

    def shot(self, path):
        r = self.send("Page.captureScreenshot", format="png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        print("[+]", path)

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def wait(fn, timeout=90, what=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return True
        time.sleep(0.4)
    print("[!] 超时:", what)
    return False


def main():
    cdp = CDP(find_page())
    cdp.send("Page.enable")
    cdp.send("Runtime.enable")
    wait(lambda: cdp.js("!!document.getElementById('btnParse')"), 30, "页面加载")
    print("[*] window.ncmWin =", cdp.js("JSON.stringify(!!window.ncmWin)"),
          " drag =", cdp.js("getComputedStyle(document.getElementById('topbar')).webkitAppRegion"))
    cdp.shot(os.path.join(HERE, "shots", "el-01-empty.png"))

    cdp.js("""(() => {
        document.getElementById('input').value = 'https://music.163.com/playlist?id=3778678';
        document.getElementById('btnParse').click();
    })()""")
    wait(lambda: (cdp.js("document.querySelectorAll('#list .row').length") or 0) > 10, 120, "列表")
    rows = cdp.js("document.querySelectorAll('#list .row').length")
    print("[*] 解析到", rows, "首")
    cdp.js("document.getAnimations().forEach(a=>{try{a.finish()}catch(e){}})")
    cdp.shot(os.path.join(HERE, "shots", "el-02-list.png"))

    cdp.js("document.getElementById('btnSettings').click()")
    time.sleep(1.2)
    cdp.js("document.getAnimations().forEach(a=>{try{a.finish()}catch(e){}})")
    cdp.shot(os.path.join(HERE, "shots", "el-03-settings.png"))
    cdp.js("document.getElementById('drawerClose').click()")
    time.sleep(0.4)

    # 只选前 2 首下载，验证链路
    cdp.js("""(() => {
        const rows = [...document.querySelectorAll('#list .row')];
        rows.forEach((r, i) => { const cb = r.querySelector('input[type=checkbox]');
            if (cb && (i > 1) && cb.checked) cb.click(); });
        document.getElementById('btnStart').click();
    })()""")
    wait(lambda: (cdp.js("[...document.querySelectorAll('#list .row .pill')].filter(e=>/完成/.test(e.textContent)).length") or 0) >= 1, 180, "下载完成")
    done = cdp.js("[...document.querySelectorAll('#list .row .pill')].filter(e=>/完成/.test(e.textContent)).length")
    print("[*] 完成", done, "首")
    cdp.js("document.getElementById('btnLog').click()")
    time.sleep(1.0)
    cdp.js("document.getAnimations().forEach(a=>{try{a.finish()}catch(e){}})")
    cdp.shot(os.path.join(HERE, "shots", "el-04-log.png"))
    print("[*] 日志尾部:", (cdp.js("document.getElementById('log').innerText") or "")[-260:])
    cdp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

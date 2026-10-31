# -*- coding: utf-8 -*-
"""轻量验证：每次用新连接读一次 DOM，避免长连接被中断。

用法：先启动带 NCM_DEBUG_PORT 的 app，再跑本脚本。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drive_electron import HERE, CDP, find_page  # noqa: E402


def read(expr):
    """每次新建 CDP 连接只求一个值，抗断连。"""
    cdp = CDP(find_page())
    try:
        cdp.send("Runtime.enable")
        return cdp.js(expr)
    finally:
        try:
            cdp.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    print("初始:", read("document.getElementById('progText').textContent"))

    cdp = CDP(find_page())
    cdp.send("Runtime.enable")
    cdp.js("""(() => {
        document.getElementById('input').value = 'https://music.163.com/playlist?id=3778678';
        document.getElementById('btnParse').click();
    })()""")
    cdp.close()
    time.sleep(12)

    cdp = CDP(find_page())
    cdp.send("Runtime.enable")
    cdp.js("""(() => {
        document.querySelectorAll('#list .row').forEach((r, i) => {
            const cb = r.querySelector('input[type=checkbox]');
            if (cb && cb.checked && i >= 3) cb.click();
        });
        document.querySelector('#levelSeg button[data-level="exhigh"]').click();
    })()""")
    cdp.close()
    time.sleep(2)

    cdp = CDP(find_page())
    cdp.send("Runtime.enable")
    cdp.js("document.getElementById('btnStart').click()")
    cdp.close()

    seen = []
    for _ in range(30):
        txt = read("document.getElementById('progText').textContent")
        w = read("document.getElementById('bar').style.width")
        if not seen or seen[-1][0] != txt:
            seen.append((txt, w))
            print("  ->", txt, "| 条宽", w)
        if txt and "3 / 3" in txt:
            break
        time.sleep(1.5)
    cdp = CDP(find_page())
    cdp.send("Page.enable")
    cdp.shot(os.path.join(HERE, "screenshots", "progress-counts.png"))
    cdp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

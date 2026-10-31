# -*- coding: utf-8 -*-
"""验证进度条改成「已下载 N / M 首」：解析 → 只选 3 首 → 下载 → 抓运行中的进度文本。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from drive_electron import HERE, CDP, find_page  # noqa: E402


def main() -> int:
    cdp = CDP(find_page())
    cdp.send("Page.enable")
    cdp.send("Runtime.enable")
    for _ in range(40):
        if cdp.js("!!document.getElementById('btnParse')"):
            break
        time.sleep(0.5)

    cdp.js("""(() => {
        document.getElementById('input').value = 'https://music.163.com/playlist?id=3778678';
        document.getElementById('btnParse').click();
    })()""")
    for _ in range(120):
        n = cdp.js("document.querySelectorAll('#list .row').length") or 0
        if n > 10:
            break
        time.sleep(0.5)
    print("解析:", n, "首；初始进度文本 =", cdp.js("document.getElementById('progText').textContent"))

    # 只留前 3 首勾选
    cdp.js("""(() => {
        document.querySelectorAll('#list .row').forEach((r, i) => {
            const cb = r.querySelector('input[type=checkbox]');
            if (cb && cb.checked && i >= 3) cb.click();
        });
        document.querySelector('#levelSeg button[data-level="exhigh"]').click();
    })()""")
    time.sleep(0.8)
    print("已选:", cdp.js("document.getElementById('progText').textContent"))
    cdp.js("document.getElementById('btnStart').click()")

    seen = []
    for _ in range(40):
        txt = cdp.js("document.getElementById('progText').textContent")
        w = cdp.js("document.getElementById('bar').style.width")
        if not seen or seen[-1][0] != txt:
            seen.append((txt, w))
        if "3 / 3" in (txt or ""):
            break
        time.sleep(1.0)
    print("进度变化:")
    for t, w in seen[:10]:
        print("   ", t, "| 条宽", w)
    cdp.shot(os.path.join(HERE, "screenshots", "progress-counts.png"))
    cdp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

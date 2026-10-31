# -*- coding: utf-8 -*-
"""验证无损/Hi-Res 档位：切换档位 → 体积估算变化 → 下载 1 首 → 看落盘文件。"""
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

    print("档位按钮:", cdp.js(
        "Array.from(document.querySelectorAll('#levelSeg button')).map(b=>b.textContent).join(' | ')"))

    # 只留 1 首做下载验证
    cdp.js("""(() => {
        document.getElementById('input').value = 'https://music.163.com/playlist?id=3778678';
        document.getElementById('btnParse').click();
    })()""")
    for _ in range(120):
        n = cdp.js("document.querySelectorAll('#list .row').length") or 0
        if n > 10:
            break
        time.sleep(0.5)
    print("解析行数:", n)

    for lv in ("exhigh", "lossless", "hires"):
        cdp.js(f"document.querySelector('#levelSeg button[data-level=\"{lv}\"]').click()")
        time.sleep(0.8)
        first = cdp.js("document.querySelector('#list .row .c.size')?.textContent || ''")
        on = cdp.js("document.querySelector('#levelSeg button.on').textContent")
        print(f"[{lv}] 按钮={on} 首行体积={first}")
    cdp.shot(os.path.join(HERE, "screenshots", "lossless-levels.png"))

    # 选无损、只下第 1 首，验证落盘格式与降级提示
    cdp.js("document.querySelector('#levelSeg button[data-level=\"lossless\"]').click()")
    time.sleep(0.5)
    cdp.js("""(() => {
        document.querySelectorAll('#list .row input[type=checkbox]').forEach((c,i) => {
            if (i > 0 && c.checked) c.click();
        });
    })()""")
    time.sleep(0.5)
    print("已选:", cdp.js("document.getElementById('selInfo')?.textContent || ''"))
    cdp.js("document.getElementById('btnStart').click()")
    for _ in range(160):
        st = cdp.js("document.querySelector('#list .row .c.state')?.textContent || ''")
        if "完成" in st or "失败" in st or "错误" in st:
            break
        time.sleep(1.0)
    print("首行状态:", st)
    cdp.js("document.getElementById('btnLog').click()")
    time.sleep(1.0)
    logs = cdp.js("document.getElementById('log').innerText.split('\\n').slice(-8).join(' || ')")
    print("日志尾部:", logs)
    cdp.shot(os.path.join(HERE, "screenshots", "lossless-download.png"))
    cdp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

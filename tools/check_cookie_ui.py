# -*- coding: utf-8 -*-
"""验证「检测 Cookie」功能：打开设置抽屉 → 点检测 → 截图 + 读回结果文本。"""
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
        if cdp.js("!!document.getElementById('btnCheckCookie')"):
            break
        time.sleep(0.5)
    else:
        raise SystemExit("页面上没有 btnCheckCookie —— 后端 web 资源没更新")

    # 先填一个明显无效的 Cookie，验证「失败」分支
    cdp.js("""(() => {
        const t = document.getElementById('setCookie');
        t.value = 'MUSIC_U=deadbeef_invalid';
        document.getElementById('btnSettings').click();
    })()""")
    time.sleep(1.0)
    cdp.js("document.getElementById('btnCheckCookie').click()")
    time.sleep(6)
    bad = cdp.js("document.getElementById('cookieState').textContent")
    bad_cls = cdp.js("document.getElementById('cookieState').className")
    print("[无效] class=%s text=%s" % (bad_cls, bad))
    cdp.shot(os.path.join(HERE, "screenshots", "cookie-bad.png"))

    # 真 Cookie：用后端配置里保存的那个
    cdp.js("""(() => {
        const t = document.getElementById('setCookie');
        t.value = '';
        document.getElementById('btnCheckCookie').click();
    })()""")
    time.sleep(4)
    empty = cdp.js("document.getElementById('cookieState').textContent")
    print("[空值] %s" % empty)
    cdp.shot(os.path.join(HERE, "screenshots", "cookie-empty.png"))
    cdp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""验证「系统自带关窗淡出」是否真的在这套 pywebview 窗口上生效。

做法：起一个真实窗口 -> 抓屏幕中心亮度序列 -> 调用 native_close -> 看亮度是否渐变到桌面。
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ncm.shell import APP_NAME, find_window_by_title, native_close, native_minimize, window_rect  # noqa: E402
import webview  # noqa: E402

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32
u32.SetProcessDPIAware()


def sample(rect, n=40):
    """连续采样窗口中心 1 点的颜色（BGR），返回 [(ms, rgb)]。"""
    x = rect[0] + rect[2] // 2
    y = rect[1] + rect[3] // 2
    screen = u32.GetDC(0)
    mem = g32.CreateCompatibleDC(screen)
    bmp = g32.CreateCompatibleBitmap(screen, 1, 1)
    g32.SelectObject(mem, bmp)
    out = []
    t0 = time.perf_counter()
    for _ in range(n):
        g32.BitBlt(mem, 0, 0, 1, 1, screen, x, y, 0x00CC0020)   # SRCCOPY
        v = g32.GetPixel(mem, 0, 0)
        out.append((round((time.perf_counter() - t0) * 1000), v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF))
        time.sleep(0.015)
    g32.DeleteObject(bmp); g32.DeleteDC(mem); u32.ReleaseDC(0, screen)
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "close"
    samples = []
    holder = {}

    def worker():
        # 等窗口出现
        for _ in range(80):
            hwnd = find_window_by_title(APP_NAME)
            if hwnd:
                break
            time.sleep(0.15)
        hwnd = find_window_by_title(APP_NAME)
        holder["hwnd"] = hwnd
        time.sleep(2.0)
        rect = window_rect(hwnd)
        holder["rect"] = rect
        th = threading.Thread(target=lambda: samples.extend(sample(rect)), daemon=True)
        th.start()
        time.sleep(0.15)
        if mode == "close":
            holder["ret"] = native_close(hwnd)
        else:
            holder["ret"] = native_minimize(hwnd)
        th.join(timeout=5)
        holder["n"] = len(samples)
        time.sleep(0.4)
        holder["still"] = bool(find_window_by_title(APP_NAME))
        try:
            webview.windows[0].destroy()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=worker, daemon=True).start()

    from ncm.server import make_server
    httpd, backend, port = make_server("anim")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    import ncm.shell as shell
    shell._run_pywebview(f"http://127.0.0.1:{port}/?t=anim")
    httpd.shutdown()

    print("mode:", mode, "ret:", holder.get("ret"), "窗口还在:", holder.get("still"))
    seq = samples
    if seq:
        uniq = []
        for s in seq:
            if not uniq or uniq[-1][1:] != s[1:]:
                uniq.append(s)
        print(f"采样 {len(seq)} 帧，颜色变化 {len(uniq)} 段：")
        for s in uniq[:12]:
            print("   ", s)
    else:
        print("没采到样本")


if __name__ == "__main__":
    main()

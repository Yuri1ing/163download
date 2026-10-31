# -*- coding: utf-8 -*-
"""网易云音乐下载器 —— 入口。

默认启动现代界面（本地服务 + Edge 应用窗口）；`--tk` 可切回旧的 Tkinter 界面。
"""
import os
import sys


def _enable_dpi():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def main():
    _enable_dpi()
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))
    if "--tk" in sys.argv:
        from ncm.ui import main as run
    else:
        from ncm.shell import main as run
    run()


if __name__ == "__main__":
    main()

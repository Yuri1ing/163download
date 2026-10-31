# -*- coding: utf-8 -*-
"""网易云音乐下载器 · Qt 版入口（PySide6）。"""

import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _dpi_aware() -> None:
    """必须在 QApplication 之前声明 DPI 感知，否则窗口会被系统位图拉伸（发虚、
    而且 GetWindowRect 拿到的是虚拟化尺寸）。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # PER_MONITOR_AWARE
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    # 必须在 import PySide6 之前、也就是 QApplication 构造前把 DPI 感知设好：
    # 不设的话 Windows 会把窗口按虚拟化尺寸交给 Qt，而 Qt 又按真实 DPI 放大渲染，
    # 结果就是"1280 的窗口里画 1920 的界面"——右侧被裁掉、字体发虚。
    _dpi_aware()
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from ncm.qtui import run
    return run()


if __name__ == "__main__":
    sys.exit(main())

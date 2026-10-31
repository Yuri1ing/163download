# -*- coding: utf-8 -*-
"""桌面外壳：起本地 HTTP 服务 → 用 WebView2 开一个**无边框**窗口 → 关窗即退出。

两条路：
1. 首选 `pywebview`（WebView2 内核，frameless=True）：窗口里没有任何浏览器自带 UI，
   标题栏由页面自绘，拖动/缩放/最小化/关闭都能做。
2. 退路 `msedge --app`：渲染一样，但 Chromium 会自己画一条 28px 工具栏，所以只在
   pywebview 起不来时使用（日志里会写明原因）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
import webbrowser

from .core import APP_NAME
from .server import STATE, VERSION, make_server

WIN_W, WIN_H = 1280, 880


# ---------------------------------------------------------------- Edge 定位
def find_edge() -> str:
    """定位 msedge.exe；找不到就返回空串（退路里会改用系统默认浏览器）。"""
    if sys.platform != "win32":
        return ""
    cands = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            cands.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    for p in cands:
        if os.path.isfile(p):
            return p
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
        ) as k:
            p = winreg.QueryValue(k, None)
            if p and os.path.isfile(p):
                return p
    except Exception:  # noqa: BLE001
        pass
    return ""


def profile_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "网易云下载器", "edge-profile")
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- Win32
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _u32.FindWindowW.restype = wintypes.HWND
    _u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _u32.IsWindowVisible.argtypes = [wintypes.HWND]
    _u32.IsWindowVisible.restype = ctypes.c_bool
    if hasattr(_u32, "GetWindowLongPtrW"):
        _u32.GetWindowLongPtrW.restype = ctypes.c_longlong
        _u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        _u32.SetWindowLongPtrW.restype = ctypes.c_longlong
        _u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
        _getlong, _setlong = _u32.GetWindowLongPtrW, _u32.SetWindowLongPtrW
    else:                                        # 32 位解释器
        _getlong, _setlong = _u32.GetWindowLongW, _u32.SetWindowLongW

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_BORDER = 0x00800000
WS_DLGFRAME = 0x00400000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x0001, 0x0002, 0x0004
SWP_FRAMECHANGED = 0x0020
SW_MINIMIZE = 6
SW_SHOW = 5
WM_CLOSE = 0x0010


def find_window_by_title(title: str):
    """按标题找工作区窗口（不限定窗口类：WinForms 与 Chromium 类名不同）。"""
    if sys.platform != "win32":
        return None
    h = _u32.FindWindowW(None, title)
    return h or None


def make_frameless(title: str) -> bool:
    """剥掉系统标题栏，只留可缩放边框（Edge 退路用）。"""
    h = find_window_by_title(title)
    if not h:
        return False
    style = _getlong(h, GWL_STYLE)
    new = style & ~(WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
                    | WS_BORDER | WS_DLGFRAME)
    new |= WS_THICKFRAME
    if new == style:
        return True
    _setlong(h, GWL_STYLE, new)
    _u32.SetWindowPos(h, None, 0, 0, 0, 0,
                      SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED)
    return True


def add_resize_border(title: str) -> bool:
    """给无边框窗口补一条可拖拽的缩放边框（pywebview 的 Form 默认没有）。"""
    h = find_window_by_title(title)
    if not h:
        return False
    style = _getlong(h, GWL_STYLE)
    if style & WS_THICKFRAME:
        return True
    _setlong(h, GWL_STYLE, style | WS_THICKFRAME)
    _u32.SetWindowPos(h, None, 0, 0, 0, 0,
                      SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED)
    return True


AW_HIDE = 0x10000
AW_BLEND = 0x0002


def native_minimize(h) -> bool:
    """交给 Windows 自己播最小化动画（会缩到任务栏），不做任何自绘动画。"""
    try:
        _u32.ShowWindow(h, SW_MINIMIZE)
        return True
    except Exception:  # noqa: BLE001
        return False


def native_close(h, delay_ms: int = 0) -> bool:
    """关窗：先用「截屏覆盖层淡出」播一段和系统一致的淡出，再真正关窗。

    WebView2 是子窗口，父窗口的 layered/AnimateWindow 管不到它的像素，
    直接关就会"内容啪地消失"，所以这里改成截屏 + 分层窗口做 alpha 渐变。
    """
    animated = False
    try:
        from .fadewin import fade_and_close      # noqa: PLC0415
        animated = fade_and_close(h, steps=20, interval_ms=17)
    except Exception as exc:  # noqa: BLE001
        print(f"[shell] 淡出动画失败: {exc!r}", file=sys.stderr)
        animated = False

    if not animated:
        try:
            _u32.AnimateWindow(h, 170, AW_BLEND | AW_HIDE)
        except Exception:  # noqa: BLE001
            pass

    def _close() -> None:
        try:
            _u32.PostMessageW(h, WM_CLOSE, 0, 0)
        except Exception:  # noqa: BLE001
            return
        # 兜底：消息循环没处理 WM_CLOSE 时（个别 pywebview 版本），1.2s 后强拆
        deadline = time.time() + 1.2
        while time.time() < deadline:
            if not _u32.IsWindow(h):
                return
            time.sleep(0.05)
        try:
            _u32.DestroyWindow(h)
        except Exception:  # noqa: BLE001
            pass
        # 兜底：窗口没了但进程还赖着（WebView2 清理偶发卡住），直接结束
        time.sleep(0.8)
        os._exit(0)

    threading.Thread(target=_close, daemon=True).start()
    return True


def win32_action(title: str, action: str) -> bool:
    h = find_window_by_title(title)
    if not h:
        return False
    if action == "minimize":
        return native_minimize(h)
    if action == "close":
        return native_close(h)
    return False


def work_area() -> tuple[int, int, int, int]:
    """屏幕可用区域（排除任务栏）。"""
    class _RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]

    r = _RECT()
    try:
        _u32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
        return r.l, r.t, r.r - r.l, r.b - r.t
    except Exception:  # noqa: BLE001
        return 0, 0, 1280, 800


def window_rect(h):
    class _RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]

    r = _RECT()
    _u32.GetWindowRect(h, ctypes.byref(r))
    return r.l, r.t, r.r - r.l, r.b - r.t


def set_window_rect(h, x: int, y: int, w: int, hgt: int) -> None:
    _u32.SetWindowPos(h, None, x, y, w, hgt, SWP_NOZORDER)


def toggle_maximize(h) -> bool:
    """自己实现最大化/还原：坐标算得准，来回切不漂移。"""
    x, y, w, hgt = window_rect(h)
    wx, wy, ww, wh = work_area()
    if abs(w - ww) <= 4 and abs(hgt - wh) <= 4:
        back = TOGGLE_MEMO.get("rect")
        if back:
            set_window_rect(h, *back)
        else:
            set_window_rect(h, wx, wy, max(980, ww // 3 * 2), max(640, wh // 3 * 2))
        TOGGLE_MEMO.pop("rect", None)
    else:
        TOGGLE_MEMO["rect"] = (x, y, w, hgt)
        set_window_rect(h, wx, wy, ww, wh)
    return True


TOGGLE_MEMO: dict = {}


# ---------------------------------------------------------------- pywebview 主路
_DRAG_SELECTOR = (".topbar, .topbar .brand, .topbar .brand-text, "
                  ".topbar .brand-text h1, .topbar .logo, .topbar .drag-zone")


def _run_pywebview(url: str) -> bool:
    try:
        import webview                      # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print(f"[shell] pywebview 不可用: {exc!r}", file=sys.stderr)
        return False

    # 拖动只认顶栏（否则输入框里拖选文字也会拽窗口）
    try:
        webview.settings["DRAG_REGION_SELECTOR"] = _DRAG_SELECTOR
        webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    except Exception:  # noqa: BLE001
        pass

    state = {"win": None, "max": False}

    def action(name: str) -> bool:
        win = state["win"]
        if win is None:
            return False
        try:
            if name == "minimize":
                # 优先走 Win32：Windows 自带的"缩到任务栏"动画
                h = find_window_by_title(APP_NAME)
                if h and native_minimize(h):
                    return True
                win.minimize()
                return True
            if name == "close":
                h = find_window_by_title(APP_NAME)
                if h and native_close(h):
                    return True
                win.destroy()
                return True
            if name in ("toggle_max", "restore"):
                h = find_window_by_title(APP_NAME)
                if h:
                    toggle_maximize(h)
                    state["max"] = not state["max"]
                    return True
                if name == "toggle_max":
                    if state["max"]:
                        win.restore()
                    else:
                        win.maximize()
                    state["max"] = not state["max"]
                    return True
                win.restore()
                state["max"] = False
                return True
        except Exception as exc:  # noqa: BLE001
            print(f"[shell] 窗口操作失败 {name}: {exc!r}", file=sys.stderr)
        return False

    from . import server as srv
    srv.WIN_HANDLER = action

    win = webview.create_window(
        APP_NAME, url,
        width=WIN_W, height=WIN_H,
        min_size=(980, 640),
        frameless=True,
        easy_drag=True,
        zoomable=False,
        text_select=False,
        background_color="#202020",
    )
    state["win"] = win

    def tune() -> None:
        # 补可缩放边框；Chromium/WinForms 偶尔重置样式，刷几次
        deadline = time.time() + 20
        while time.time() < deadline:
            if add_resize_border(APP_NAME):
                time.sleep(3)
                add_resize_border(APP_NAME)
                return
            time.sleep(0.3)

    def ensure_visible() -> None:
        """个别机器上 pywebview 建好窗口却没置 WS_VISIBLE（表现为双击没反应），兜底显式显示。"""
        if sys.platform != "win32":
            return
        for _ in range(60):
            h = find_window_by_title(APP_NAME)
            if h:
                try:
                    if not _u32.IsWindowVisible(h):
                        _u32.ShowWindow(h, SW_SHOW)
                except Exception:  # noqa: BLE001
                    pass
                break
            time.sleep(0.2)
        tune()

    def boot() -> None:
        threading.Thread(target=ensure_visible, daemon=True).start()

    webview.start(boot, private_mode=False, debug=False)
    srv.WIN_HANDLER = None
    # 窗口已关：WebView2 的清理偶尔会挂住，直接结束进程，避免"关掉了还在后台"
    try:
        srv.shutdown()
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)


# ---------------------------------------------------------------- Edge 退路
def _launch_edge(edge: str, url: str, profile: str):
    args = [
        edge, f"--app={url}", f"--window-size={WIN_W},{WIN_H}",
        f"--user-data-dir={profile}", "--no-first-run",
        "--no-default-browser-check", "--disable-extensions",
    ]
    try:
        return subprocess.Popen(args, close_fds=True)
    except Exception:  # noqa: BLE001
        return None


def _run_edge(url: str) -> None:
    edge = find_edge()
    proc = _launch_edge(edge, url, profile_dir()) if edge else None

    t0 = time.time()
    while time.time() - t0 < 20 and not STATE["ever"]:
        time.sleep(0.4)
    if not STATE["ever"]:
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        alt = profile_dir() + "-" + uuid.uuid4().hex[:6]
        proc = _launch_edge(edge, url, alt) if edge else None
        t1 = time.time()
        while time.time() - t1 < 20 and not STATE["ever"]:
            time.sleep(0.4)
    if not STATE["ever"]:
        webbrowser.open(url)

    from . import server as srv
    srv.WIN_HANDLER = lambda a: win32_action(APP_NAME, a)

    def frame_worker() -> None:
        while True:
            make_frameless(APP_NAME)
            time.sleep(1.0)

    threading.Thread(target=frame_worker, daemon=True).start()

    gone_since = None
    while True:
        time.sleep(0.6)
        if STATE["ever"] and STATE["clients"] == 0:
            gone_since = gone_since or time.time()
            if time.time() - gone_since > 6:
                break
        else:
            gone_since = None
    try:
        if proc is not None and proc.poll() is None:
            proc.terminate()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 入口
def main() -> None:
    token = uuid.uuid4().hex
    httpd, backend, port = make_server(token)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/?t={token}"

    backend.log(f"{APP_NAME} v{VERSION} 启动中…")
    ok = False
    try:
        ok = _run_pywebview(url)
    except Exception as exc:  # noqa: BLE001
        print(f"[shell] pywebview 启动失败: {exc!r}", file=sys.stderr)
        ok = False
    if not ok:
        backend.log("WebView2 窗口没起来，改用 Edge 应用窗口", "warn")
        _run_edge(url)

    try:
        httpd.shutdown()
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)

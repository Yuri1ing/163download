# -*- coding: utf-8 -*-
"""关窗淡出：截下窗口最后一帧，用一个分层窗口在屏幕上把它由不透明渐隐到透明。

为什么不用 UpdateLayeredWindow 的 per-pixel alpha：那条路 alpha 无法回读、
也无法确认真的在渐变。这里用最老实的做法——WS_EX_LAYERED + 
SetLayeredWindowAttributes(LWA_ALPHA)，每一帧的 alpha 都能 GetLayeredWindowAttributes 读回来核对。

为什么必须"截屏"：WebView2 把网页画在自己的子窗口里，父窗口加 WS_EX_LAYERED
或 AlphaBlend 都作用不到子窗口像素，直接改父窗口 alpha 会「瞬间消失」
（这正是用户反馈的问题）。把最后一帧搬到我们自己的窗口里，才能任意调透明度。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32
k32 = ctypes.windll.kernel32

SRCCOPY = 0x00CC0020
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_CLOSE = 0x0010
LWA_ALPHA = 0x00000002
SW_SHOWNA = 8
SW_HIDE = 0
DIB_RGB_COLORS = 0


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", wt.RECT),
                ("fRestore", wt.BOOL), ("fIncUpdate", wt.BOOL),
                ("rgbReserved", ctypes.c_ubyte * 32)]


u32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
u32.CreateWindowExW.restype = wt.HWND
u32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.DefWindowProcW.restype = ctypes.c_ssize_t
u32.RegisterClassW.argtypes = [ctypes.c_void_p]
u32.RegisterClassW.restype = wt.ATOM
u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u32.GetWindowRect.restype = wt.BOOL
u32.LoadCursorW.argtypes = [wt.HINSTANCE, wt.LPVOID]
u32.LoadCursorW.restype = wt.HANDLE
u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
u32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.COLORREF, ctypes.c_ubyte, wt.DWORD]
u32.GetLayeredWindowAttributes.argtypes = [wt.HWND, ctypes.POINTER(wt.COLORREF),
                                           ctypes.POINTER(ctypes.c_ubyte),
                                           ctypes.POINTER(wt.DWORD)]
u32.BeginPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
u32.BeginPaint.restype = wt.HDC
u32.EndPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

_state: dict[str, object] = {}


def _wndproc(hwnd, msg, wparam, lparam):
    if msg == WM_PAINT:
        ps = PAINTSTRUCT()
        hdc = u32.BeginPaint(hwnd, ctypes.byref(ps))
        memdc = _state.get("memdc")
        if memdc:
            g32.BitBlt(hdc, 0, 0, _state["w"], _state["h"], memdc, 0, 0, SRCCOPY)
        u32.EndPaint(hwnd, ctypes.byref(ps))
        return 0
    if msg == WM_ERASEBKGND:
        return 1
    return u32.DefWindowProcW(hwnd, msg, wparam, lparam)


_proc_ref = WNDPROC(_wndproc)
_state["proc"] = _proc_ref          # 必须保住引用，否则回调被 GC


def _overlay_class() -> str:
    name = "NcmFadeOverlay2"
    wc = WNDCLASSW()
    wc.lpfnWndProc = ctypes.cast(_proc_ref, ctypes.c_void_p)
    wc.hInstance = k32.GetModuleHandleW(None)
    wc.lpszClassName = name
    wc.hCursor = u32.LoadCursorW(None, 32512)
    if not u32.RegisterClassW(ctypes.byref(wc)):
        err = k32.GetLastError()
        if err not in (0, 1410):
            raise ctypes.WinError(err)
    return name


def _capture(rect) -> tuple:
    """把屏幕上的窗口区域拷进内存 DC，返回 (memdc, bitmap)。"""
    x, y, w, h = rect
    screen = u32.GetDC(0)
    memdc = g32.CreateCompatibleDC(screen)
    bmp = g32.CreateCompatibleBitmap(screen, w, h)
    g32.SelectObject(memdc, bmp)
    g32.BitBlt(memdc, 0, 0, w, h, screen, x, y, SRCCOPY)
    u32.ReleaseDC(0, screen)
    return memdc, bmp


def fade_and_close(hwnd: int, steps: int = 12, interval_ms: int = 18) -> bool:
    """先截帧、遮住原窗口，再逐级降 alpha，最后真的关窗。"""
    rect = wt.RECT()
    if not u32.GetWindowRect(hwnd, ctypes.byref(rect)):
        u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return False
    x, y = rect.left, rect.top
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return False

    memdc, bmp = _capture((x, y, w, h))
    _state.update(memdc=memdc, w=w, h=h)
    debug = bool(int(os.environ.get("NCM_FADE_DEBUG", "0") or 0))

    overlay = 0
    try:
        cls = _overlay_class()
        overlay = u32.CreateWindowExW(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                                      | WS_EX_TOPMOST, cls, "", WS_POPUP | 0x02000000,
                                      x, y, w, h, None, None,
                                      k32.GetModuleHandleW(None), None)
        if not overlay:
            raise ctypes.WinError(k32.GetLastError())

        u32.SetLayeredWindowAttributes(overlay, 0, 255, LWA_ALPHA)
        u32.ShowWindow(overlay, SW_SHOWNA)
        u32.InvalidateRect(overlay, None, True)
        u32.UpdateWindow(overlay)
        # 原窗口立刻藏起来，用户看到的已经是这张"截图"
        u32.ShowWindow(hwnd, SW_HIDE)

        # ease-out：前段慢、后段快自然收尾，视觉上更接近系统淡出
        alphas = [round(255 * (1 - i / steps) ** 1.3) for i in range(steps + 1)]
        for a in alphas:
            u32.SetLayeredWindowAttributes(overlay, 0, max(0, min(255, a)), LWA_ALPHA)
            if debug:
                key = wt.COLORREF()
                got = ctypes.c_ubyte()
                flags = wt.DWORD()
                u32.GetLayeredWindowAttributes(overlay, ctypes.byref(key),
                                               ctypes.byref(got), ctypes.byref(flags))
                print(f"[fade] set={a} actual={got.value} flags={flags.value}", flush=True)
            time.sleep(interval_ms / 1000)
    except Exception as exc:  # noqa: BLE001
        if debug:
            print(f"[fade] overlay 失败，直接关窗：{exc}", flush=True)
    finally:
        if overlay:
            u32.DestroyWindow(overlay)
        g32.DeleteObject(bmp)
        g32.DeleteDC(memdc)
        _state.clear()
        _state["proc"] = _proc_ref
        u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return True

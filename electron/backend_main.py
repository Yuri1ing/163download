# -*- coding: utf-8 -*-
"""Electron sidecar 入口：起本地 HTTP 后端，把端口打到 stdout 让 Electron 接。

协议很简单：启动后第一行输出 {"port": 12345, "token": "..."} ，之后就是普通服务。
token 由 Electron 生成并通过环境变量 NCM_TOKEN 传进来（防止本机其它程序乱调）。
"""
import json
import os
import sys
import threading
import time


def _watch_parent(ppid: int) -> None:
    """父进程（Electron）没了就自杀，避免 PyInstaller 子进程变野进程。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, int(ppid))  # QUERY_LIMITED_INFORMATION
        if not handle:
            return
        while True:
            time.sleep(2)
            code = ctypes.c_ulong(0)
            ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
            if not ok or code.value != 259:  # 259 = STILL_ACTIVE
                os._exit(0)
    except Exception:  # noqa: BLE001
        return


def main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from ncm.server import make_server  # noqa: E402

    ppid = os.environ.get("NCM_PARENT_PID")
    if ppid and ppid.isdigit():
        threading.Thread(target=_watch_parent, args=(int(ppid),), daemon=True).start()

    token = os.environ.get("NCM_TOKEN", "")
    httpd, _backend, port = make_server(token)
    sys.stdout.write(json.dumps({"port": port, "token": token}) + "\n")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

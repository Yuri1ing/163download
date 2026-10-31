# -*- coding: utf-8 -*-
"""把 tools/gen_icon.ps1 渲染出的 PNGS 组装成多尺寸 .ico。

流程：
    powershell tools\\gen_icon.ps1     # GDI+ 渲染 build\\icon\\i*.png
    python tools\\gen_icon.py          # 组装 build\\ncm.ico + ncm\\web\\favicon.ico
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "build", "icon")
SIZES = [256, 128, 64, 48, 32, 24, 16]


def build_ico(pairs, out_ico):
    """pairs: [(size, png_bytes)] 由大到小；ICO 内直接存 PNG（Vista+ 支持）。"""
    count = len(pairs)
    header = struct.pack("<HHH", 0, 1, count)
    entries, blobs = b"", b""
    offset = 6 + 16 * count
    for size, data in pairs:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    with open(out_ico, "wb") as fh:
        fh.write(header + entries + blobs)


def main() -> int:
    pairs = []
    for size in SIZES:
        path = os.path.join(SRC, f"i{size}.png")
        if not os.path.exists(path):
            print(f"[!] 缺少 {size}px，先跑 tools/gen_icon.ps1")
            continue
        with open(path, "rb") as fh:
            pairs.append((size, fh.read()))
    if not pairs:
        return 1

    exe_ico = os.path.join(ROOT, "build", "ncm.ico")
    web_ico = os.path.join(ROOT, "ncm", "web", "favicon.ico")
    build_ico(pairs, exe_ico)
    build_ico([p for p in pairs if p[0] <= 64], web_ico)
    print(f"[+] exe 图标 {exe_ico} ({os.path.getsize(exe_ico)}B)")
    print(f"[+] web 图标 {web_ico} ({os.path.getsize(web_ico)}B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

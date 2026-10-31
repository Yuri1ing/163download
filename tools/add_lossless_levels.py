# -*- coding: utf-8 -*-
"""把「无损 FLAC」「Hi-Res」两档加回音质选项，并让文件格式校验按档位自适应。"""
import io
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))


def patch(path, old, new, tag=""):
    p = os.path.join(ROOT, path)
    s = io.open(p, encoding="utf-8").read()
    if old not in s:
        if new.strip() and new.strip() in s:
            print(f"[skip] {path} {tag} 已改过")
            return
        raise SystemExit(f"[fail] {path} 锚点缺失 [{tag}]:\n{old[:160]}")
    io.open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
    print(f"[ok] {path} {tag}")


# ---------------------------------------------------------------- api.py 档位
patch(
    "ncm/api.py",
    '''    "exhigh":   {"label": "极高 320kbps", "encode": "mp3", "br": 320000, "kbps": 320, "ext": ".mp3"},
}

# 老配置/外部传进来的无损档位统一折算成 320k MP3（本工具只产出 MP3）
LEGACY_LEVELS = {"lossless": "exhigh", "hires": "exhigh"}


def normalize_level(level: str) -> str:
    """把任意档位收敛到我们支持的 MP3 档位，非法值退回 exhigh。"""
    if level in LEVELS:
        return level
    return LEGACY_LEVELS.get(level or "", "exhigh")''',
    '''    "exhigh":   {"label": "极高 320kbps", "encode": "mp3", "br": 320000, "kbps": 320, "ext": ".mp3"},
    "lossless": {"label": "无损 FLAC", "encode": "flac", "br": 999000, "kbps": 1000, "ext": ".flac"},
    "hires":    {"label": "Hi-Res", "encode": "flac", "br": 1900000, "kbps": 1900, "ext": ".flac"},
}

# 只做兜底：真的不认识的档位才退回 320k MP3
LEGACY_LEVELS: Dict[str, str] = {}


def normalize_level(level: str) -> str:
    """非法/未知档位退回 exhigh；无损与 Hi-Res 都是一等公民。"""
    if level in LEVELS:
        return level
    return LEGACY_LEVELS.get(level or "", "exhigh")


def level_ext(level: str) -> str:
    """该档位期望的落盘扩展名（.mp3 / .flac）。"""
    return LEVELS[normalize_level(level)]["ext"]


def level_want(level: str) -> str:
    """该档位期望的真实格式（mp3 / flac），用于文件头校验。"""
    return LEVELS[normalize_level(level)]["encode"]''',
    "level-table",
)

# ---------------------------------------------------------------- core.py 落盘扩展名 + 校验
patch(
    "ncm/core.py",
    "from .api import LEVELS, NeteaseAPI, normalize_level, track_from_song",
    "from .api import LEVELS, NeteaseAPI, level_ext, level_want, normalize_level, track_from_song",
    "import",
)

patch(
    "ncm/core.py",
    '            final_path = os.path.join(base_dir, stem + ".mp3")',
    '            final_path = os.path.join(base_dir, stem + level_ext(s.level))',
    "ext",
)

patch(
    "ncm/core.py",
    """            got = self._download(url, final_path, track, src)
            if got and s.strict_mp3:
                real = sniff_audio(final_path)
                if real and real != "mp3":
                    self.on_event("notice", {
                        "track": track,
                        "text": f"接口给的是 {real.upper()}（不是 MP3），换源重取…"})""",
    """            got = self._download(url, final_path, track, src)
            want = level_want(s.level)
            if got and s.strict_mp3:
                real = sniff_audio(final_path)
                if real and real != want:
                    self.on_event("notice", {
                        "track": track,
                        "text": (f"接口给的是 {real.upper()}，与所选音质要求的 "
                                 f"{want.upper()} 不符，换源重取…")})""",
    "strict",
)

patch(
    "ncm/core.py",
    """            if got:
                real = sniff_audio(final_path)
                if real and real != "mp3":
                    # 关了严格校验：按真实格式改名，避免「扩展名 mp3 其实是 flac」""",
    """            if got:
                real = sniff_audio(final_path)
                if real and real != want:
                    # 关了严格校验：按真实格式改名，避免「扩展名 mp3 其实是 flac」""",
    "rename",
)

# 兜底源那一步也按档位判断
patch(
    "ncm/core.py",
    """                real2 = sniff_audio(p2)
                if s.strict_mp3 and real2 and real2 != "mp3":""",
    """                real2 = sniff_audio(p2)
                if s.strict_mp3 and real2 and real2 != level_want(s.level):""",
    "fallback",
)

# ---------------------------------------------------------------- 前端档位按钮
patch(
    "ncm/web/index.html",
    '''      <div class="segmented" id="levelSeg" title="只输出 MP3">
        <button data-level="standard">标准 128k</button>
        <button data-level="higher">较高 192k</button>
        <button data-level="exhigh" class="on">极高 320k</button>
      </div>''',
    '''      <div class="segmented" id="levelSeg" title="音质（无损 / Hi-Res 需要会员 Cookie）">
        <button data-level="standard">标准 128k</button>
        <button data-level="higher">较高 192k</button>
        <button data-level="exhigh" class="on">极高 320k</button>
        <button data-level="lossless">无损 FLAC</button>
        <button data-level="hires">Hi-Res</button>
      </div>''',
    "seg",
)

patch(
    "ncm/web/index.html",
    '<label class="switch"><input type="checkbox" id="setStrictMp3" checked /><span class="track"></span><span class="switch-label">只收 MP3（校验）</span></label>',
    '<label class="switch"><input type="checkbox" id="setStrictMp3" checked /><span class="track"></span><span class="switch-label">文件格式校验</span></label>',
    "toggle",
)

patch(
    "ncm/web/index.html",
    '<p class="hint">开启后落盘会读文件头校验，接口若偷偷给 FLAC/M4A 会自动换源重取。</p>',
    '<p class="hint">开启后落盘会读文件头校验：选 MP3 档就要求真是 MP3，选无损 / Hi-Res 就要求真是 FLAC，不符自动换源重取。</p>',
    "hint",
)

# ---------------------------------------------------------------- 前端体积估算 & 文案
patch(
    "ncm/web/app.js",
    "  const KBPS = { standard: 128, higher: 192, exhigh: 320 };",
    "  const KBPS = { standard: 128, higher: 192, exhigh: 320, lossless: 1000, hires: 1900 };\n"
    "  const LEVEL_LABEL = { standard: \"标准 128kbps\", higher: \"较高 192kbps\", exhigh: \"极高 320kbps\",\n"
    "                        lossless: \"无损 FLAC\", hires: \"Hi-Res\" };",
    "kbps",
)

patch(
    "ncm/web/app.js",
    '    log(`就绪 · 音质 ${({standard:"标准 128k",higher:"较高 192k",exhigh:"极高 320k"})[settings.level] || "极高 320k"} · 仅 MP3 · 保存到 ${settings.save_dir}`);',
    '    log(`就绪 · 音质 ${LEVEL_LABEL[settings.level] || "极高 320kbps"} · 保存到 ${settings.save_dir}`);',
    "log",
)

print("done")

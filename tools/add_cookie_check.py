# -*- coding: utf-8 -*-
"""给「网易云下载器」加 Cookie 校验功能：后端 check_cookie + 前端「检测」按钮。"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if len(sys.argv) > 1:
    ROOT = sys.argv[1]


def patch(path, old, new, count=1):
    p = os.path.join(ROOT, path)
    s = io.open(p, encoding="utf-8").read()
    if new.strip() and new.strip() in s:
        print(f"[skip] {path} 已改过")
        return
    if old not in s:
        raise SystemExit(f"[fail] {path} 找不到锚点:\n{old[:120]}")
    s = s.replace(old, new, count)
    io.open(p, "w", encoding="utf-8").write(s)
    print(f"[ok] {path}")


# ---------------------------------------------------------------- 后端
patch(
    "ncm/server.py",
    """    # ---------------------------------------------------------- 解析
    def parse(self, text: str) -> dict:""",
    '''    # ---------------------------------------------------------- Cookie 校验
    def check_cookie(self, cookie: str = "") -> dict:
        """校验 Cookie 是否有效：返回昵称/UID/VIP 等级，失败给出原因。"""
        raw = (cookie if cookie is not None else "").strip() or (self.settings.cookie or "").strip()
        if not raw:
            return {"ok": False, "reason": "empty", "message": "还没填 Cookie"}
        from .api import Api  # 局部导入，避免循环依赖

        try:
            prof = Api(cookie=raw).check_cookie()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": "error", "message": f"检测出错：{exc}"}
        if not prof:
            return {"ok": False, "reason": "invalid",
                    "message": "Cookie 无效或已过期（请重新登录网易云复制）"}
        vip = int(prof.get("vipType") or 0)
        return {
            "ok": True,
            "message": "Cookie 有效",
            "nickname": prof.get("nickname") or "(未命名)",
            "userId": prof.get("userId"),
            "vipType": vip,
            "vipLabel": {0: "普通账号", 10: "黑胶VIP", 11: "黑胶VIP"}.get(vip, f"VIP{vip}"),
            "avatar": prof.get("avatarUrl") or "",
            "level": prof.get("level"),
        }

    # ---------------------------------------------------------- 解析
    def parse(self, text: str) -> dict:''',
)

# ---------------------------------------------------------------- 前端 HTML
patch(
    "ncm/web/index.html",
    """      <label class="field">
        <span>Cookie（可选）</span>
        <textarea id="setCookie" rows="3" placeholder="MUSIC_U=...&__csrf=..."></textarea>
        <small>填了用自己账号的合法权限下载（私密歌单也必须填）；留空即匿名模式。</small>
      </label>""",
    """      <label class="field">
        <span>Cookie（可选）</span>
        <textarea id="setCookie" rows="3" placeholder="MUSIC_U=...&__csrf=..."></textarea>
        <div class="cookie-row">
          <button class="chip tiny" id="btnCheckCookie" type="button">检测 Cookie</button>
          <span class="cookie-state" id="cookieState"></span>
        </div>
        <small>填了用自己账号的合法权限下载（私密歌单也必须填）；留空即匿名模式。</small>
      </label>""",
)

# ---------------------------------------------------------------- 前端 JS
patch(
    "ncm/web/app.js",
    """    set_setting: (key, value) => call("set_setting", { key, value }),""",
    """    set_setting: (key, value) => call("set_setting", { key, value }),
    check_cookie: (cookie) => call("check_cookie", { cookie }),""",
)

patch(
    "ncm/web/app.js",
    """  function openDrawer(on) {""",
    '''  /* ------------------------------------------------------------ Cookie 校验 */
  function showCookieState(res) {
    const el = $("cookieState");
    if (!el) return;
    if (!res) { el.textContent = ""; el.className = "cookie-state"; return; }
    if (res.ok) {
      el.className = "cookie-state ok";
      el.textContent = `✔ ${res.nickname} · UID ${res.userId} · ${res.vipLabel}`;
      $("statusText").textContent = "已登录（Cookie）";
      $("status").classList.add("paid");
    } else {
      el.className = "cookie-state bad";
      el.textContent = `✘ ${res.message}`;
      if (res.reason === "invalid" || res.reason === "empty") {
        $("statusText").textContent = "匿名模式";
        $("status").classList.remove("paid");
      }
    }
  }

  async function checkCookie(announce) {
    const btn = $("btnCheckCookie");
    const raw = ($("setCookie").value || "").trim();
    if (btn) { btn.disabled = true; btn.textContent = "检测中…"; }
    if (!raw && announce) log("Cookie 为空，当前是匿名模式", "warn");
    try {
      const res = await api.check_cookie(raw);
      showCookieState(res);
      if (announce) log(res.ok ? `Cookie 有效：${res.nickname}（UID ${res.userId} · ${res.vipLabel}）`
                               : `Cookie 检测失败：${res.message}`, res.ok ? "ok" : "warn");
    } catch (e) {
      showCookieState({ ok: false, message: String(e) });
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "检测 Cookie"; }
    }
  }

  function openDrawer(on) {''',
)

patch(
    "ncm/web/app.js",
    """    $("setCookie").value = settings.cookie || "";""",
    """    $("setCookie").value = settings.cookie || "";
    showCookieState(null);
    if ((settings.cookie || "").trim()) checkCookie(false);""",
)

# 绑定按钮 + 保存时顺便校验
patch(
    "ncm/web/app.js",
    """  $("btnSettings").onclick""",
    """  $("btnCheckCookie").onclick = () => checkCookie(true);
  $("btnSettings").onclick""",
)

# ---------------------------------------------------------------- 样式
patch(
    "ncm/web/style.css",
    """.field small { font-size: 11px; color: var(--fg-mute); line-height: 1.55; }""",
    """.field small { font-size: 11px; color: var(--fg-mute); line-height: 1.55; }
.cookie-row { display: flex; align-items: center; gap: 8px; margin: 2px 0 4px; flex-wrap: wrap; }
.cookie-row .chip.tiny { cursor: pointer; }
.cookie-row .chip.tiny:disabled { opacity: .55; cursor: default; }
.cookie-state { font-size: 11.5px; line-height: 1.5; word-break: break-all; }
.cookie-state.ok { color: #3fd18b; }
.cookie-state.bad { color: #ff8a80; }""",
)

print("done")

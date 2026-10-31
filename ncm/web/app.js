/* 前端逻辑：与本地 Python 后端（HTTP + SSE）交互 */
(() => {
  "use strict";

  /* ------------------------------------------------------------ 后端桥 */
  const TOKEN = new URLSearchParams(location.search).get("t") || "";

  async function call(name, body) {
    const res = await fetch(`/api/${name}?t=${encodeURIComponent(TOKEN)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Token": TOKEN },
      body: JSON.stringify(body === undefined ? {} : body),
    });
    if (!res.ok) throw new Error(`${name} ${res.status}`);
    return res.json();
  }

  const api = {
    ready: () => call("ready"),
    parse: (text) => call("parse", { text }),
    download: (uids) => call("download", { uids }),
    stop: () => call("stop"),
    set_setting: (key, value) => call("set_setting", { key, value }),
    check_cookie: (cookie) => call("check_cookie", { cookie }),
    save_settings: (patch) => call("save_settings", { patch }),
    open_dir: () => call("open_dir"),
    open_url: (url) => call("open_url", { url }),
    pick_dir: () => call("pick_dir"),
    win: (action) => call("win", { action }),
  };

  function connectEvents() {
    let es = null;
    const open = () => {
      es = new EventSource(`/api/events?t=${encodeURIComponent(TOKEN)}`);
      es.onmessage = (e) => {
        try { window.__ev(JSON.parse(e.data)); } catch (_) { /* 忽略坏包 */ }
      };
      es.onerror = () => { /* EventSource 自己会重连 */ };
    };
    open();
  }

  const $ = (id) => document.getElementById(id);
  const listEl = $("list");
  const emptyEl = $("empty");

  let tracks = [];            // 全量
  let rows = new Map();       // uid -> {el, pill}
  let selected = new Set();
  let settings = null;
  let running = false;
  let parsed = 0;

  /* ------------------------------------------------------------ 工具 */
  const fmtDur = (ms) => {
    const s = Math.round((ms || 0) / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  const fmtSize = (n) => {
    if (!n) return "";
    const u = ["B", "KB", "MB", "GB"];
    let i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v >= 100 ? 0 : 1)}${u[i]}`;
  };

  /* 按当前音质估算 MP3 体积：CBR 码率 × 时长（接口只回码率，不回体积） */
  const KBPS = { standard: 128, higher: 192, exhigh: 320, lossless: 1000, hires: 1900 };
  const LEVEL_LABEL = { standard: "标准 128kbps", higher: "较高 192kbps", exhigh: "极高 320kbps",
                        lossless: "无损 FLAC", hires: "Hi-Res" };
  const estSize = (t) => {
    const kbps = KBPS[(settings && settings.level) || "exhigh"] || 320;
    const secs = (t.duration || 0) / 1000;
    if (!secs) return "";
    return fmtSize((secs * kbps * 1000) / 8);
  };
  function refreshSizes() {
    rows.forEach(({ el, t }) => {
      if (t._realSize) return;              // 已下载完，保留实际体积
      const cell = el.querySelector(".size");
      if (cell) cell.textContent = estSize(t);
    });
  }

  function toast(msg, kind = "") {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = msg;
    $("toasts").appendChild(el);
    setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 320); }, 3200);
  }

  function log(msg, kind = "") {
    const box = $("log");
    const t = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    const div = document.createElement("div");
    div.innerHTML = `<span class="t">${t}</span><span class="${kind}"></span>`;
    div.lastChild.textContent = msg;
    box.appendChild(div);
    while (box.childElementCount > 400) box.firstElementChild.remove();
    box.scrollTop = box.scrollHeight;
  }

  const FEE = {
    0: { text: "免费", cls: "" },
    1: { text: "VIP", cls: "vip" },
    4: { text: "付费专辑", cls: "vip" },
    8: { text: "低质免费", cls: "vip" },
  };

  function feeOf(t) {
    if (t.fee === null || t.fee === undefined) return { text: "—", cls: "" };
    return FEE[t.fee] || { text: "受限", cls: "none" };
  }

  /* ------------------------------------------------------------ 渲染 */
  function updateCount() {
    $("count").textContent = `共 ${tracks.length} 首 · 已选 ${selected.size} 首`;
  }

  function makeRow(t, idx) {
    const el = document.createElement("div");
    el.className = "row";
    el.dataset.uid = t.uid;

    const fee = feeOf(t);
    el.innerHTML = `
      <div class="c sel"><span class="cbx"><svg viewBox="0 0 24 24"><path d="M4 12.5 9.5 18 20 6.5" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span></div>
      <div class="c idx">${idx}</div>
      <div class="c title"><img class="cover" loading="lazy" src="${t.cover || ""}" alt="" onerror="this.style.visibility='hidden'"><span class="name"></span></div>
      <div class="c artist"></div>
      <div class="c album"></div>
      <div class="c dur">${fmtDur(t.duration)}</div>
      <div class="c size">${estSize(t)}</div>
      <div class="c feecell"><span class="fee ${fee.cls}">${fee.text}</span></div>
      <div class="c statuscell"><span class="pill">待下载</span></div>`;

    el.querySelector(".name").textContent = t.title || "";
    el.querySelector(".artist").textContent = t.artist || "";
    el.querySelector(".album").textContent = t.album || "";

    const pill = el.querySelector(".pill");
    el.querySelector(".sel").addEventListener("click", (e) => {
      e.stopPropagation();
      toggle(t.uid);
    });
    el.addEventListener("dblclick", () => {
      if (!t.id) return;
      // 双击：打开该曲在网易云的页面（在系统浏览器里）
      api.open_url(`https://music.163.com/song?id=${t.id}`);
    });
    rows.set(t.uid, { el, pill, t });
    return el;
  }

  function renderAll() {
    listEl.innerHTML = "";
    rows.clear();
    if (!tracks.length) {
      listEl.appendChild(emptyEl);
      updateCount();
      return;
    }
    const frag = document.createDocumentFragment();
    tracks.forEach((t, i) => frag.appendChild(makeRow(t, i + 1)));
    listEl.appendChild(frag);
    listEl.scrollTop = 0;
    updateCount();
  }

  function appendTracks(list) {
    if (!list || !list.length) return;
    const wasEmpty = tracks.length === 0;
    if (wasEmpty) listEl.innerHTML = "";
    const frag = document.createDocumentFragment();
    const start = tracks.length;
    list.forEach((t, i) => {
      tracks.push(t);
      selected.add(t.uid);
      const row = makeRow(t, start + i + 1);
      row.classList.add("sel");
      frag.appendChild(row);
    });
    listEl.appendChild(frag);
    updateCount();
  }

  function toggle(uid, force) {
    const rec = rows.get(uid);
    if (!rec) return;
    const on = force === undefined ? !selected.has(uid) : force;
    if (on) { selected.add(uid); rec.el.classList.add("sel"); }
    else { selected.delete(uid); rec.el.classList.remove("sel"); }
    updateCount();
  }

  function setPill(uid, text, kind) {
    const rec = rows.get(uid);
    if (!rec) return;
    rec.pill.textContent = text;
    rec.pill.className = `pill ${kind || ""}`;
  }

  function setCell(uid, key, text) {
    const rec = rows.get(uid);
    if (!rec) return;
    const el = rec.el.querySelector(`.${key}`);
    if (el) el.textContent = text;
  }

  /* ------------------------------------------------------------ 后端事件 */
  window.__ev = (msg) => {
    switch (msg.type) {
      case "ready":
        settings = msg.settings;
        applySettings();
        break;

      case "parse_start":
        $("btnParse").disabled = true;
        $("btnParse").querySelector("span").textContent = "解析中…";
        parsed = 0;
        break;

      case "tracks":
        appendTracks(msg.list);
        parsed += msg.list.length;
        break;

      case "parse_done":
        $("btnParse").disabled = false;
        $("btnParse").querySelector("span").textContent = "解析 / 搜索";
        if (msg.added) toast(`解析到 ${msg.added} 首`, "ok");
        else toast("没解析到歌曲", "warn");
        $("statusText").textContent = settings && settings.cookie ? "已登录（Cookie）" : "匿名模式";
        break;

      case "log":
        log(msg.msg, msg.kind);
        break;

      case "toast":
        toast(msg.msg, msg.kind);
        break;

      case "start":
        setPill(msg.uid, "下载中", "dl");
        break;

      case "done": {
        const rec = rows.get(msg.uid);
        if (rec) {
          rec.t._realSize = msg.size || 0;
          const cell = rec.el.querySelector(".size");
          if (cell && msg.size) cell.textContent = fmtSize(msg.size);
        }
        const fmt = msg.fmt || "MP3";
        setPill(msg.uid, fmt === "MP3"
          ? `完成 ${fmtSize(msg.size)}`
          : `完成 ${fmtSize(msg.size)}·${fmt}`, "ok");
        if (msg.src && msg.src !== "网易云") setCell(msg.uid, "album", `（源：${msg.src}）`);
        break;
      }

      case "skipped":
        setPill(msg.uid, "已存在", "skip");
        break;

      case "failed":
        setPill(msg.uid, "失败", "err");
        break;

      case "notice":
        setPill(msg.uid, "换源中", "skip");
        log(msg.text, "warn");
        break;

      case "progress":
        renderProgress(msg);
        $("speed").textContent = msg.speed ? `${fmtSize(msg.speed)}/s` : "";
        break;

      case "finished":
        running = false;
        $("btnStart").disabled = false;
        $("btnStop").disabled = true;
        renderProgress(msg);
        toast(`完成 ${msg.done} 首${msg.failed ? `，失败 ${msg.failed}` : ""}${msg.skipped ? `，跳过 ${msg.skipped}` : ""}`,
              msg.failed ? "warn" : "ok");
        log(`本次结束：成功 ${msg.done}，失败 ${msg.failed}，跳过 ${msg.skipped}`, msg.failed ? "warn" : "ok");
        break;

      case "dir":
        settings.save_dir = msg.path;
        $("setDir").value = msg.path;
        break;

      case "open_dir_done":
        break;
    }
  };

  /* ------------------------------------------------------------ 设置 */
  function applySettings() {
    $("setDir").value = settings.save_dir;
    $("setTpl").value = settings.template;
    $("setThreads").value = settings.concurrency;
    $("ccVal").textContent = settings.concurrency;
    $("setCover").checked = !!settings.write_cover;
    $("setLyric").checked = !!settings.write_lyric;
    $("setSkip").checked = !!settings.skip_existing;
    $("setOrganize").checked = !!settings.organize;
    $("setStrictMp3").checked = settings.strict_mp3 !== false;
    $("setCookie").value = settings.cookie || "";
    showCookieState(null);
    if ((settings.cookie || "").trim()) checkCookie(false);
    $("fallback").checked = !!settings.fallback_enabled;
    document.querySelectorAll("#levelSeg button").forEach((b) => {
      b.classList.toggle("on", b.dataset.level === settings.level);
    });
    $("statusText").textContent = settings.cookie ? "已登录（Cookie）" : "匿名模式";
    $("status").classList.toggle("paid", !!settings.cookie);
    log(`就绪 · 音质 ${LEVEL_LABEL[settings.level] || "极高 320kbps"} · 保存到 ${settings.save_dir}`);
  }

  /* 进度条按「首」计算：已下载（含失败/跳过） / 总首数 */
  function renderProgress(msg) {
    const total = msg.total || 0;
    const done = progDone(msg);
    const pct = total ? Math.min(100, (done / total) * 100) : 0;
    $("bar").style.width = `${pct}%`;
    $("progText").textContent = `已下载 ${done} / ${total} 首`;
    const left = Math.max(0, total - done);
    $("progText").title = `已下载 ${msg.done || 0} 首 · 失败 ${msg.failed || 0} 首 · 跳过 ${msg.skipped || 0} 首 · 剩余 ${left} 首`;
  }

  // 后端 progress 事件里的 skipped 字段可能缺省，直接相加会出 NaN
  function progDone(msg) {
    return (msg.done || 0) + (msg.failed || 0) + (msg.skipped || 0);
  }

  /* ------------------------------------------------------------ Cookie 校验 */
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

  /* 选了无损/Hi-Res 但没填 Cookie 时提醒一句（不影响使用，会自动降级） */
  function hintLevelQuality() {
    const lv = (settings && settings.level) || "exhigh";
    if ((lv === "lossless" || lv === "hires") && !(settings && (settings.cookie || "").trim())) {
      log(`${LEVEL_LABEL[lv]} 需要会员 Cookie，当前匿名模式会自动降级为 320k MP3`, "warn");
    }
  }

  function openDrawer(on) {
    $("drawer").classList.toggle("open", on);
    $("scrim").classList.toggle("on", on);
  }

  /* ------------------------------------------------------------ 窗口（无系统标题栏） */
  // 在 Electron / WebView2(pywebview) 里窗口拖动由外壳接管（CSS app-region / easy_drag），
  // 页面里再调 window.moveTo 会跟它打架，所以只给 Edge 退路保留脚本拖动。
  const IS_ELECTRON = !!(window.ncmWin && window.ncmWin.isElectron);
  const NATIVE_DRAG = IS_ELECTRON
    || !!(window.pywebview && window.pywebview.platform === "edgechromium");

  // 窗口动作：Electron 走 IPC，其余走本地后端的 Win32 实现
  function winAction(name) {
    if (IS_ELECTRON) {
      const map = { minimize: "minimize", close: "close", toggle_max: "toggleMax" };
      const fn = window.ncmWin[map[name]];
      if (typeof fn === "function") { fn(); return; }
    }
    api.win(name);
  }

  function bindWindow() {
    const bar = $("topbar");
    let dragging = false, sx = 0, sy = 0, wx = 0, wy = 0;

    bar.addEventListener("mousedown", (e) => {
      if (NATIVE_DRAG) return;
      if (e.button !== 0) return;
      if (e.target.closest("button, input, .win-ctrls, .top-actions")) return;
      dragging = true;
      sx = e.screenX; sy = e.screenY;
      wx = window.screenX; wy = window.screenY;
      bar.style.cursor = "grabbing";
      e.preventDefault();
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      window.moveTo(wx + (e.screenX - sx), wy + (e.screenY - sy));
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
      bar.style.cursor = "";
    });
    // 双击顶栏：最大化/还原（用后端 Win32 / 窗口对象调用）
    bar.addEventListener("dblclick", (e) => {
      if (e.target.closest("button, input, .top-actions")) return;
      winAction("toggle_max");
    });

    /* 最小化 / 关闭：动画交给 Windows 自己播（SW_MINIMIZE + AnimateWindow 淡出），
       页面这边只做极轻的"按下反馈"，不再自绘缩放淡出，避免和系统动画打架 */
    const press = (el, done) => {
      el.classList.add("pressed");
      setTimeout(() => {
        el.classList.remove("pressed");
        done();
      }, 90);
    };

    $("btnMin").addEventListener("click", (e) => {
      e.stopPropagation();
      press(e.currentTarget, () => winAction("minimize"));
    });
    $("btnClose").addEventListener("click", (e) => {
      e.stopPropagation();
      // 不做 90ms 的按下延迟：原生关窗就是从"按下"瞬间开始淡出
      e.currentTarget.classList.add("pressed");
      winAction("close");
    });
  }

  /* ------------------------------------------------------------ 交互绑定 */
  function bind() {
    $("btnParse").addEventListener("click", async () => {
      const text = $("input").value.trim();
      if (!text) { toast("先粘贴链接或输入关键词", "warn"); return; }
      tracks = [];
      rows.clear();
      selected.clear();
      listEl.innerHTML = "";
      listEl.appendChild(emptyEl);
      updateCount();
      await api.parse(text);
    });

    $("input").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("btnParse").click();
    });

    document.querySelectorAll("#levelSeg button").forEach((b) => {
      b.addEventListener("click", () => {
        document.querySelectorAll("#levelSeg button").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        api.set_setting("level", b.dataset.level);
        // 音质变了，估算大小跟着变（已下载完的保留真实体积）
        if (settings) settings.level = b.dataset.level;
        refreshSizes();
      });
    });

    $("fallback").addEventListener("change", (e) => {
      api.set_setting("fallback_enabled", e.target.checked);
    });

    $("btnAll").addEventListener("click", () => { tracks.forEach((t) => toggle(t.uid, true)); });
    $("btnNone").addEventListener("click", () => { tracks.forEach((t) => toggle(t.uid, false)); });
    $("btnInvert").addEventListener("click", () => {
      tracks.forEach((t) => toggle(t.uid, !selected.has(t.uid)));
    });
    $("btnRemove").addEventListener("click", () => {
      if (!selected.size) { toast("没有选中的歌曲", "warn"); return; }
      const drop = new Set(selected);
      tracks = tracks.filter((t) => !drop.has(t.uid));
      selected.clear();
      renderAll();
      tracks.forEach((t) => { if (!rows.get(t.uid)) return; });
      // 重新勾选剩下的（renderAll 会清空选中状态）
      selected = new Set(tracks.map((t) => t.uid));
      renderAllSel();
      updateCount();
    });
    $("btnClear").addEventListener("click", () => {
      tracks = []; rows.clear(); selected.clear();
      listEl.innerHTML = ""; listEl.appendChild(emptyEl);
      updateCount();
      $("bar").style.width = "0%"; $("progText").textContent = "已下载 0 / 0 首"; $("speed").textContent = "";
    });

    $("btnStart").addEventListener("click", async () => {
      if (running) return;
      const uids = tracks.filter((t) => selected.has(t.uid)).map((t) => t.uid);
      if (!uids.length) { toast("先勾选要下载的歌", "warn"); return; }
      running = true;
      $("btnStart").disabled = true;
      $("btnStop").disabled = false;
      $("bar").style.width = "0%";
      log(`开始下载 ${uids.length} 首…`);
      await api.download(uids);
    });

    $("btnStop").addEventListener("click", () => {
      api.stop();
      log("已发送停止信号", "warn");
    });

    $("btnDir").addEventListener("click", () => api.open_dir());
    $("btnCheckCookie").addEventListener("click", () => checkCookie(true));
    $("btnSettings").addEventListener("click", () => openDrawer(true));
    $("drawerClose").addEventListener("click", () => openDrawer(false));
    $("scrim").addEventListener("click", () => openDrawer(false));

    $("btnPick").addEventListener("click", async () => {
      const p = await api.pick_dir();
      if (p) $("setDir").value = p;
    });

    $("setThreads").addEventListener("input", (e) => {
      $("ccVal").textContent = e.target.value;
    });

    $("btnSaveSet").addEventListener("click", async () => {
      const patch = {
        save_dir: $("setDir").value,
        template: $("setTpl").value,
        concurrency: +$("setThreads").value,
        write_cover: $("setCover").checked,
        write_lyric: $("setLyric").checked,
        skip_existing: $("setSkip").checked,
        organize: $("setOrganize").checked,
        strict_mp3: $("setStrictMp3").checked,
        cookie: $("setCookie").value.trim(),
      };
      settings = await api.save_settings(patch);
      applySettings();
      openDrawer(false);
      toast("设置已保存", "ok");
    });

    $("btnLog").addEventListener("click", () => $("logPanel").classList.toggle("open"));
    $("btnLogClose").addEventListener("click", () => $("logPanel").classList.remove("open"));
    $("btnLogClear").addEventListener("click", () => { $("log").innerHTML = ""; });

    // 列表全选快捷键
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a"
          && document.activeElement.tagName !== "TEXTAREA"
          && document.activeElement.tagName !== "INPUT") {
        e.preventDefault();
        tracks.forEach((t) => toggle(t.uid, true));
      }
      if (e.key === "Escape") openDrawer(false);
    });
  }

  function renderAllSel() {
    tracks.forEach((t) => {
      const rec = rows.get(t.uid);
      if (!rec) return;
      const on = selected.has(t.uid);
      rec.el.classList.toggle("sel", on);
    });
  }

  async function boot() {
    bind();
    bindWindow();
    connectEvents();
    try {
      settings = await api.ready();
      applySettings();
    } catch (_) {
      toast("后端没连上，请重启程序", "err");
    }
    log("界面已就绪");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

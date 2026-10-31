'use strict';
/**
 * 网易云音乐下载器 —— Electron 壳
 *
 * 职责边界：
 *   · Electron 只负责窗口、原生动画、系统交互（渲染内核 = Chromium）
 *   · 下载/解析/打标签全部交给 sidecar 后端（ncm_backend.exe，即原来那套
 *     已经调通的 Python 引擎，通过 127.0.0.1 上的本地 HTTP 通信）
 *   · 这样"内核换成 Electron"的同时，功能与原来 100% 一致，不会因为重写
 *     解析逻辑而退化。
 */
const { app, BrowserWindow, ipcMain, Menu, shell, dialog } = require('electron');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');
const fs = require('fs');

const WIN_W = 1280;
const WIN_H = 880;
const TOKEN = crypto.randomBytes(16).toString('hex');

// 调试用：NCM_DEBUG_PORT=9333 时开 CDP，方便自动化截图/回归
if (process.env.NCM_DEBUG_PORT) {
  app.commandLine.appendSwitch('remote-debugging-port', process.env.NCM_DEBUG_PORT);
  app.commandLine.appendSwitch('remote-allow-origins', '*');
}

let win = null;
let backend = null;
let backendPort = 0;
let closing = false;

function backendPath() {
  const exe = process.platform === 'win32' ? 'ncm_backend.exe' : 'ncm_backend';
  // 打包后 --extra-resource 会把 exe 平铺在 resources/ 下；两种位置都找一遍
  const candidates = [
    path.join(process.resourcesPath || '', 'backend', exe),
    path.join(process.resourcesPath || '', exe),
    path.join(__dirname, '..', 'dist', exe),
    path.join(__dirname, 'dist', exe),
  ];
  for (const c of candidates) {
    if (c && fs.existsSync(c)) return c;
  }
  return candidates[0];
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const exe = backendPath();
    if (!fs.existsSync(exe)) return reject(new Error('找不到后端程序：' + exe));

    backend = spawn(exe, [], {
      env: { ...process.env, NCM_TOKEN: TOKEN, NCM_PARENT_PID: String(process.pid) },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });

    let buf = '';
    const timer = setTimeout(() => reject(new Error('后端启动超时')), 45000);

    backend.stdout.on('data', (chunk) => {
      buf += chunk.toString('utf8');
      const lines = buf.split(/\r?\n/);
      buf = lines.pop() || '';
      for (const line of lines) {
        const t = line.trim();
        if (!t.startsWith('{')) continue;
        try {
          const info = JSON.parse(t);
          if (info.port) {
            backendPort = info.port;
            clearTimeout(timer);
            resolve(info);
          }
        } catch (_) { /* 非 JSON 行忽略 */ }
      }
    });
    backend.stderr.on('data', (d) => process.stderr.write('[backend] ' + d));
    backend.on('exit', (code) => {
      if (!closing && code !== 0) {
        dialog.showErrorBox('后端异常退出', `下载引擎退出，代码 ${code}。`);
        app.quit();
      }
    });
    backend.on('error', reject);
  });
}

/**
 * 关闭动画：直接调 Windows 自己的 AnimateWindow(AW_BLEND|AW_HIDE)，
 * 就是系统给原生窗口用的那套淡出，时长/曲线由系统决定，不再自己贴 alpha。
 */
let u32 = null;
function loadUser32() {
  if (u32 !== null) return u32;
  try {
    const koffi = require('koffi');
    u32 = koffi.load('user32.dll');
  } catch (e) {
    console.warn('koffi 不可用，退回系统默认关闭', e.message);
    u32 = false;
  }
  return u32;
}

const AW_HIDE = 0x00010000;
const AW_BLEND = 0x00020000;

function nativeClose() {
  if (!win || win.isDestroyed()) return;
  closing = true;
  // 观感对齐微信/QQ：淡出 + 轻微缩小（中心不动），~150ms
  const b = win.getBounds();
  const cx = b.x + b.width / 2;
  const cy = b.y + b.height / 2;
  const steps = 10;
  let i = 0;
  const timer = setInterval(() => {
    i += 1;
    if (!win || win.isDestroyed()) return clearInterval(timer);
    const t = i / steps;
    const scale = 1 - 0.045 * t;                 // 收到 95.5%
    const w = Math.round(b.width * scale);
    const h = Math.round(b.height * scale);
    try {
      win.setBounds({ x: Math.round(cx - w / 2), y: Math.round(cy - h / 2), width: w, height: h },
                    false);
    } catch (_) {}
    win.setOpacity(Math.max(0, 1 - Math.pow(t, 0.75)));
    if (i >= steps) {
      clearInterval(timer);
      if (win && !win.isDestroyed()) win.destroy();
    }
  }, 15);
}

function createWindow() {
  win = new BrowserWindow({
    width: WIN_W,
    height: WIN_H,
    minWidth: 980,
    minHeight: 620,
    frame: false,
    show: false,
    backgroundColor: '#202020',
    title: '网易云音乐下载器',
    icon: path.join(__dirname, 'build', 'ncm.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  // 关键实验：Chromium 默认会把窗口的 DWM 过渡关掉（DWMWA_TRANSITIONS_FORCEDISABLED=1），
  // 这里显式打开，让系统自己播窗口过渡（这就是"原生关闭动画"的来源）
  if (process.env.NCM_DWM_TRANSITIONS !== '0') {
    try {
      const koffi = require('koffi');
      const dwm = koffi.load('dwmapi.dll');
      const setAttr = dwm.func('long DwmSetWindowAttribute(void *hwnd, uint32 attr, void *val, uint32 size)');
      const hwnd = win.getNativeWindowHandle().readBigUInt64LE(0);
      const buf = Buffer.alloc(4);
      buf.writeInt32LE(0, 0);              // FALSE = 允许过渡
      const hr = setAttr(hwnd, 3, buf, 4); // DWMWA_TRANSITIONS_FORCEDISABLED
      console.log('DwmSetWindowAttribute(transitions) hr=', hr);
    } catch (e) {
      console.warn('DWM 过渡开启失败', e.message);
    }
  }

  Menu.setApplicationMenu(null);
  win.loadFile(path.join(__dirname, 'loading.html'));

  win.once('ready-to-show', () => win.show());

  win.on('close', (e) => {
    if (closing) return;
    e.preventDefault();
    nativeClose();
  });

  win.on('closed', () => { win = null; });

  // 页面里的外链一律走系统浏览器
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  return win;
}

ipcMain.handle('win:minimize', () => { if (win) win.minimize(); });
ipcMain.handle('win:toggleMax', () => {
  if (!win) return;
  win.isMaximized() ? win.unmaximize() : win.maximize();
});
ipcMain.handle('win:close', () => { if (win) win.close(); });
ipcMain.handle('app:info', () => ({ electron: process.versions.electron }));

app.whenReady().then(async () => {
  createWindow();
  try {
    const info = await startBackend();
    const url = `http://127.0.0.1:${info.port}/?t=${TOKEN}`;
    await win.loadURL(url);
  } catch (err) {
    dialog.showErrorBox('启动失败', String(err && err.message ? err.message : err));
    app.quit();
  }
});

function killBackend() {
  if (!backend) return;
  const pid = backend.pid;
  try {
    // PyInstaller onefile 是"父引导进程 + 子进程"结构，必须整棵树一起收掉
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true });
    } else {
      backend.kill('SIGKILL');
    }
  } catch (_) { /* 忽略 */ }
  backend = null;
}

app.on('window-all-closed', () => {
  closing = true;
  killBackend();
  app.quit();
});

app.on('before-quit', () => {
  closing = true;
  killBackend();
});

# 163download · 网易云音乐下载器

一个 Windows 桌面下载器：把网易云音乐的**歌单 / 专辑 / 歌手作品 / 单曲**整批下成 MP3，
自动写好标题、歌手、专辑、封面、歌词，拷到手机或车机上信息全都在。

匿名就能下（约七成曲目直接给完整原版）；遇到只回 30 秒试听的付费曲，会自动去别的音源找完整版，
找不到就老实报错，**不会偷偷塞给你一个 30 秒的文件**。

![主界面](screenshots/el-02-list.png)

## 特性

- **批量下载**：歌单、专辑、歌手全部作品、单曲、关键词搜索，一次挂几百首；1–8 线程、失败重试、已存在自动跳过
- **五档音质**：标准 128k / 较高 192k / 极高 320k / 无损 FLAC / Hi-Res，列表里先按档位预估体积
- **标签齐全**：ID3v2.4（FLAC 用 Vorbis Comment）+ 1200×1200 内嵌封面 + 内嵌歌词 + 音轨号
- **只收 MP3**：开启后落地会校验文件头，接口偷偷给 FLAC/M4A 就自动换源重取
- **音源兜底**：网易云只给试听时，按「歌名 + 歌手 + 时长」去酷我找完整版，并逐一核对实际时长
- **Cookie 检测**：填完点一下就知道有效 / 过期 / 格式错，不用等下载才发现
- **界面**：WinUI 深色风、封面缩略图、权限徽章、逐首状态、按首数推进的进度条；关窗有淡出动画

| 设置 | 日志 |
|---|---|
| ![](screenshots/el-03-settings.png) | ![](screenshots/el-04-log.png) |

## 快速开始

下载 Release 里的压缩包，解压后双击 `网易云音乐下载器.exe`，免安装、不需要运行库。

1. 粘链接或 ID，一行一个：
   ```
   https://music.163.com/playlist?id=3778678      # 歌单
   https://music.163.com/album?id=32311           # 专辑
   https://music.163.com/artist?id=6452           # 歌手全部作品
   https://music.163.com/song?id=287398           # 单曲
   周杰伦 稻香                                     # 也可以直接搜索
   ```
2. 选音质 → 点「解析 / 搜索」→ 列表勾选 → 「开始下载」
3. 文件默认存到桌面同级目录，可在「设置 → 保存目录」里改

窗口操作：拖顶栏移动、双击顶栏最大化、四边拖拽缩放。

## 用自己的账号（可选）

不做任何事也能用。想下私密歌单、VIP 曲或 Hi-Res 时填 Cookie：

1. 浏览器登录 <https://music.163.com>
2. `F12` → Network → 点任意一条 `api` 请求 → 复制 Request Headers 里的 `Cookie`
3. 取其中的 `MUSIC_U=...`（连 `__csrf=...` 一起更稳），粘进「设置 → Cookie」，点「检测 Cookie」确认后保存

> 链接里带 `uct2=` 的私有歌单，匿名接口读不到，必须登录。

## 常见问题

**下载目录里的 `.part` 是什么？**
下载中的临时文件，完整下完才会改成正式文件名（避免半截文件被播放器误读）。正常完成或失败都会自动清理，
只有进程被强杀 / 断电才会残留，直接删掉即可。

**为什么有些歌下不下来？**
那首在各平台都要付费。程序会明确告诉你「各平台均为付费曲」，而不是给你个试听片段。
填了自己账号的 Cookie 后，已购 / VIP 曲就能正常下。

**需要 API key 吗？**
不需要，接口走的是网页版同一套签名。

## 从源码运行

需要 Node 18+ 和 Python 3.10+。

```bash
# 1) Python 引擎（sidecar）
pip install mutagen requests pycryptodome
python -m PyInstaller --onefile --console --name ncm_backend \
  --add-data "ncm/web;ncm/web" --collect-submodules ncm \
  --hidden-import mutagen --hidden-import requests electron/backend_main.py

# 2) Electron 外壳
cd electron
npm install            # 国内可加 ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
npm start
```

打包成绿色版目录：

```bash
cd electron
npx electron-packager . "网易云音乐下载器" --platform=win32 --arch=x64 \
  --out=../dist-electron --overwrite --icon=build/ncm.ico \
  --extra-resource=../dist/ncm_backend.exe
```

## 结构

```
electron/        Electron 外壳：窗口 / 关闭动画 / 单实例 / 拉起 sidecar
  main.js        主进程
  preload.js     渲染层桥
  backend_main.py  后端入口（打印端口给主进程）
ncm/             下载引擎
  api.py         网易云 eapi/weapi 签名、搜索、歌单、直链、歌词
  core.py        下载引擎：线程池、试听检测、换源、文件头校验
  fallback.py    酷我音源匹配
  tagger.py      ID3 / FLAC 标签写入
  server.py      本地 HTTP + SSE 后端
  web/           界面（原生 HTML/CSS/JS，无框架无 CDN）
tools/           CDP 驱动与验证脚本（截图 / 进度 / Cookie / 动画探针）
```

架构上只有一件事值得说明：**Electron 是壳，Python 是引擎**。Chromium 的页面画在子窗口里，
对父窗口做 `WS_EX_LAYERED`、`AnimateWindow` 都影响不到页面像素，所以关闭动画只能由壳进程对窗口本身做。

## 免责声明

仅用于个人学习与备份**可公开试听**的音乐。请勿用于传播、售卖或任何商业用途；
由此产生的版权问题由使用者自行承担。喜欢请支持正版。

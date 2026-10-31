# -*- coding: utf-8 -*-
"""Qt 版界面截图（不需要真实桌面前台）。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from ncm.qtui import MainWindow, QSS, _make_check_icon  # noqa: E402

OUT = os.path.join(ROOT, "shots")


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for(app, cond, timeout=120.0, label=""):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    print("超时:", label)
    return False


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS.replace("__CHECK__", _make_check_icon()))
    w = MainWindow()
    w.resize(1280, 880)
    w.show()
    pump(app, 0.8)
    w.grab().save(os.path.join(OUT, "qt-01-empty.png"))
    print("[1] 空界面")

    w.input.setPlainText("https://music.163.com/playlist?id=3778678")
    w._parse()
    ok = wait_for(app, lambda: w.table.rowCount() > 30, 150, "解析")
    pump(app, 3.0)                      # 等封面
    w.grab().save(os.path.join(OUT, "qt-02-list.png"))
    print("[2] 列表行数", w.table.rowCount(), "ok=", ok)

    w._open_dir = lambda: None
    dlg = None
    from ncm.qtui import SettingsDialog
    dlg = SettingsDialog(w, w.backend.ready())
    dlg.show()
    pump(app, 0.6)
    dlg.grab().save(os.path.join(OUT, "qt-03-settings.png"))
    dlg.close()
    print("[3] 设置")

    w.log_box.setVisible(True)
    w.log_box.appendPlainText("23:59:59  ✔ 孙燕姿 - 我不难过（网易云 · MP3）")
    w.log_box.appendPlainText("23:59:59  ✔ 马也_Crabbit - 海屿你（酷我兜底 · MP3）")
    w.log_box.appendPlainText("23:59:59  ✔ Max李玄 - 明知故犯（网易云 · MP3）")
    pump(app, 0.5)
    w.grab().save(os.path.join(OUT, "qt-04-log.png"))
    print("[4] 日志")
    return 0


if __name__ == "__main__":
    sys.exit(main())

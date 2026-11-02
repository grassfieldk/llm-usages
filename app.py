from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import json
import math
import os
import subprocess
import sys
import threading
import time
import winreg

import claude_auth
from providers import Usage, executable, fetch


def check():
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(fetch, ("Codex", "Claude")):
            print(json.dumps({"provider": result.provider, "error": result.error,
                              "windows": [{"name": w.name, "used": w.used, "reset": w.reset.isoformat() if w.reset else None} for w in result.windows]}, ensure_ascii=False))


if "--check" in sys.argv:
    check()
    raise SystemExit()

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPoint,
                            QPropertyAnimation, QSettings, Qt, QTimer, Signal)
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QGraphicsDropShadowEffect,
                              QHBoxLayout,
                              QLabel, QMenu, QProgressBar, QPushButton,
                              QSpinBox, QSystemTrayIcon, QVBoxLayout, QWidget)

ASSETS = Path(__file__).resolve().parent / "assets"
SHADOW = 16

STYLE = """
QWidget { background: #121212; color: #eeeeee; font-family: 'Noto Sans JP', 'Yu Gothic UI'; font-size: 12px; }
QWidget#shell { background: transparent; }
QWidget#popup { background: #121212; border: 1px solid #292929; border-radius: 12px; }
QLabel { background: transparent; border: none; }
QLabel#heading { font-size: 13px; font-weight: 600; }
QLabel#muted { color: #a1a1a1; font-size: 11px; }
QLabel#quotaTitle { font-size: 13px; font-weight: 700; }
QLabel#quotaDetail { color: #a1a1a1; font-size: 11px; font-weight: 700; }
QWidget#quota { background: #1e1e1e; border: 1px solid #292929; border-radius: 16px; }
QPushButton { background: transparent; border: 1px solid #343434; border-radius: 6px; padding: 1px 10px 5px; min-height: 18px; }
QPushButton:hover { background: #292929; border-color: #494949; }
QPushButton:pressed { background: #404040; }
QPushButton:focus { border-color: #a1a1a1; }
QPushButton:disabled { color: #777777; border-color: #373737; }
QProgressBar { background: #333333; border: none; border-radius: 3px; }
QProgressBar::chunk { background: #ffffff; border-radius: 3px; }
QLineEdit, QSpinBox { background: #292929; border: 1px solid #494949; border-radius: 0; padding: 2px 4px 6px; }
QMenu { border: 1px solid #494949; padding: 3px; }
QMenu::item { padding: 3px 20px 7px; }
QMenu::item:selected { background: #363636; }
"""


class Bridge(QObject):
    done = Signal(object)
    logged_in = Signal(str)


def reset_text(reset, now=None):
    if reset is None:
        return "リセット時刻は未提供"
    seconds = (reset - (now or datetime.now().astimezone())).total_seconds()
    if seconds <= 0:
        return "リセット時刻に到達"
    minutes = math.ceil(seconds / 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    parts = ([f"{days} 日"] if days else []) + ([f"{hours} 時間"] if hours else [])
    if not days and minutes:
        parts.append(f"{minutes} 分")
    duration = " ".join(parts)
    return f"{duration}後にリセット" if days else f"リセットまで {duration}"


def quota_title(name):
    if name == "週間":
        return "週ごとの利用上限"
    if name.endswith(" 時間"):
        return f"{name}ごとの利用上限"
    return f"{name}の利用上限"


def tray_icon(values):
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(Qt.PenStyle.NoPen)
    for i, (name, color) in enumerate((("Codex", "#3566f0"), ("Claude", "#d97757"))):
        usage = values.get(name)
        window = next((w for w in usage.windows if w.name.endswith("5 時間")), None) if usage and not usage.error else None
        if window:
            remaining = 100 - window.used
            painter.setBrush(QColor(color))
            painter.drawRect(0, 2 + i * 16, round(remaining / 100 * 32), 12)
    painter.end()
    return QIcon(pixmap)


class Popup(QWidget):
    def __init__(self, owner):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.owner = owner
        self.closed_at = 0.0
        self.showing = False
        self.setObjectName("shell")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(460 + SHADOW * 2)
        self.setWindowTitle("LLM Usages")
        shell = QVBoxLayout(self)
        shell.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        frame = QWidget()
        frame.setObjectName("popup")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 150))
        frame.setGraphicsEffect(shadow)
        shell.addWidget(frame)
        self.motion = QPropertyAnimation(self, b"pos", self)
        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.animation = QParallelAnimationGroup(self)
        self.animation.addAnimation(self.motion)
        self.animation.addAnimation(self.fade)
        self.animation.finished.connect(lambda: None if self.showing else self.hide())
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        top = QHBoxLayout()
        heading = QLabel("LLM Usages")
        heading.setObjectName("heading")
        top.addWidget(heading)
        top.addStretch()
        settings = QPushButton("設定")
        settings.clicked.connect(owner.settings_dialog)
        top.addWidget(settings)
        hide = QPushButton("閉じる")
        hide.clicked.connect(self.dismiss)
        top.addWidget(hide)
        layout.addLayout(top)
        self.cards = QVBoxLayout()
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(18)
        layout.addLayout(self.cards)
        bottom = QHBoxLayout()
        self.status = QLabel("取得中…")
        self.status.setObjectName("muted")
        bottom.addWidget(self.status)
        bottom.addStretch()
        self.refresh = QPushButton("更新")
        self.refresh.clicked.connect(owner.refresh)
        bottom.addWidget(self.refresh)
        layout.addLayout(bottom)
        self.clock = QTimer(self)
        self.clock.timeout.connect(lambda: self.render() if self.isVisible() else None)
        self.clock.start(60000)

    def render(self):
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        for provider in ("Codex", "Claude"):
            result = self.owner.values.get(provider)
            card = QWidget()
            layout = QVBoxLayout(card)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            title = QLabel(provider)
            title.setStyleSheet("font-size: 13px; font-weight: 600;")
            title_row = QHBoxLayout()
            title_row.setSpacing(6)
            icon = QLabel()
            icon.setPixmap(QIcon(str(ASSETS / f"{provider.lower()}.png")).pixmap(16, 16))
            title_row.addWidget(icon)
            title_row.addWidget(title)
            title_row.addStretch()
            layout.addLayout(title_row)
            previous = self.owner.previous.get(provider)
            display = previous if result and result.error and previous else result
            quota = QWidget()
            quota.setObjectName("quota")
            quota_layout = QVBoxLayout(quota)
            quota_layout.setContentsMargins(16, 16, 16, 16)
            quota_layout.setSpacing(28)
            layout.addWidget(quota)
            if result and result.error:
                warning = QLabel(result.error)
                warning.setWordWrap(True)
                warning.setStyleSheet("color: #d2ab80;")
                quota_layout.addWidget(warning)
            if display and display.windows:
                captured = QLabel(f"{'前回' if result and result.error else '更新'} {display.captured:%H:%M}")
                captured.setObjectName("muted")
                title_row.addWidget(captured)
                for window in display.windows:
                    item = QVBoxLayout()
                    item.setSpacing(6)
                    name = QLabel(quota_title(window.name))
                    name.setObjectName("quotaTitle")
                    name.setWordWrap(True)
                    item.addWidget(name)
                    row = QHBoxLayout()
                    label = QLabel(reset_text(window.reset))
                    label.setObjectName("quotaDetail")
                    if window.reset:
                        label.setToolTip(window.reset.strftime("%Y/%m/%d %H:%M"))
                    row.addWidget(label)
                    row.addStretch()
                    remaining = max(0, min(100, 100 - window.used))
                    value = QLabel(f"残り {remaining:g}%")
                    value.setObjectName("quotaDetail")
                    row.addWidget(value)
                    item.addLayout(row)
                    bar = QProgressBar()
                    bar.setRange(0, 1000)
                    bar.setValue(round(remaining * 10))
                    bar.setTextVisible(False)
                    bar.setFixedHeight(6)
                    if remaining <= 50:
                        bar.setStyleSheet(f"QProgressBar::chunk {{ background: {'#ef5350' if remaining <= 20 else '#f5c542'}; }}")
                    item.addWidget(bar)
                    quota_layout.addLayout(item)
            elif not result:
                quota_layout.addWidget(QLabel("取得中…"))
            if result and result.error:
                button = QPushButton("ログイン")
                button.clicked.connect(lambda checked=False, p=provider: self.owner.login(p))
                quota_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)
            self.cards.addWidget(card)
        self.status.setText("取得中…" if self.owner.pending else f"{self.owner.interval()} 分ごとに更新")
        self.refresh.setEnabled(not self.owner.pending)
        self.fit()
        QTimer.singleShot(0, self.fit)

    def fit(self):
        self.layout().activate()
        height = self.layout().totalHeightForWidth(self.width()) if self.layout().hasHeightForWidth() else self.layout().totalSizeHint().height()
        offset = QPoint(0, self.height() - height)
        self.setFixedHeight(height)
        if self.isVisible():
            self.move(self.pos() + offset)
            if self.showing and self.animation.state() == QParallelAnimationGroup.State.Running:
                self.motion.setEndValue(self.motion.endValue() + offset)

    def animate(self, showing, start, end, duration, curve):
        self.showing = showing
        self.animation.stop()
        self.motion.setStartValue(start)
        self.motion.setEndValue(end)
        self.fade.setStartValue(self.windowOpacity())
        self.fade.setEndValue(1.0 if showing else 0.0)
        for animation in (self.motion, self.fade):
            animation.setDuration(duration)
            animation.setEasingCurve(curve)
        self.animation.start()

    def appear(self, pos):
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.move(pos + QPoint(0, 10))
            self.show()
        self.raise_()
        self.activateWindow()
        self.animate(True, self.pos(), pos, 180, QEasingCurve.Type.OutCubic)

    def dismiss(self):
        if self.isVisible() and self.showing:
            self.animate(False, self.pos(), self.pos() + QPoint(0, 6), 140, QEasingCurve.Type.InCubic)

    def closeEvent(self, event):
        event.ignore()
        self.dismiss()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            QTimer.singleShot(0, self.hide_if_outside)
        super().changeEvent(event)

    def hide_if_outside(self):
        active = QApplication.activeWindow()
        if self.isVisible() and active is not self and (active is None or active.parentWidget() is not self):
            self.closed_at = time.monotonic()
            self.dismiss()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(event)


class App(QObject):
    def __init__(self, application):
        super().__init__()
        self.application = application
        self.settings = QSettings("LLMUsages", "LLM Usages")
        self.values = {}
        self.previous = {}
        self.pending = set()
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.bridge = Bridge()
        self.bridge.done.connect(self.received)
        self.bridge.logged_in.connect(self.logged_in)
        self.popup = Popup(self)
        self.tray = QSystemTrayIcon(tray_icon({}), self)
        self.tray.setToolTip("LLM Usages / 取得中")
        menu = QMenu()
        for label, callback in (("使用状況を表示", self.show), ("更新", self.refresh), ("設定", self.settings_dialog), ("終了", self.quit)):
            action = QAction(label, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.activated)
        self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(self.interval() * 60000)
        self.popup.render()
        self.refresh()

    def interval(self):
        return max(1, min(60, int(self.settings.value("interval", 5))))

    def refresh(self):
        if self.pending:
            return
        self.pending = {"Codex", "Claude"}
        self.popup.render()
        for provider in ("Codex", "Claude"):
            future = self.pool.submit(fetch, provider)
            future.add_done_callback(lambda f: self.bridge.done.emit(f.result()))

    def received(self, usage: Usage):
        self.pending.discard(usage.provider)
        self.values[usage.provider] = usage
        if not usage.error:
            self.previous[usage.provider] = usage
        self.tray.setIcon(tray_icon(self.previous))
        lines = ["LLM Usages"]
        for provider in ("Codex", "Claude"):
            result = self.values.get(provider)
            if result:
                text = "取得失敗" if result.error else " / ".join(f"{w.name} 残り {100 - w.used:g}%" for w in result.windows)
                lines.append(f"{provider}: {text}")
        self.tray.setToolTip("\n".join(lines)[:127])
        self.popup.render()

    def activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.popup.isVisible() and self.popup.showing:
                self.popup.dismiss()
            elif time.monotonic() - self.popup.closed_at > 0.5:
                self.show()

    def show(self):
        self.popup.render()
        rect = self.tray.geometry()
        screen = QApplication.screenAt(rect.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        width, height = self.popup.width() - SHADOW * 2, self.popup.height() - SHADOW * 2
        x = rect.right() - width if not rect.isNull() else area.right() - width - 16
        y = area.bottom() - height - 8
        x = max(area.left() + 8, min(x, area.right() - width - 8))
        self.popup.appear(QPoint(x - SHADOW, max(area.top() + 8, y) - SHADOW))

    def login(self, provider):
        if provider == "Claude":
            threading.Thread(target=self.claude_login, daemon=True).start()
            return
        command = executable("codex")
        if not command:
            self.tray.showMessage("LLM Usages", "Codex のコマンドが見つかりません")
            return
        subprocess.Popen([command, "login"], creationflags=subprocess.CREATE_NEW_CONSOLE)

    def claude_login(self):
        try:
            claude_auth.login()
            self.bridge.logged_in.emit("")
        except Exception as error:
            self.bridge.logged_in.emit(str(error) if isinstance(error, RuntimeError) else "Claude のログインに失敗しました")

    def logged_in(self, error):
        if error:
            self.tray.showMessage("LLM Usages", error)
        else:
            self.refresh()

    def settings_dialog(self):
        dialog = QDialog(self.popup)
        dialog.setWindowTitle("LLM Usages / 設定")
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("自動更新の間隔 (分)"))
        interval = QSpinBox()
        interval.setRange(1, 60)
        interval.setValue(self.interval())
        layout.addWidget(interval)
        startup = QCheckBox("Windows 起動時に起動")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, "LLM Usages")
            startup.setChecked(True)
        except OSError:
            pass
        layout.addWidget(startup)
        logins = QHBoxLayout()
        for provider in ("Codex", "Claude"):
            button = QPushButton(f"{provider} にログイン")
            button.clicked.connect(lambda checked=False, p=provider: self.login(p))
            logins.addWidget(button)
        layout.addLayout(logins)
        note = QLabel("Codex はログイン完了後、使用状況の画面で「更新」を押してください")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        save = QPushButton("保存")
        def commit():
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                    if startup.isChecked():
                        command = f'"{sys.executable.replace("python.exe", "pythonw.exe")}" "{Path(__file__).resolve()}"'
                        winreg.SetValueEx(key, "LLM Usages", 0, winreg.REG_SZ, command)
                    else:
                        try:
                            winreg.DeleteValue(key, "LLM Usages")
                        except FileNotFoundError:
                            pass
            except OSError:
                note.setText("起動設定を保存できませんでした")
                return
            self.settings.setValue("interval", interval.value())
            self.timer.start(self.interval() * 60000)
            dialog.accept()
            self.refresh()
        save.clicked.connect(commit)
        layout.addWidget(save)
        dialog.exec()

    def quit(self):
        self.timer.stop()
        self.tray.hide()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.application.quit()


def main():
    # 標準の DirectWrite はサブピクセル描画を止められないため FreeType でグレースケール描画する
    os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
    application = QApplication(sys.argv)
    application.setStyle("Fusion")
    application.setQuitOnLastWindowClosed(False)
    application.setStyleSheet(STYLE)
    socket = QLocalSocket()
    socket.connectToServer("LLMUsages.Application")
    if socket.waitForConnected(300):
        socket.write(b"show")
        socket.waitForBytesWritten(300)
        return
    server = QLocalServer()
    QLocalServer.removeServer("LLMUsages.Application")
    if not server.listen("LLMUsages.Application"):
        raise SystemExit("アプリを起動できませんでした")
    app = App(application)
    def connection():
        client = server.nextPendingConnection()
        app.show()
        client.disconnectFromServer()
        client.deleteLater()
    server.newConnection.connect(connection)
    if "--show" in sys.argv:
        app.show()
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()

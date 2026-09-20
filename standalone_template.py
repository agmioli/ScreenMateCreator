# standalone_template.py
import sys
import os
import json
import tempfile
import hashlib
from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                             QPushButton, QSlider, QMenu, QSystemTrayIcon,
                             QMessageBox)
from PyQt6.QtCore import Qt, QTimer, QLockFile
from PyQt6.QtGui import QPixmap, QTransform, QIcon, QAction


def _app_dir():
    """Папка, где лежит сам exe (или скрипт)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _acquire_single_instance_lock():
    """
    Пытается получить блокировку для этого конкретного exe.
    Возвращает QLockFile или None, если уже запущен другой экземпляр.
    """
    try:
        if getattr(sys, 'frozen', False):
            key_source = os.path.abspath(sys.executable)
        else:
            key_source = os.path.abspath(__file__)
        h = hashlib.md5(key_source.encode('utf-8')).hexdigest()[:16]
        lock_path = os.path.join(tempfile.gettempdir(), f"screenmate_{h}.lock")

        lock = QLockFile(lock_path)
        lock.setStaleLockTime(0)
        if not lock.tryLock(100):
            return None
        return lock
    except Exception as e:
        print(f"Ошибка проверки единственного экземпляра: {e}")
        return None


def _force_exit():
    """Гарантированно завершает процесс, даже если Qt завис."""
    try:
        QApplication.quit()
    except Exception:
        pass
    # Даём Qt 100 мс, чтобы корректно выйти
    QTimer.singleShot(100, lambda: os._exit(0))


APP_DIR = _app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
FRAMES_DIR = os.path.join(APP_DIR, "frames")
ICON_PATH = os.path.join(APP_DIR, "app.ico")

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
except Exception as e:
    print(f"Не удалось загрузить config.json: {e}")
    CONFIG = {"title": "Screenmate", "scale": 1.0, "rotation": 0.0, "frame_delay": 150}

TITLE = CONFIG.get("title", "Screenmate")


class ScreenmateOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(TITLE)
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))

        self.label = QLabel(self)
        self.frames = []
        self.current = 0
        self.timer = None

        self.scale = CONFIG.get("scale", 1.0)
        self.rotation = CONFIG.get("rotation", 0.0)
        self.frame_delay = CONFIG.get("frame_delay", 150)

        self.load_frames()
        self.old_pos = None

    def load_frames(self):
        i = 0
        while True:
            path = os.path.join(FRAMES_DIR, f"frame_{i:04d}.png")
            if not os.path.exists(path):
                break
            pix = QPixmap(path)
            if pix.isNull():
                break
            self.frames.append(pix)
            i += 1

        if self.frames:
            self.apply_transformations()
            self.start_timer()

    def start_timer(self):
        if self.timer:
            self.timer.stop()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)
        self.timer.start(self.frame_delay)

    def next_frame(self):
        if not self.frames:
            return
        self.current = (self.current + 1) % len(self.frames)
        self.apply_transformations()

    def apply_transformations(self):
        if not self.frames:
            return
        pix = self.frames[self.current]
        if self.rotation != 0:
            pix = pix.transformed(QTransform().rotate(self.rotation),
                                  Qt.TransformationMode.SmoothTransformation)
        if self.scale != 1.0:
            size = pix.size() * self.scale
            pix = pix.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self.label.setPixmap(pix)
        self.label.resize(pix.size())
        self.setFixedSize(pix.size())

    def showEvent(self, event):
        super().showEvent(event)
        if self.frames:
            self.apply_transformations()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = event.globalPosition().toPoint()
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = None

    def show_menu(self, pos):
        menu = QMenu(self)
        hide_action = menu.addAction("Скрыть/Hide")
        settings_action = menu.addAction("Настройки/Settings")
        action = menu.exec(pos)
        if action == hide_action:
            self.hide()
        elif action == settings_action:
            ctrl.showNormal()
            ctrl.activateWindow()


class ControlPanel(QWidget):
    def __init__(self, overlay):
        super().__init__()
        self.overlay = overlay
        self.setWindowTitle(TITLE)
        self.resize(560, 200)
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))

        layout = QVBoxLayout(self)

        row1 = QHBoxLayout()
        self.show_btn = QPushButton("Показ/Show")
        self.show_btn.setCheckable(True)
        self.show_btn.setChecked(True)
        self.show_btn.clicked.connect(self.toggle)
        row1.addWidget(self.show_btn)

        row1.addWidget(QLabel("Размер:"))
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(10, 300)
        self.scale_slider.setValue(int(overlay.scale * 100))
        self.scale_slider.valueChanged.connect(self.update_scale)
        row1.addWidget(self.scale_slider)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Поворот:"))
        self.rot_slider = QSlider(Qt.Orientation.Horizontal)
        self.rot_slider.setRange(0, 360)
        self.rot_slider.setValue(int(overlay.rotation))
        self.rot_slider.valueChanged.connect(self.update_rotation)
        row2.addWidget(self.rot_slider)

        row2.addWidget(QLabel("Скорость:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(20, 500)
        self.speed_slider.setInvertedAppearance(True)
        self.speed_slider.setValue(overlay.frame_delay)
        self.speed_slider.valueChanged.connect(self.update_speed)
        row2.addWidget(self.speed_slider)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        min_btn = QPushButton("Свернуть в трей / Minimize to tray")
        min_btn.clicked.connect(self.hide)
        exit_btn = QPushButton("Закрыть / Exit")
        exit_btn.clicked.connect(self.exit_app)
        row3.addWidget(min_btn)
        row3.addWidget(exit_btn)
        layout.addLayout(row3)

    def toggle(self):
        if self.show_btn.isChecked():
            self.show_btn.setText("Скрыть/Hide")
            self.overlay.show()
            self.overlay.raise_()
        else:
            self.show_btn.setText("Показ/Show")
            self.overlay.hide()

    def update_scale(self, value):
        self.overlay.scale = value / 100.0
        self.overlay.apply_transformations()

    def update_rotation(self, value):
        self.overlay.rotation = value
        self.overlay.apply_transformations()

    def update_speed(self, value):
        self.overlay.frame_delay = value
        if self.overlay.timer:
            self.overlay.timer.setInterval(value)

    def exit_app(self):
        """Полное закрытие программы: таймер, трей, все окна, процесс."""
        try:
            if self.overlay.timer:
                self.overlay.timer.stop()
                self.overlay.timer = None
        except Exception:
            pass

        try:
            self.overlay.hide()
            self.overlay.close()
        except Exception:
            pass

        try:
            tray.hide()
        except Exception:
            pass

        try:
            self.hide()
            self.close()
        except Exception:
            pass

        _force_exit()

    def closeEvent(self, event):
        # Закрытие крестиком = сворачивание в трей (как задумано)
        event.ignore()
        self.hide()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    lock = _acquire_single_instance_lock()
    if lock is None:
        QMessageBox.information(None, TITLE,
            f"Скринмейт «{TITLE}» уже запущен.\n"
            f"The screenmate «{TITLE}» is already running.")
        sys.exit(0)

    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

    overlay = ScreenmateOverlay()
    ctrl = ControlPanel(overlay)

    tray_icon = QIcon(ICON_PATH) if os.path.exists(ICON_PATH) else app.style().standardIcon(
        app.style().StandardPixmap.SP_ComputerIcon)
    tray = QSystemTrayIcon(tray_icon)
    tray_menu = QMenu()
    open_act = QAction("Открыть / Open", None)
    open_act.triggered.connect(lambda: (ctrl.showNormal(), ctrl.activateWindow()))
    exit_act = QAction("Выход / Exit", None)
    exit_act.triggered.connect(ctrl.exit_app)
    tray_menu.addAction(open_act)
    tray_menu.addAction(exit_act)
    tray.setContextMenu(tray_menu)
    tray.show()

    ctrl.show()
    overlay.show()

    lock_ref = lock  # noqa: F841

    sys.exit(app.exec())
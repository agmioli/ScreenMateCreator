# animation_player.py
import os
import sys
import uuid
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QSlider, QFileDialog,
                             QMessageBox, QStatusBar, QFrame)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QTransform, QIcon


SUPPORTED_EXTS = (".gif", ".tgs", ".json", ".webm")


def _icon():
    """Возвращает QIcon из app_icon.ico, если файл найден."""
    try:
        base = sys._MEIPASS
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "app_icon.ico")
    return QIcon(path) if os.path.exists(path) else QIcon()


class AnimationPlayerWindow(QMainWindow):
    """Отдельное окно-плеер для просмотра анимаций с drag & drop."""

    def __init__(self, parent=None, initial_path=None):
        super().__init__(parent)
        self.setWindowTitle("Play animation")
        self.resize(720, 760)
        self.setMinimumSize(480, 560)
        # Стандартная рамка Windows: крестик, свернуть, развернуть
        self.setAcceptDrops(True)

        icon = _icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        self.frames = []
        self.current = 0
        self.timer = None
        self.scale = 1.0
        self.rotation = 0
        self.delay = 100
        self.is_playing = False
        self.current_path = None

        self._build_ui()
        self._set_status("Готово. Перетащите файл анимации в окно.")

        if initial_path:
            self.load_file(initial_path)

    # ---------- Интерфейс ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Верхняя строка: путь к файлу + кнопки управления окном
        top_row = QHBoxLayout()
        self.info_label = QLabel("Файл не выбран")
        self.info_label.setStyleSheet("font-weight: bold;")
        top_row.addWidget(self.info_label, 1)

        open_btn = QPushButton("Открыть файл / Open file")
        open_btn.clicked.connect(self.open_dialog)
        top_row.addWidget(open_btn)

        close_btn = QPushButton("Закрыть окно / Close window")
        close_btn.clicked.connect(self.close)
        top_row.addWidget(close_btn)

        layout.addLayout(top_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # Область просмотра
        self.canvas = QLabel(
            "Перетащите сюда файл анимации\n"
            "(.gif / .tgs / .json / .webm)\n\n"
            "или нажмите «Открыть файл»"
        )
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setMinimumHeight(280)
        self.canvas.setStyleSheet(
            "border: 2px dashed #555; background: #1e1e1e; color: #aaa;"
            "font-size: 14px;"
        )
        layout.addWidget(self.canvas, 1)

        # Кнопки управления воспроизведением
        ctrl_row = QHBoxLayout()
        self.play_pause_btn = QPushButton("⏸ Пауза / Pause")
        self.play_pause_btn.clicked.connect(self.toggle_play)
        self.play_pause_btn.setEnabled(False)
        ctrl_row.addWidget(self.play_pause_btn)

        self.stop_btn = QPushButton("⏹ Стоп / Stop")
        self.stop_btn.clicked.connect(self.stop_playback)
        self.stop_btn.setEnabled(False)
        ctrl_row.addWidget(self.stop_btn)

        ctrl_row.addStretch(1)
        layout.addLayout(ctrl_row)

        # Ползунок размера
        row = QHBoxLayout()
        row.addWidget(QLabel("Размер:"))
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(10, 300)
        self.scale_slider.setValue(100)
        self.scale_slider.valueChanged.connect(self._update_scale)
        row.addWidget(self.scale_slider)
        self.scale_label = QLabel("100%")
        self.scale_label.setFixedWidth(50)
        self.scale_slider.valueChanged.connect(
            lambda v: self.scale_label.setText(f"{v}%"))
        row.addWidget(self.scale_label)
        layout.addLayout(row)

        # Ползунок поворота
        row = QHBoxLayout()
        row.addWidget(QLabel("Поворот:"))
        self.rot_slider = QSlider(Qt.Orientation.Horizontal)
        self.rot_slider.setRange(0, 360)
        self.rot_slider.valueChanged.connect(self._update_rotation)
        row.addWidget(self.rot_slider)
        self.rot_label = QLabel("0°")
        self.rot_label.setFixedWidth(50)
        self.rot_slider.valueChanged.connect(
            lambda v: self.rot_label.setText(f"{v}°"))
        row.addWidget(self.rot_label)
        layout.addLayout(row)

        # Ползунок скорости
        row = QHBoxLayout()
        row.addWidget(QLabel("Скорость:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(20, 500)
        self.speed_slider.setValue(100)
        self.speed_slider.setInvertedAppearance(True)
        self.speed_slider.valueChanged.connect(self._update_speed)
        row.addWidget(self.speed_slider)
        self.speed_label = QLabel("100 мс")
        self.speed_label.setFixedWidth(60)
        self.speed_slider.valueChanged.connect(
            lambda v: self.speed_label.setText(f"{v} мс"))
        row.addWidget(self.speed_label)
        layout.addLayout(row)

        # Разделитель
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line2)

        # Кнопка создания скринмейта из просматриваемого файла
        self.create_screenmate_btn = QPushButton(
            "Создать скринмейт из этого файла / Create a screenmate from this file"
        )
        self.create_screenmate_btn.setEnabled(False)
        self.create_screenmate_btn.clicked.connect(self.create_screenmate_from_file)
        layout.addWidget(self.create_screenmate_btn)

        # Статус-бар
        self.setStatusBar(QStatusBar(self))

    def _set_status(self, text):
        self.statusBar().showMessage(text)

    # ---------- Drag & Drop ----------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if not path:
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext in SUPPORTED_EXTS:
                self.load_file(path)
                event.acceptProposedAction()
                return
            else:
                QMessageBox.warning(
                    self, "Формат не поддерживается",
                    f"Файл: {os.path.basename(path)}\n"
                    f"Формат {ext} не поддерживается.\n\n"
                    f"Поддерживаются: {', '.join(SUPPORTED_EXTS)}"
                )
                return

    # ---------- Загрузка ----------
    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл анимации", "",
            "Animated Files (*.gif *.tgs *.json *.webm)"
        )
        if path:
            self.load_file(path)

    def load_file(self, path):
        ext = os.path.splitext(path)[1].lower().replace(".", "")
        if ext not in ("gif", "tgs", "json", "webm"):
            QMessageBox.warning(self, "Ошибка", f"Формат {ext} не поддерживается.")
            return

        # Ленивый импорт, чтобы не было циклической зависимости с main.py
        try:
            from main import ScreenmateWindow
        except ImportError as e:
            QMessageBox.critical(self, "Ошибка",
                f"Не удалось импортировать ScreenmateWindow из main.py:\n{e}")
            return

        fake_data = {"type": ext, "paths": [path]}

        try:
            self._set_status("Загрузка кадров...")
            temp = ScreenmateWindow(fake_data, None)
            self.frames = list(temp.frames)
            if temp.timer:
                temp.timer.stop()
            temp.close()
            temp.deleteLater()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка загрузки", str(e))
            self._set_status("Ошибка загрузки")
            return

        if not self.frames:
            QMessageBox.warning(self, "Ошибка",
                "Не удалось извлечь кадры из файла.\n"
                "Возможно, файл повреждён или содержит неподдерживаемые данные.")
            self._set_status("Не удалось извлечь кадры")
            return

        self.current_path = path
        self.current = 0
        self.info_label.setText(f"Файл: {os.path.basename(path)}")
        self.canvas.setStyleSheet(
            "border: 2px solid #555; background: #1e1e1e;"
        )

        # Запуск воспроизведения
        if self.timer:
            self.timer.stop()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._next_frame)
        self.timer.start(self.delay)
        self.is_playing = True
        self.play_pause_btn.setText("⏸ Пауза / Pause")
        self.play_pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.create_screenmate_btn.setEnabled(True)

        self._render()
        self._set_status(
            f"Загружено: {os.path.basename(path)}  ·  кадров: {len(self.frames)}"
        )

    # ---------- Создание скринмейта ----------
    def create_screenmate_from_file(self):
        """Добавляет просматриваемый файл в список персонажей главного окна.
        Файл копируется в assets/<char_id>/ через главное окно."""
        if not self.current_path or not os.path.exists(self.current_path):
            QMessageBox.warning(self, "Ошибка", "Сначала откройте файл анимации.")
            return

        parent = self.parent()
        if parent is None or not hasattr(parent, "add_character"):
            QMessageBox.critical(self, "Ошибка",
                "Главное окно недоступно. Откройте плеер через кнопку "
                "«Просмотр анимационных файлов» в главном окне программы.")
            return

        ext = os.path.splitext(self.current_path)[1].lower().replace(".", "")
        char_id = str(uuid.uuid4())

        # Копируем файл в assets/<char_id>/ через метод главного окна
        try:
            new_paths = parent.copy_files_to_assets(char_id, [self.current_path])
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                f"Не удалось скопировать файл в папку assets:\n{e}")
            return

        if not new_paths:
            QMessageBox.critical(self, "Ошибка",
                "Не удалось скопировать файл в папку assets.\n"
                "Проверьте права доступа к папке программы.")
            return

        char_data = {
            "id": char_id,
            "type": ext,
            "paths": new_paths,
            "scale": 1.0,
            "rotation": 0.0,
            "frame_delay": 100,
            "is_visible": False,
        }

        try:
            parent.add_character(char_data)
            self._set_status(
                f"Скринмейт создан: {os.path.basename(self.current_path)}"
            )
            QMessageBox.information(self, "Готово",
                f"Скринмейт создан и добавлен в список:\n\n"
                f"{os.path.basename(self.current_path)}\n\n"
                f"Вы можете включить его в главном окне через кнопку «Показ/Show».")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                f"Не удалось создать скринмейт:\n{e}")

    # ---------- Управление воспроизведением ----------
    def toggle_play(self):
        if not self.frames:
            return
        if self.is_playing:
            if self.timer:
                self.timer.stop()
            self.is_playing = False
            self.play_pause_btn.setText("▶ Играть / Play")
            self._set_status("Пауза")
        else:
            if self.timer is None:
                self.timer = QTimer(self)
                self.timer.timeout.connect(self._next_frame)
            self.timer.start(self.delay)
            self.is_playing = True
            self.play_pause_btn.setText("⏸ Пауза / Pause")
            self._set_status("Воспроизведение...")

    def stop_playback(self):
        if self.timer:
            self.timer.stop()
        self.is_playing = False
        self.current = 0
        self.play_pause_btn.setText("▶ Играть / Play")
        self.play_pause_btn.setEnabled(bool(self.frames))
        self._render()
        self._set_status("Остановлено")

    def _next_frame(self):
        if not self.frames:
            return
        self.current = (self.current + 1) % len(self.frames)
        self._render()

    def _render(self):
        if not self.frames:
            return
        pix = self.frames[self.current]

        if self.rotation != 0:
            pix = pix.transformed(
                QTransform().rotate(self.rotation),
                Qt.TransformationMode.SmoothTransformation
            )
        if self.scale != 1.0:
            size = pix.size() * self.scale
            pix = pix.scaled(size,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)

        self.canvas.setPixmap(pix)

    # ---------- Ползунки ----------
    def _update_scale(self, value):
        self.scale = value / 100.0
        self._render()

    def _update_rotation(self, value):
        self.rotation = value
        self._render()

    def _update_speed(self, value):
        self.delay = value
        if self.timer and self.is_playing:
            self.timer.setInterval(value)

    # ---------- Закрытие ----------
    def closeEvent(self, event):
        if self.timer:
            self.timer.stop()
        # Сообщаем главному окну, что плеер закрыт
        parent = self.parent()
        if parent is not None and hasattr(parent, "_player"):
            parent._player = None
        event.accept()
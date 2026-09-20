import sys
import os
import json
import uuid
import shutil
import hashlib
import tempfile
import subprocess
import cv2
from PIL import Image, ImageSequence
from rlottie_python import LottieAnimation
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QScrollArea, 
                             QFileDialog, QSlider, QDialog, QSystemTrayIcon, 
                             QMenu, QFrame, QMessageBox)
from PyQt6.QtCore import Qt, QTimer, QSize, QPoint, QLockFile
from PyQt6.QtGui import QMovie, QPixmap, QTransform, QIcon, QAction, QImage

# Файл для сохранения данных
DATA_FILE = "screenmates_data.json"
ICON_FILE = "app_icon.ico"

# Файл для логов
LOG_FILE = os.path.join(tempfile.gettempdir(), "smc_debug.log")


def _log_to_file(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")
    except Exception:
        pass


def _log(msg):
    print(msg)
    _log_to_file(msg)


def get_base_dir():
    """Возвращает папку, рядом с которой лежит программа (или exe)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_assets_dir():
    """Возвращает путь к папке assets, создаёт её при необходимости."""
    assets = os.path.join(get_base_dir(), "assets")
    os.makedirs(assets, exist_ok=True)
    return assets


def resource_path(relative_path):
    """Получает путь к встроенному ресурсу (работает и для exe)."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_icon():
    """Возвращает QIcon из app_icon.ico, если файл существует."""
    path = resource_path(ICON_FILE)
    if os.path.exists(path):
        return QIcon(path)
    return QIcon()


def _no_window_kwargs():
    """Возвращает kwargs для subprocess, скрывающие окно консоли на Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _acquire_single_instance_lock():
    """Не даёт запустить вторую копию программы."""
    try:
        if getattr(sys, 'frozen', False):
            key_source = os.path.abspath(sys.executable)
        else:
            key_source = os.path.abspath(__file__)
        h = hashlib.md5(key_source.encode("utf-8")).hexdigest()[:16]
        lock_path = os.path.join(tempfile.gettempdir(), f"screenmatecreator_{h}.lock")

        lock = QLockFile(lock_path)
        lock.setStaleLockTime(0)
        if not lock.tryLock(100):
            return None
        return lock
    except Exception as e:
        _log(f"Ошибка проверки единственного экземпляра: {e}")
        return None


def convert_json_to_tgs(json_path):
    """
    Конвертирует Lottie JSON в TGS напрямую через библиотеку lottie.
    Работает и в PyCharm, и в собранном exe (без subprocess).
    """
    temp_tgs = os.path.join(tempfile.gettempdir(), f"smc_{uuid.uuid4().hex}.tgs")
    try:
        _log(f"Начинаю конвертацию JSON->TGS: {json_path}")

        from lottie.importers import importers
        from lottie.exporters import exporters

        try:
            import lottie.importers.lottie  # noqa: F401
            _log("Импортирован lottie.importers.lottie")
        except Exception as e:
            _log(f"Не удалось импортировать lottie.importers.lottie: {e}")

        try:
            import lottie.exporters.tgs  # noqa: F401
            _log("Импортирован lottie.exporters.tgs")
        except Exception as e:
            _log(f"Не удалось импортировать lottie.exporters.tgs: {e}")

        try:
            available_importers = [imp.name for imp in importers]
            _log(f"Доступные importers: {available_importers}")
        except Exception as e:
            _log(f"Не удалось получить список importers: {e}")

        importer = None
        for name in ("lottie", "json"):
            try:
                importer = importers.get(name)
                if importer is not None:
                    _log(f"Использую importer: {name}")
                    break
            except Exception:
                continue

        if importer is None:
            _log("Не найден Lottie importer в библиотеке lottie.")
            return None

        with open(json_path, "rb") as f:
            animation = importer.process(f)
        _log("JSON успешно распарсен.")

        try:
            available_exporters = [exp.name for exp in exporters]
            _log(f"Доступные exporters: {available_exporters}")
        except Exception as e:
            _log(f"Не удалось получить список exporters: {e}")

        exporter = exporters.get("tgs")
        if exporter is None:
            _log("Не найден TGS exporter в библиотеке lottie.")
            return None

        with open(temp_tgs, "wb") as f:
            exporter.process(animation, f)

        if os.path.exists(temp_tgs) and os.path.getsize(temp_tgs) > 0:
            size = os.path.getsize(temp_tgs)
            _log(f"JSON->TGS успешно: {temp_tgs} ({size} байт)")
            return temp_tgs

        _log("TGS-файл не создан или пуст.")
        return None

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        _log(f"Ошибка конвертации JSON->TGS: {e}\n{tb}")
        return None


class DataManager:
    """Управление сохранением и загрузкой персонажей"""
    @staticmethod
    def load_data():
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                _log(f"Ошибка загрузки данных: {e}")
        return []

    @staticmethod
    def save_data(data):
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            _log(f"Ошибка сохранения данных: {e}")


class ScreenmateWindow(QWidget):
    """Окно самого скринмейта (висит поверх всех окон)"""
    def __init__(self, char_data, main_window):
        super().__init__()
        self.char_data = char_data
        self.main_window = main_window
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                            Qt.WindowType.WindowStaysOnTopHint | 
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        icon = get_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        
        self.label = QLabel(self)
        self.frames = []
        self.current_frame_index = 0
        self.timer = None
        
        self.scale = char_data.get("scale", 1.0)
        self.rotation = char_data.get("rotation", 0.0)
        self.frame_delay = char_data.get("frame_delay", 150)
        
        self.setup_animation()
        self.old_pos = None

    def extract_gif_frames(self, path, preview_only=False):
        frames = []
        try:
            pil_img = Image.open(path)
            for i, frame in enumerate(ImageSequence.Iterator(pil_img)):
                if preview_only and i >= 1:
                    break
                frame = frame.convert("RGBA")
                data = frame.tobytes("raw", "RGBA")
                qimage = QImage(data, frame.width, frame.height, QImage.Format.Format_RGBA8888)
                frames.append(QPixmap.fromImage(qimage))
        except Exception as e:
            _log(f"Ошибка чтения GIF: {e}")
        return frames

    def extract_lottie_frames(self, path, ext, preview_only=False):
        temp_tgs_path = None
        try:
            if ext == 'tgs':
                anim = LottieAnimation.from_tgs(path)
            else:
                temp_tgs_path = convert_json_to_tgs(path)
                if temp_tgs_path:
                    anim = LottieAnimation.from_tgs(temp_tgs_path)
                else:
                    _log("Не удалось конвертировать JSON в TGS, пробую напрямую...")
                    anim = LottieAnimation.from_file(path)
            
            total_frames = anim.lottie_animation_get_totalframe()
            frames = []
            limit = 1 if preview_only else total_frames
            
            for i in range(limit):
                pil_image = anim.render_pillow_frame(frame_num=i)
                data = pil_image.tobytes("raw", "RGBA")
                qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
                frames.append(QPixmap.fromImage(qimage))
            
            anim.lottie_animation_destroy()
            return frames
        except Exception as e:
            _log(f"Ошибка чтения Lottie: {e}")
            return []
        finally:
            if temp_tgs_path and os.path.exists(temp_tgs_path):
                try:
                    os.remove(temp_tgs_path)
                except Exception:
                    pass

    def extract_webm_frames(self, path, preview_only=False):
        """Извлекает кадры из WEBM с альфа-каналом через FFmpeg."""
        frames = []
        temp_dir = tempfile.mkdtemp(prefix="smc_webm_")
        try:
            ffmpeg_path = resource_path(os.path.join("bin", "ffmpeg.exe"))
            if not os.path.exists(ffmpeg_path):
                local = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "bin", "ffmpeg.exe")
                if os.path.exists(local):
                    ffmpeg_path = local
                else:
                    ffmpeg_path = "ffmpeg"

            output_pattern = os.path.join(temp_dir, "frame_%04d.png")
            cmd = [
                ffmpeg_path,
                "-c:v", "libvpx-vp9",
                "-i", path,
                "-fps_mode", "passthrough",
                "-pix_fmt", "rgba",
                output_pattern
            ]
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=180,
                **_no_window_kwargs()
            )

            if result.returncode != 0:
                _log(f"Ошибка FFmpeg: {result.stderr[-2000:]}")
                return []

            frame_files = sorted(f for f in os.listdir(temp_dir) if f.endswith(".png"))
            if not frame_files:
                _log("FFmpeg не извлёк ни одного кадра.")
                return []

            limit = 1 if preview_only else len(frame_files)
            for frame_file in frame_files[:limit]:
                full_path = os.path.join(temp_dir, frame_file)
                img = QImage(full_path).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                pixmap = QPixmap.fromImage(img)
                frames.append(pixmap)

            return frames
        except Exception as e:
            _log(f"Ошибка чтения WEBM: {e}")
            return []
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def setup_animation(self):
        char_type = self.char_data["type"]
        paths = self.char_data["paths"]

        if not paths:
            return

        if char_type == "gif":
            self.frames = self.extract_gif_frames(paths[0])
        elif char_type == "frames":
            self.frames = [QPixmap(p) for p in paths if os.path.exists(p)]
        elif char_type in ["tgs", "json"]:
            self.frames = self.extract_lottie_frames(paths[0], char_type)
        elif char_type == "webm":
            self.frames = self.extract_webm_frames(paths[0])
        
        if self.frames:
            self.apply_transformations()
            self.start_timer()

    def start_timer(self):
        if self.timer:
            self.timer.stop()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)
        self.timer.start(self.frame_delay)

    def set_frame_delay(self, delay_ms):
        self.frame_delay = delay_ms
        if self.timer:
            self.timer.setInterval(delay_ms)

    def next_frame(self):
        if not self.frames: return
        self.current_frame_index = (self.current_frame_index + 1) % len(self.frames)
        self.update_frame()

    def update_frame(self):
        if not self.frames: return
        pixmap = self.frames[self.current_frame_index]
        if pixmap and not pixmap.isNull():
            self.apply_transformations(pixmap)

    def apply_transformations(self, pixmap=None):
        if pixmap is None:
            if not self.frames: return
            pixmap = self.frames[self.current_frame_index]

        if pixmap and not pixmap.isNull():
            if self.rotation != 0:
                transform = QTransform().rotate(self.rotation)
                pixmap = pixmap.transformed(transform, Qt.TransformationMode.SmoothTransformation)

            if self.scale != 1.0:
                size = pixmap.size() * self.scale
                pixmap = pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)

            self.label.setPixmap(pixmap)
            self.label.resize(pixmap.size())
            self.setFixedSize(pixmap.size())

    def showEvent(self, event):
        super().showEvent(event)
        if self.frames:
            self.apply_transformations()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = event.globalPosition().toPoint()
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self.old_pos:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = None

    def show_context_menu(self, pos):
        menu = QMenu(self)
        hide_action = menu.addAction("Скрыть/Hide")
        settings_action = menu.addAction("Настройки/Settings")
        
        action = menu.exec(pos)
        if action == hide_action:
            self.hide()
            if self.main_window is not None:
                self.main_window.update_visibility_state(self.char_data["id"], False)
        elif action == settings_action:
            if self.main_window is not None:
                self.main_window.showNormal()
                self.main_window.activateWindow()


class CreateFramesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create frames")
        self.resize(400, 500)
        self.frames_paths = []
        
        icon = get_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        
        self.layout = QVBoxLayout(self)
        self.assemble_btn = QPushButton("Собрать персонажа/Assemble the character")
        self.assemble_btn.clicked.connect(self.assemble_character)
        self.layout.addWidget(self.assemble_btn)
        
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("Скорость (мс/кадр):"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(20, 500)
        self.speed_slider.setValue(150)
        self.speed_slider.setInvertedAppearance(True)
        speed_layout.addWidget(self.speed_slider)
        self.speed_label = QLabel("150 мс")
        self.speed_slider.valueChanged.connect(lambda v: self.speed_label.setText(f"{v} мс"))
        speed_layout.addWidget(self.speed_label)
        self.layout.addLayout(speed_layout)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll)
        
        self.add_frame_button()

    def add_frame_button(self):
        btn = QPushButton("Добавить файл/кадр : Add file/frame")
        btn.clicked.connect(lambda: self.select_frame(btn))
        self.scroll_layout.addWidget(btn)

    def select_frame(self, button):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите PNG", "", "PNG Files (*.png)")
        if file_path:
            self.frames_paths.append(file_path)
            self.scroll_layout.removeWidget(button)
            button.deleteLater()
            
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                preview = QLabel()
                preview.setPixmap(pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.scroll_layout.addWidget(preview)
            
            self.add_frame_button()

    def assemble_character(self):
        if not self.frames_paths:
            QMessageBox.warning(self, "Ошибка", "Добавьте хотя бы один кадр!")
            return
        
        char_id = str(uuid.uuid4())
        
        new_paths = self.parent().copy_files_to_assets(char_id, self.frames_paths)
        if not new_paths:
            QMessageBox.critical(self, "Ошибка",
                "Не удалось скопировать файлы кадров в папку assets.")
            return
        
        char_data = {
            "id": char_id,
            "type": "frames",
            "paths": new_paths,
            "scale": 1.0,
            "rotation": 0.0,
            "frame_delay": self.speed_slider.value(),
            "is_visible": False
        }
        self.parent().add_character(char_data)
        self.accept()


class CharacterWidget(QWidget):
    def __init__(self, char_data, main_window):
        super().__init__()
        self.char_data = char_data
        self.main_window = main_window
        self.screenmate_window = None
        
        self.layout = QVBoxLayout(self)
        
        top_row = QHBoxLayout()
        
        self.preview = QLabel()
        self.preview.setFixedSize(80, 80)
        self.preview.setStyleSheet("border: 1px solid gray;")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.load_preview()
        top_row.addWidget(self.preview)
        
        btn_column = QVBoxLayout()
        
        self.toggle_btn = QPushButton("Показ/Show")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self.toggle_visibility)
        btn_column.addWidget(self.toggle_btn)
        
        self.delete_btn = QPushButton("Удалить/Delete")
        self.delete_btn.clicked.connect(self.confirm_delete)
        btn_column.addWidget(self.delete_btn)
        
        top_row.addLayout(btn_column)
        
        top_row.addWidget(QLabel("Размер:"))
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(10, 300)
        self.scale_slider.setValue(int(self.char_data.get("scale", 1.0) * 100))
        self.scale_slider.valueChanged.connect(self.update_scale)
        top_row.addWidget(self.scale_slider)
        
        self.layout.addLayout(top_row)
        
        bottom_row = QHBoxLayout()
        
        bottom_row.addWidget(QLabel("Поворот:"))
        self.rot_slider = QSlider(Qt.Orientation.Horizontal)
        self.rot_slider.setRange(0, 360)
        self.rot_slider.setValue(int(self.char_data.get("rotation", 0)))
        self.rot_slider.valueChanged.connect(self.update_rotation)
        bottom_row.addWidget(self.rot_slider)
        
        bottom_row.addWidget(QLabel("Скорость:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(20, 500)
        self.speed_slider.setInvertedAppearance(True)
        self.speed_slider.setValue(self.char_data.get("frame_delay", 150))
        self.speed_slider.valueChanged.connect(self.update_speed)
        bottom_row.addWidget(self.speed_slider)
        
        self.speed_label = QLabel(f"{self.char_data.get('frame_delay', 150)} мс")
        self.speed_label.setFixedWidth(60)
        bottom_row.addWidget(self.speed_label)
        
        self.layout.addLayout(bottom_row)
        
        self.export_btn = QPushButton("Сделать отдельным exe-файлом / Make it a separate exe file")
        self.export_btn.clicked.connect(self.make_exe)
        self.layout.addWidget(self.export_btn)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self.layout.addWidget(line)

    def load_preview(self):
        paths = self.char_data["paths"]
        if not paths: return
        
        temp_sm = ScreenmateWindow(self.char_data, self.main_window)
        if temp_sm.frames:
            self.preview.setPixmap(temp_sm.frames[0].scaled(
                80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if temp_sm.timer:
            temp_sm.timer.stop()
        temp_sm.close()

    def make_exe(self):
        """Собирает отдельный EXE-файл для этого персонажа."""
        temp_sm = ScreenmateWindow(self.char_data, self.main_window)
        frames = list(temp_sm.frames)
        if temp_sm.timer:
            temp_sm.timer.stop()
        temp_sm.close()

        if not frames:
            QMessageBox.warning(self, "Ошибка", "Не удалось загрузить кадры анимации.")
            return

        try:
            from screenmate_export import export_screenmate
        except ImportError:
            QMessageBox.critical(self, "Ошибка",
                "Не найден файл screenmate_export.py рядом с main.py.\n"
                "Убедитесь, что он создан.")
            return

        export_screenmate(self, self.char_data, frames)

    def confirm_delete(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Удаление/Delete")
        msg.setText("Точно удалить скринмейт/Delete the screenshot?")
        icon = get_icon()
        if not icon.isNull():
            msg.setWindowIcon(icon)
        
        yes_btn = msg.addButton("Да/Yes", QMessageBox.ButtonRole.YesRole)
        no_btn = msg.addButton("НЕТ! / NO!", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(no_btn)
        
        msg.exec()
        
        if msg.clickedButton() == yes_btn:
            self.delete_character()

    def delete_character(self):
        if self.screenmate_window:
            self.screenmate_window.hide()
            if self.screenmate_window.timer:
                self.screenmate_window.timer.stop()
            self.screenmate_window.close()
            self.screenmate_window = None
        
        char_id = self.char_data["id"]
        
        try:
            assets_dir = get_assets_dir()
            char_assets = os.path.join(assets_dir, char_id)
            if os.path.isdir(char_assets):
                shutil.rmtree(char_assets, ignore_errors=True)
        except Exception as e:
            _log(f"Не удалось удалить папку assets: {e}")
        
        if char_id in self.main_window.character_widgets:
            del self.main_window.character_widgets[char_id]
        self.main_window.characters = [c for c in self.main_window.characters if c["id"] != char_id]
        self.main_window.save_characters()
        
        self.main_window.scroll_layout.removeWidget(self)
        self.deleteLater()

    def toggle_visibility(self):
        if self.toggle_btn.isChecked():
            self.toggle_btn.setText("Скрыть/Hide")
            self.char_data["is_visible"] = True
            self.show_screenmate()
        else:
            self.toggle_btn.setText("Показ/Show")
            self.char_data["is_visible"] = False
            self.hide_screenmate()

    def show_screenmate(self):
        if not self.screenmate_window:
            self.screenmate_window = ScreenmateWindow(self.char_data, self.main_window)
        else:
            self.screenmate_window.set_frame_delay(self.char_data.get("frame_delay", 150))
        if self.screenmate_window.frames:
            self.screenmate_window.apply_transformations()
        self.screenmate_window.show()
        self.screenmate_window.raise_()

    def hide_screenmate(self):
        if self.screenmate_window:
            self.screenmate_window.hide()

    def update_scale(self, value):
        self.char_data["scale"] = value / 100.0
        if self.screenmate_window:
            self.screenmate_window.scale = self.char_data["scale"]
            self.screenmate_window.apply_transformations()
        self.main_window.save_characters()

    def update_rotation(self, value):
        self.char_data["rotation"] = value
        if self.screenmate_window:
            self.screenmate_window.rotation = self.char_data["rotation"]
            self.screenmate_window.apply_transformations()
        self.main_window.save_characters()

    def update_speed(self, value):
        self.char_data["frame_delay"] = value
        self.speed_label.setText(f"{value} мс")
        if self.screenmate_window:
            self.screenmate_window.set_frame_delay(value)
        self.main_window.save_characters()

    def sync_button_state(self, is_visible):
        self.toggle_btn.setChecked(is_visible)
        self.toggle_btn.setText("Скрыть/Hide" if is_visible else "Показ/Show")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ScreenMateCreator")
        self.resize(800, 600)
        
        icon = get_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        
        get_assets_dir()
        
        self.characters = DataManager.load_data()
        self.character_widgets = {}
        self._player = None
        
        self.setup_ui()
        self.setup_tray()
        self.load_existing_characters()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        header = QLabel("ScreenMateCreator(Milan Agmioli.2026)")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        main_layout.addWidget(header)
        
        top_buttons = QHBoxLayout()
        minimize_btn = QPushButton("Свернуть в панель / Minimize to the Windows tray")
        minimize_btn.clicked.connect(self.hide)
        exit_btn = QPushButton("Закрыть / Exit")
        exit_btn.clicked.connect(self.close_application)
        top_buttons.addWidget(minimize_btn)
        top_buttons.addWidget(exit_btn)
        main_layout.addLayout(top_buttons)
        
        create_section_label = QLabel("СОЗДАНИЕ СКРИНМЕЙТОВ")
        create_section_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        create_section_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-top: 10px; margin-bottom: 5px;")
        main_layout.addWidget(create_section_label)
        
        create_anim_btn = QPushButton("Создать из анимированного файла / Create from an animated file")
        create_anim_btn.clicked.connect(self.create_from_animated)
        main_layout.addWidget(create_anim_btn)
        
        create_seq_btn = QPushButton("Создать из последовательности рисунков / Create from a sequence of drawings")
        create_seq_btn.clicked.connect(self.create_from_sequence)
        main_layout.addWidget(create_seq_btn)
        
        player_section_label = QLabel("Плеер анимаций / Animation player")
        player_section_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        player_section_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-top: 10px; margin-bottom: 5px;")
        main_layout.addWidget(player_section_label)
        
        play_btn = QPushButton("Просмотр анимационных файлов / Play animation")
        play_btn.clicked.connect(self.open_animation_player)
        main_layout.addWidget(play_btn)
        
        list_label = QLabel("СОЗДАННЫЕ ПЕРСОНАЖИ / THE CREATED SCREENMATES")
        list_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        list_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-top: 10px; margin-bottom: 5px;")
        main_layout.addWidget(list_label)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon = get_icon()
        if not icon.isNull():
            self.tray_icon.setIcon(icon)
        else:
            self.tray_icon.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        
        tray_menu = QMenu()
        show_action = QAction("Открыть / Open", self)
        show_action.triggered.connect(self.showNormal)
        exit_action = QAction("Выход / Exit", self)
        exit_action.triggered.connect(self.close_application)
        
        tray_menu.addAction(show_action)
        tray_menu.addAction(exit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def copy_files_to_assets(self, char_id, source_paths):
        """Копирует исходные файлы в assets/<char_id>/ и возвращает новые пути."""
        assets_dir = get_assets_dir()
        char_dir = os.path.join(assets_dir, char_id)
        os.makedirs(char_dir, exist_ok=True)
        
        new_paths = []
        used_names = set()
        
        for i, src in enumerate(source_paths):
            if not os.path.exists(src):
                _log(f"Файл не найден, пропускаю: {src}")
                continue
            
            base_name = os.path.basename(src)
            name_root, name_ext = os.path.splitext(base_name)
            final_name = base_name
            counter = 0
            while final_name in used_names:
                counter += 1
                final_name = f"{name_root}_{counter}{name_ext}"
            used_names.add(final_name)
            
            dst = os.path.join(char_dir, final_name)
            try:
                shutil.copy2(src, dst)
            except shutil.SameFileError:
                pass
            except Exception as e:
                _log(f"Не удалось скопировать {src} -> {dst}: {e}")
                continue
            
            new_paths.append(dst)
        
        return new_paths

    def open_animation_player(self):
        """Открывает окно-плеер для просмотра анимаций."""
        try:
            from animation_player import AnimationPlayerWindow
        except ImportError as e:
            QMessageBox.critical(self, "Ошибка",
                f"Не найден файл animation_player.py рядом с main.py.\n{e}")
            return
        
        if self._player is None:
            self._player = AnimationPlayerWindow(self)
        self._player.show()
        self._player.raise_()
        self._player.activateWindow()

    def create_from_animated(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите анимированный файл", "", 
            "Animated Files (*.gif *.tgs *.json *.webm)"
        )
        if not file_path:
            return
        
        ext = os.path.splitext(file_path)[1].lower().replace('.', '')
        
        if ext == "gif":
            char_type = "gif"
        elif ext in ["tgs", "json"]:
            char_type = ext
        elif ext == "webm":
            char_type = "webm"
        else:
            QMessageBox.warning(self, "Ошибка", f"Формат {ext} не поддерживается.")
            return
        
        char_id = str(uuid.uuid4())
        
        new_paths = self.copy_files_to_assets(char_id, [file_path])
        if not new_paths:
            QMessageBox.critical(self, "Ошибка",
                "Не удалось скопировать файл в папку assets.\n"
                "Проверьте права доступа к папке программы.")
            return
        
        char_data = {
            "id": char_id,
            "type": char_type,
            "paths": new_paths,
            "scale": 1.0,
            "rotation": 0.0,
            "frame_delay": 100,
            "is_visible": False
        }
        self.add_character(char_data)

    def create_from_sequence(self):
        dialog = CreateFramesDialog(self)
        dialog.exec()

    def add_character(self, char_data):
        self.characters.append(char_data)
        self.save_characters()
        
        widget = CharacterWidget(char_data, self)
        self.character_widgets[char_data["id"]] = widget
        self.scroll_layout.addWidget(widget)

    def load_existing_characters(self):
        for char_data in self.characters:
            if "frame_delay" not in char_data:
                char_data["frame_delay"] = 100
            if char_data["frame_delay"] > 500:
                char_data["frame_delay"] = 500
            widget = CharacterWidget(char_data, self)
            self.character_widgets[char_data["id"]] = widget
            self.scroll_layout.addWidget(widget)

    def save_characters(self):
        DataManager.save_data(self.characters)

    def update_visibility_state(self, char_id, is_visible):
        if char_id in self.character_widgets:
            self.character_widgets[char_id].sync_button_state(is_visible)

    def close_application(self):
        """Полное закрытие программы."""
        # Закрываем все окна скринмейтов
        for widget in self.character_widgets.values():
            if widget.screenmate_window:
                try:
                    if widget.screenmate_window.timer:
                        widget.screenmate_window.timer.stop()
                    widget.screenmate_window.close()
                except Exception:
                    pass
        # Закрываем плеер
        if self._player is not None:
            try:
                self._player.close()
            except Exception:
                pass
        # Скрываем трей
        try:
            self.tray_icon.hide()
        except Exception:
            pass

        QApplication.quit()
        # Гарантированный выход через 100 мс, если что-то осталось висеть
        QTimer.singleShot(100, lambda: os._exit(0))

    def closeEvent(self, event):
        """Крестик в заголовке окна = полное закрытие программы."""
        event.accept()
        self.close_application()


if __name__ == "__main__":
    _log("=" * 50)
    _log("Запуск ScreenMateCreator")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Защита от повторного запуска
    instance_lock = _acquire_single_instance_lock()
    if instance_lock is None:
        QMessageBox.information(None, "ScreenMateCreator",
            "Программа ScreenMateCreator уже запущена.\n"
            "ScreenMateCreator is already running.")
        sys.exit(0)

    icon = get_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = MainWindow()
    window.show()

    # Держим ссылку, чтобы lock не собрался сборщиком мусора
    _lock_ref = instance_lock  # noqa: F841

    sys.exit(app.exec())
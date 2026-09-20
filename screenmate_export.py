# screenmate_export.py
import os
import sys
import json
import shutil
import tempfile
import subprocess
from PIL import Image
from PyQt6.QtWidgets import (QFileDialog, QMessageBox, QInputDialog, QLineEdit)


def resource_path(relative):
    try:
        base = sys._MEIPASS
    except Exception:
        base = os.path.abspath(".")
    return os.path.join(base, relative)


def _no_window_kwargs():
    """Скрывает окно консоли дочернего процесса на Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def get_player_dir():
    """Ищет папку ScreenmatePlayer (с exe и _internal внутри)."""
    candidates = [
        resource_path(os.path.join("standalone_player", "ScreenmatePlayer")),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "standalone_player", "ScreenmatePlayer"),
        os.path.join(os.path.dirname(sys.executable),
                     "standalone_player", "ScreenmatePlayer"),
    ]
    for c in candidates:
        if os.path.isdir(c) and os.path.exists(os.path.join(c, "ScreenmatePlayer.exe")):
            return c
    return None


def sanitize_filename(name: str) -> str:
    """Убирает недопустимые для Windows символы в имени файла."""
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, '_')
    name = name.strip('. ')
    if len(name) > 80:
        name = name[:80].rstrip('. ')
    return name


def create_shortcut_via_vbs(shortcut_path, target_path, icon_path=None, working_dir=None):
    """Создаёт .lnk ярлык с кастомной иконкой через WScript.Shell (VBS)."""
    vbs_lines = [
        'Set oWS = WScript.CreateObject("WScript.Shell")',
        f'Set oLink = oWS.CreateShortcut("{shortcut_path}")',
        f'oLink.TargetPath = "{target_path}"',
    ]
    if icon_path:
        vbs_lines.append(f'oLink.IconLocation = "{icon_path}"')
    if working_dir:
        vbs_lines.append(f'oLink.WorkingDirectory = "{working_dir}"')
    vbs_lines.append('oLink.Save')

    vbs_content = "\n".join(vbs_lines)

    tmp_vbs = None
    try:
        fd, tmp_vbs = tempfile.mkstemp(suffix=".vbs")
        os.close(fd)
        with open(tmp_vbs, "w", encoding="cp1251") as f:
            f.write(vbs_content)

        result = subprocess.run(
            ["cscript", "//nologo", tmp_vbs],
            capture_output=True, text=True, timeout=15,
            **_no_window_kwargs()
        )
        if result.returncode != 0:
            print(f"cscript ошибка: {result.stderr or result.stdout}")
            return False
        return os.path.exists(shortcut_path)
    except Exception as e:
        print(f"Ошибка создания ярлыка: {e}")
        return False
    finally:
        if tmp_vbs and os.path.exists(tmp_vbs):
            try:
                os.remove(tmp_vbs)
            except Exception:
                pass


def export_screenmate(parent, char_data, frames):
    """Экспортирует персонажа в отдельную папку с exe и ярлыком."""
    if not frames:
        QMessageBox.warning(parent, "Ошибка", "Нет кадров для экспорта.")
        return

    # 1. Папка плеера
    player_dir = get_player_dir()
    if not player_dir:
        QMessageBox.critical(parent, "Ошибка",
            "Не найдена папка 'standalone_player\\ScreenmatePlayer'.\n\n"
            "Соберите плеер командой:\n"
            "pyinstaller --noconsole --onedir --name=\"ScreenmatePlayer\" standalone_template.py\n"
            "и скопируйте папку dist\\ScreenmatePlayer в\n"
            "standalone_player\\ScreenmatePlayer рядом с main.py.")
        return

    # 2. Папка сохранения
    save_dir = QFileDialog.getExistingDirectory(
        parent,
        "Куда сохранить готовый скринмейт / Where to save"
    )
    if not save_dir:
        return

    # 3. Имя скринмейта
    default_name = f"Screenmate_{char_data['id'][:8]}"
    name, ok = QInputDialog.getText(
        parent,
        "Имя скринмейта / Name of the screenmate",
        "Введите имя (используется для заголовка окна и имени файла):\n"
        "Enter a name (used for window title and file name):",
        QLineEdit.EchoMode.Normal,
        default_name
    )
    if not ok:
        return

    user_name = sanitize_filename(name.strip()) if name.strip() else default_name
    if not user_name:
        user_name = default_name

    # 4. Иконка
    icon_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Иконка для ярлыка (отмена — из первого кадра)",
        "",
        "Icon Files (*.ico)"
    )

    # 5. Папка назначения
    final_dest = os.path.join(save_dir, user_name)
    if os.path.exists(final_dest):
        reply = QMessageBox.question(
            parent, "Папка существует",
            f"Папка '{user_name}' уже существует.\n"
            f"Удалить её содержимое и продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(final_dest)
        except Exception as e:
            QMessageBox.critical(parent, "Ошибка",
                f"Не удалось очистить папку назначения:\n{e}")
            return

    # 6. Копируем папку плеера через robocopy
    try:
        result = subprocess.run(
            ["robocopy", player_dir, final_dest, "/E",
             "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/R:1", "/W:1"],
            capture_output=True, text=True, timeout=300,
            **_no_window_kwargs()
        )
        if result.returncode >= 8:
            QMessageBox.critical(parent, "Ошибка",
                f"robocopy завершился с ошибкой (код {result.returncode}):\n"
                f"{result.stdout[-500:]}\n{result.stderr[-500:]}")
            return
    except Exception as e:
        QMessageBox.critical(parent, "Ошибка",
            f"Не удалось скопировать папку плеера:\n{e}")
        return

    # 7. Переименовываем exe
    src_exe = os.path.join(final_dest, "ScreenmatePlayer.exe")
    dest_exe_name = user_name + ".exe"
    dest_exe = os.path.join(final_dest, dest_exe_name)
    try:
        if os.path.exists(src_exe):
            os.rename(src_exe, dest_exe)
    except Exception as e:
        QMessageBox.critical(parent, "Ошибка",
            f"Не удалось переименовать exe:\n{e}")
        return

    # 8. Кадры
    frames_dir = os.path.join(final_dest, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for i, pix in enumerate(frames):
        pix.save(os.path.join(frames_dir, f"frame_{i:04d}.png"), "PNG")

    # 9. config.json
    config = {
        "title": user_name,
        "scale": char_data.get("scale", 1.0),
        "rotation": char_data.get("rotation", 0.0),
        "frame_delay": char_data.get("frame_delay", 150),
    }
    with open(os.path.join(final_dest, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    # 10. .ico
    dest_icon = os.path.join(final_dest, "app.ico")
    if icon_path and os.path.exists(icon_path):
        try:
            shutil.copy2(icon_path, dest_icon)
        except Exception as e:
            print(f"Не удалось скопировать иконку: {e}")
    else:
        first_png = os.path.join(frames_dir, "frame_0000.png")
        if os.path.exists(first_png):
            try:
                img = Image.open(first_png).convert("RGBA")
                img.save(dest_icon, format="ICO",
                         sizes=[(16, 16), (32, 32), (48, 48),
                                (64, 64), (128, 128), (256, 256)])
            except Exception as e:
                print(f"Не удалось создать иконку: {e}")

    # 11. Ярлык
    shortcut_path = os.path.join(final_dest, user_name + ".lnk")
    shortcut_ok = False
    if os.path.exists(dest_icon):
        shortcut_ok = create_shortcut_via_vbs(
            shortcut_path=shortcut_path,
            target_path=dest_exe,
            icon_path=dest_icon,
            working_dir=final_dest,
        )

    # 12. Итог
    if shortcut_ok:
        hint = (f"\n\n✅ Ярлык с вашей иконкой:\n{user_name}.lnk\n\n"
                f"Запускайте именно ярлык — на нём будет ваша иконка.")
    else:
        hint = f"\n\n⚠ Не удалось создать ярлык.\nЗапускайте {dest_exe_name}."

    QMessageBox.information(parent, "Готово",
        f"Скринмейт «{user_name}» успешно создан!\n\n"
        f"Папка: {final_dest}\n\n"
        f"Запускайте файл:\n{user_name}\\{user_name}.exe"
        f"{hint}")
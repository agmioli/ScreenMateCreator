@echo off
cd /d E:\ScreenMateCreator
pyinstaller --noconsole --onefile --name="ScreenMateCreator" --icon="app_icon.ico" --add-data "app_icon.ico;." --add-data "standalone_template.py;." --add-data "bin\ffmpeg.exe;bin" --add-data "bin\ffprobe.exe;bin" --collect-all rlottie_python --collect-all cv2 --collect-all PIL --collect-all lottie --collect-all cairosvg --collect-all av main.py
pause
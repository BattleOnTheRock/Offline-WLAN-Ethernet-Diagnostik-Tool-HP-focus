@echo off
rem Baut dist\WLAN-Diagnose.exe (eine Datei, ohne Konsole, fordert Adminrechte an).
python -m pip install --upgrade pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --uac-admin --name WLAN-Diagnose run.py || exit /b 1
echo.
echo Fertig: dist\WLAN-Diagnose.exe

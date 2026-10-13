@echo off
rem ============================================================
rem  Rebuilds D:\zyro\ZYRO.exe (the portable desktop-app file).
rem  Double-click this file any time after changing Zyro's code.
rem
rem  The exe bundles gui.py + core\ + ALL libraries INCLUDING
rem  yt-dlp, so video downloads work with no venv installed.
rem  It is also the file that goes into ZYRO-setup.zip for others.
rem ============================================================
cd /d D:\zyro

venv\Scripts\python.exe -m pip install --quiet pyinstaller
venv\Scripts\pyinstaller.exe --noconfirm --onefile --windowed ^
    --icon=zyro.ico --name=ZYRO gui.py
if errorlevel 1 (
    echo.
    echo BUILD FAILED -- see the messages above.
    pause
    exit /b 1
)

copy /y dist\ZYRO.exe ZYRO.exe >nul
rmdir /s /q build 2>nul
del ZYRO.spec 2>nul

echo.
echo Done. Your portable app is at:  D:\zyro\ZYRO.exe
echo (make_installer.bat builds the shareable ZYRO-setup.zip)
pause

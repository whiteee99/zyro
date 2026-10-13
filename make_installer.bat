@echo off
rem ============================================================
rem  Builds ZYRO-setup.zip -- the shareable installer zip for
rem  OTHER people's PCs. Double-click this file any time.
rem
rem  The zip contains everything ZYRO needs on a new PC:
rem    ZYRO.exe (whole app + all libraries incl. yt-dlp),
rem    tools\ffmpeg (video/music converter),
rem    skills\ (the know-how files),
rem    zyro.ico, README.txt (setup steps) and install.ps1
rem    (desktop icon + Ctrl+Alt+Z hotkey).
rem
rem  The only thing others install themselves: Ollama + the free
rem  qwen3:1.7b model (README.txt explains how, 2 minutes).
rem ============================================================
cd /d D:\zyro

echo [1/3] Building the exe (about a minute)...
venv\Scripts\python.exe -m pip install --quiet pyinstaller
venv\Scripts\pyinstaller.exe --noconfirm --onefile --windowed ^
    --icon=zyro.ico --name=ZYRO gui.py
if errorlevel 1 (
    echo BUILD FAILED -- see the messages above.
    pause
    exit /b 1
)
copy /y dist\ZYRO.exe ZYRO.exe >nul
rmdir /s /q build 2>nul
del ZYRO.spec 2>nul

echo [2/3] Collecting files...
rmdir /s /q release 2>nul
mkdir release\ZYRO\tools\ffmpeg release\ZYRO\skills
copy /y ZYRO.exe release\ZYRO\ >nul
copy /y zyro.ico release\ZYRO\ >nul
copy /y installer_files\README.txt release\ZYRO\ >nul
copy /y installer_files\install.ps1 release\ZYRO\ >nul
copy /y skills\*.md release\ZYRO\skills\ >nul
copy /y tools\ffmpeg\ffmpeg.exe release\ZYRO\tools\ffmpeg\ >nul
copy /y tools\ffmpeg\ffprobe.exe release\ZYRO\tools\ffmpeg\ >nul

echo [3/3] Zipping (a few minutes for ~400 MB)...
powershell -NoProfile -Command "Compress-Archive -Path 'D:\zyro\release\ZYRO\*' -DestinationPath 'D:\zyro\ZYRO-setup.zip' -Force"
rmdir /s /q release 2>nul
rmdir /s /q dist 2>nul

echo.
echo Done! Share this file:  D:\zyro\ZYRO-setup.zip
pause

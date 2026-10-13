==========================================================
  ZYRO -- your personal AI  (read me first!)
==========================================================

WHAT THIS IS
------------
ZYRO is a personal AI assistant that runs fully on YOUR Windows PC.
It chats, controls the PC, downloads videos/files and installs
software for you. Nothing goes to any cloud -- it uses a free local
AI model called Ollama.


STEP 1 -- UNZIP
---------------
Unzip this folder anywhere you like (D:\ZYRO is a nice spot) and
keep the files together. Everything ZYRO saves (chats, downloads,
screenshots) stays INSIDE this folder.


STEP 2 -- INSTALL OLLAMA (the AI brain, one time)
-------------------------------------------------
ZYRO needs the free Ollama app + one small model (~1.4 GB):

  1. Download Ollama from  https://ollama.com/download  and install.
  2. Open a terminal (Windows key, type "cmd", Enter) and run:
         ollama pull qwen3:1.7b
     Wait for the download to finish.
  3. Keep Ollama running (it sits in the tray by default).


STEP 3 -- RUN ZYRO
------------------
Double-click  ZYRO.exe  in this folder.
(If Windows shows a blue "Windows protected your PC" box, that is
normal for new apps: click "More info" -> "Run anyway".)

OPTIONAL -- desktop icon + Ctrl+Alt+Z hotkey
--------------------------------------------
Right-click  install.ps1  ->  "Run with PowerShell". This adds:
  - a ZYRO icon on your desktop
  - the Ctrl+Alt+Z hotkey (opens/focuses ZYRO from anywhere,
    starts automatically with Windows)


WHAT IT CAN DO (just ask in normal words)
-----------------------------------------
- Files: list, read, write, open; search this drive by name
- Downloads: any file link; YouTube videos as mp4 or mp3
  (saved into downloads\ and downloads\videos\)
- Software: search and install from the Windows catalogue
  (always asks first)
- PC control: volume, media keys, screenshots, clipboard,
  wallpaper, open apps/sites, move/close windows, game mode,
  system info, run Windows commands (dangerous ones always ask)
- Skills: it knows recipes like file-organizer, gaming-session,
  video-music, daily-briefing -- ask "use the daily-briefing skill"
- CODE MODE: click "CODE" (top-right) and pick a project folder and
  ZYRO works on your code like a coding assistant: it reads the real
  files, shows a DIFF of every change before it happens, runs
  commands and tests, and can UNDO the last change. Four modes:
  PLAN (read only), ASK (everything waits for your yes), EDIT (file
  changes apply, commands ask) and AUTO. Deleting files, emptying
  the Recycle Bin, killing a process, shutting down and downloading
  video ALWAYS ask, in every mode.

TIPS
----
- The AUTO button toggles whether normal skills ask permission.
- Installing/deleting/shutdown-type actions ALWAYS ask first.
- The X button really quits: it saves, stops Ollama and closes, so
  nothing is left in RAM. Use the tray menu to only HIDE the window.
- If ZYRO answers nothing: check that Ollama is running.
- Errors are logged to zyro_error.log in this folder.

REQUIREMENTS: Windows 10/11 64-bit, 8 GB RAM recommended,
Ollama + the qwen3:1.7b model (free), internet for downloads.
For CODE mode qwen3:4b is a better brain: ollama pull qwen3:4b

==========================================================

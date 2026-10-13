"""ZYRO's location logic (Phase 10: portable installs).

PROJECT_ROOT is where ZYRO lives:
  - running from source -> the project folder (D:\\zyro on the
    owner's machine, wherever it was unzipped elsewhere)
  - running as the frozen ZYRO.exe -> the exe's own folder

Every folder (memory, downloads, captures, skills, tools) hangs off
this root, so a copied/cloned install keeps working on any drive.
"""

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller onefile: sys.executable IS the exe the user ran.
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The drive ZYRO is installed on (e.g. "D:\\"). search_files and
# set_wallpaper are allowed anywhere on THIS drive only.
DRIVE_ROOT = PROJECT_ROOT.anchor

MEMORY_DIR = PROJECT_ROOT / "memory"
DOWNLOAD_DIR = PROJECT_ROOT / "downloads"
VIDEO_DIR = DOWNLOAD_DIR / "videos"
CAPTURE_DIR = PROJECT_ROOT / "captures"
SKILLS_DIR = PROJECT_ROOT / "skills"
FFMPEG_DIR = PROJECT_ROOT / "tools" / "ffmpeg"
ICON_FILE = PROJECT_ROOT / "zyro.ico"

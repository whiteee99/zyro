"""ZYRO's hotkey helper core -- the Ctrl+Alt+Z summoner.

Runs either as hotkey.pyw (source install, via pythonw) or as
"ZYRO.exe --hotkey" (portable install). Waits for Ctrl+Alt+Z, then
focuses the System window or launches it.
"""

import ctypes
import subprocess
import sys
from ctypes import wintypes

from core import paths

USER32 = ctypes.windll.user32
KERNEL32 = ctypes.windll.kernel32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000   # holding the combo fires once, not repeatedly
VK_Z = 0x5A
WM_HOTKEY = 0x0312
HOTKEY_ID = 0xB100      # arbitrary id, just must be ours
SW_RESTORE = 9
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# The GUI window title set by gui.py -- exact match for FindWindow.
WINDOW_TITLE = "\u25c6 SYSTEM \u25c6"

LOG = paths.PROJECT_ROOT / "zyro_error.log"


def log(text):
    """Append one line to the shared ZYRO log (best effort)."""
    try:
        from datetime import datetime
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    + " [hotkey] " + text + "\n")
    except OSError:
        pass


def summon():
    """Ctrl+Alt+Z just fired: focus ZYRO, or start it if it is closed."""
    hwnd = USER32.FindWindowW(None, WINDOW_TITLE)
    # A zombie app can leave an invisible window with our title whose
    # thread no longer pumps messages -- Windows' own IsHungAppWindow
    # detects that, and we treat it as "not open".
    if hwnd and USER32.IsHungAppWindow(hwnd):
        hwnd = None
    if hwnd:
        # Hidden-to-tray (withdrawn) and minimized windows both count
        # as "open" -- show them again, then bring them to the front.
        if USER32.IsIconic(hwnd) or not USER32.IsWindowVisible(hwnd):
            USER32.ShowWindow(hwnd, SW_RESTORE)
        USER32.SetForegroundWindow(hwnd)
        log("raised the existing ZYRO window")
    else:
        try:
            if getattr(sys, "frozen", False):
                # Portable install: the exe itself, no args = GUI mode.
                subprocess.Popen([sys.executable],
                                 cwd=str(paths.PROJECT_ROOT))
            else:
                # Source install: the project's own venv pythonw.
                pythonw = str(paths.PROJECT_ROOT / "venv" / "Scripts"
                              / "pythonw.exe")
                gui = str(paths.PROJECT_ROOT / "gui.py")
                subprocess.Popen([pythonw, gui],
                                 cwd=str(paths.PROJECT_ROOT))
            log("launched ZYRO via Ctrl+Alt+Z")
        except OSError as e:
            log(f"could not launch ZYRO ({e})")


def main():
    if not USER32.RegisterHotKey(None, HOTKEY_ID,
                                 MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
                                 VK_Z):
        err = KERNEL32.GetLastError()
        if err == ERROR_HOTKEY_ALREADY_REGISTERED:
            log("another hotkey helper is already running -- exiting")
            sys.exit(0)  # not an error: the first helper owns the key
        log(f"RegisterHotKey failed (error {err}) -- Ctrl+Alt+Z is "
            "probably taken by another program")
        USER32.MessageBoxW(
            0, "ZYRO could not register Ctrl+Alt+Z.\nAnother program "
               "probably uses this combination.", "ZYRO hotkey", 0x30)
        sys.exit(1)
    log("listening for Ctrl+Alt+Z")

    msg = wintypes.MSG()
    # The classic Windows message loop: sleep until a message arrives.
    # summon() is wrapped so one bad launch can never silently kill
    # the loop (which is exactly how the hotkey once went dead).
    while USER32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
            try:
                summon()
            except Exception as e:
                log(f"summon failed ({e})")

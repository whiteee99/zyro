"""ZYRO's extra PC-control tools (Phase 9).

screenshot      -- save a PNG of the screen into D:\\zyro\\captures
clipboard_read  -- read the clipboard's text
clipboard_write -- put text on the clipboard
system_info     -- CPU, RAM, disks, battery summary
media_key       -- press play / next / previous / stop / volume keys
search_files    -- find files on D: by name (read-only)
list_processes  -- list running programs
open_file       -- open any file inside D:\\zyro with Windows' default app
set_wallpaper   -- set the desktop wallpaper (image must be on D:)

Every function returns a plain string and catches its own errors, so
ZYRO never crashes. Writes stay inside D:\\zyro (captures only).
"""

import ctypes
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from core import paths

# Screenshots land inside the install folder.
CAPTURE_DIR = paths.CAPTURE_DIR
ZYRO_ROOT = paths.PROJECT_ROOT

# Path of the most recent screenshot -- the vision flow attaches it.
LAST_CAPTURE = None

# search_files caps, so a huge disk scan cannot run forever or flood
# the model's context.
MAX_SEARCH_RESULTS = 100
MAX_SEARCH_SECONDS = 20

# The media keys media_key may press (VK codes), hand-written -- the
# model can only pick a key from this map, never send its own code.
MEDIA_KEYS = {
    "play": 0xB3,        # play/pause toggle
    "next": 0xB0,
    "previous": 0xB1,
    "stop": 0xB2,
    "volumeup": 0xAF,
    "volumedown": 0xAE,
    "mute": 0xAD,
}


def inside_zyro(path_text):
    """Resolve a (relative or absolute) path and allow it ONLY if it
    lands inside D:\\zyro. Returns the full Path or None."""
    if not isinstance(path_text, str) or not path_text.strip():
        return None
    stripped = path_text.strip()
    try:
        full = (ZYRO_ROOT / stripped).resolve()
    except (OSError, ValueError):
        return None
    base = str(ZYRO_ROOT.resolve()).lower()
    text = str(full).lower()
    if text == base or text.startswith(base + "\\"):
        return full
    return None


def screenshot():
    """Capture the whole screen into D:\\zyro\\captures as a PNG."""
    global LAST_CAPTURE
    try:
        from PIL import ImageGrab
    except ImportError:
        return ("ERROR: Pillow is not installed. Run: "
                "venv\\Scripts\\python -m pip install pillow")
    try:
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime("screenshot_%Y%m%d_%H%M%S.png")
        target = CAPTURE_DIR / name
        image = ImageGrab.grab()
        image.save(target, "PNG")
    except Exception as e:
        return f"ERROR: could not take the screenshot ({e})."
    LAST_CAPTURE = str(target)  # the engine attaches it for vision
    kb = target.stat().st_size / 1024
    return (f"OK: screenshot saved as {name} ({kb:.0f} KB) in "
            f"D:\\zyro\\captures.")


def clipboard_read():
    """Return the text currently on the Windows clipboard."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13
    if not user32.OpenClipboard(0):
        return "ERROR: the clipboard is busy, try again."
    try:
        user32.GetClipboardData.restype = ctypes.c_void_p
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return "(the clipboard holds no text right now)"
        kernel32.GlobalLock.restype = ctypes.c_void_p
        pointer = kernel32.GlobalLock(ctypes.c_void_p(handle))
        if not pointer:
            return "ERROR: could not read the clipboard data."
        try:
            text = ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(ctypes.c_void_p(handle))
        text = text.strip()
        if len(text) > 2000:
            text = text[:2000] + " ...[clipboard continues]"
        return text if text else "(the clipboard is empty)"
    except Exception as e:
        return f"ERROR: could not read the clipboard ({e})."
    finally:
        user32.CloseClipboard()


def clipboard_write(text):
    """Replace the clipboard's content with the given text."""
    if not isinstance(text, str):
        return "ERROR: clipboard_write needs text 'content'."
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    # Exact 64-bit signatures: without these, ctypes truncates the
    # HGLOBAL handle / pointer and GlobalLock fails.
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
    if not user32.OpenClipboard(0):
        return "ERROR: the clipboard is busy, try again."
    try:
        user32.EmptyClipboard()
        data = ctypes.create_unicode_buffer(text)
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE,
                                      ctypes.sizeof(data))
        if not handle:
            return "ERROR: could not allocate clipboard memory."
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return "ERROR: could not prepare the clipboard data."
        ctypes.memmove(pointer, data, ctypes.sizeof(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            return "ERROR: Windows refused the clipboard update."
        return f"OK: {len(text)} characters put on the clipboard."
    except Exception as e:
        return f"ERROR: could not write the clipboard ({e})."
    finally:
        user32.CloseClipboard()


def _battery_line():
    """One line about the battery, or None on a desktop PC."""
    try:
        import psutil
        battery = psutil.sensors_battery()
    except Exception:
        return None
    if battery is None:
        return None
    state = "plugged in" if battery.power_plugged else "on battery"
    return f"Battery: {battery.percent:.0f}% ({state})"


def system_info():
    """A short summary of the PC's hardware: CPU, RAM, both disks,
    battery."""
    import platform
    import shutil
    lines = []
    try:
        import psutil
        vm = psutil.virtual_memory()
        lines.append(f"RAM: {vm.total / (1024 ** 3):.1f} GB total, "
                     f"{vm.available / (1024 ** 3):.1f} GB free")
        cpu = psutil.cpu_percent(interval=0.3)
        lines.append(f"CPU: {platform.processor() or 'x64'} "
                     f"({os.cpu_count()} threads, {cpu:.0f}% busy now)")
    except Exception:
        lines.append(f"CPU: {os.cpu_count()} threads")
    for drive in ("C:\\", "D:\\"):
        try:
            total, used, free = shutil.disk_usage(drive)
            lines.append(f"Disk {drive[0]}: {free / (1024 ** 3):.0f} GB "
                         f"free of {total / (1024 ** 3):.0f} GB")
        except OSError:
            pass
    battery = _battery_line()
    if battery:
        lines.append(battery)
    return "\n".join(lines) or "ERROR: could not read the system info."


def media_key(key):
    """Press one media key (play, next, previous, stop, volumeup,
    volumedown, mute) for every app at once."""
    if key not in MEDIA_KEYS:
        return ("ERROR: key must be one of: "
                + ", ".join(sorted(MEDIA_KEYS)) + ".")
    try:
        user32 = ctypes.windll.user32
        code = MEDIA_KEYS[key]
        user32.keybd_event(code, 0, 0, 0)      # key down
        user32.keybd_event(code, 0, 2, 0)      # key up (2 = KEYEVENTF_KEYUP)
    except Exception as e:
        return f"ERROR: could not press the media key ({e})."
    return f"OK: pressed the {key} media key."


def search_files(name, root=r"D:\\"):
    """Find files on D: whose name contains the given text. Read-only,
    capped in time and results, and it never leaves the D: drive."""
    if not isinstance(name, str) or not name.strip():
        return "ERROR: search_files needs a 'name' to look for."
    needle = name.strip().lower()
    drive = paths.DRIVE_ROOT.strip("\\").lower()
    base = root if (isinstance(root, str)
                    and root.strip().lower().startswith(drive)) \
        else paths.DRIVE_ROOT
    try:
        hits = []
        start = time.time()
        skip = {"$recycle.bin", "system volume information"}
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d.lower() not in skip]
            for fname in filenames:
                if needle in fname.lower():
                    hits.append(os.path.join(dirpath, fname))
                    if len(hits) >= MAX_SEARCH_RESULTS:
                        break
            if (len(hits) >= MAX_SEARCH_RESULTS
                    or time.time() - start > MAX_SEARCH_SECONDS):
                break
    except Exception as e:
        return f"ERROR: the search failed ({e})."
    if not hits:
        return f"(no files on D: match \"{needle}\")"
    shown = "\n".join(hits[:MAX_SEARCH_RESULTS])
    if len(shown) > 3000:
        shown = shown[:3000] + " ...[more results not shown]"
    extra = (f"\n...[stopped at {MAX_SEARCH_RESULTS} results]"
             if len(hits) >= MAX_SEARCH_RESULTS else "")
    return f"Found {len(hits)} file(s):\n" + shown + extra


def list_processes():
    """List the running programs (name + memory), capped."""
    try:
        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True, text=True, errors="replace", timeout=30)
    except Exception as e:
        return f"ERROR: could not list processes ({e})."
    lines = []
    for line in (result.stdout or "").splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 5:
            lines.append(f"{parts[0]}  (pid {parts[1]}, {parts[4]} K)")
    if not lines:
        return "(no process list returned)"
    return "\n".join(lines[:80])


def open_file(path):
    """Open any file inside D:\\zyro with Windows' default app (a
    downloaded game, video, installer...). The permission gate has
    already verified the path stays inside D:\\zyro."""
    full = inside_zyro(path)
    if full is None or not full.is_file():
        return ("ERROR: that file was not found inside D:\\zyro "
                f"({path}).")
    try:
        os.startfile(str(full))
    except OSError as e:
        return f"ERROR: could not open the file ({e})."
    return f"OK: opened {full.name}."


def set_wallpaper(path):
    """Set the desktop wallpaper. The image may live anywhere on D:.
    The permission gate has already verified the path is on D:."""
    try:
        if not os.path.isfile(path):
            return f"ERROR: no image found at {path}."
        SPI_SETDESKWALLPAPER = 0x0014
        SPIF_UPDATEANDSEND = 0x03
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER, 0, str(path), SPIF_UPDATEANDSEND)
    except Exception as e:
        return f"ERROR: could not set the wallpaper ({e})."
    if not ok:
        return "ERROR: Windows refused the wallpaper change."
    return f"OK: desktop wallpaper set to {os.path.basename(path)}."

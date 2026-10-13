"""ZYRO's tools (Phases 3-8 + finale + AGENT MODE + web + repo explorer).

Phase 3 tools only READ; they are safe to auto-run. Phase 4 adds
write_file / append_file. Phase 5 adds system tools (set_volume /
mute_toggle / open_app). Phase 7 adds open_site. Phase 8 adds
game_mode. The finale adds move_window / close_window. AGENT MODE
adds run_command: real Windows shell commands. WEB READING adds
read_site. REPO EXPLORER adds list_repo: list files INSIDE any
GitHub repo folder (handles /tree/BRANCH/ links and folder names
with spaces). Every function returns a plain string and catches its
own errors, so ZYRO never crashes.
"""

import os
import subprocess
import urllib.parse
from datetime import datetime

from core import downloads, sysops  # Phase 9: downloads + PC control
from core import skills             # Phase 10: loadable know-how
from core import browser            # Phase 11: visible browser
from core import devtools           # Phase 11: grep / edit / python

# read_file never returns more than this many characters, so a huge
# file cannot blow up the model's small context window.
MAX_READ_CHARS = 2000

# Phase 4: write_file / append_file never accept more content than this,
# so one reply cannot fill the disk or drown the model's context.
MAX_WRITE_CHARS = 10000

# AGENT MODE: command output is capped so a chatty command (like a
# huge dir) cannot flood the model's small context window.
MAX_COMMAND_OUTPUT = 4000

# WEB READING: page text is capped for the same reason.
MAX_SITE_CHARS = 4000

# REPO EXPLORER: max items listed per folder.
MAX_LIST_ITEMS = 100

# Phase 5: the ONLY apps open_app may launch. This dict is hand-written
# on purpose -- the model can never add to it, never pass a path, and
# never launch anything that is not listed here. Keys are the friendly
# names the model may ask for; values are the real programs.
ALLOWED_APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
}


def run_tool(request):
    """Run one validated tool request and return the result as a string."""
    tool = request["tool"]
    if tool == "list_files":
        return _list_files(request["path"])
    if tool == "read_file":
        return _read_file(request["path"])
    if tool == "get_time":
        return _get_time()
    if tool == "write_file":
        return _write_file(request.get("path"), request.get("content"), "w")
    if tool == "append_file":
        return _write_file(request.get("path"), request.get("content"), "a")
    if tool == "set_volume":
        return _set_volume(request.get("level"))
    if tool == "mute_toggle":
        return _mute_toggle()
    if tool == "open_app":
        return _open_app(request.get("app"))
    if tool == "open_site":
        return _open_site(request.get("url"))
    if tool == "game_mode":
        return _game_mode(request.get("state"))
    if tool == "move_window":
        return _move_window(request.get("window"), request.get("place"))
    if tool == "close_window":
        return _close_window(request.get("window"))
    if tool == "run_command":
        return _run_command(request.get("command"))
    if tool == "read_site":
        return _read_site(request.get("url"))
    if tool == "list_repo":
        return _list_repo(request.get("url"))
    # ---------- Phase 9: downloads, software and PC control ----------
    if tool == "download_file":
        return downloads.download_file(request.get("url"),
                                       request.get("name"))
    if tool == "download_video":
        return downloads.download_video(request.get("url"),
                                        request.get("kind", "video"))
    if tool == "winget_search":
        return downloads.winget_search(request.get("query"))
    if tool == "winget_install":
        return downloads.winget_install(request.get("app_id"))
    if tool == "screenshot":
        return sysops.screenshot()
    if tool == "clipboard_read":
        return sysops.clipboard_read()
    if tool == "clipboard_write":
        return sysops.clipboard_write(request.get("content"))
    if tool == "media_key":
        return sysops.media_key(request.get("key"))
    if tool == "system_info":
        return sysops.system_info()
    if tool == "search_files":
        return sysops.search_files(request.get("name"),
                                   request.get("root", "D:\\"))
    if tool == "list_processes":
        return sysops.list_processes()
    if tool == "open_file":
        return sysops.open_file(request.get("path"))
    if tool == "set_wallpaper":
        return sysops.set_wallpaper(request.get("path"))
    if tool == "read_skill":
        return skills.read_skill(request.get("name"))
    # ---------- Phase 11: dev tools, vision, browser, model ----------
    if tool == "search_in_files":
        return devtools.search_in_files(request.get("pattern"),
                                        request.get("root"))
    if tool == "edit_file":
        return devtools.edit_file(request.get("path"),
                                  request.get("find"),
                                  request.get("replace"))
    if tool == "run_python":
        return devtools.run_python(request.get("code"))
    if tool == "look_screen":
        result = sysops.screenshot()
        from core import advisor
        if result.startswith("OK:") and advisor.vision_model() is None:
            result += (" NOTE: no vision model is installed, so I "
                       "cannot see it yet -- ask the user to install "
                       "moondream (suggest_model shows how).")
        return result
    if tool == "look_image":
        path = request.get("path")
        if not path or not os.path.isfile(path):
            return "ERROR: that image file was not found."
        sysops.LAST_CAPTURE = path  # the engine attaches it
        return f"OK: image ready for me to look at: {path}"
    if tool == "browser_open":
        return browser.open_url(request.get("url"))
    if tool == "browser_click":
        return browser.click(request.get("text"))
    if tool == "browser_type":
        return browser.fill(request.get("label"),
                            request.get("value"))
    if tool == "browser_close":
        return browser.close_browser()
    if tool == "update_ytdlp":
        return downloads.update_ytdlp()
    # suggest_model / switch_model are engine-special (they need the
    # current model); they never reach this dispatcher.
    return "ERROR: unknown tool."  # can't happen, but stay safe


def _list_files(folder):
    """Return the names in a folder, one per line, sorted."""
    try:
        names = sorted(os.listdir(folder))
    except OSError as e:
        return f"ERROR: cannot list that folder ({e})."
    if not names:
        return "(the folder is empty)"
    return "\n".join(names)


def _read_file(path):
    """Return the first 2000 characters of a text file."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(MAX_READ_CHARS)
    except OSError as e:
        return f"ERROR: cannot read that file ({e})."
    if len(content) == MAX_READ_CHARS:
        content += "\n...[file continues -- first 2000 characters shown]"
    return content if content.strip() else "(the file is empty)"


def _write_file(path, content, mode):
    """Shared engine for write_file (mode "w") and append_file (mode "a").
    "w" creates the file or overwrites it completely; "a" adds content
    at the end (and creates the file if it does not exist yet)."""
    if not isinstance(path, str) or not isinstance(content, str):
        return "ERROR: a write needs a text 'path' and text 'content'."
    if len(content) > MAX_WRITE_CHARS:
        return (f"ERROR: content is {len(content)} characters, but the "
                f"limit is {MAX_WRITE_CHARS}. Write a shorter text.")
    try:
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return f"ERROR: cannot write that file ({e})."
    verb = "overwrote" if mode == "w" else "appended to"
    return f"OK: {verb} {path} ({len(content)} characters written)."


def _get_time():
    """Return the current local date and time."""
    return datetime.now().strftime("%A %d %B %Y, %H:%M")


def _get_volume_control():
    """Return a pycaw master-volume control, or None if the Windows
    audio system is unreachable (no speakers, COM trouble, ...). pycaw
    is imported here, not at the top, so a missing/broken audio stack
    can never stop ZYRO from starting."""
    try:
        from pycaw.pycaw import AudioUtilities
        device = AudioUtilities.GetSpeakers()
        if hasattr(device, "EndpointVolume"):
            # pycaw 2026: GetSpeakers() returns an AudioDevice wrapper.
            return device.EndpointVolume
        # Older pycaw: GetSpeakers() returns the raw COM device, so we
        # activate the volume interface on it ourselves.
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume
        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception:
        return None


def _set_volume(level):
    """Set the master volume to a whole number from 0 to 100. Refuses
    (politely) anything else -- bool, text, floats, out-of-range numbers."""
    if isinstance(level, bool) or not isinstance(level, int):
        return ("ERROR: 'level' must be a whole number between 0 and 100 "
                '(like "level": 30).')
    if not 0 <= level <= 100:
        return "ERROR: volume level must be between 0 and 100."
    volume = _get_volume_control()
    if volume is None:
        return "ERROR: could not reach the Windows volume control."
    try:
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
    except Exception as e:
        return f"ERROR: could not set the volume ({e})."
    return f"OK: master volume set to {level}%."


def _mute_toggle():
    """Flip the master mute: muted becomes unmuted and back."""
    volume = _get_volume_control()
    if volume is None:
        return "ERROR: could not reach the Windows volume control."
    try:
        was_muted = bool(volume.GetMute())
        volume.SetMute(not was_muted, None)
    except Exception as e:
        return f"ERROR: could not change the mute ({e})."
    return "OK: volume unmuted." if was_muted else "OK: volume muted."


def _open_app(app):
    """Launch one app from the fixed ALLOWED_APPS list. Anything else --
    other names, full paths, made-up programs -- gets a polite refusal."""
    if not isinstance(app, str) or not app.strip():
        return ("ERROR: 'app' must be a name from the allowed list: "
                + ", ".join(sorted(ALLOWED_APPS)) + ".")
    app = app.strip().lower()
    if app not in ALLOWED_APPS:
        return ("ERROR: I am only allowed to open these apps: "
                + ", ".join(sorted(ALLOWED_APPS)) + ".")
    try:
        os.startfile(ALLOWED_APPS[app])
    except OSError as e:
        return f"ERROR: could not open {app} ({e})."
    return f"OK: opened {app}."


def _open_site(url):
    """PHASE 7: open one allowed website in the default browser. The
    permission gate has already checked the site is on the allowed
    list -- this function just opens it."""
    if not isinstance(url, str) or not url.strip():
        return "ERROR: open_site needs a website address."
    try:
        os.startfile(url)
    except OSError as e:
        return f"ERROR: could not open the website ({e})."
    return f"OK: opened {url} in your browser."


def _game_mode(state):
    """PHASE 8: flip Windows' own Game Mode on or off. This touches ONE
    known registry key in HKEY_CURRENT_USER with fixed values -- no
    commands, no other keys, fully reversible with the matching "off".
    winreg is built into Python, so no new package is needed."""
    if state not in ("on", "off"):
        return "ERROR: game_mode state must be \"on\" or \"off\"."
    try:
        import winreg
        value = 1 if state == "on" else 0
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar",
            0, winreg.KEY_SET_VALUE)
        try:
            winreg.SetValueEx(key, "AllowAutoGameMode", 0,
                              winreg.REG_DWORD, value)
            winreg.SetValueEx(key, "AutoGameModeEnabled", 0,
                              winreg.REG_DWORD, value)
        finally:
            key.Close()
    except OSError as e:
        return f"ERROR: could not change Game Mode ({e})."
    return f"OK: Windows Game Mode turned {state}."


def _find_window(title):
    """Shared helper: find one visible window whose title CONTAINS the
    given word. Returns the window handle, or None."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                   wintypes.LPARAM)

    def on_window(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                found.append((hwnd, buf.value))
        return True

    callback = enum_proc(on_window)  # keep it alive during the call
    user32.EnumWindows(callback, 0)

    needle = title.strip().lower()
    return next((h for h, t in found if needle in t.lower()), None)


def _move_window(title, place):
    """FINALE: move or maximize one visible window by a word in its
    title. Fixed actions only -- left half, right half, maximize."""
    if not isinstance(title, str) or not title.strip():
        return ("ERROR: move_window needs the window's name, "
                'like "Notepad".')
    if place not in ("left", "right", "maximize"):
        return "ERROR: place must be \"left\", \"right\" or \"maximize\"."
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = _find_window(title)
        if hwnd is None:
            return ("ERROR: no open window's title contains \""
                    + title.strip() + "\". Use a word from the "
                    "window title.")

        if place == "maximize":
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            return "OK: window maximized."

        width = user32.GetSystemMetrics(0)   # screen width in pixels
        height = user32.GetSystemMetrics(1)  # screen height in pixels
        x = 0 if place == "left" else width // 2
        user32.SetWindowPos(hwnd, 0, x, 0, width // 2, height, 0x0044)
        return f"OK: window moved to the {place} half of the screen."
    except Exception as e:
        return f"ERROR: could not move the window ({e})."


def _close_window(title):
    """FINALE+: POLITELY close one window by a word in its title (the
    same message as clicking the X button). Never force-kills."""
    if not isinstance(title, str) or not title.strip():
        return "ERROR: close_window needs the window's name, like \"Notepad\"."
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = _find_window(title)
        if hwnd is None:
            return ("ERROR: no open window's title contains \""
                    + title.strip() + "\". Use a word from the "
                    "window title.")

        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # 0x0010 = WM_CLOSE
        return f"OK: asked the \"{title.strip()}\" window to close."
    except Exception as e:
        return f"ERROR: could not close the window ({e})."


def _run_command(command):
    """AGENT MODE: run one Windows shell command and return its output.
    Output is capped and a timeout stops runaway commands."""
    if not isinstance(command, str) or not command.strip():
        return "ERROR: run_command needs a 'command' string."
    try:
        result = subprocess.run(
            command.strip(), shell=True, capture_output=True, text=True,
            errors="replace", timeout=60)
    except subprocess.TimeoutExpired:
        return ("ERROR: the command did not finish within 60 seconds "
                "and was stopped.")
    except Exception as e:
        return f"ERROR: could not run the command ({e})."
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    text = ""
    if out:
        text += out
    if err:
        text += ("\n[stderr]\n" + err) if text else err
    if not text:
        text = ("(no output -- command finished, exit code "
                + str(result.returncode) + ")")
    if len(text) > MAX_COMMAND_OUTPUT:
        text = (text[:MAX_COMMAND_OUTPUT]
                + "\n...[output continues -- first 4000 characters shown]")
    return text


def _read_site(url):
    """WEB READING: fetch the public text of one allowed website. The
    permission gate has already checked the host is on ALLOWED_SITES
    and cleaned the address. Uses only the Python standard library.
    GitHub repository links are special-cased: GitHub's public API
    returns a clean description + file list instead of HTML mush."""
    if not isinstance(url, str) or not url.strip():
        return "ERROR: read_site needs a website address."
    url = url.strip()
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host == "github.com":
            return _read_github_repo(url)
        return _read_plain_page(url)
    except Exception as e:
        return f"ERROR: could not read that site ({e})."


def _read_plain_page(url):
    """Fetch a normal web page and strip it down to readable text."""
    try:
        import re as page_re
        from urllib.request import Request, urlopen
        req = Request(url, headers={"User-Agent": "ZYRO-local-assistant"})
        with urlopen(req, timeout=15) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            html = resp.read(300000).decode(charset, errors="replace")
        text = page_re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        text = page_re.sub(r"(?s)<[^>]+>", " ", text)
        text = page_re.sub(r"\s+", " ", text).strip()
        if not text:
            return "(the page had no readable text)"
        if len(text) > MAX_SITE_CHARS:
            text = text[:MAX_SITE_CHARS] + " ...[page continues]"
        return text
    except Exception as e:
        return f"ERROR: could not read that page ({e})."


def _read_github_repo(url):
    """GitHub special reader: ask GitHub's public API about the repo
    (description, language, stars) and list its top-level files."""
    try:
        import json as repo_json
        from urllib.parse import urlparse
        from urllib.request import Request, urlopen
        parts = [p for p in urlparse(url).path.split("/") if p]
        if len(parts) < 2:
            return ("ERROR: that GitHub link is not a repository. "
                    "Use github.com/USER/REPO.")
        user, repo = parts[0], parts[1]
        headers = {"User-Agent": "ZYRO-local-assistant",
                   "Accept": "application/vnd.github+json"}
        api = "https://api.github.com/repos/" + user + "/" + repo
        with urlopen(Request(api, headers=headers), timeout=15) as resp:
            info = repo_json.loads(resp.read(200000).decode("utf-8",
                                                            errors="replace"))
        lines = ["repository: " + str(info.get("full_name",
                                               user + "/" + repo))]
        if info.get("description"):
            lines.append("description: " + str(info["description"]))
        lines.append("language: " + str(info.get("language", "?")))
        lines.append("stars: " + str(info.get("stargazers_count", "?")))
        with urlopen(Request(api + "/contents", headers=headers),
                     timeout=15) as resp:
            items = repo_json.loads(resp.read(300000).decode("utf-8",
                                                             errors="replace"))
        if isinstance(items, list):
            lines.append("top-level files and folders:")
            for item in items[:40]:
                kind = "folder" if item.get("type") == "dir" else "file"
                lines.append("  [" + kind + "] " + str(item.get("name", "?")))
        text = "\n".join(lines)
        if len(text) > MAX_SITE_CHARS:
            text = text[:MAX_SITE_CHARS] + " ...[continues]"
        return text
    except Exception as e:
        return f"ERROR: could not read the GitHub repo ({e})."


def _list_repo(url):
    """REPO EXPLORER: list files INSIDE a GitHub repo folder (or the
    root). The permission gate has already verified the host is
    github.com and cleaned the path. FIX: GitHub web links look like
    .../tree/BRANCH/folder -- the API does not use that prefix, so it
    is stripped here before calling GitHub's contents API."""
    if not isinstance(url, str) or not url.strip():
        return "ERROR: list_repo needs a GitHub repository address."
    try:
        import json as repo_json
        from urllib.request import Request, urlopen
        parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
        if len(parts) < 2:
            return ("ERROR: that GitHub link is not a repository. "
                    "Use github.com/USER/REPO.")
        user, repo = parts[0], parts[1]
        sub_parts = parts[2:]
        # FIX: drop the web-only "tree/BRANCH" (or "blob/BRANCH")
        # prefix -- the contents API never uses it.
        if sub_parts and sub_parts[0].lower() in ("tree", "blob"):
            sub_parts = sub_parts[2:]  # marker + branch name
        subpath = "/".join(sub_parts)
        headers = {"User-Agent": "ZYRO-local-assistant",
                   "Accept": "application/vnd.github+json"}
        api = ("https://api.github.com/repos/" + user + "/" + repo
               + "/contents/" + urllib.parse.quote(subpath))
        with urlopen(Request(api, headers=headers), timeout=15) as resp:
            items = repo_json.loads(resp.read(300000).decode("utf-8",
                                                             errors="replace"))
        if isinstance(items, dict):
            # A single file was requested -- give its download info.
            return ("That is a single file. Its download link is: "
                    + str(items.get("download_url", "(unknown)")))
        if not items:
            return "(that folder is empty)"
        lines = ["folder: " + (subpath or "(root)")]
        for item in items[:MAX_LIST_ITEMS]:
            kind = "folder" if item.get("type") == "dir" else "file"
            size = item.get("size", 0)
            extra = f" ({size} bytes)" if kind == "file" else ""
            lines.append("  [" + kind + "] "
                         + str(item.get("name", "?")) + extra)
        if len(items) > MAX_LIST_ITEMS:
            lines.append("...[more items not shown]")
        text = "\n".join(lines)
        if len(text) > MAX_SITE_CHARS:
            text = text[:MAX_SITE_CHARS] + " ...[continues]"
        return text
    except Exception as e:
        msg = f"ERROR: could not explore the repo ({e})."
        if "404" in str(e) or "Not Found" in str(e):
            msg += (" TIP: the folder name may be spelled differently. "
                    "List the repo root first, then use an exact folder "
                    "name from that list.")
        return msg
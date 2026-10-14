r"""ZYRO's permission gate (Phases 3-8 + finale + AGENT MODE + web).

The AI model can never run anything by itself. It can only ASK for an
action by printing one small JSON object, e.g.
{"tool": "read_file", "path": "notes.txt"}

Every reply passes through check_reply() below -- the ONLY door between
the model and the tools:
  - the tool name must be on the fixed whitelist (ALLOWED_TOOLS)
  - any path must stay inside D:\zyro (no "..", no other drives)
  - write tools must carry "content" as a plain string
  - open_site / read_site only accept hosts on ALLOWED_SITES; they may
    keep a clean path (for GitHub USER/REPO links)
  - list_repo explores INSIDE GitHub repos (same host check; spaces
    in folder names like "Session 01" are handled)
  - run_command is flagged critical when it matches the hint list --
    critical commands ALWAYS ask the human, even in AUTO mode
  - anything malformed gets a polite refusal instead of a crash

SAFE_TOOLS run automatically; RISKY_TOOLS go through the human's
AUTO switch / approval dialog.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse, unquote

from core import paths
from core.tools import ALLOWED_APPS  # Phase 5: the only launchable apps
from core.sysops import MEDIA_KEYS   # Phase 9: the only media keys
from core.downloads import check_url  # Phase 9: public-URL validation

# The only folder ZYRO may ever touch with the file TOOLS (now the
# install folder, D:\zyro on the owner's machine); shell commands go
# where the human's approval layers allow.
BASE_DIR = paths.PROJECT_ROOT

# The fixed menu of tools, split by risk. Extended BY HAND across the
# phases -- the model can never add anything to it.
SAFE_TOOLS = {"list_files", "read_file", "get_time", "read_site",
              "list_repo", "winget_search", "system_info",
              "search_files", "list_processes", "media_key",
              "read_skill", "search_in_files", "suggest_model"}
RISKY_TOOLS = {"write_file", "append_file", "set_volume", "mute_toggle",
               "open_app", "open_site", "game_mode", "move_window",
               "close_window", "run_command", "download_file",
               "download_video", "winget_install", "screenshot",
               "clipboard_read", "clipboard_write", "open_file",
               "set_wallpaper", "edit_file", "run_python",
               "look_screen", "look_image", "switch_model",
               "browser_open", "browser_click", "browser_type",
               "browser_close", "update_ytdlp"}
ALLOWED_TOOLS = SAFE_TOOLS | RISKY_TOOLS

# AUTO MODE NEVER COVERS THESE, whatever the model says.
#
# They are the tools that can run code, launch a downloaded program, or
# pull a file off the internet -- the short chain that turns a poisoned
# web page or a downloaded file into code running as the user:
#
#     download_file  ->  open_file     (fetch and launch a program)
#     run_python                       (any code at all)
#     run_command                      (any shell command at all)
#
# "how to use zyro.txt" has always promised that dangerous actions ask
# first "no matter what". These four had been slipping through AUTO.
ALWAYS_ASK = {"run_python", "run_command", "open_file", "download_file"}


def auto_allows(request, auto_on):
    """Would AUTO mode approve this request without asking the human?

    AUTO still covers the everyday things -- volume, media keys, apps,
    screenshots, the browser, file writes inside the install folder --
    but never the four above, and never anything flagged critical.
    """
    if not auto_on:
        return False
    if request.get("critical"):
        return False
    return request.get("tool") not in ALWAYS_ASK

# Which tools need a "path" argument (list_files treats a missing path
# as "the main folder"; the rest refuse).
TOOLS_WITH_PATH = {"list_files", "read_file", "write_file", "append_file"}

# The ONLY websites open_site may open and read_site may read.
# Hand-written on purpose -- the model can never add to this list.
ALLOWED_SITES = {"youtube.com", "google.com", "wikipedia.org",
                 "github.com", "gmail.com"}

# AGENT MODE: commands matching these hints are CRITICAL -- they always
# ask the human, even with AUTO-approval on.
CRITICAL_COMMAND_HINTS = (
    "format ", "diskpart", "cipher ", "vssadmin", "bcdedit",
    "shutdown", "logoff", "restart-computer", "stop-computer",
    "del ", "erase ", "rd /s", "rmdir", "remove-item",
    "rm -rf", "rm -r ", "reg delete", "reg add", "reg import",
    "regedit", "taskkill", "net user", "net localgroup", "schtasks",
    "wmic",
    # Phase 9: shell-based downloads / installs bypass the dedicated
    # download tools and their safety checks -- so they ALWAYS ask.
    "curl ", "wget ", "invoke-webrequest", "start-bitstransfer",
    "bitsadmin", "winget install", "pip install", "msiexec",
    "certutil",
)


def _extract_json(text):
    """Find the first {...} block in the model's reply and parse it.
    Returns a dict, or None if the reply holds no JSON object."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:  # not valid JSON
        return None
    return data if isinstance(data, dict) else None


def _resolve_inside(path_text):
    r"""Turn a requested path into a real full path -- but only if it
    lands inside D:\zyro. Returns the full Path, or None if it would
    land outside."""
    # POLISH FIX: the model sometimes says "zyro/notes.txt" when it
    # means a file directly in D:\zyro. Strip that prefix (both
    # slash types) so the path lands in the right place.
    stripped = path_text.strip()
    if stripped.lower().startswith(("zyro/", "zyro\\")):
        path_text = stripped[5:]
    try:
        full = (BASE_DIR / path_text).resolve()
    except (OSError, ValueError):
        return None
    base = str(BASE_DIR.resolve()).lower()
    full_text = str(full).lower()
    if full_text == base or full_text.startswith(base + "\\"):
        return full
    return None


def _host_of(url):
    """Pull the clean host name out of an address ('www.' removed),
    or None if it is not a plain web address."""
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def check_reply(text):
    """Inspect one model reply (already think-stripped).
    Returns (kind, request, refusal):
      ("none", None, None)    no tool request -- the reply is just chat
      ("bad",  None, msg)     looked like a request but was refused
      ("ok",   request, None) safe to run; request = {"tool": ..., ...}
    """
    data = _extract_json(text)
    if data is None:
        # No parseable JSON. If the reply at least TRIED to name a tool,
        # tell the model its JSON was broken; otherwise it is just chat.
        if '"tool"' in text or "'tool'" in text:
            return ("bad", None,
                    "That tool request was not valid JSON. Reply with exactly: "
                    '{"tool": "read_file", "path": "notes.txt"}')
        return "none", None, None
    if "tool" not in data:
        return "none", None, None  # JSON, but not a tool request

    tool = data.get("tool")
    # isinstance first: a non-string "tool" (e.g. a JSON list) is unhashable
    # and would crash set membership -- the gate must refuse it, not crash.
    if not isinstance(tool, str) or tool not in ALLOWED_TOOLS:
        allowed = ", ".join(sorted(ALLOWED_TOOLS))
        return ("bad", None,
                f"'{tool}' is not an allowed tool. Allowed tools: {allowed}.")

    if tool == "get_time":
        return "ok", {"tool": tool}, None

    if tool == "set_volume":
        level = data.get("level")
        # bool is a subclass of int in Python, so True would sneak past a
        # plain isinstance check -- refuse it explicitly.
        if isinstance(level, bool) or not isinstance(level, int):
            return ("bad", None,
                    "set_volume needs 'level' as a whole number between 0 "
                    'and 100 (a JSON number like "level": 30).')
        if not 0 <= level <= 100:
            return ("bad", None,
                    "Volume level must be between 0 and 100, "
                    f"not {level}.")
        return "ok", {"tool": tool, "level": level}, None

    if tool == "mute_toggle":
        return "ok", {"tool": tool}, None

    if tool == "open_app":
        app = data.get("app")
        if not isinstance(app, str) or not app.strip():
            return ("bad", None,
                    "open_app needs an 'app' name, e.g. "
                    '{"tool": "open_app", "app": "notepad"}.')
        app = app.strip().lower()
        if app not in ALLOWED_APPS:
            return ("bad", None,
                    f"'{app}' is not on the allowed apps list. I can only "
                    f"open: {', '.join(sorted(ALLOWED_APPS))}.")
        return "ok", {"tool": tool, "app": app}, None

    if tool == "open_site":
        host = _host_of(data.get("url"))
        if host is None:
            return ("bad", None,
                    "open_site needs a 'url', for example: "
                    '{"tool": "open_site", "url": "https://www.youtube.com"}')
        if host not in ALLOWED_SITES:
            return ("bad", None,
                    f"'{host}' is not on the allowed sites list. Allowed "
                    "sites: " + ", ".join(sorted(ALLOWED_SITES)) + ".")
        return "ok", {"tool": tool, "url": "https://" + host}, None

    # WEB READING: like open_site, but a clean PATH may be kept so
    # GitHub USER/REPO links work. Only letters, digits and / . _ -
    # survive the cleaning -- no queries, no tricks.
    if tool == "read_site":
        raw = data.get("url")
        host = _host_of(raw)
        if host is None:
            return ("bad", None,
                    "read_site needs a 'url', for example: "
                    '{"tool": "read_site", '
                    '"url": "https://github.com/USER/REPO"}')
        if host not in ALLOWED_SITES:
            return ("bad", None,
                    f"'{host}' is not on the allowed sites list. Allowed "
                    "sites: " + ", ".join(sorted(ALLOWED_SITES)) + ".")
        path_part = unquote(urlparse(raw.strip()).path)
        clean = "".join(ch for ch in path_part
                        if ch.isalnum() or ch in "/._-")
        return "ok", {"tool": tool, "url": "https://" + host + clean}, None

    # REPO EXPLORER: like read_site, but explores INSIDE a GitHub
    # repository folder. Same host check + path cleaning. Spaces are
    # allowed here because GitHub folders like "Session 01" contain
    # them; tools.py re-encodes them safely before calling GitHub.
    if tool == "list_repo":
        raw = data.get("url")
        host = _host_of(raw)
        if host is None:
            return ("bad", None,
                    "list_repo needs a 'url', for example: "
                    '{"tool": "list_repo", '
                    '"url": "https://github.com/USER/REPO/tree/main"}')
        if host not in ALLOWED_SITES:
            return ("bad", None,
                    f"'{host}' is not on the allowed sites list. Allowed "
                    "sites: " + ", ".join(sorted(ALLOWED_SITES)) + ".")
        path_part = unquote(urlparse(raw.strip()).path)
        clean = "".join(ch for ch in path_part
                        if ch.isalnum() or ch in "/._- ")
        return "ok", {"tool": tool, "url": "https://" + host + clean}, None

    if tool == "game_mode":
        state = data.get("state")
        if not isinstance(state, str) or state.strip().lower() not in ("on", "off"):
            return ("bad", None,
                    'game_mode needs \'state\' as exactly "on" or "off", '
                    'e.g. {"tool": "game_mode", "state": "on"}.')
        return "ok", {"tool": tool, "state": state.strip().lower()}, None

    if tool == "move_window":
        win = data.get("window")
        place = data.get("place")
        if not isinstance(win, str) or not win.strip():
            return ("bad", None,
                    'move_window needs \'window\' (the window title), e.g. '
                    '{"tool": "move_window", "window": "Notepad", '
                    '"place": "left"}.')
        if not isinstance(place, str) or place.strip().lower() not in (
                "left", "right", "maximize"):
            return ("bad", None,
                    'move_window \'place\' must be "left", "right" or '
                    '"maximize".')
        return ("ok", {"tool": tool, "window": win.strip(),
                       "place": place.strip().lower()}, None)

    if tool == "close_window":
        win = data.get("window")
        if not isinstance(win, str) or not win.strip():
            return ("bad", None,
                    'close_window needs \'window\' (the window title), '
                    'e.g. {"tool": "close_window", "window": "Notepad"}.')
        return "ok", {"tool": tool, "window": win.strip()}, None

    if tool == "run_command":
        cmd = data.get("command")
        if not isinstance(cmd, str) or not cmd.strip():
            return ("bad", None,
                    'run_command needs \'command\' as text, e.g. '
                    '{"tool": "run_command", "command": "dir D:\\\\zyro"}.')
        cmd = cmd.strip()
        low = cmd.lower()
        critical = any(hint in low for hint in CRITICAL_COMMAND_HINTS)
        return ("ok", {"tool": tool, "command": cmd,
                       "critical": critical}, None)

    # ---------- Phase 9: downloads, software and PC control ----------

    if tool == "download_file":
        ok, value = check_url(data.get("url"))
        if not ok:
            return ("bad", None, value)
        name = data.get("name")
        if name is not None and (not isinstance(name, str)
                                 or not name.strip() or len(name) > 120):
            return ("bad", None,
                    "download_file 'name' must be a short file name like "
                    '"setup.zip".')
        return ("ok", {"tool": tool, "url": value, "name": name}, None)

    if tool == "download_video":
        ok, value = check_url(data.get("url"))
        if not ok:
            return ("bad", None, value)
        kind = data.get("kind", "video")
        if kind not in ("video", "audio"):
            return ("bad", None,
                    'download_video \'kind\' must be "video" or "audio".')
        return ("ok", {"tool": tool, "url": value, "kind": kind}, None)

    if tool == "winget_search":
        query = data.get("query")
        if not isinstance(query, str) or not query.strip():
            return ("bad", None,
                    'winget_search needs a \'query\', e.g. '
                    '{"tool": "winget_search", "query": "vlc"}.')
        return ("ok", {"tool": tool, "query": query.strip()[:80]}, None)

    if tool == "winget_install":
        app_id = data.get("app_id")
        if (not isinstance(app_id, str) or not app_id.strip()
                or not re.fullmatch(r"[A-Za-z0-9._+\- ]{1,120}",
                                    app_id.strip())):
            return ("bad", None,
                    'winget_install needs an \'app_id\' from '
                    'winget_search, e.g. {"tool": "winget_install", '
                    '"app_id": "VideoLAN.VLC"}.')
        return ("ok", {"tool": tool, "app_id": app_id.strip(),
                       "critical": True}, None)  # installs ALWAYS ask

    if tool == "screenshot":
        return "ok", {"tool": tool}, None

    if tool == "clipboard_read":
        return "ok", {"tool": tool}, None

    if tool == "clipboard_write":
        content = data.get("content")
        if not isinstance(content, str):
            return ("bad", None,
                    'clipboard_write needs \'content\' as text, e.g. '
                    '{"tool": "clipboard_write", "content": "hello"}.')
        return "ok", {"tool": tool, "content": content}, None

    if tool == "media_key":
        key = data.get("key")
        if not isinstance(key, str) or key.strip().lower() not in MEDIA_KEYS:
            return ("bad", None,
                    "media_key 'key' must be one of: "
                    + ", ".join(sorted(MEDIA_KEYS)) + ".")
        return ("ok", {"tool": tool,
                       "key": key.strip().lower()}, None)

    if tool == "read_skill":
        name = data.get("name")
        if (not isinstance(name, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}",
                                    name.strip().lower())):
            return ("bad", None,
                    'read_skill needs a skill \'name\' from the skills '
                    'list, e.g. {"tool": "read_skill", '
                    '"name": "file-organizer"}.')
        return ("ok", {"tool": tool,
                       "name": name.strip().lower()}, None)

    if tool == "search_in_files":
        pattern = data.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            return ("bad", None,
                    'search_in_files needs a \'pattern\' of text to '
                    'find, e.g. {"tool": "search_in_files", '
                    '"pattern": "TODO"}.')
        root = data.get("root")
        if root is not None and (not isinstance(root, str)
                                 or len(root) > 300):
            return ("bad", None,
                    "search_in_files 'root' must be a folder on this "
                    "PC (short text).")
        return ("ok", {"tool": tool, "pattern": pattern.strip()[:100],
                       "root": root}, None)

    if tool == "edit_file":
        path = data.get("path")
        find = data.get("find")
        replace = data.get("replace")
        if not isinstance(path, str) or not path.strip():
            return ("bad", None,
                    'edit_file needs a \'path\' inside the ZYRO '
                    'install folder.')
        full = _resolve_inside(path)
        if full is None:
            return ("bad", None,
                    "edit_file only edits files inside the ZYRO "
                    "install folder, and that path is outside it.")
        if not isinstance(find, str) or not find:
            return ("bad", None,
                    'edit_file needs non-empty \'find\' text and a '
                    '\'replace\' text.')
        if not isinstance(replace, str):
            return ("bad", None,
                    "edit_file needs 'replace' as text (it may be "
                    'empty: "").')
        return ("ok", {"tool": tool, "path": str(full), "find": find,
                       "replace": replace}, None)

    if tool == "run_python":
        code = data.get("code")
        if not isinstance(code, str) or not code.strip():
            return ("bad", None,
                    'run_python needs a \'code\' string, e.g. '
                    '{"tool": "run_python", "code": "print(1+1)"}.')
        return ("ok", {"tool": tool, "code": code[:8000]}, None)

    if tool == "look_screen":
        return "ok", {"tool": tool}, None

    if tool == "look_image":
        path = data.get("path")
        if not isinstance(path, str) or not path.strip():
            return ("bad", None,
                    'look_image needs a \'path\' to an image inside '
                    'the ZYRO install folder.')
        full = _resolve_inside(path)
        if full is None:
            return ("bad", None,
                    "look_image only looks at images inside the ZYRO "
                    "install folder.")
        return "ok", {"tool": tool, "path": str(full)}, None

    if tool == "switch_model":
        name = data.get("name")
        if (not isinstance(name, str)
                or not re.fullmatch(r"[A-Za-z0-9._:\-]{1,60}",
                                    name.strip())):
            return ("bad", None,
                    'switch_model needs a \'name\' like "qwen3:4b", '
                    'e.g. {"tool": "switch_model", "name": '
                    '"qwen3:4b"}.')
        return ("ok", {"tool": tool, "name": name.strip()}, None)

    if tool == "suggest_model":
        return "ok", {"tool": tool}, None

    if tool == "browser_open":
        url = data.get("url")
        if not isinstance(url, str) or not url.strip():
            return ("bad", None,
                    'browser_open needs a \'url\', e.g. '
                    '{"tool": "browser_open", "url": "github.com"}.')
        if url.strip().lower().startswith(("javascript:", "file:",
                                           "data:")):
            return ("bad", None,
                    "browser_open only opens http/https pages.")
        return ("ok", {"tool": tool, "url": url.strip()[:500]}, None)

    if tool == "browser_click":
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            return ("bad", None,
                    'browser_click needs the \'text\' of the button '
                    'or link to click.')
        return ("ok", {"tool": tool, "text": text.strip()[:100]}, None)

    if tool == "browser_type":
        label = data.get("label")
        value = data.get("value")
        if not isinstance(label, str) or not label.strip():
            return ("bad", None,
                    'browser_type needs the field\'s \'label\' '
                    '(placeholder) and the \'value\' to type.')
        if not isinstance(value, str):
            return ("bad", None,
                    "browser_type needs 'value' as text.")
        return ("ok", {"tool": tool, "label": label.strip()[:100],
                       "value": value[:500]}, None)

    if tool == "browser_close":
        return "ok", {"tool": tool}, None

    if tool == "update_ytdlp":
        return "ok", {"tool": tool}, None

    if tool == "system_info":
        return "ok", {"tool": tool}, None

    if tool == "list_processes":
        return "ok", {"tool": tool}, None

    if tool == "search_files":
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            return ("bad", None,
                    'search_files needs a \'name\' to look for, e.g. '
                    '{"tool": "search_files", "name": "report"}.')
        drive = paths.DRIVE_ROOT.strip("\\").lower()  # e.g. "d:"
        root = data.get("root", paths.DRIVE_ROOT)
        if isinstance(root, str) and root.strip():
            if not root.strip().lower().startswith(drive):
                return ("bad", None,
                        "search_files only looks inside the "
                        + drive.upper() + " drive of this install.")
            root = root.strip()
        else:
            root = paths.DRIVE_ROOT
        return ("ok", {"tool": tool, "name": name.strip()[:100],
                       "root": root}, None)

    if tool == "set_wallpaper":
        raw = data.get("path")
        if not isinstance(raw, str) or not raw.strip():
            return ("bad", None,
                    'set_wallpaper needs a \'path\' to an image on D:, '
                    'e.g. {"tool": "set_wallpaper", "path": '
                    '"D:\\\\pics\\\\wall.jpg"}.')
        raw = raw.strip()
        p = Path(raw)
        try:
            if p.is_absolute():
                if not str(p).lower().startswith(
                        paths.DRIVE_ROOT.strip("\\").lower()):
                    return ("bad", None,
                            "set_wallpaper only accepts images on "
                            "the install drive ("
                            + paths.DRIVE_ROOT.strip("\\").upper()
                            + ").")
                full = p
            else:
                full = _resolve_inside(raw)
        except (OSError, ValueError):
            return ("bad", None, "That wallpaper path is not valid.")
        if full is None:
            return ("bad", None,
                    "That path is outside the D: drive, so I am not "
                    "allowed to use it as a wallpaper.")
        return "ok", {"tool": tool, "path": str(full)}, None

    if tool == "open_file":
        path = data.get("path")
        if not isinstance(path, str) or not path.strip():
            return ("bad", None,
                    'open_file needs a \'path\' inside D:\\zyro, e.g. '
                    '{"tool": "open_file", "path": '
                    '"downloads\\setup.exe"}.')
        full = _resolve_inside(path)
        if full is None:
            return ("bad", None,
                    "open_file only opens files inside D:\\zyro, and "
                    "that path is outside it.")
        return "ok", {"tool": tool, "path": str(full)}, None

    path = data.get("path")
    if not isinstance(path, str) or not path.strip():
        if tool == "list_files":
            path = "."  # empty path = the main D:\zyro folder
        else:
            return ("bad", None,
                    f"{tool} needs a 'path' to a file inside D:\\zyro.")

    full = _resolve_inside(path)
    if full is None:
        return ("bad", None,
                "That path is outside D:\\zyro, so I am not allowed to touch it.")

    if tool in RISKY_TOOLS:
        content = data.get("content")
        if not isinstance(content, str):
            return ("bad", None,
                    f"{tool} needs 'content' as plain text "
                    '(a JSON string like "content": "some text").')
        return "ok", {"tool": tool, "path": str(full), "content": content}, None

    return "ok", {"tool": tool, "path": str(full)}, None
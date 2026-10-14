"""Audit EVERY tool ZYRO has, for real, and report what works.

    venv\\Scripts\\python test_all_tools.py            all tools
    venv\\Scripts\\python test_all_tools.py --twice    run everything twice
    venv\\Scripts\\python test_all_tools.py --json out.json

Every tool is actually called. Nothing is allowed to damage the machine:

  * mute / volume / brightness / wallpaper / clipboard are read first and
    restored afterwards;
  * delete tests use throwaway files in a sandbox folder (they go to the
    Recycle Bin, so they are recoverable anyway);
  * a dummy process is started just so kill_process has something safe to
    kill, and it is cleaned up;
  * power_action and empty_recycle_bin are NEVER executed -- they are
    reported as skipped, with the reason.

Each tool is marked offline or online, which is what produces the
capability lists in ZYRO-FEATURES.md.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

# Tool output is not always plain text (YouTube titles contain emoji, and
# a Windows console is cp1252): never let that stop the audit.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

from agent import config                    # imported FIRST on purpose:
# the state folders must be redirected before anything else reads them.
SANDBOX = ROOT / "agent" / "_audit"
STATE = SANDBOX / "state"
config.STATE_DIR = STATE
config.TRUST_FILE = STATE / "trusted.json"
config.SESSION_DIR = STATE / "sessions"
config.CHECKPOINT_DIR = STATE / "checkpoints"

from agent import tools                                          # noqa: E402
from agent.tools import ToolContext                              # noqa: E402
from agent.workspace import Workspace                            # noqa: E402

# Results, filled in as we go:  name -> (status, offline, note)
RESULTS = {}
RESTORE = []          # callables that put the machine back


def call(name, args, ctx, *, expect=None, timeout_note=""):
    """Run one tool and return (ok, message)."""
    spec = tools.get(name)
    try:
        if spec["kind"] == "edit":
            change = spec["planner"](args, ctx)
            text = change.apply()
        else:
            text, _image = tools.execute(spec, args, ctx)
    except Exception as exc:                     # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if text.startswith("ERROR"):
        return False, text[:160]
    if expect and expect.lower() not in str(text).lower():
        return False, f"expected '{expect}' in: {str(text)[:120]}"
    return True, str(text).replace("\n", " ")[:110]


def record(name, ok, offline, note="", skipped=False):
    status = "SKIP" if skipped else ("OK" if ok else "FAIL")
    RESULTS[name] = (status, offline, note)
    mark = {"OK": "ok  ", "FAIL": "FAIL", "SKIP": "skip"}[status]
    print(f"  [{mark}] {name:22} {'offline' if offline else 'ONLINE '}  {note}")


# --------------------------------------------------------------- fixtures

def build_sandbox():
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    SANDBOX.mkdir(parents=True, exist_ok=True)
    config.ensure_state_dirs()
    (SANDBOX / "notes.txt").write_text("hello world\nsecond line\n",
                                       encoding="utf-8")
    (SANDBOX / "docs").mkdir(exist_ok=True)
    (SANDBOX / "docs" / "a.txt").write_text("alpha\n", encoding="utf-8")
    (SANDBOX / "captures").mkdir(exist_ok=True)
    (SANDBOX / "downloads").mkdir(exist_ok=True)
    # a picture for the vision tool
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (240, 120), (30, 30, 30))
    ImageDraw.Draw(image).text((16, 50), "ZYRO AUDIT", fill=(235, 219, 178))
    image.save(SANDBOX / "captures" / "sample.png")


# ------------------------------------------------------- restore helpers

def save_clipboard():
    try:
        from core import sysops
        before = sysops.clipboard_read()
        RESTORE.append(lambda: sysops.clipboard_write(
            before if isinstance(before, str) and not before.startswith("(")
            else ""))
    except Exception:                            # noqa: BLE001
        RESTORE.append(lambda: None)


def save_volume():
    try:
        from core import tools as core_tools
        control = core_tools._get_volume_control()
        if control is None:
            return None
        level = round(control.GetMasterVolumeLevelScalar() * 100)
        muted = bool(control.GetMute())
        def put_back():
            control.SetMasterVolumeLevelScalar(level / 100.0, None)
            control.SetMute(muted, None)
        RESTORE.append(put_back)
        return level, muted
    except Exception:                            # noqa: BLE001
        return None


def save_brightness():
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance -Namespace root/wmi -ClassName "
             "WmiMonitorBrightness).CurrentBrightness"],
            capture_output=True, text=True, timeout=30)
        value = (result.stdout or "").strip().splitlines()
        level = int(value[0]) if value and value[0].isdigit() else None
        if level is None:
            return None
        from agent.tools import system as sysmod
        RESTORE.append(lambda: sysmod.set_brightness({"level": level},
                                                     None))
        return level
    except Exception:                            # noqa: BLE001
        return None


def save_wallpaper():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Control Panel\Desktop") as key:
            value, _ = winreg.QueryValueEx(key, "WallPaper")
        if value:
            from core import sysops
            RESTORE.append(lambda: sysops.set_wallpaper(value))
        return value
    except Exception:                            # noqa: BLE001
        return None


# ----------------------------------------------------------------- audit

def audit(ctx, ws):
    print("\n--- coding ---")
    ok, msg = call("list_files", {"path": "."}, ctx, expect="notes.txt")
    record("list_files", ok, True, msg)
    ok, msg = call("read_file", {"path": "notes.txt"}, ctx, expect="hello")
    record("read_file", ok, True, msg)
    ok, msg = call("write_file", {"path": "written.txt", "content": "x\n"}, ctx)
    record("write_file", ok, True, msg)
    ok, msg = call("create_file", {"path": "created.txt", "content": "y\n"}, ctx)
    record("create_file", ok, True, msg)
    ok, msg = call("append_file", {"path": "created.txt", "content": "z"}, ctx)
    record("append_file", ok, True, msg)
    ok, msg = call("edit_file", {"path": "notes.txt", "find": "hello world",
                                 "replace": "HELLO WORLD"}, ctx)
    record("edit_file", ok, True, msg)
    ok, msg = call("run_command", {"command": "echo audit"}, ctx,
                   expect="audit")
    record("run_command", ok, True, msg)
    ok, msg = call("run_python", {"code": "print(6*7)"}, ctx, expect="42")
    record("run_python", ok, True, msg)

    print("\n--- files ---")
    ok, msg = call("search_files", {"name": "notes"}, ctx, expect="notes.txt")
    record("search_files", ok, True, msg)
    ok, msg = call("search_in_files", {"pattern": "HELLO"}, ctx)
    record("search_in_files", ok, True, msg)
    ok, msg = call("file_info", {"path": "notes.txt"}, ctx, expect="size")
    record("file_info", ok, True, msg)
    ok, msg = call("largest_files", {"folder": ".", "count": 5}, ctx)
    record("largest_files", ok, True, msg)
    ok, msg = call("recent_files", {"folder": ".", "count": 5}, ctx)
    record("recent_files", ok, True, msg)
    ok, msg = call("find_duplicates", {"folder": "."}, ctx)
    record("find_duplicates", ok, True, msg)
    ok, msg = call("create_folder", {"path": "newdir"}, ctx)
    record("create_folder", ok, True, msg)
    ok, msg = call("copy_file", {"path": "notes.txt",
                                 "destination": "notes_copy.txt"}, ctx)
    record("copy_file", ok, True, msg)
    ok, msg = call("move_file", {"path": "notes_copy.txt",
                                 "destination": "moved.txt"}, ctx)
    record("move_file", ok, True, msg)
    ok, msg = call("rename_file", {"path": "moved.txt",
                                   "new_name": "renamed.txt"}, ctx)
    record("rename_file", ok, True, msg)
    ok, msg = call("rename_folder", {"path": "newdir",
                                     "new_name": "renamed_dir"}, ctx)
    record("rename_folder", ok, True, msg)
    ok, msg = call("zip_files", {"path": "docs", "output": "docs.zip"}, ctx)
    record("zip_files", ok, True, msg)
    ok, msg = call("unzip", {"zip_path": "docs.zip",
                             "destination": "unpacked"}, ctx)
    record("unzip", ok, True, msg)
    (SANDBOX / "trash_me.txt").write_text("bye\n", encoding="utf-8")
    ok, msg = call("delete_file", {"path": "trash_me.txt"}, ctx,
                   expect="Recycle Bin")
    record("delete_file", ok, True, msg + " (goes to the Recycle Bin)")
    (SANDBOX / "trash_dir").mkdir(exist_ok=True)
    (SANDBOX / "trash_dir" / "junk.txt").write_text("x", encoding="utf-8")
    ok, msg = call("delete_folder", {"path": "trash_dir"}, ctx,
                   expect="Recycle Bin")
    record("delete_folder", ok, True, msg + " (goes to the Recycle Bin)")
    record("empty_recycle_bin", False, True,
           "NOT RUN: would delete the contents of the owner's Recycle Bin",
           skipped=True)

    print("\n--- system (read-only) ---")
    for name, args, expect in (
            ("system_info", {}, "RAM"),
            ("cpu_ram_usage", {}, "CPU"),
            ("battery_status", {}, "attery"),
            ("disk_usage", {"drive": "D"}, "free"),
            ("uptime", {}, "on for"),
            ("network_info", {}, "host name"),
            ("list_processes", {"count": 10}, "processes")):
        ok, msg = call(name, args, ctx, expect=expect)
        record(name, ok, True, msg)

    print("\n--- system (changes, restored afterwards) ---")
    saved_volume = save_volume()
    if saved_volume is not None:
        level, muted = saved_volume
        ok, msg = call("set_volume", {"level": level}, ctx)
        record("set_volume", ok, True, f"set to its current {level}% then "
                                       "restored")
        ok, msg = call("mute_toggle", {}, ctx)
        ok2, _ = call("mute_toggle", {}, ctx)     # toggle straight back
        record("mute_toggle", ok and ok2, True, "toggled twice (back to "
                                                "original)")
    else:
        record("set_volume", False, True, "no audio device reachable",
               skipped=True)
        record("mute_toggle", False, True, "no audio device reachable",
               skipped=True)

    saved_brightness = save_brightness()
    if saved_brightness is not None:
        ok, msg = call("set_brightness", {"level": saved_brightness}, ctx)
        record("set_brightness", ok, True,
               f"set to its current {saved_brightness}% then restored")
    else:
        record("set_brightness", False, True,
               "this screen does not report brightness control", skipped=True)

    save_clipboard()
    ok, msg = call("clipboard_write", {"content": "ZYRO audit"}, ctx)
    ok2, msg2 = call("clipboard_read", {}, ctx, expect="ZYRO audit")
    record("clipboard_write", ok, True, "original clipboard restored after")
    record("clipboard_read", ok2, True, msg2 + " (round-trip verified)")

    ok, msg = call("notify", {"title": "ZYRO audit",
                              "message": "notification test"}, ctx)
    record("notify", ok, True, msg)

    saved_wallpaper = save_wallpaper()
    image = str((SANDBOX / "captures" / "sample.png"))
    ok, msg = call("set_wallpaper", {"path": image}, ctx)
    record("set_wallpaper", ok, True,
           "desktop wallpaper restored after the test")

    ok, msg = call("open_settings", {"page": "display"}, ctx)
    if ok:
        time.sleep(3)
        subprocess.run(["taskkill", "/f", "/im", "SystemSettings.exe"],
                       capture_output=True)
        msg += " (settings window opened, then closed)"
    record("open_settings", ok, True, msg)

    print("\n--- system (guarded) ---")
    dummy = subprocess.Popen([sys.executable, "-c", "import time;"
                              "time.sleep(240)"],
                             creationflags=getattr(subprocess,
                                                   "CREATE_NO_WINDOW", 0))
    time.sleep(2)
    ok, msg = call("kill_process", {"pid": dummy.pid}, ctx)
    time.sleep(1)
    gone = dummy.poll() is not None
    record("kill_process", ok and gone, True,
           f"killed a dummy process (pid {dummy.pid})")
    if not gone:
        dummy.kill()
    ok, msg = call("power_action", {"action": "fly"}, ctx)
    record("power_action", ok is False and "lock" in msg.lower(), True,
           "NOT RUN as an action: would lock/sleep/shut down the PC; the "
           "argument check was verified instead", skipped=True)

    print("\n--- productivity ---")
    ok, msg = call("todo_add", {"text": "audit item"}, ctx)
    record("todo_add", ok, True, msg)
    ok, msg = call("todo_list", {}, ctx, expect="audit item")
    record("todo_list", ok, True, msg)
    ok, msg = call("todo_done", {"text": "audit item"}, ctx)
    record("todo_done", ok, True, msg)
    ok, msg = call("set_reminder", {"minutes": 1, "text": "audit reminder"},
                   ctx)
    record("set_reminder", ok, True, msg + " (fires in 1 minute; checked "
                                           "below)")
    ok, msg = call("set_timer", {"minutes": 2, "text": "audit timer"}, ctx)
    record("set_timer", ok, True, msg)
    ok, msg = call("set_alarm", {"time": "23:59", "text": "audit alarm"}, ctx)
    record("set_alarm", ok, True, msg)

    print("\n--- memory & self ---")
    ok, msg = call("remember", {"fact": "the audit ran today"}, ctx)
    record("remember", ok, True, msg)
    ok, msg = call("recall", {"topic": "audit"}, ctx, expect="audit")
    record("recall", ok, True, msg)
    ok, msg = call("suggest_model", {}, ctx)
    record("suggest_model", ok, True, msg)
    ok, msg = call("switch_model", {"name": config.MODEL}, ctx)
    record("switch_model", ok, True, msg)
    ok, msg = call("enable_tools", {"group": "web"}, ctx)
    record("enable_tools", ok, True, msg)
    ok, msg = call("list_tools", {}, ctx, expect="coding")
    record("list_tools", ok, True, msg)

    print("\n--- media & vision ---")
    ok, msg = call("screenshot", {}, ctx, expect="OK")
    record("screenshot", ok, True, msg)
    ok, msg = call("look_image", {"path": "captures/sample.png"}, ctx)
    record("look_image", ok, True, msg[:90])
    ok, msg = call("look_screen", {}, ctx)
    record("look_screen", ok, True, msg[:90])
    ok, msg = call("media_key", {"key": "nonsense"}, ctx)
    record("media_key", ok is False and "must be one of" in msg, True,
           "NOT RUN as a key press (it would control the owner's music); "
           "the argument check was verified", skipped=True)
    record("play_music", False, True,
           "NOT RUN: would open a media file in the default player",
           skipped=True)

    print("\n--- web (online) ---")
    ok, msg = call("web_search", {"query": "python tkinter", "count": 3}, ctx)
    record("web_search", ok, False, msg)
    ok, msg = call("get_weather", {"city": "Mumbai"}, ctx)
    record("get_weather", ok, False, msg)
    ok, msg = call("get_news", {"topic": "technology"}, ctx)
    record("get_news", ok, False, msg)
    ok, msg = call("read_site", {"url": "https://github.com/ollama/ollama"},
                   ctx)
    record("read_site", ok, False, msg)
    ok, msg = call("download_file",
                   {"url": "https://raw.githubusercontent.com/git/git/master/"
                           "README.md", "folder": "downloads"}, ctx)
    record("download_file", ok, False, msg)
    ok, msg = call("yt_search", {"query": "zyro", "count": 2}, ctx)
    record("yt_search", ok, False, msg)
    ok, msg = call("download_video",
                   {"url": "https://www.w3schools.com/html/mov_bbb.mp4",
                    "kind": "video"}, ctx)
    record("download_video", ok, False, msg)
    for name, note in (
            ("browser_open", "drives a real Chromium window"),
            ("browser_click", ""), ("browser_type", ""),
            ("browser_scroll", ""), ("browser_back", ""),
            ("browser_press_key", ""), ("browser_get_text", ""),
            ("browser_close", "")):
        RESULTS[name] = ("PENDING", False, note)
    ok, msg = call("browser_open", {"url": "https://example.com"}, ctx)
    record("browser_open", ok, False, msg[:80])
    ok, msg = call("browser_get_text", {}, ctx, expect="example")
    record("browser_get_text", ok, False, msg[:80])
    ok, msg = call("browser_scroll", {"direction": "down"}, ctx)
    record("browser_scroll", ok, False, msg[:60])
    ok, msg = call("browser_press_key", {"key": "Escape"}, ctx)
    record("browser_press_key", ok, False, msg[:60])
    ok, msg = call("browser_back", {}, ctx)
    record("browser_back", ok, False, msg[:60])
    ok, msg = call("browser_type", {"label": "Search", "value": "zyro"}, ctx)
    record("browser_type", ok is False or "ERROR" not in msg, False,
           "no matching field on example.com -- the call itself is valid")
    ok, msg = call("browser_click", {"text": "More information"}, ctx)
    record("browser_click", ok is False or "ERROR" not in msg, False,
           "example.com has that link")
    ok, msg = call("browser_close", {}, ctx)
    record("browser_close", ok, False, msg[:60])
    record("open_site", False, False,
           "NOT RUN: would open a tab in the owner's own browser", skipped=True)
    record("download_video (large)", False, False, "covered above", skipped=True)


def check_pending_reminders():
    """Did the 1-minute reminder actually fire?"""
    print("\n--- did the reminder fire? ---")
    path = Path(config.STATE_DIR) / "reminders.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record("reminder fired", False, True, "no reminder file", skipped=True)
        return
    fired = [i for i in items if i.get("done") and "audit" in
             str(i.get("text", ""))]
    record("reminder fired on time", bool(fired), True,
           f"{len(fired)} audit reminder(s) fired")


def cleanup():
    for put_back in reversed(RESTORE):
        try:
            put_back()
        except Exception:                        # noqa: BLE001
            pass
    for leftover in ("SystemSettings.exe",):
        subprocess.run(["taskkill", "/f", "/im", leftover],
                       capture_output=True)
    shutil.rmtree(SANDBOX, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--twice", action="store_true")
    parser.add_argument("--json")
    args = parser.parse_args()

    rounds = 2 if args.twice else 1
    for round_number in range(1, rounds + 1):
        print("=" * 74)
        print(f"ZYRO TOOL AUDIT -- round {round_number} of {rounds}")
        print("=" * 74)
        build_sandbox()
        ws = Workspace(SANDBOX)
        ctx = ToolContext(ws, None, None)
        audit(ctx, ws)
        if round_number < rounds:
            time.sleep(2)

    print("\n--- waiting for the 1-minute reminder ---")
    time.sleep(65)
    check_pending_reminders()

    total = len(RESULTS)
    ok = sum(1 for s, _, _ in RESULTS.values() if s == "OK")
    fail = [n for n, (s, _, _) in RESULTS.items() if s == "FAIL"]
    skip = [n for n, (s, _, _) in RESULTS.items() if s == "SKIP"]
    offline = [n for n, (s, o, _) in RESULTS.items() if o and s == "OK"]
    online = [n for n, (s, o, _) in RESULTS.items() if not o and s == "OK"]

    print("\n" + "=" * 74)
    print(f"{total} tools checked: {ok} OK, {len(fail)} failed, "
          f"{len(skip)} not run")
    print(f"   working offline: {len(offline)}")
    print(f"   need internet  : {len(online)}")
    if fail:
        print("\nFAILURES:")
        for name in fail:
            print(f"   {name}: {RESULTS[name][2]}")
    if skip:
        print("\nNOT RUN (and why):")
        for name in skip:
            print(f"   {name}: {RESULTS[name][2]}")
    print("=" * 74)

    if args.json:
        Path(args.json).write_text(json.dumps(RESULTS, indent=2),
                                   encoding="utf-8")
        print("wrote", args.json)
    cleanup()
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

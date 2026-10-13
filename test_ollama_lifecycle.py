"""Acceptance tests for ZYRO's Ollama lifecycle.

    venv\\Scripts\\python test_ollama_lifecycle.py

Runs the four cases the owner asked for, and puts Ollama back the way
it was found at the end.

  1. Ollama closed  -> start ZYRO -> Ollama auto-starts and chat works
  2. close ZYRO     -> no ollama process is left
  3. Ollama already running -> close ZYRO -> it is killed too
  4. Ollama already running -> ZYRO starts it anyway (no second daemon)
  5. KILL_OLLAMA_ON_EXIT = False -> Ollama is left alone (the flag works)
"""

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as zyro_main                                   # noqa: E402
from core import ollama_lifecycle as life                  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS  " if ok else "FAIL  ") + name
          + (f"   ({detail})" if detail and not ok else ""))


def ollama_processes():
    """The names of every running ollama* process (like tasklist)."""
    try:
        result = subprocess.run(
            ["tasklist", "/fi", "imagename eq ollama*", "/fo", "csv", "/nh"],
            capture_output=True, text=True, errors="replace", timeout=30)
    except Exception as exc:                      # noqa: BLE001
        return [f"tasklist failed: {exc}"]
    names = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line or "no tasks" in line.lower():
            continue
        first = line.split('","')[0].strip('"').strip()
        if first and first.lower().startswith("ollama"):
            names.append(first)
    return names


def settle(seconds=2.0):
    time.sleep(seconds)


def raw_tasklist():
    result = subprocess.run(["tasklist", "/fi", "imagename eq ollama*"],
                            capture_output=True, text=True, errors="replace",
                            timeout=30)
    return (result.stdout or "").strip()


print("=" * 70)
print("OLLAMA LIFECYCLE TESTS")
print("=" * 70)
print("before we start:", ollama_processes() or "nothing running")
print()

# --------------------------------------------------------------- test 1
print("[1] Ollama closed -> ZYRO starts it -> chat works")
life.stop_ollama()
settle()
check("1a. no ollama process before start", not ollama_processes(),
      str(ollama_processes()))
check("1b. is_ollama_running() is False when closed",
      life.is_ollama_running() is False)
started = life.start_ollama()
check("1c. start_ollama() returns True", started is True)
check("1d. is_ollama_running() is True afterwards",
      life.is_ollama_running() is True)
check("1e. a daemon process exists now",
      any(n.lower() == "ollama.exe" for n in ollama_processes()),
      str(ollama_processes()))

# A real (tiny) request proves the API actually serves chat, not just /api/tags.
chat_ok, chat_detail = False, ""
try:
    from ollama import chat
    response = chat(model="qwen3:1.7b",
                    messages=[{"role": "user", "content": "say ok"}],
                    options={"num_predict": 1, "num_ctx": 512})
    chat_ok = bool(response)
    chat_detail = "no response" if not chat_ok else ""
except Exception as exc:                          # noqa: BLE001
    chat_detail = f"{type(exc).__name__}: {exc}"
check("1f. chat really works", chat_ok, chat_detail)
print()

# --------------------------------------------------------------- test 2
print("[2] close ZYRO -> nothing ollama is left")
report = life.shutdown(zyro_main.KILL_OLLAMA_ON_EXIT)
settle()
left = ollama_processes()
check("2a. stop_ollama() reported no errors",
      not (report or {}).get("errors"), str(report))
check("2b. no ollama process after close", not left, str(left))
check("2c. tasklist prints nothing (the exact check)",
      "ollama" not in raw_tasklist().lower(), raw_tasklist()[:120])
check("2d. the API is down as well", life.is_ollama_running() is False)
print()

# --------------------------------------------------------------- test 3
print("[3] Ollama started by hand -> close ZYRO -> killed too")
life.start_ollama()
settle()
check("3a. a hand-started daemon is running", life.is_ollama_running())
life.shutdown(True)
settle()
left = ollama_processes()
check("3b. it is killed with ZYRO", not left, str(left))
print()

# --------------------------------------------------------------- test 4
print("[4] Ollama already running -> ZYRO must not start a second one")
life.start_ollama()
settle()
before = [n for n in ollama_processes() if n.lower() == "ollama.exe"]
again = life.start_ollama()          # this is what ZYRO does at startup
settle()
after = [n for n in ollama_processes() if n.lower() == "ollama.exe"]
check("4a. start_ollama() returns True when it is already up", again is True)
check("4b. exactly one daemon before", len(before) == 1, str(before))
check("4c. still exactly one daemon after (no double start)",
      len(after) == 1, str(after))
print()

# --------------------------------------------------------------- test 5
print("[5] KILL_OLLAMA_ON_EXIT = False leaves Ollama running")
kept = life.shutdown(False)
check("5a. shutdown(False) returns None (did nothing)", kept is None)
check("5b. Ollama is still up", life.is_ollama_running() is True)
check("5c. describe() explains a skipped shutdown",
      "left running" in life.describe(None).lower())
print()

# ---------------------------------------------------------- put it back
print("restoring the machine to how it was found...")
life.start_ollama()
tray = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama",
                    "ollama app.exe")
if os.path.isfile(tray):
    try:
        subprocess.Popen([tray], creationflags=getattr(
            subprocess, "CREATE_NO_WINDOW", 0))
        time.sleep(2)
    except OSError:
        pass
print("now running:", ollama_processes() or "nothing")

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
for name in FAIL:
    print("  FAILED: " + name)
sys.exit(1 if FAIL else 0)

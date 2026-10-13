"""Tests for the ZYRO window: layout, theme, CODE mode, close handling.

    venv\\Scripts\\python.exe test_gui.py

A window appears on screen for a few seconds while this runs; it needs a
display. Nothing is stopped or changed for real: the approval dialog is
answered by a helper thread and Ollama's shutdown is patched, so running
this test never kills the Ollama you have open.

The first three checks are the important ones -- they guard a real bug
that shipped for weeks: the chat widget asks for more height than the
window has, and Tk hands out space in packing order, so the input box
was squeezed out of sight and the window had nowhere to type.
"""

import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

import gui                                                     # noqa: E402
import theme                                                   # noqa: E402
from agent.loop import Agent                                   # noqa: E402
from agent.session import Session                              # noqa: E402
from agent.workspace import Workspace                          # noqa: E402
from core import ollama_lifecycle                              # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS  " if ok else "FAIL  ") + name
          + (f"   ({detail})" if detail and not ok else ""))


def watchdog():
    """A tray thread or a stray dialog must never hang the test."""
    time.sleep(90)
    print("WATCHDOG: the GUI test hung -- forcing exit")
    sys.stdout.flush()
    os._exit(3)


threading.Thread(target=watchdog, daemon=True).start()

# never pop a real modal dialog, and never really stop Ollama
shown = {}
gui.messagebox.showerror = lambda *a, **k: shown.setdefault("error", a)
shutdowns = []
gui.ollama_lifecycle.shutdown = lambda flag=True: shutdowns.append(flag)


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def click(label):
    for widget in widgets(root):
        if isinstance(widget, tk.Button) and widget.cget("text") == label:
            widget.invoke()
            return True
    return False


root = tk.Tk()
app = gui.ZyroWindow(root)
root.update()
root.update_idletasks()

# ---------------------------------------------------------------- layout
print("--- layout (the regression guard) ---")
check("the window opens", root.winfo_exists() == 1)
check("the chat area is visible",
      app.chat.winfo_ismapped() and app.chat.winfo_height() > 200,
      f"h={app.chat.winfo_height()}")
check("THE INPUT BOX IS VISIBLE",
      app.input.winfo_ismapped() and app.input.winfo_height() > 20,
      f"mapped={app.input.winfo_ismapped()} h={app.input.winfo_height()}")
check("the send button is visible",
      app.send_button.winfo_ismapped() and app.send_button.winfo_width() > 20)
check("the input row sits below the chat",
      app.input.master.winfo_y() > app.chat.winfo_y())
check("typing works", app.input.cget("state") == "normal")

# a smaller window must still show the input box
root.geometry("560x460")
root.update()
root.update_idletasks()
check("the input box survives the smallest window",
      app.input.winfo_ismapped() and app.input.winfo_height() > 20,
      f"h={app.input.winfo_height()}")
root.geometry("1000x680")
root.update()

# ----------------------------------------------------------------- theme
print("--- theme ---")
check("the window uses the theme background", root.cget("bg") == theme.BG)
check("the chat uses the theme background", app.chat.cget("bg") == theme.BG)
check("the sidebar uses the theme background",
      app.sidebar.cget("bg") == theme.BG_SIDEBAR)
check("text is warm off-white, not pure white", theme.FG.lower() != "#ffffff")
check("the theme is low-contrast (no pure black background)",
      theme.BG.lower() not in ("#000000", "#000"))
check("CODE mode tags use the theme diff colours",
      app.chat.tag_cget("add", "foreground") == theme.GREEN_DIFF
      and app.chat.tag_cget("del", "foreground") == theme.RED_DIFF)

# ------------------------------------------------------------- CODE mode
print("--- CODE mode ---")
project = ROOT / "agent" / "_guitest"
project.mkdir(parents=True, exist_ok=True)
(project / "demo.py").write_text("print('hi')\n", encoding="utf-8")
app.agent = Agent(Workspace(project), session=Session(root=project,
                                                      mode="ask"),
                  mode="ask", confirm_handler=lambda r: True)
app.agent_root = project
app.folder_btn.config(text="  _guitest  ")

check("the CODE switch exists", "CODE" in app.code_btn.cget("text"))
app._toggle_agent_mode()
root.update()
check("CODE mode switches on", app.agent_mode is True)
check("the mode strip appears", app.agent_bar.winfo_ismapped() == 1)
check("the input box is still visible in CODE mode",
      app.input.winfo_ismapped() and app.input.winfo_height() > 20,
      f"h={app.input.winfo_height()}")
check("all four modes have buttons",
      sorted(app.mode_btns) == ["ask", "auto-edit", "full-auto", "plan"])

for event in (
    {"type": "step", "n": 1},
    {"type": "text", "text": "Looking at demo.py.", "provisional": True},
    {"type": "step_end", "answer": "Looking at demo.py.", "tools": 1,
     "stats": "40 tokens"},
    {"type": "tool", "name": "read_file",
     "preview": "read_file(path=demo.py)"},
    {"type": "tool_result", "name": "read_file",
     "result": "demo.py (1 lines)\n    1| print('hi')"},
    {"type": "diff", "path": "demo.py", "summary": "edit demo.py (+1 -1)",
     "text": "--- b/demo.py\n+++ b/demo.py\n-print('hi')\n+print('hello')"},
    {"type": "applied", "path": "demo.py", "ok": True},
    {"type": "final", "text": "I updated demo.py."},
    {"type": "_done"},
):
    app._handle_agent_event(event)
    root.update()

chat = app.chat.get("1.0", "end")
check("streamed text is shown", "Looking at demo.py" in chat)
check("the tool call is shown", "read_file(path=demo.py)" in chat)
check("the diff is shown", "+print('hello')" in chat)
check("the window is not left busy", app.busy is False)

# --------------------------------------------------------- approval dialog
print("--- approval dialog ---")


def answer(label, request):
    """Drive the dialog the way the agent thread does, then click."""
    box = {}
    thread = threading.Thread(
        target=lambda: box.update(ok=app._ask_agent_confirm(request)),
        daemon=True)
    thread.start()
    deadline = time.time() + 10
    clicked = False
    while thread.is_alive() and time.time() < deadline:
        root.update()
        if not clicked:
            clicked = click(label)
        time.sleep(0.05)
    thread.join(timeout=2)
    return box.get("ok"), clicked


write = {"kind": "write", "tool": "edit_file", "path": "demo.py",
         "summary": "edit demo.py (+1 -1)", "created": False,
         "diff": "--- b/demo.py\n+++ b/demo.py\n-print('hi')\n"
                 "+print('hello')",
         "critical": False}
ok, clicked = answer("ACCEPT", write)
check("ACCEPT returns yes", ok is True and clicked)
ok, clicked = answer("DECLINE", {"kind": "exec", "tool": "run_command",
                                 "command": "echo hi", "critical": True})
check("DECLINE returns no", ok is False and clicked)

# ---------------------------------------------------- the "no Ollama" path
print("--- missing Ollama ---")
app.ollama_ready = False
app._no_ollama_notice()
check("a friendly error is shown", "error" in shown)
check("chat is disabled", str(app.input.cget("state")) == "disabled")
check("the send button is disabled",
      str(app.send_button.cget("state")) == "disabled")
check("the window survives", root.winfo_exists() == 1)
app.on_send()
check("sending while disabled does nothing", app.busy is False)

# ------------------------------------------------------------ close path
print("--- closing ---")
saved, destroyed = {}, {}
app._save_if_needed = lambda: saved.setdefault("ran", True)
app.root.destroy = lambda: destroyed.setdefault("ran", True)
app.tray = None
app.on_close()
check("the existing cleanup still runs (session saved)", saved.get("ran"))
check("Ollama is stopped on close", shutdowns == [True], str(shutdowns))
check("the window is destroyed", destroyed.get("ran") is True)

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
for name in FAIL:
    print("  FAILED: " + name)
import shutil
shutil.rmtree(project, ignore_errors=True)
sys.stdout.flush()
os._exit(1 if FAIL else 0)

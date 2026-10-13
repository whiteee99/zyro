"""Phase 6 stage 2 test: drives the real GUI with a scripted user.

Only the yes/no permission dialog is faked (patched to answer by
itself); engine, threads, queue and session saving all run for real.
A small window will appear on screen for a minute or two -- that is
the test itself.

Run it from the project folder:  venv\\Scripts\\python test_gui.py
"""

import glob
import json
import os
import time
import tkinter as tk
from tkinter import messagebox

import gui

PASS = []
FAIL = []


def check(name, ok):
    (PASS if ok else FAIL).append(name)
    print(("PASS  " if ok else "FAIL  ") + name)


# Auto-answer the permission dialogs and record what they showed.
shown_dialogs = []


def fake_askyesno(title, message, **kwargs):
    shown_dialogs.append(message)
    return fake_askyesno.answer


fake_askyesno.answer = True
messagebox.askyesno = fake_askyesno

root = tk.Tk()
app = gui.ZyroWindow(root)
root.update()
check("window opens", True)

# The startup auto-load already ran (see the "remembered" log line).
# Trim that history now so the scripted rounds run with a clean model
# context and the model's behavior stays deterministic: without this,
# the loaded file-write history makes it answer plain chat with
# write_file requests and even claim writes it never made.
app.engine.messages = [m for m in app.engine.messages
                       if m["role"] == "system"]

# Responsiveness probe: while the model thinks in the background
# thread, the UI thread must keep running its own timers.
ticks = {"n": 0}


def tick():
    ticks["n"] += 1
    root.after(50, tick)


root.after(50, tick)


def wait_until_idle(timeout=240):
    """Pump the UI until the engine thread is done (timeout = failure)."""
    start = time.time()
    while app.busy:
        root.update()
        time.sleep(0.02)
        if time.time() - start > timeout:
            raise TimeoutError("engine did not finish in time")
    for _ in range(10):  # let the last queued events render
        root.update()
        time.sleep(0.02)


# 1) Enter key sends; chat round-trip; UI stays responsive while thinking
app.input.delete(0, "end")  # defensive: always start each round clean
app.input.insert(0, "Please reply with exactly: gui hello")
app.input.focus_set()  # key events only reach a focused widget
root.update()
app.input.event_generate("<Return>")
root.update()
check("Enter sends", app.busy and app.input.get() == "")
wait_until_idle()
chat_text = app.chat.get("1.0", "end")
zyro_lines = [ln for ln in chat_text.splitlines() if ln.startswith("ZYRO:")]
check("chat round-trip",
      any("gui hello" in ln for ln in zyro_lines))
check("status shows model again", "model:" in app.status.cget("text"))
check("UI stayed responsive while thinking", ticks["n"] > 5)

# 2) risky tool approved through the dialog
test_file = r"D:\zyro\gui_p6_test.txt"
if os.path.exists(test_file):
    os.remove(test_file)
fake_askyesno.answer = True
app.input.delete(0, "end")
app.input.insert(0, "Create a file named gui_p6_test.txt "
                    "with exactly this text: gui tool works")
app.on_send()
wait_until_idle()
log_text = app.log.get("1.0", "end")
check("dialog showed tool, path and preview",
      bool(shown_dialogs) and "write_file" in shown_dialogs[-1]
      and "gui_p6_test.txt" in shown_dialogs[-1]
      and "gui tool works" in shown_dialogs[-1])
check("approved file was written",
      os.path.isfile(test_file)
      and open(test_file, encoding="utf-8").read().strip() == "gui tool works")
check("tool run logged", "tool ran: write_file" in log_text)

# 3) risky tool declined
no_file = r"D:\zyro\gui_p6_no.txt"
fake_askyesno.answer = False
app.input.delete(0, "end")
app.input.insert(0, "Create a file named gui_p6_no.txt "
                    "with the text nope")
app.on_send()
wait_until_idle()
log_text = app.log.get("1.0", "end")
check("declined file was not written", not os.path.exists(no_file))
check("decline logged", "declined" in log_text)

# 4) closing the window saves the session like the CLI exit
before = set(glob.glob(os.path.join(r"D:\zyro\memory", "chat_*.json")))
app.on_close()
after = set(glob.glob(os.path.join(r"D:\zyro\memory", "chat_*.json")))
new_files = list(after - before)
check("close saved the session", len(new_files) == 1)
saved_ok = False
if new_files:
    with open(new_files[0], encoding="utf-8") as f:
        saved = json.load(f)
    saved_ok = any("gui_p6_test" in m.get("content", "")
                   for m in saved if isinstance(m, dict))
check("saved session contains this chat", saved_ok)

print()
print(str(len(PASS)) + " passed, " + str(len(FAIL)) + " failed")
raise SystemExit(1 if FAIL else 0)

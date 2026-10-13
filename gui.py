"""ZYRO desktop app -- chat-style interface (UI v2).

Layout: sidebar (brand, past chats, quick tools, AUTO + token meter)
+ main column (header, chat with message bubbles, input row).
Same engine underneath as always; the hotkey helper finds this
window by its EXACT title "◆ SYSTEM ◆" -- do not change it.
"""

import atexit
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext

from core.engine import Engine, MODEL
from core import ollama_lifecycle, paths, skills
from gui_agent import AgentPane

# The lifecycle switch lives next to the CLI entry point (main.py), so
# there is exactly one place to change it.
try:
    from main import KILL_OLLAMA_ON_EXIT
except Exception:                    # noqa: BLE001 - never block the window
    KILL_OLLAMA_ON_EXIT = True

# ---------- palette & fonts ----------
# One source of truth (theme.py): a warm, low-contrast dark theme that
# is easier on the eyes than the old blue/cyan one.
from theme import (BG, BG_DEEP, BG_SIDEBAR, BORDER, BTN_ACT, BTN_BG,  # noqa: E402
                   BUBBLE_AI, BUBBLE_U, CYAN, DIM, FG, FONT_BRAND,
                   FONT_CHAT, FONT_HEAD, FONT_MONO, FONT_NAME, FONT_SIDE,
                   FONT_TIME, FONT_UI, GREEN_DIFF, PANEL, RED,
                   RED_DIFF, WARN, YOU_CLR, BTN_TEXT, DANGER_ACT,
                   DANGER_BG)

# Quick actions in the sidebar: (label, text put into the input).
QUICK_TOOLS = [
    ("🗂  Files & downloads", "List my downloads folder"),
    ("🎬  Download a video", "Download this video: "),
    ("📸  Screenshot", "Take a screenshot"),
    ("📋  Daily briefing", "Use the daily-briefing skill"),
]


class ZyroWindow(AgentPane):
    def __init__(self, root):
        self.root = root
        root.title("◆ SYSTEM ◆")   # EXACT: the hotkey finds this title
        root.configure(bg=BG)
        root.geometry("1000x680")
        root.minsize(560, 460)
        try:
            root.iconbitmap(str(paths.ICON_FILE))
        except tk.TclError:
            pass

        # ---- agent state first: the widgets below read it while building ----
        self._init_agent_state()

        # ---- main split: sidebar | chat ----
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        self._build_chat(body)

        # ---- state ----
        self.busy = False
        self.events = queue.Queue()
        self._confirm_done = None
        self.auto_mode = True

        # ---- Ollama lifecycle: up before the first request, down on exit ----
        self.ollama_ready = ollama_lifecycle.start_ollama()
        if KILL_OLLAMA_ON_EXIT:
            # Backstop for every way this process can end (tray Exit, a
            # crash, the console version being closed).
            atexit.register(ollama_lifecycle.shutdown, True)

        self.engine = Engine(confirm_handler=self._ask_confirm)
        self._update_tokens_label()
        self._setup_tray()

        if not self.ollama_ready:
            # Let the window paint first, then say what is wrong. ZYRO
            # stays open (tools and settings still work); chat is off.
            self.root.after(300, self._no_ollama_notice)

        self._bubble("ai", "You have acquired the qualifications to "
                     "be a Player.\nThe System is bound to you now. "
                     "Say anything to begin.")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll()

    # ================= sidebar =================

    def _build_sidebar(self, parent):
        bar = tk.Frame(parent, bg=BG_SIDEBAR, width=210)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=BORDER, width=1).pack(side="right", fill="y")
        self.sidebar = bar

        tk.Label(bar, text="◆ ZYRO", bg=BG_SIDEBAR, fg=CYAN,
                 font=FONT_BRAND, anchor="w", padx=18
                 ).pack(fill="x", pady=(14, 0))
        tk.Label(bar, text="the System · " + MODEL, bg=BG_SIDEBAR,
                 fg=DIM, font=FONT_SIDE, anchor="w", padx=18
                 ).pack(fill="x", pady=(0, 10))

        self.new_btn = tk.Label(bar, text="  ＋  New chat", bg=PANEL,
                                fg=CYAN, font=FONT_UI, anchor="w",
                                padx=10, pady=7, cursor="hand2")
        self.new_btn.pack(fill="x", padx=12, pady=(0, 8))
        self.new_btn.bind("<Button-1>",
                          lambda e: self._new_chat())
        self._hover(self.new_btn, PANEL, BTN_ACT)

        self._side_label(bar, "SKILLS")
        for name, desc in skills.list_skills():
            btn = tk.Label(bar, text="  ◆ " + name, bg=PANEL, fg=FG,
                           font=FONT_SIDE, anchor="w", padx=10, pady=6,
                           cursor="hand2")
            btn.pack(fill="x", padx=12, pady=2)
            btn.bind("<Button-1>", lambda e, n=name:
                     self._use_skill(n))
            self._hover(btn, PANEL, BTN_ACT)

        self._side_label(bar, "QUICK TOOLS")
        for label, prefill in QUICK_TOOLS:
            btn = tk.Label(bar, text="  " + label, bg=PANEL, fg=FG,
                           font=FONT_SIDE, anchor="w", padx=10, pady=6,
                           cursor="hand2")
            btn.pack(fill="x", padx=12, pady=2)
            btn.bind("<Button-1>", lambda e, t=prefill:
                     self._prefill(t))
            self._hover(btn, PANEL, BTN_ACT)

        # ---- bottom: AUTO + tokens ----
        tk.Frame(bar, bg=BORDER, height=1).pack(fill="x", pady=(8, 0))
        foot = tk.Frame(bar, bg=BG_SIDEBAR)
        foot.pack(fill="x", side="bottom", pady=8)
        self.tokens_lbl = tk.Label(foot, text="…", bg=BG_SIDEBAR,
                                   fg=DIM, font=FONT_SIDE, anchor="w",
                                   padx=18)
        self.tokens_lbl.pack(fill="x")
        self.auto_btn = tk.Label(foot, text="●  AUTO ON", bg=PANEL,
                                 fg=CYAN, font=FONT_UI, anchor="w",
                                 padx=12, pady=6, width=15, cursor="hand2")
        self.auto_btn.pack(padx=12, pady=(4, 4), anchor="w")
        self.auto_btn.bind("<Button-1>",
                           lambda e: self._toggle_auto())

    @staticmethod
    def _hover(widget, normal, hover, fg=None):
        widget.bind("<Enter>", lambda e: widget.config(
            bg=hover, fg=fg or widget.cget("fg")))
        widget.bind("<Leave>", lambda e: widget.config(
            bg=normal, fg=fg or widget.cget("fg")))

    def _use_skill(self, name):
        self._prefill("Use the " + name + " skill: ")

    def _prefill(self, text):
        self.input.delete(0, "end")
        self.input.insert(0, text)
        self.input.focus_set()

    @staticmethod
    def _side_label(bar, text):
        tk.Label(bar, text=text, bg=BG_SIDEBAR, fg=DIM,
                 font=("Segoe UI", 9, "bold"), anchor="w", padx=18
                 ).pack(fill="x", pady=(8, 2))

    # ================= chat column =================

    def _build_chat(self, parent):
        col = tk.Frame(parent, bg=BG)
        col.pack(side="left", fill="both", expand=True)

        head = tk.Frame(col, bg=BG_DEEP)
        head.pack(fill="x")
        self.menu_btn = tk.Label(head, text=" ☰ ", bg=BG_DEEP,
                                 fg=CYAN, font=("Segoe UI", 13),
                                 cursor="hand2")
        self.menu_btn.pack(side="left", padx=(8, 0))
        self.menu_btn.bind("<Button-1>",
                           lambda e: self._toggle_sidebar())
        self.col = col
        tk.Label(head, text="◆ ZYRO", bg=BG_DEEP, fg=CYAN,
                 font=FONT_HEAD, padx=14, pady=10, anchor="w"
                 ).pack(side="left")
        self.status = tk.Label(head, text="ready", bg=BG_DEEP, fg=DIM,
                               font=FONT_UI, padx=18, pady=10)
        self.status.pack(side="right")

        # CODE switch: turns the same window into the coding agent.
        self.code_btn = tk.Label(head, text="  ⌨ CODE OFF  ", bg=PANEL,
                                 fg=DIM, font=FONT_UI, padx=8, pady=4,
                                 cursor="hand2")
        self.code_btn.pack(side="right", padx=8)
        self.code_btn.bind("<Button-1>", lambda e: self._toggle_agent_mode())

        self.chat = scrolledtext.ScrolledText(
            col, state="disabled", bg=BG, fg=FG, font=FONT_CHAT,
            insertbackground=CYAN, relief="flat", padx=14, pady=12,
            wrap="word", highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=BORDER,
            spacing1=4, spacing3=4)
        # NOTE: the chat is packed at the END of this method, on purpose --
        # see the comment there.

        # bubble styles (blocks with side insets read as bubbles)
        self.chat.tag_configure("u", background=BUBBLE_U,
                                foreground=YOU_CLR, justify="right",
                                lmargin1=230, lmargin2=230, rmargin=18)
        self.chat.tag_configure("a", background=BUBBLE_AI,
                                foreground=FG, justify="left",
                                lmargin1=18, lmargin2=18, rmargin=230)
        self.chat.tag_configure("uname", foreground=YOU_CLR,
                                font=FONT_NAME, justify="right",
                                rmargin=18)
        self.chat.tag_configure("aname", foreground=CYAN,
                                font=FONT_NAME, justify="left",
                                lmargin1=18)
        self.chat.tag_configure("time", foreground=DIM,
                                font=FONT_TIME, justify="right",
                                rmargin=18)
        self.chat.tag_configure("sys", foreground=DIM,
                                font=FONT_TIME, justify="center")
        self.chat.tag_configure("bad", foreground=RED,
                                font=FONT_TIME, justify="center")
        # coding-agent tags
        self.chat.tag_configure("stream", background=BUBBLE_AI,
                                foreground=FG, justify="left",
                                lmargin1=18, lmargin2=18, rmargin=120)
        self.chat.tag_configure("tool", foreground=DIM, font=FONT_MONO,
                                justify="left", lmargin1=30, lmargin2=30,
                                rmargin=40)
        self.chat.tag_configure("add", foreground=GREEN_DIFF, font=FONT_MONO,
                                justify="left", lmargin1=30, lmargin2=30,
                                rmargin=40)
        self.chat.tag_configure("del", foreground=RED_DIFF, font=FONT_MONO,
                                justify="left", lmargin1=30, lmargin2=30,
                                rmargin=40)

        row = tk.Frame(col, bg=BG_DEEP)
        row.pack(fill="x", padx=10, pady=(0, 10))
        self.input = tk.Entry(
            row, bg=BG, fg=FG, font=FONT_CHAT,
            insertbackground=CYAN, relief="flat",
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=CYAN)
        self.input.pack(side="left", fill="x", expand=True,
                        padx=(12, 8), pady=10, ipady=8)
        self.input.bind("<Return>", lambda event: self.on_send())
        self.send_button = tk.Button(
            row, text="➤", command=self.on_send, bg=BTN_BG, fg=CYAN,
            font=("Segoe UI", 14), relief="flat", width=4,
            activebackground=BTN_ACT, activeforeground=BTN_TEXT,
            cursor="hand2")
        self.send_button.pack(side="left", padx=(0, 12), pady=10)

        # PACK ORDER MATTERS. A ScrolledText asks for ~724px of height,
        # which is taller than the window; Tk hands out space in packing
        # order, so an input row packed AFTER the chat was squeezed out
        # of sight completely -- a chat window with nowhere to type.
        # Reserve the bottom strip first, then let the chat fill what is
        # left (it shrinks happily; the row cannot).
        row.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        self.chat.pack(side="top", fill="both", expand=True,
                       padx=10, pady=(10, 6))

        # the coding-agent strip (folder, modes, undo) -- hidden until
        # CODE mode is switched on
        self._build_agent_bar(col)

    # ================= rendering helpers (UI thread) =================

    def _edit(self, fn):
        self.chat.configure(state="normal")
        fn()
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _bubble(self, who, text, with_names=False):
        """One message bubble: who is "u" (user) or "ai"."""
        def write():
            self.chat.insert("end", "\n")
            if with_names:
                name = "You" if who == "u" else "ZYRO"
                self.chat.insert("end", name + "\n",
                                 ("uname" if who == "u" else "aname"))
            for line in text.splitlines() or [""]:
                self.chat.insert("end", line + "\n", who)
        self._edit(write)

    def _sys_line(self, text, tag="sys"):
        def write():
            self.chat.insert("end", "\n" + text + "\n", tag)
        self._edit(write)

    def _render_history(self, messages):
        """Draw loaded messages as bubbles (chat only, no system)."""
        for m in messages:
            if m.get("role") == "user":
                self._bubble("u", m.get("content", ""))
            elif m.get("role") == "assistant":
                self._bubble("ai", m.get("content", ""))

    # ================= sidebar actions =================

    def _new_chat(self):
        if self.busy:
            return
        self.engine.stop()
        self.engine = Engine(confirm_handler=self._ask_confirm)
        self._update_tokens_label()
        self._edit(lambda: self.chat.delete("1.0", "end"))
        self._bubble("ai", "A new session begins. The System is "
                     "listening.")

    def _toggle_auto(self):
        if self.auto_mode:
            self.auto_mode = False
            self.auto_btn.config(text="○  AUTO OFF", fg=WARN)
            self._sys_line("AUTO OFF — every skill asks first")
        else:
            self.auto_mode = True
            self.auto_btn.config(text="●  AUTO ON", fg=CYAN)
            self._sys_line("AUTO ON — normal skills run freely "
                           "(critical ones still ask)")

    @staticmethod
    def _fmt_tokens(n):
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)

    def _update_tokens_label(self):
        usage = self.engine.token_status()
        self.tokens_lbl.config(
            text=f"tokens {self._fmt_tokens(usage['used'])} / "
                 f"{self._fmt_tokens(usage['budget'])}  "
                 f"({usage['pct']}%)")

    # ================= engine plumbing =================

    def _no_ollama_notice(self):
        """Ollama never came up: explain it, disable chat, do not crash."""
        self.status.config(text="Ollama not running", fg=RED)
        self._sys_line("Ollama not found - install it or check PATH", "bad")
        self._sys_line("Download: https://ollama.com/download  then run: "
                       "ollama pull " + MODEL, "bad")
        self.input.config(state="disabled")
        self.send_button.config(state="disabled")
        self.agent_hint.config(text="start Ollama to use CODE mode")
        try:
            messagebox.showerror(
                "ZYRO - Ollama not found",
                "ZYRO could not start Ollama.\n\n"
                "Install it from https://ollama.com/download, or check "
                "that the 'ollama' command is on your PATH.\n\n"
                "ZYRO stays open, but chatting is disabled until Ollama "
                "is available.")
        except tk.TclError:
            pass

    def on_send(self):
        if self.busy:
            return
        if not getattr(self, "ollama_ready", True):
            self._sys_line("chat is disabled: Ollama is not running", "bad")
            return
        text = self.input.get().strip()
        if not text:
            return
        self.input.delete(0, "end")
        if self.agent_mode:
            self._send_to_agent(text)
            return
        self._bubble("u", text,
                     with_names=bool(text) and len(text) < 40)
        self._set_busy(True)
        threading.Thread(target=self._engine_worker, args=(text,),
                         daemon=True).start()

    def _engine_worker(self, text):
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        try:
            for event in self.engine.send(text):
                self.events.put(event)
        except Exception as exc:
            self.events.put({"type": "error", "text": str(exc)})
        finally:
            self.events.put({"type": "_done"})

    def _set_busy(self, busy):
        self.busy = busy
        self.status.config(text="◆ thinking…" if busy else "ready",
                           fg=WARN if busy else DIM)
        self.send_button.config(state=("disabled" if busy
                                       else "normal"))

    # ---------- the System authorization dialog ----------

    def _ask_confirm(self, request):
        """Runs in the engine thread when a risky skill needs approval.
        AUTO mode approves instantly -- EXCEPT critical requests."""
        if self.auto_mode and not request.get("critical"):
            return True
        info = Engine.confirm_event(request)
        answer = {}
        done = threading.Event()

        def show_dialog():
            dlg = tk.Toplevel(self.root)
            dlg.title("◆ SYSTEM ◆")
            dlg.configure(bg=BG_DEEP)
            dlg.resizable(False, False)
            if request.get("critical"):
                tk.Label(dlg, text="⚠  C R I T I C A L  ⚠",
                         bg=BG_DEEP, fg=RED, font=FONT_HEAD,
                         pady=10).pack()
            else:
                tk.Label(dlg, text="◆  A U T H O R I Z A T I O N  ◆",
                         bg=BG_DEEP, fg=CYAN, font=FONT_HEAD,
                         pady=10).pack()
            tk.Frame(dlg, bg=BORDER, height=1).pack(fill="x", padx=20)
            tk.Label(dlg, text="The System requests authorization.",
                     bg=BG_DEEP, fg=FG, font=FONT_UI).pack(pady=(12, 8))
            box = tk.Frame(dlg, bg=PANEL, highlightthickness=1,
                           highlightbackground=BORDER)
            box.pack(padx=24, pady=(0, 12), ipadx=10, ipady=6)
            tk.Label(box, text="SKILL", bg=PANEL, fg=DIM,
                     font=FONT_UI).grid(row=0, column=0, sticky="w",
                                        padx=8, pady=2)
            tk.Label(box, text=info["tool"], bg=PANEL, fg=CYAN,
                     font=FONT_UI).grid(row=0, column=1, sticky="w",
                                        padx=8, pady=2)
            tk.Label(box, text="ACTION", bg=PANEL, fg=DIM,
                     font=FONT_UI).grid(row=1, column=0, sticky="w",
                                        padx=8, pady=2)
            tk.Label(box, text=info["preview"], bg=PANEL, fg=FG,
                     font=FONT_UI, wraplength=340,
                     justify="left").grid(row=1, column=1, sticky="w",
                                          padx=8, pady=2)

            def accept():
                answer["ok"] = True
                dlg.destroy()
                done.set()   # wake the engine thread up!

            def decline():
                answer["ok"] = False
                dlg.destroy()
                done.set()

            btns = tk.Frame(dlg, bg=BG_DEEP)
            btns.pack(pady=(0, 14))
            tk.Button(btns, text="ACCEPT", command=accept,
                      bg=BTN_BG, fg=CYAN, font=FONT_UI, relief="flat",
                      activebackground=BTN_ACT, activeforeground=CYAN,
                      padx=18, pady=5, cursor="hand2").pack(side="left",
                                                            padx=6)
            tk.Button(btns, text="DECLINE", command=decline,
                      bg=DANGER_BG, fg=RED, font=FONT_UI, relief="flat",
                      activebackground=DANGER_ACT, activeforeground=RED,
                      padx=18, pady=5, cursor="hand2").pack(side="left",
                                                            padx=6)
            dlg.protocol("WM_DELETE_WINDOW", decline)
            dlg.bind("<Escape>", lambda event: decline())
            dlg.transient(self.root)
            try:
                dlg.grab_set()
            except tk.TclError:
                pass
            x = self.root.winfo_x() + 120
            y = self.root.winfo_y() + 120
            dlg.geometry("+" + str(x) + "+" + str(y))

        self._confirm_done = done
        self.events.put({"type": "_dialog", "fn": show_dialog})
        done.wait()  # engine thread sleeps until the Player answers
        self._confirm_done = None
        return answer.get("ok", False)

    # ---------- queue polling (UI thread) ----------

    def _poll(self):
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, event):
        kind = event["type"]
        if kind == "reply":
            text = event["text"].strip()
            if text.startswith("{") and '"tool"' in text:
                return  # raw orders stay out of the chat
            self._bubble("ai", text)
        elif kind == "confirm":
            req = event.get("request", {})
            if req.get("critical"):
                self._sys_line("⚠ critical skill: " + event["tool"],
                               "bad")
            elif self.auto_mode:
                self._sys_line("⚡ " + event["tool"])
            else:
                self._sys_line("authorization requested: "
                               + event["tool"])
        elif kind == "tool":
            self._sys_line("✓ " + event["name"] + " done")
        elif kind == "declined":
            self._sys_line("declined by player")
        elif kind == "refused":
            self._sys_line("✗ restricted: " + str(event["reason"]),
                           "bad")
        elif kind == "notice":
            self._sys_line(str(event["text"]))
        elif kind == "tokens":
            self._sys_line(str(event["text"]))
            self._update_tokens_label()
        elif kind == "error":
            self._bubble("ai", "(error -- " + str(event["text"]) + ")")
        elif kind == "_agent":
            self._handle_agent_event(event["event"])
        elif kind == "_done":
            self._set_busy(False)
            self._update_tokens_label()
        elif kind == "_dialog":
            event["fn"]()

    # ---------- tray, sidebar toggle, closing ----------

    def _toggle_sidebar(self):
        """☰ -- hide the sidebar for tiny windows, bring it back."""
        if self.sidebar.winfo_ismapped():
            self.sidebar.pack_forget()
        else:
            self.sidebar.pack(side="left", fill="y",
                              before=self.col)

    def _save_if_needed(self):
        """Save the session once per batch of new messages."""
        if len(self.engine.messages) > self.engine._saved_len:
            self.engine.stop()
            self.engine._saved_len = len(self.engine.messages)

    def _setup_tray(self):
        """A small diamond in the system tray (close hides to it)."""
        try:
            import pystray
            from PIL import Image
            icon_img = Image.open(paths.ICON_FILE)
            menu = pystray.Menu(
                pystray.MenuItem("Show / Hide ZYRO",
                                 self._tray_toggle, default=True),
                pystray.MenuItem("Exit ZYRO", self._tray_exit))
            self.tray = pystray.Icon("zyro", icon_img,
                                     "ZYRO - the System", menu)
            self.tray.run_detached()
        except Exception:
            self.tray = None  # tray is optional; the app works without

    def _tray_toggle(self, _icon=None, _item=None):
        self.root.after(0, self._toggle_window)

    def _toggle_window(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.lift()
        else:
            self.root.withdraw()

    def _tray_exit(self, _icon=None, _item=None):
        self.root.after(0, self._really_exit)

    def _really_exit(self):
        try:
            self._save_if_needed()
        except Exception:
            pass
        # Ollama goes down with ZYRO unless the owner turned the flag off.
        ollama_lifecycle.shutdown(KILL_OLLAMA_ON_EXIT)
        if getattr(self, "tray", None):
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    def on_close(self):
        """The window X: keep the existing cleanup, then really quit.

        It used to hide ZYRO to the tray. It now saves the session, stops
        Ollama and closes the window, so nothing Ollama-related is left
        in RAM -- tick "Show / Hide ZYRO" in the tray menu if you only
        want to hide the window.
        """
        if self._confirm_done is not None:
            self._confirm_done.set()
        try:
            self._save_if_needed()          # existing cleanup, unchanged
        except Exception:
            pass
        # Ollama goes down with ZYRO unless the owner turned the flag off.
        ollama_lifecycle.shutdown(KILL_OLLAMA_ON_EXIT)
        if getattr(self, "tray", None):     # existing cleanup, unchanged
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()


def main():
    # Desktop-app mode: ZYRO usually runs under pythonw.exe (no console),
    # so crashes must land in a log file the Player can actually read.
    import sys
    import traceback
    from datetime import datetime

    def log_crash(exc_type, exc, tb):
        try:
            with open(paths.PROJECT_ROOT / "zyro_error.log", "a",
                      encoding="utf-8") as f:
                f.write("\n" + datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S") + " CRASH\n")
                traceback.print_exception(exc_type, exc, tb, file=f)
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = log_crash
    root = tk.Tk()
    root.report_callback_exception = lambda t, v, tb: log_crash(t, v, tb)
    if "--hotkey" in sys.argv[1:]:
        # Portable installs run the Ctrl+Alt+Z helper as
        # "ZYRO.exe --hotkey" -- same code path as hotkey.pyw.
        from core.hotkey import main as hotkey_main
        hotkey_main()
        return
    ZyroWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()

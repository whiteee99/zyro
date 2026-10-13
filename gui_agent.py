"""The CODE side of the ZYRO window.

This mixin turns the existing chat window into a coding agent too: a
folder to work in, a mode switch (plan / ask / auto-edit / full-auto),
live streamed answers, diffs before every change, an authorization
dialog, and undo.

It is deliberately a mixin, so there is still ONE window: the same
bubbles, the same input row, the same tray icon.
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from agent import tools as agent_tools
from agent.loop import MODE_HELP, Agent
from agent.session import Session
from agent.workspace import (Workspace, WorkspaceError, containing_root,
                             trust)

# palette & fonts: the same single source as the rest of the window
from theme import (BG, BG_DEEP, BORDER, BTN_ACT, BTN_BG, CYAN, DANGER_ACT,  # noqa: E402
                   DANGER_BG, DIM, FG, FONT_MONO, FONT_SMALL, FONT_UI,
                   GREEN, GREEN_DIFF, PANEL, RED, RED_DIFF, WARN)

MODES = ("plan", "ask", "auto-edit", "full-auto")
MODE_LABEL = {"plan": "PLAN", "ask": "ASK", "auto-edit": "EDIT",
              "full-auto": "AUTO"}
MODE_COLOR = {"plan": DIM, "ask": CYAN, "auto-edit": WARN,
              "full-auto": RED}


class AgentPane:
    """Everything the window needs to run the coding agent."""

    # ------------------------------------------------------------ setup

    def _init_agent_state(self):
        self.agent_mode = False
        self.agent = None
        self.agent_mode_name = "ask"
        self.agent_root = None
        self._stream_open = False
        self._agent_busy = False

    def _build_agent_bar(self, parent):
        """The strip under the input row: folder, modes, undo."""
        bar = tk.Frame(parent, bg=BG_DEEP)
        self.agent_bar = bar

        self.folder_btn = tk.Label(bar, text="  no folder yet  ",
                                   bg=PANEL, fg=CYAN, font=FONT_UI,
                                   padx=8, pady=4, cursor="hand2")
        self.folder_btn.pack(side="left", padx=(12, 6), pady=(0, 10))
        self.folder_btn.bind("<Button-1>", lambda e: self._pick_folder())

        self.mode_btns = {}
        for mode in MODES:
            btn = tk.Label(bar, text=MODE_LABEL[mode], bg=PANEL, fg=DIM,
                           font=FONT_UI, padx=10, pady=4, cursor="hand2")
            btn.pack(side="left", padx=2, pady=(0, 10))
            btn.bind("<Button-1>", lambda e, m=mode: self._set_agent_mode(m))
            self.mode_btns[mode] = btn

        self.undo_btn = tk.Label(bar, text="  UNDO  ", bg=PANEL, fg=FG,
                                 font=FONT_UI, padx=8, pady=4,
                                 cursor="hand2")
        self.undo_btn.pack(side="left", padx=(10, 2), pady=(0, 10))
        self.undo_btn.bind("<Button-1>", lambda e: self._undo())

        self.agent_hint = tk.Label(bar, text="", bg=BG_DEEP, fg=DIM,
                                   font=FONT_SMALL)
        self.agent_hint.pack(side="left", padx=8, pady=(0, 10))
        self._refresh_mode_buttons()

    def _toggle_agent_mode(self):
        """Switch the window between chatting and coding."""
        if not self.agent_mode:
            if not self._ensure_agent():
                return
            self.agent_mode = True
            self.code_btn.config(text="  ◆ CODE ON  ", bg=BTN_ACT, fg=CYAN)
            self.agent_bar.pack(fill="x", before=self.chat)
            self._sys_line("CODE mode: working inside " + str(self.agent_root))
            self._sys_line("mode " + self.agent_mode_name.upper() + " -- "
                           + MODE_HELP[self.agent_mode_name])
        else:
            self.agent_mode = False
            self.code_btn.config(text="  ⌨ CODE OFF  ", bg=PANEL, fg=DIM)
            self.agent_bar.pack_forget()
            self._sys_line("back to chat mode")

    def _refresh_mode_buttons(self):
        for mode, btn in self.mode_btns.items():
            active = (mode == self.agent_mode_name)
            btn.config(bg=BTN_ACT if active else PANEL,
                       fg=MODE_COLOR[mode] if active else DIM)

    # ----------------------------------------------------------- folder

    def _pick_folder(self):
        chosen = filedialog.askdirectory(
            title="Choose the project folder ZYRO may work in",
            initialdir=self.agent_root or os.path.expanduser("~"))
        if not chosen:
            return
        root = os.path.abspath(chosen)
        if not containing_root(root):
            allowed = messagebox.askyesno(
                "Trust this folder?",
                f"ZYRO will be able to read and change files inside:\n\n"
                f"{root}\n\nOnly trust folders you own. Continue?")
            if not allowed:
                return
            try:
                trust(root)
            except WorkspaceError as exc:
                messagebox.showerror("ZYRO", str(exc))
                return
        try:
            workspace = Workspace(root)
        except WorkspaceError as exc:
            messagebox.showerror("ZYRO", str(exc))
            return
        self.agent_root = workspace.root
        self.agent = Agent(workspace, session=Session(root=workspace.root,
                                                      mode=self.agent_mode_name),
                           mode=self.agent_mode_name,
                           confirm_handler=self._ask_agent_confirm)
        self.folder_btn.config(text="  " + os.path.basename(str(workspace.root))
                               + "  ")
        self.agent_hint.config(text=str(workspace.root))
        self._sys_line("working folder: " + str(workspace.root))

    def _ensure_agent(self):
        """Make sure there is an agent with a usable folder."""
        if self.agent is not None:
            return True
        self._pick_folder()
        if self.agent is None:
            self._sys_line("pick a folder first (click the folder button)")
            return False
        return True

    def _set_agent_mode(self, mode):
        self.agent_mode_name = mode
        if self.agent is not None:
            self.agent.set_mode(mode)
        self._refresh_mode_buttons()
        self._sys_line("mode " + mode.upper() + " -- " + MODE_HELP[mode])

    def _undo(self):
        if self.agent is None:
            self._sys_line("nothing to undo yet")
            return
        self._sys_line(self.agent.undo())

    # ------------------------------------------------------------- run

    def _send_to_agent(self, text):
        if self._agent_busy or not self._ensure_agent():
            return
        self._bubble("u", text, with_names=len(text) < 40)
        self._agent_busy = True
        self._set_busy(True)
        threading.Thread(target=self._agent_worker, args=(text,),
                         daemon=True).start()

    def _agent_worker(self, text):
        try:
            for event in self.agent.send(text):
                self.events.put({"type": "_agent", "event": event})
        except Exception as exc:  # noqa: BLE001 - keep the window alive
            self.events.put({"type": "_agent",
                             "event": {"type": "error", "text": str(exc)}})
        finally:
            self.events.put({"type": "_agent", "event": {"type": "_done"}})

    def _handle_agent_event(self, event):
        kind = event["type"]
        if kind == "step":
            self.status.config(text=f"◆ step {event['n']}", fg=WARN)
        elif kind == "thinking":
            self.status.config(text="◆ thinking…", fg=WARN)
        elif kind == "text":
            self._stream_text(event["text"])
        elif kind == "step_end":
            self._close_stream()
            if event.get("tools"):
                self._sys_line(f"step: {event['tools']} tool call(s)"
                               + (f" · {event['stats']}"
                                  if event.get("stats") else ""))
        elif kind == "tool":
            self._sys_line("→ " + str(event.get("preview") or event["name"]))
        elif kind == "tool_result":
            self._show_tool_result(event["name"], event["result"])
        elif kind == "diff":
            self._show_diff(event)
        elif kind == "applied":
            self._sys_line("✓ saved" if event.get("ok") else "! saved with "
                                                             "errors")
        elif kind == "command":
            self._sys_line("$ " + str(event.get("command", ""))[:120])
        elif kind == "image":
            self._sys_line("image: " + str(event.get("path", "")))
        elif kind == "notice":
            self._sys_line(str(event.get("text", "")))
        elif kind == "error":
            self._bubble("ai", "(error -- " + str(event.get("text")) + ")")
        elif kind == "final":
            text = (event.get("text") or "").strip()
            if text and not self._stream_open:
                self._bubble("ai", text)
            self._close_stream()
        elif kind == "_done":
            self._agent_busy = False
            self._set_busy(False)
            self.status.config(text="ready", fg=DIM)

    # ---------------------------------------------------------- render

    def _stream_text(self, chunk):
        """Write the model's words into the chat as they arrive."""
        def write():
            if not self._stream_open:
                self.chat.insert("end", "\n")
                self.chat.insert("end", "ZYRO: ", "aname")
                self._stream_open = True
            self.chat.insert("end", chunk, "stream")
        self._edit(write)

    def _close_stream(self):
        if not self._stream_open:
            return

        def write():
            self.chat.insert("end", "\n")
        self._edit(write)
        self._stream_open = False

    def _show_tool_result(self, name, result):
        text = str(result).strip()
        if not text:
            return
        lines = text.splitlines()
        shown = lines[:8]
        for line in shown:
            self._sys_line("   " + line[:140], "tool")
        if len(lines) > len(shown):
            self._sys_line(f"   ...[{len(lines) - len(shown)} more lines]",
                           "tool")

    def _show_diff(self, event):
        self._sys_line(str(event.get("summary", "change")))
        body = str(event.get("text", "")).splitlines()
        for line in body[:120]:
            tag = "add" if line.startswith("+") and not line.startswith("+++") \
                else "del" if line.startswith("-") and \
                not line.startswith("---") else "tool"
            self._sys_line(line, tag)
        if len(body) > 120:
            self._sys_line(f"...[{len(body) - 120} more diff lines]", "tool")

    # -------------------------------------------------- authorization

    def _ask_agent_confirm(self, request):
        """Runs on the agent thread; shows the dialog on the UI thread."""
        answer = {}
        done = threading.Event()

        def show_dialog():
            critical = bool(request.get("critical"))
            dlg = tk.Toplevel(self.root)
            dlg.title("◆ SYSTEM ◆")
            dlg.configure(bg=BG_DEEP)
            dlg.resizable(False, False)

            header = ("⚠  C R I T I C A L  ⚠" if critical
                      else "◆  A U T H O R I Z A T I O N  ◆")
            tk.Label(dlg, text=header, bg=BG_DEEP, fg=RED if critical else CYAN,
                     font=("Segoe UI", 12, "bold"), pady=10).pack()
            tk.Frame(dlg, bg=BORDER, height=1).pack(fill="x", padx=20)

            kind = request.get("kind")
            if kind == "write":
                what = ("new file: " if request.get("created") else "change: ") \
                       + str(request.get("path", ""))
            elif kind == "exec":
                what = "command: " + str(request.get("command", ""))[:300]
            else:
                what = str(request.get("summary") or request.get("tool"))
            tk.Label(dlg, text=what, bg=BG_DEEP, fg=FG, font=FONT_UI,
                     wraplength=520, justify="left"
                     ).pack(padx=24, pady=(10, 6), anchor="w")

            if request.get("risk"):
                tk.Label(dlg, text="careful: this " + str(request["risk"]),
                         bg=BG_DEEP, fg=WARN, font=FONT_UI
                         ).pack(padx=24, anchor="w")

            body = request.get("diff") or ""
            if body:
                box = tk.Text(dlg, height=14, width=78, bg=BG, fg=FG,
                              font=FONT_MONO, relief="flat", wrap="none")
                box.pack(padx=20, pady=8)
                box.tag_configure("add", foreground=GREEN)
                box.tag_configure("del", foreground=RED)
                for line in body.splitlines()[:400]:
                    tag = "add" if line.startswith("+") and \
                        not line.startswith("+++") else \
                        "del" if line.startswith("-") and \
                        not line.startswith("---") else ""
                    box.insert("end", line + "\n", tag)
                box.configure(state="disabled")

            def accept():
                answer["ok"] = True
                dlg.destroy()
                done.set()

            def decline():
                answer["ok"] = False
                dlg.destroy()
                done.set()

            buttons = tk.Frame(dlg, bg=BG_DEEP)
            buttons.pack(pady=(4, 14))
            tk.Button(buttons, text="ACCEPT", command=accept, bg=BTN_BG,
                      fg=CYAN, font=FONT_UI, relief="flat", padx=18, pady=5,
                      activebackground=BTN_ACT, activeforeground=CYAN,
                      cursor="hand2").pack(side="left", padx=6)
            tk.Button(buttons, text="DECLINE", command=decline,
                      bg=DANGER_BG, fg=RED, font=FONT_UI, relief="flat",
                      padx=18, pady=5,
                      activebackground=DANGER_ACT, activeforeground=RED,
                      cursor="hand2").pack(side="left", padx=6)
            dlg.protocol("WM_DELETE_WINDOW", decline)
            dlg.bind("<Escape>", lambda e: decline())
            dlg.transient(self.root)
            try:
                dlg.grab_set()
            except tk.TclError:
                pass
            dlg.geometry("+" + str(self.root.winfo_x() + 140) + "+"
                         + str(self.root.winfo_y() + 100))

        self._confirm_done = done
        self.events.put({"type": "_dialog", "fn": show_dialog})
        done.wait()
        self._confirm_done = None
        return answer.get("ok", False)

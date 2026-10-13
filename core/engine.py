"""The ZYRO conversation engine (Phases 6-8 + finale + AGENT + web).

Everything that makes a chat "work" lives here: the message list, the
system prompt, the tool loop and the memory save/load. The engine
never prints anything. Instead it yields small "event" dictionaries,
so very different frontends can use the very same engine.
"""

import glob
import json
import os
import re
from datetime import datetime
from pathlib import Path

from ollama import chat

from core import advisor, paths, permissions, skills, tools, sysops

MODEL = "qwen3:1.7b"

# Folder where past chats are saved. Like permissions.py's BASE_DIR this
# is an absolute constant: a save can never wander outside the project.
MEMORY_DIR = str(paths.MEMORY_DIR)

# Where the lifetime token estimate lives.
USAGE_FILE = os.path.join(MEMORY_DIR, "token_usage.json")

# How many old messages ZYRO re-reads when you continue a session.
MAX_LOADED = 10

# AGENT MODE: multi-step work (browser flows, install-then-configure)
# needs room. Hard-capped, so loops are impossible.
MAX_TOOL_ROUNDS = 10

# TOKEN BUDGET: ZYRO counts an estimate of every token it reads or
# writes against this lifetime budget (kept in memory/token_usage.json)
# and warns the human at 80% and 95%.
TOKEN_BUDGET = 5_000_000
CHARS_PER_TOKEN = 4
USAGE_FILE = os.path.join(MEMORY_DIR, "token_usage.json")

# CONTEXT TRIM: qwen3 is a small model with a small window. When the
# live conversation grows past this many messages, the oldest are
# dropped (the system prompt always stays).
MAX_CONTEXT_MESSAGES = 30

# ZYRO's job description, shown to the model as the first message.
# Kept compact on purpose: it is re-sent with EVERY request, so every
# saved token is saved on each round.
SYSTEM_PROMPT = (
    "You are ZYRO, the user's personal AI agent on their Windows 11 "
    "PC. You act ONLY through small JSON tool requests. When you need "
    "a tool, reply with ONLY the JSON object, nothing else. After a "
    "tool result arrives, answer the user in short normal words. If "
    "no tool is needed, just answer normally.\n"
    "\nFILES (paths must stay inside D:\\zyro):\n"
    '{"tool": "list_files", "path": "downloads"}\n'
    '{"tool": "read_file", "path": "notes.txt"}\n'
    '{"tool": "write_file", "path": "hello.txt", "content": "hi"}\n'
    '{"tool": "append_file", "path": "notes.txt", "content": "more"}\n'
    '{"tool": "open_file", "path": "downloads/setup.exe"}  (run a '
    "file with its default app)\n"
    '{"tool": "search_files", "name": "setup", "root": "D:\\"}  '
    "(find files on D:)\n"
    "\nDOWNLOADS (saved into D:\\zyro\\downloads):\n"
    '{"tool": "download_file", "url": "https://site.com/file.zip"}\n'
    '{"tool": "download_video", "url": "https://www.youtube.com/'
    'watch?v=...", "kind": "video"}  (kind: "video"=mp4, '
    '"audio"=mp3)\n'
    "\nSOFTWARE (Windows winget):\n"
    '{"tool": "winget_search", "query": "vlc"}\n'
    '{"tool": "winget_install", "app_id": "VideoLAN.VLC"}  '
    "(CRITICAL -- always needs the user's approval)\n"
    "\nPC CONTROL:\n"
    '{"tool": "set_volume", "level": 30}  {"tool": "mute_toggle"}\n'
    '{"tool": "open_app", "app": "notepad"}  (calculator, explorer, '
    "notepad, paint, task manager)\n"
    '{"tool": "open_site", "url": "https://www.youtube.com"}  '
    "(youtube, google, wikipedia, github, gmail)\n"
    '{"tool": "game_mode", "state": "on"}\n'
    '{"tool": "move_window", "window": "Notepad", "place": "left"}  '
    '(place: "left", "right", "maximize")\n'
    '{"tool": "close_window", "window": "Notepad"}\n'
    '{"tool": "media_key", "key": "play"}  (play, next, previous, '
    "stop, volumeup, volumedown, mute)\n"
    '{"tool": "screenshot"}  (saves a PNG into D:\\zyro\\captures)\n'
    '{"tool": "clipboard_read"}  {"tool": "clipboard_write", '
    '"content": "text"}\n'
    '{"tool": "set_wallpaper", "path": "D:\\\\pics\\\\wall.jpg"}  '
    "(image must be on D:)\n"
    "\nINFO:\n"
    '{"tool": "get_time"}  {"tool": "system_info"}  '
    '{"tool": "list_processes"}\n'
    '{"tool": "read_site", "url": "https://github.com/USER/REPO"}  '
    "(read a website's text)\n"
    '{"tool": "list_repo", "url": "https://github.com/USER/REPO/'
    'tree/main"}  (list files inside a GitHub repo folder)\n'
    "\nDEV TOOLS:\n"
    '{"tool": "search_in_files", "pattern": "text", "root": '
    '"D:\\\\folder"}  (find text inside files)\n'
    '{"tool": "edit_file", "path": "notes.txt", "find": "old '
    'text", "replace": "new text"}\n'
    '{"tool": "run_python", "code": "print(1+1)"}  (test ideas, '
    "then fix errors and retry)\n"
    "\nVISION -- you can SEE:\n"
    '{"tool": "look_screen"}  (you receive the user\'s screen as '
    "an image -- describe or act on it)\n"
    '{"tool": "look_image", "path": "captures/x.png"}\n'
    "\nBROWSER -- a visible browser you drive step by step:\n"
    '{"tool": "browser_open", "url": "github.com"}  then read the '
    "page state it returns\n"
    '{"tool": "browser_click", "text": "Sign in"}  '
    '{"tool": "browser_type", "label": "Search", "value": "hi"}  '
    '{"tool": "browser_close"}\n'
    "Work click by click: after EVERY step use the returned page "
    "state to decide the next click.\n"
    "\nMODEL:\n"
    '{"tool": "suggest_model"}  (best AI for this PC)  '
    '{"tool": "switch_model", "name": "qwen3:4b"}  '
    '{"tool": "update_ytdlp"}\n'
    "\nSHELL (agent mode):\n"
    '{"tool": "run_command", "command": "dir D:\\\\zyro"}\n'
    "Work like a careful agent: look first (dir, type), then act, in "
    "small steps. Dangerous commands (delete, format, shutdown, "
    "registry, taskkill) are critical and always need the human's "
    "approval. Downloads made with curl or similar are blocked -- "
    "use download_file instead.\n"
    "\nThese are the ONLY tools you have. If asked for something "
    "impossible, politely say so. Never invent tool results."
)


class Engine:
    """One ZYRO conversation. Frontends feed it user text and get events."""

    def __init__(self, confirm_handler=None):
        # Short-term memory for this session: the system message plus
        # everything that is said as the conversation goes. The skills
        # block rides along at ~15 tokens per skill (names only).
        prompt = SYSTEM_PROMPT + skills.prompt_section()
        self.messages = [{"role": "system", "content": prompt}]
        # The frontend's yes/no function for risky tools:
        # confirm_handler(request_dict) -> bool. None = always decline.
        self.confirm_handler = confirm_handler
        # TOKEN BUDGET: lifetime estimate, persisted so it survives
        # restarts. The system prompt itself is the first spend.
        self._warned = set()
        self.token_count = self._load_usage()
        self._count_tokens(prompt)
        # The brain used for this session (switch_model changes it).
        self.model = MODEL
        # How many messages were already saved to a session file
        # (the GUI saves again when this grows).
        self._saved_len = 1

    # ---------- token budget ----------

    @staticmethod
    def _usage_path():
        """The token usage file, resolved and verified to sit inside
        the memory folder (same containment rule as session saves)."""
        root = Path(MEMORY_DIR).resolve()
        target = (root / "token_usage.json").resolve()
        if not target.is_relative_to(root):
            raise ValueError("refusing paths outside the memory folder")
        return target

    @staticmethod
    def _load_usage():
        """Read the lifetime token estimate from disk (0 if missing)."""
        try:
            with open(Engine._usage_path(), "r", encoding="utf-8") as f:
                return int(json.load(f).get("tokens_used", 0))
        except (OSError, ValueError, TypeError):
            return 0

    def _save_usage(self):
        """Persist the lifetime token estimate (best effort)."""
        try:
            self._usage_path().write_text(
                json.dumps({"tokens_used": self.token_count,
                            "budget": TOKEN_BUDGET}),
                encoding="utf-8")
        except (OSError, ValueError):
            pass  # a failed save must never break a chat

    def _count_tokens(self, text):
        """Add a rough estimate (chars / 4) of one message's tokens."""
        self.token_count += max(1, len(text or "") // CHARS_PER_TOKEN)

    def token_status(self):
        """{"used", "budget", "pct"} for the frontends' status bars."""
        pct = self.token_count / TOKEN_BUDGET * 100 if TOKEN_BUDGET else 0
        return {"used": self.token_count, "budget": TOKEN_BUDGET,
                "pct": round(pct, 1)}

    def _budget_events(self):
        """Yield a warning event the first time a threshold is crossed."""
        for level in (0.8, 0.95):
            if level not in self._warned \
                    and self.token_count >= TOKEN_BUDGET * level:
                self._warned.add(level)
                yield {"type": "tokens", "text":
                       f"Token budget {level:.0%} used: "
                       f"{self.token_count:,} of {TOKEN_BUDGET:,}"}
        if self.token_count >= TOKEN_BUDGET and "full" not in self._warned:
            self._warned.add("full")
            yield {"type": "tokens", "text":
                   "Token budget reached -- old messages are trimmed "
                   "harder, but consider starting fresh."}

    # ---------- audit + model switching (Phase 11) ----------

    def _audit(self, text):
        """Append one line to history.log -- every skill that was
        refused, declined or run, with a timestamp (best effort)."""
        try:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(paths.PROJECT_ROOT / "history.log", "a",
                      encoding="utf-8") as f:
                f.write(stamp + "  " + text + "\n")
        except OSError:
            pass

    def _switch_model(self, name):
        """Change the session's brain to an installed model."""
        installed = advisor.installed_models()
        if name.lower() not in [n.lower() for n in installed]:
            return ("ERROR: '" + name + "' is not installed. "
                    "Installed models: " + ", ".join(installed) +
                    ". Pull new ones with: ollama pull <name>")
        self.model = name
        return ("OK: this session now uses " + name + ". It answers "
                "from your next message.")

    # ---------- memory ----------

    def start(self):
        """Look for saved sessions.

        Returns {"count": how many exist, "newest": path of the latest
        one, or None}."""
        sessions = sorted(glob.glob(os.path.join(MEMORY_DIR, "chat_*.json")))
        return {"count": len(sessions),
                "newest": sessions[-1] if sessions else None}

    def start_history(self):
        """Basenames of the saved sessions, oldest first (sidebar)."""
        sessions = sorted(glob.glob(os.path.join(MEMORY_DIR, "chat_*.json")))
        return [os.path.basename(s) for s in sessions]

    def load_session(self, path):
        """Continue a saved chat. Returns how many messages were
        remembered, or None if the file could not be read."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                past = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        # Skip the saved system message (we already have a fresh one).
        past = [m for m in past if m.get("role") != "system"]
        # POLISH FIX: keep only real chat -- drop saved tool JSON and
        # helper feedback so old habits never leak into a new session.
        real_chat = []
        for m in past:
            role = m.get("role")
            content = m.get("content", "")
            if role == "assistant" and permissions.check_reply(content)[0] != "none":
                continue  # a saved tool request, not real chat
            if role == "user" and content.startswith(("[Tool result",
                                                      "[Permission refused]",
                                                      "[User declined]")):
                continue  # helper feedback, not real chat
            real_chat.append(m)
        past = real_chat[-MAX_LOADED:]
        self.messages.extend(past)
        return len(past)

    def stop(self):
        """Save the whole conversation. Returns the saved path, or
        None when nothing was chatted."""
        self._save_usage()  # persist the token budget before leaving
        if len(self.messages) <= 1:  # only the system message = nothing to save
            return None
        os.makedirs(MEMORY_DIR, exist_ok=True)
        # Seconds in the name, so two saves in one minute never clash.
        filename = datetime.now().strftime("chat_%Y-%m-%d_%H-%M-%S.json")
        filename = os.path.basename(filename)
        if not re.fullmatch(r"chat_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json",
                            filename):
            raise ValueError("unexpected session filename: " + filename)
        memory_root = Path(MEMORY_DIR).resolve()
        target = (memory_root / filename).resolve()
        if not target.is_relative_to(memory_root):
            raise ValueError("refusing to save outside the memory folder")
        # Copy the list first: a background thread (gui.py) may still be
        # adding messages while we write the snapshot to disk. Image
        # BYTES (vision) are replaced with a note -- they are huge and
        # not JSON-serializable, and the chat works without them.
        snapshot = []
        for m in list(self.messages):
            if isinstance(m, dict) and m.get("images"):
                m = {**m, "images": ["<image was shown earlier>"]}
            snapshot.append(m)
        target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        return str(target)

    # ---------- conversation ----------

    def send(self, user_text):
        """Feed one user message; yields events until ZYRO is done."""
        # Remember what the user just said.
        self.messages.append({"role": "user", "content": user_text})
        self._count_tokens(user_text)
        yield from self._budget_events()

        for round_num in range(MAX_TOOL_ROUNDS + 1):
            # CONTEXT TRIM: qwen3 has a small window. When the chat
            # grows past MAX_CONTEXT_MESSAGES, drop the oldest
            # messages (the system prompt always stays first).
            if len(self.messages) > MAX_CONTEXT_MESSAGES:
                self.messages[:] = ([self.messages[0]]
                                    + self.messages[
                                        -(MAX_CONTEXT_MESSAGES - 1):])
            # VISION: if the newest message carries an image, ask a
            # vision model (when one is installed) for this reply.
            model_to_use = self.model
            if self.messages[-1].get("images"):
                seen_by = advisor.vision_model()
                if seen_by:
                    model_to_use = seen_by
            response = chat(model=model_to_use, messages=self.messages)
            reply = response.message.content

            # Qwen3 drafts its reasoning in a think block before the
            # real answer. Delete it (even if it spans many lines) so
            # we only ever see the answer itself.
            reply = re.sub(r"", "", reply,
                           flags=re.DOTALL).strip()
            if not reply:
                reply = "(no visible answer -- ask again)"

            # Remember what ZYRO said, so the next reply has context.
            self.messages.append({"role": "assistant", "content": reply})
            self._count_tokens(reply)
            yield {"type": "reply", "text": reply}

            # Is this reply a tool request? The permission gate decides.
            kind, request, refusal = permissions.check_reply(reply)

            if kind == "none":
                return  # a normal chat answer -- nothing to run

            if round_num == MAX_TOOL_ROUNDS:
                yield {"type": "notice",
                       "text": "[tool limit reached -- request ignored]"}
                return

            if kind == "bad":
                yield {"type": "refused", "reason": refusal}
                self._audit("REFUSED " + refusal[:100])
                feedback = ("[Permission refused] " + refusal +
                            " Either fix the tool request or just answer "
                            "the user normally.")
            else:  # kind == "ok" -- gate-approved; risky tools need the human
                allowed = True
                if request["tool"] in permissions.RISKY_TOOLS:
                    # A risky action runs ONLY when the human layer
                    # approves (AUTO switch or dialog in the frontend).
                    yield Engine.confirm_event(request)
                    allowed = (self.confirm_handler(request)
                               if self.confirm_handler else False)
                    if not allowed:
                        self._audit("DECLINED " + request["tool"])
                        yield {"type": "declined"}
                if allowed:
                    # Model-level actions live here (they need the
                    # session's current brain); everything else is a
                    # normal gated tool.
                    if request["tool"] == "switch_model":
                        result = self._switch_model(request["name"])
                    elif request["tool"] == "suggest_model":
                        result = advisor.suggest_model(self.model)
                    else:
                        result = tools.run_tool(request)
                    self._audit("RAN " + request["tool"] + " "
                                + str({k: v for k, v in request.items()
                                       if k not in ("tool", "content",
                                                    "code")})[:120])
                    yield {"type": "tool", "name": request["tool"],
                           "request": request}
                    feedback = (f"[Tool result for {request['tool']}]:\n"
                                f"{result}\n\n"
                                "Use this to answer the user's last message "
                                "in normal words.")
                    # VISION: look_screen / look_image hand their image
                    # to the next model call (see the loop head). The
                    # ollama client wants image BYTES -- a path string
                    # would be read as base64 garbage.
                    if request["tool"] in ("look_screen", "look_image"):
                        img = (sysops.LAST_CAPTURE
                               if request["tool"] == "look_screen"
                               else request.get("path"))
                        img_data = None
                        if img and os.path.isfile(img):
                            try:
                                with open(img, "rb") as f:
                                    img_data = f.read()
                            except OSError:
                                pass
                        if img_data:
                            feedback = {"role": "user",
                                        "content": feedback,
                                        "images": [img_data]}
                else:
                    feedback = ("[User declined] The human did not allow "
                                f"that {request['tool']}, so nothing was "
                                "done. Do not try it again; answer the user "
                                "in normal words.")

            # The result (or the refusal) goes to the model as a user
            # message, then the loop lets it speak again. A vision
            # result arrives as a dict that also carries the image.
            if isinstance(feedback, str):
                feedback = {"role": "user", "content": feedback}
            self.messages.append(feedback)
            self._count_tokens(feedback["content"])
            yield from self._budget_events()
            self._save_usage()

    @staticmethod
    def confirm_event(request):
        """Build the "confirm" event a frontend shows next to its ask."""
        tool = request["tool"]
        path = request.get("path", "")
        if tool in ("write_file", "append_file"):
            content = request.get("content", "")
            preview = content[:200] + ("..." if len(content) > 200 else "")
        elif tool == "set_volume":
            preview = f"set master volume to {request['level']}%"
        elif tool == "mute_toggle":
            preview = "toggle the master mute"
        elif tool == "open_site":
            preview = f"open {request.get('url', 'website')} in your browser"
        elif tool == "game_mode":
            preview = f"turn Windows Game Mode {request.get('state', '')}"
        elif tool == "move_window":
            preview = (f'move window "{request.get("window", "")}" '
                       f"to the {request.get('place', '')} of the screen")
        elif tool == "close_window":
            preview = f'close the window "{request.get("window", "")}"'
        elif tool == "run_command":
            preview = request.get("command", "")
            if len(preview) > 120:
                preview = preview[:120] + "..."
        elif tool == "download_file":
            preview = (f"download {request.get('url', '')} into "
                       "D:\\zyro\\downloads")
        elif tool == "download_video":
            preview = (f"download the {request.get('kind', 'video')} from "
                       f"{request.get('url', '')} with yt-dlp")
        elif tool == "winget_search":
            preview = f"search winget for \"{request.get('query', '')}\""
        elif tool == "winget_install":
            preview = (f"INSTALL SOFTWARE: {request.get('app_id', '')} "
                       "via winget")
        elif tool == "screenshot":
            preview = "capture the screen into D:\\zyro\\captures"
        elif tool == "clipboard_read":
            preview = "read the text on the clipboard"
        elif tool == "clipboard_write":
            preview = ("put on the clipboard: "
                       + request.get("content", "")[:120])
        elif tool == "media_key":
            preview = f"press the {request.get('key', '')} media key"
        elif tool == "system_info":
            preview = "read the PC's hardware info"
        elif tool == "list_processes":
            preview = "list the running programs"
        elif tool == "search_files":
            preview = (f"search {request.get('root', 'D:')} for files "
                       f"named like \"{request.get('name', '')}\"")
        elif tool == "set_wallpaper":
            preview = f"set the desktop wallpaper to {request.get('path', '')}"
        elif tool == "open_file":
            preview = f"open the file {request.get('path', '')}"
        else:  # open_app -- and a safe generic for anything newer
            if tool == "open_app":
                preview = f"open {request['app']}"
            else:
                preview = str({k: v for k, v in request.items()
                               if k not in ("tool", "content", "code")
                               })[:150] or tool
        return {"type": "confirm", "tool": tool, "path": path,
                "preview": preview, "request": request}
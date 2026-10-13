"""Sessions: every agent run is saved, and can be resumed later.

The transcript is stored as the exact message list the model saw, so
resuming a session gives the model the same context it had before.
Tool calls are saved in the same shape Ollama returns them, which
keeps replay exact.
"""

import json
import time
from pathlib import Path

from . import config


def _stamp():
    return time.strftime("%Y-%m-%d_%H-%M-%S")


def _serialisable(call):
    """Turn an Ollama ToolCall object into plain JSON."""
    function = getattr(call, "function", None)
    if function is None and isinstance(call, dict):
        function = call.get("function")
        if isinstance(function, dict):
            return {"function": {"name": function.get("name", ""),
                                 "arguments": function.get("arguments", {})}}
    name = getattr(function, "name", "") if function is not None else ""
    arguments = getattr(function, "arguments", {}) if function is not None \
        else {}
    if not isinstance(arguments, dict):
        arguments = dict(arguments or {})
    return {"function": {"name": name, "arguments": arguments}}


def serialise_messages(messages):
    """A JSON-safe copy of the transcript."""
    out = []
    for message in messages:
        clean = {k: v for k, v in message.items() if k != "tool_calls"}
        calls = message.get("tool_calls")
        if calls:
            clean["tool_calls"] = [_serialisable(c) for c in calls]
        out.append(clean)
    return out


class Session:
    """One conversation with the agent, tied to one project folder."""

    def __init__(self, root, mode="ask", model=None, session_id=None,
                 messages=None):
        config.ensure_state_dirs()
        self.id = session_id or _stamp()
        self.root = str(root)
        self.mode = mode
        self.model = model or config.MODEL
        self.created = time.strftime("%Y-%m-%d %H:%M:%S")
        self.messages = list(messages or [])
        self.path = config.SESSION_DIR / f"session_{self.id}.json"

    # ---- persistence ----

    def save(self):
        """Write the transcript (best effort). Returns the path or None."""
        payload = {
            "id": self.id,
            "root": self.root,
            "mode": self.mode,
            "model": self.model,
            "created": self.created,
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": serialise_messages(self.messages),
        }
        try:
            config.ensure_state_dirs()
            self.path.write_text(json.dumps(payload, indent=2),
                                 encoding="utf-8")
        except OSError:
            return None
        return self.path

    @staticmethod
    def load(path):
        """Read a saved session. Returns None when it cannot be used."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or "root" not in data:
            return None
        session = Session(root=data["root"], mode=data.get("mode", "ask"),
                          model=data.get("model"), session_id=data.get("id"),
                          messages=data.get("messages") or [])
        session.created = data.get("created", session.created)
        return session

    @staticmethod
    def recent(limit=10):
        """The newest saved sessions, newest first."""
        config.ensure_state_dirs()
        files = sorted(config.SESSION_DIR.glob("session_*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:limit]


def transcript_preview(session, limit=6):
    """A few readable lines about a session, for the resume list."""
    lines = []
    for message in session.messages:
        role = message.get("role")
        if role == "user":
            text = str(message.get("content", "")).strip().splitlines()
            if text:
                lines.append("you: " + text[0][:70])
        elif role == "assistant" and message.get("tool_calls"):
            for call in message["tool_calls"]:
                name = call.get("function", {}).get("name", "?")
                lines.append("  -> " + name)
    return lines[:limit]

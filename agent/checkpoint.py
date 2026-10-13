"""Undo: snapshot a file before the agent changes it.

Every write and every replace takes a snapshot first, so ":undo" in
the terminal (and the Undo button in the window) can put the previous
content back. Snapshots live outside the workspace, under the agent's
own state folder, so a bad edit inside the project cannot destroy the
history of how to fix it.
"""

import json
import shutil
import time
from pathlib import Path

from . import config


class Checkpoints:
    """An append-only list of file snapshots for one session."""

    def __init__(self, session_id):
        config.ensure_state_dirs()
        self.session_id = session_id
        self.dir = config.CHECKPOINT_DIR / session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.dir / "manifest.jsonl"

    # ---- writing ----

    def snapshot(self, path, reason=""):
        """Save the current state of `path`. Returns the entry id.

        The entry remembers whether the file existed at all, so undo
        can delete a file the agent created.
        """
        path = Path(path)
        existed = path.is_file()
        entry_id = self._next_id()
        stored = ""
        if existed:
            stored = f"{entry_id:04d}_{path.name}"
            try:
                shutil.copy2(path, self.dir / stored)
            except OSError:
                return None
        entry = {
            "id": entry_id,
            "path": str(path),
            "existed": existed,
            "stored": stored,
            "reason": reason,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(self.manifest, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        self._prune()
        return entry_id

    def journal(self, op, source="", target="", note=""):
        """Record a structural change (move, rename, delete, zip ...).

        These cannot be undone by restoring file content, so they are
        written down instead: the owner can always see what happened,
        and deletions go to the Recycle Bin rather than vanishing.
        """
        entry = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "op": op,
            "source": source,
            "target": target,
            "note": note,
        }
        try:
            with open(self.dir / "journal.jsonl", "a",
                      encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except OSError:
            pass
        return entry

    def journal_entries(self, limit=50):
        """The newest journal entries, newest first."""
        try:
            lines = (self.dir / "journal.jsonl").read_text(
                encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return list(reversed(out))

    # ---- reading ----

    def entries(self):
        """Every snapshot, oldest first (never raises)."""
        try:
            lines = self.manifest.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and "path" in entry:
                out.append(entry)
        return out

    # ---- undo ----

    def undo_last(self):
        """Restore the newest snapshot. Returns (path, detail) or None."""
        entries = self.entries()
        if not entries:
            return None
        entry = entries[-1]
        target = Path(entry["path"])
        try:
            if entry.get("existed"):
                source = self.dir / entry.get("stored", "")
                if not source.is_file():
                    return None
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                detail = "restored previous content"
            elif target.is_file():
                target.unlink()
                detail = "removed the file the agent created"
            else:
                detail = "nothing to undo"
        except OSError as exc:
            return None, f"could not undo ({exc})"
        self._drop_last()
        return str(target), detail

    # ---- internals ----

    def _next_id(self):
        entries = self.entries()
        return (entries[-1]["id"] + 1) if entries else 1

    def _drop_last(self):
        entries = self.entries()
        if not entries:
            return
        entries.pop()
        self._rewrite(entries)

    def _prune(self):
        entries = self.entries()
        if len(entries) <= config.MAX_CHECKPOINTS:
            return
        keep = entries[-config.MAX_CHECKPOINTS:]
        for old in entries[:len(entries) - len(keep)]:
            stored = old.get("stored")
            if stored:
                try:
                    (self.dir / stored).unlink(missing_ok=True)
                except OSError:
                    pass
        self._rewrite(keep)

    def _rewrite(self, entries):
        try:
            text = "".join(json.dumps(e) + "\n" for e in entries)
            self.manifest.write_text(text, encoding="utf-8")
        except OSError:
            pass

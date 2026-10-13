"""Which folders the agent may touch, and how a path is made safe.

Two separate ideas live here:

* the TRUST LIST -- folders the owner has explicitly allowed. It is
  stored as JSON outside the workspace, so pointing the agent at a new
  project can never widen its own permissions by itself.
* a Workspace -- one trusted folder, with resolve() as the single door
  every file tool goes through. Like the chat engine's permission
  gate, the rule is "resolve first, compare after": symlinks, `..`,
  other drives and sibling folders with a shared prefix are all
  refused before any file is opened.
"""

import fnmatch
import json
import os
from pathlib import Path

from . import config


class WorkspaceError(Exception):
    """A path is outside the workspace, missing, or not usable."""


# ---------------------------------------------------------------- trust

def load_trusted():
    """The trusted folders, as absolute path strings (never raises)."""
    try:
        data = json.loads(config.TRUST_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    roots = data.get("roots") if isinstance(data, dict) else None
    if not isinstance(roots, list):
        return []
    return [r for r in roots if isinstance(r, str) and r.strip()]


def _save_trusted(roots):
    config.ensure_state_dirs()
    payload = {"roots": sorted({str(r) for r in roots})}
    config.TRUST_FILE.write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


def trust(path):
    """Allow a folder (and everything under it). Returns the real path."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise WorkspaceError(f"not a folder: {path}")
    roots = load_trusted()
    if str(root) not in roots:
        roots.append(str(root))
        _save_trusted(roots)
    return root


def untrust(path):
    """Forget a trusted folder. Returns True when it was in the list."""
    root = str(Path(path).expanduser().resolve())
    roots = load_trusted()
    if root not in roots:
        return False
    roots.remove(root)
    _save_trusted(roots)
    return True


def trusted_roots():
    """Trusted folders that still exist, as resolved Paths."""
    out = []
    for text in load_trusted():
        try:
            path = Path(text).resolve()
        except (OSError, ValueError):
            continue
        if path.is_dir():
            out.append(path)
    return out


def containing_root(path):
    """The trusted folder that contains `path`, or None."""
    try:
        target = Path(path).expanduser().resolve()
    except (OSError, ValueError):
        return None
    for root in trusted_roots():
        if target == root or _inside(root, target):
            return root
    return None


def _inside(base, candidate):
    """True when `candidate` is `base` or strictly below it."""
    base_text = os.path.normcase(str(base)).rstrip("\\/")
    cand_text = os.path.normcase(str(candidate))
    return cand_text == base_text or cand_text.startswith(base_text + os.sep)


# ------------------------------------------------------------ workspace

class Workspace:
    """One trusted project folder. Every path goes through resolve()."""

    def __init__(self, root):
        try:
            resolved = Path(root).expanduser().resolve()
        except (OSError, ValueError) as exc:
            raise WorkspaceError(f"cannot use that folder ({exc})") from exc
        if not resolved.is_dir():
            raise WorkspaceError(f"not a folder: {root}")
        self.root = resolved
        self._ignores = self._load_ignores()

    # ---- paths ----

    def resolve(self, text, *, must_exist=False, for_write=False,
                expect="any"):
        """Turn a model-supplied path into a real path inside the root.

        expect: "any", "file" or "dir" -- what the caller needs it to be.
        Raises WorkspaceError for anything outside the folder, for a
        missing path when must_exist is set, and for a missing parent
        on a plain file write.
        """
        if not isinstance(text, str) or not text.strip():
            raise WorkspaceError("an empty path was given")
        cleaned = text.strip().strip('"').strip("'")
        candidate = Path(cleaned)
        if not candidate.is_absolute():
            candidate = self.root / cleaned
        try:
            # resolve() follows symlinks and junctions, so an escape
            # through a link is caught by the comparison below.
            full = candidate.resolve()
        except (OSError, ValueError) as exc:
            raise WorkspaceError(f"that path is not valid ({exc})") from exc
        if not _inside(self.root, full):
            raise WorkspaceError(
                f"'{cleaned}' is outside the workspace folder "
                f"({self.root}). Only files inside it can be used.")
        if self.is_secret(full):
            raise WorkspaceError(
                f"'{full.name}' looks like a secrets file, so it is "
                "never read or written by the agent.")
        if must_exist:
            if not full.exists():
                raise WorkspaceError(f"no such file or folder: "
                                     f"{self.rel(full)}")
            if expect == "file" and full.is_dir():
                raise WorkspaceError(
                    f"'{self.rel(full)}' is a folder, not a file")
            if expect == "dir" and not full.is_dir():
                raise WorkspaceError(
                    f"'{self.rel(full)}' is not a folder")
        elif for_write and expect != "dir":
            parent = full.parent
            if not parent.is_dir():
                raise WorkspaceError(
                    "the folder for that file does not exist: "
                    f"{self.rel(parent)}")
        return full

    def rel(self, path):
        """A short display path (relative to the root when possible)."""
        try:
            return str(Path(path).relative_to(self.root))
        except ValueError:
            return str(path)

    def is_secret(self, path):
        """Files that are never read or written, whatever the mode."""
        return Path(path).name.lower() in config.SECRET_NAMES

    def is_ignored(self, path):
        """True for build junk, VCS folders and .zyroignore matches."""
        rel = self.rel(path).replace("\\", "/")
        parts = rel.split("/")
        if any(part in config.DEFAULT_IGNORES for part in parts[:-1]):
            return True
        if parts and parts[-1] in config.DEFAULT_IGNORES:
            return True
        return _matches(rel, self._ignores)

    # ---- walking ----

    def iter_files(self, start=None, limit=5000):
        """Text-ish files under the root, ignoring junk. Yields Paths."""
        if start is None:
            base = self.root
        elif isinstance(start, Path):
            base = start          # already resolved by the caller
            if not _inside(self.root, base):
                raise WorkspaceError("that folder is outside the workspace")
        else:
            base = self.resolve(start)
        if base.is_file():
            yield base
            return
        count = 0
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d.lower() not in
                           {i.lower() for i in config.DEFAULT_IGNORES}]
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if self.is_ignored(path) or self.is_secret(path):
                    continue
                yield path
                count += 1
                if count >= limit:
                    return

    def overview(self, max_entries=70, max_depth=2):
        """A compact map of the project, shown to the model once.

        Small models waste whole steps discovering where things are, so
        the first two levels of the tree are handed to them up front.
        """
        lines = []

        def walk(folder, depth, prefix):
            if depth > max_depth or len(lines) >= max_entries:
                return
            try:
                entries = sorted(folder.iterdir(),
                                 key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return
            for entry in entries:
                if len(lines) >= max_entries:
                    return
                if self.is_ignored(entry) or self.is_secret(entry):
                    continue
                if entry.is_dir():
                    lines.append(f"{prefix}{entry.name}/")
                    walk(entry, depth + 1, prefix + "  ")
                else:
                    lines.append(f"{prefix}{entry.name}")

        walk(self.root, 1, "")
        if not lines:
            return "(the project folder is empty)"
        if len(lines) >= max_entries:
            lines.append("...[more files not shown -- use find_files]")
        return "\n".join(lines)

    def _load_ignores(self):
        """Patterns from .zyroignore (and .gitignore as a fallback)."""
        patterns = []
        for name in (".zyroignore", ".gitignore"):
            path = self.root / name
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("!"):
                    continue
                patterns.append(line)
            if patterns:
                break  # .zyroignore wins when it exists
        return patterns


def _matches(rel, patterns):
    """gitignore-lite: whole path, basename, or any directory part."""
    if not patterns:
        return False
    rel = rel.replace("\\", "/")
    name = rel.rsplit("/", 1)[-1]
    for raw in patterns:
        pattern = raw.strip().lstrip("/").rstrip("/")
        if not pattern:
            continue
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
            return True
        if "/" not in pattern and pattern in rel.split("/"):
            return True
    return False


def is_binary(path):
    """A file is treated as binary when NUL bytes appear early on."""
    try:
        with open(path, "rb") as handle:
            chunk = handle.read(config.BINARY_SNIFF_BYTES)
    except OSError:
        return True
    return b"\x00" in chunk

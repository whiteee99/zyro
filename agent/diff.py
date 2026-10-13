"""Unified diffs, so every file change can be reviewed before it lands.

The agent never writes a file silently: the loop builds the new text,
this module turns old-vs-new into a unified diff, and the frontend
shows it (and, in ask mode, waits for a yes).
"""

import difflib
import os

# ANSI colours for the terminal frontend; harmless when piped.
GREEN = "\x1b[32m"
RED = "\x1b[31m"
CYAN = "\x1b[36m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


def _lines(text):
    """Split into newline-terminated lines so diffs stay tidy."""
    return [line + "\n" for line in text.splitlines()]


def unified(old, new, name="file", context=3):
    """A unified diff of two texts ('' when they are identical)."""
    if old == new:
        return ""
    diff = difflib.unified_diff(
        _lines(old), _lines(new),
        fromfile=name, tofile=name, n=context, lineterm="\n")
    return "".join(diff)


def counts(old, new):
    """(lines added, lines removed) -- for one-line summaries."""
    added = removed = 0
    for line in unified(old, new).splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def summary(old, new, name="file"):
    """A short human line: 'notes.txt: +3 -1'."""
    added, removed = counts(old, new)
    if not added and not removed:
        return f"{name}: no change"
    return f"{name}: +{added} -{removed}"


def render(diff_text, color=None):
    """Colour a unified diff for a terminal (auto-detects a TTY)."""
    if color is None:
        color = _stdout_is_tty()
    if not color or not diff_text:
        return diff_text
    out = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            out.append(CYAN + line + RESET)
        elif line.startswith("@@"):
            out.append(CYAN + line + RESET)
        elif line.startswith("+"):
            out.append(GREEN + line + RESET)
        elif line.startswith("-"):
            out.append(RED + line + RESET)
        else:
            out.append(DIM + line + RESET)
    return "\n".join(out)


def _stdout_is_tty():
    try:
        return os.isatty(1)
    except (OSError, ValueError):
        return False


def preview(old, new, name="file", limit=200):
    """Diff trimmed to `limit` lines, with a note when it was cut."""
    text = unified(old, new, name)
    lines = text.splitlines()
    if len(lines) > limit:
        lines = lines[:limit] + [f"...[{len(lines) - limit} more diff "
                                 "lines]"]
    return "\n".join(lines)

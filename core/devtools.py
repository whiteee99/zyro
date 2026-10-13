"""ZYRO's developer tools (Phase 11): grep, edit, run Python.

search_in_files -- find TEXT inside files (read-only, capped)
edit_file       -- surgical find-and-replace inside the install folder
run_python      -- run a short Python snippet and return its output,
                   so ZYRO can test ideas and self-correct

Every function returns a plain string and catches its own errors.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from core import paths

MAX_FILE_BYTES = 200_000        # edit_file only touches text files
MAX_SEARCH_RESULTS = 30
MAX_SEARCH_SECONDS = 15
MAX_SNIPPET_CHARS = 8000        # run_python output cap
MAX_RUN_SECONDS = 30
SKIP_DIRS = {"$recycle.bin", "system volume information",
             "node_modules", "__pycache__", "venv", ".git"}


def search_in_files(pattern, root=None):
    """Find files whose TEXT contains the pattern (case-insensitive).
    Searches the install drive only, capped in time and results."""
    if not isinstance(pattern, str) or not pattern.strip():
        return "ERROR: search_in_files needs a 'pattern' to look for."
    pattern = pattern.strip()[:100]
    needle = pattern.lower()
    drive = paths.DRIVE_ROOT.strip("\\").lower()
    base = paths.PROJECT_ROOT
    if isinstance(root, str) and root.strip():
        root = root.strip()
        try:
            cand = Path(root).resolve()
        except (OSError, ValueError):
            return "ERROR: that search root is not valid."
        if not str(cand).lower().startswith(drive):
            return ("ERROR: search_in_files only searches the "
                    + drive.upper() + " drive.")
        base = cand
    hits = []
    start = time.time()
    try:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d.lower() not in SKIP_DIRS]
            for fname in filenames:
                if time.time() - start > MAX_SEARCH_SECONDS:
                    break
                full = os.path.join(dirpath, fname)
                try:
                    if os.path.getsize(full) > 1_000_000:
                        continue  # skip big/binary files
                    with open(full, "r", encoding="utf-8",
                              errors="ignore") as f:
                        for lineno, line in enumerate(f, 1):
                            if needle in line.lower():
                                text = line.strip()[:120]
                                hits.append(f"{full}:{lineno}: {text}")
                                break  # one hit per file is enough
                except OSError:
                    continue
                if len(hits) >= MAX_SEARCH_RESULTS:
                    break
            if len(hits) >= MAX_SEARCH_RESULTS:
                break
    except OSError as e:
        return f"ERROR: the search failed ({e})."
    if not hits:
        return f'(no files contain "{pattern}")'
    extra = (f"\n...[stopped at {MAX_SEARCH_RESULTS} files]"
             if len(hits) >= MAX_SEARCH_RESULTS else "")
    return f"Found {len(hits)} file(s):\n" + "\n".join(hits) + extra


def _inside_install(path_text):
    """Resolve a path and allow it ONLY inside the install folder."""
    if not isinstance(path_text, str) or not path_text.strip():
        return None
    try:
        full = (paths.PROJECT_ROOT / path_text.strip()).resolve()
    except (OSError, ValueError):
        return None
    base = str(paths.PROJECT_ROOT.resolve()).lower()
    text = str(full).lower()
    if text == base or text.startswith(base + "\\"):
        return full
    return None


def edit_file(path_text, find, replace):
    """Replace every occurrence of 'find' with 'replace' in one text
    file inside the install folder. Text files up to 200 KB only."""
    full = _inside_install(path_text)
    if full is None or not full.is_file():
        return ("ERROR: edit_file needs a real file inside the ZYRO "
                "install folder.")
    if not isinstance(find, str) or find == "":
        return "ERROR: edit_file needs a non-empty 'find' text."
    if not isinstance(replace, str):
        return "ERROR: edit_file needs 'replace' as text."
    try:
        if full.stat().st_size > MAX_FILE_BYTES:
            return ("ERROR: that file is too big to edit safely "
                    "(limit 200 KB).")
        original = full.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as e:
        return f"ERROR: could not read that file as text ({e})."
    count = original.count(find)
    if count == 0:
        return ("ERROR: the 'find' text does not appear in that "
                "file -- nothing was changed.")
    try:
        full.write_text(original.replace(find, replace),
                        encoding="utf-8")
    except OSError as e:
        return f"ERROR: could not save the edit ({e})."
    return (f"OK: replaced {count} occurrence(s) in "
            f"{full.name}.")


def _find_python():
    """The venv Python if this is a source install, else 'python'
    from PATH (portable installs have no venv)."""
    venv = paths.PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return str(venv)
    return "python" if sys.executable else None


def run_python(code):
    """Run a short Python snippet with the venv interpreter and
    return stdout/stderr (capped). Marked RISKY by the gate."""
    if not isinstance(code, str) or not code.strip():
        return "ERROR: run_python needs a 'code' string."
    if len(code) > MAX_SNIPPET_CHARS:
        return (f"ERROR: the snippet is {len(code)} characters; the "
                f"limit is {MAX_SNIPPET_CHARS}.")
    python = _find_python()
    try:
        result = subprocess.run(
            [python, "-c", code], capture_output=True, text=True,
            errors="replace", timeout=MAX_RUN_SECONDS,
            cwd=str(paths.PROJECT_ROOT))
    except FileNotFoundError:
        return ("ERROR: no Python found. Install Python or keep the "
                "venv folder next to ZYRO.")
    except subprocess.TimeoutExpired:
        return (f"ERROR: the snippet ran past {MAX_RUN_SECONDS} "
                "seconds and was stopped.")
    except Exception as e:
        return f"ERROR: could not run Python ({e})."
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    text = out + (("\n[stderr]\n" + err) if err and out else err)
    if not text:
        text = ("(no output -- finished with exit code "
                + str(result.returncode) + ")")
    if len(text) > 2000:
        text = text[:2000] + " ...[output continues]"
    return text

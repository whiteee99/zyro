"""ZYRO's skills (Phase 10): tiny how-to files the model loads on demand.

A skill is a small .md file in D:\\zyro\\skills. Only the NAMES are
shown in the system prompt (a few tokens each); the model pulls the
full text with the read_skill tool only when needed. This is what
keeps skills affordable for the small qwen3 model.
"""

import re
from core import paths

# One skill may never be longer than this (protects the context).
MAX_SKILL_CHARS = 1500

_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}")


def _skill_files():
    """The available skill files, sorted by name (missing folder = [])."""
    try:
        return sorted(paths.SKILLS_DIR.glob("*.md"))
    except OSError:
        return []


def _describe(path):
    """One-line description of a skill: its first non-empty line."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                text = line.strip().lstrip("#").strip()
                if text:
                    return text[:90]
    except OSError:
        pass
    return "no description"


def list_skills():
    """[(name, description)] for every skill file."""
    return [(p.stem, _describe(p)) for p in _skill_files()]


def prompt_section():
    """The compact skills block appended to the system prompt."""
    skills = list_skills()
    if not skills:
        return ""
    lines = ["\n\nSKILLS -- optional know-how you can load first:"]
    for name, desc in skills:
        lines.append(f"- {name}: {desc}")
    lines.append('Load one with {"tool": "read_skill", '
                 '"name": "file-organizer"} and follow its steps.')
    return "\n".join(lines)


def read_skill(name):
    """Return one skill's text (the permission gate validated the
    name's shape; a wrong name just lists what exists)."""
    if not isinstance(name, str):
        return "ERROR: read_skill needs a skill 'name'."
    name = name.strip().lower()
    if not _NAME_RE.fullmatch(name):
        return "ERROR: skill names are lowercase words with - or _."
    # Containment: the resolved path must sit directly in the skills
    # folder -- no separators in the name survive the regex, but the
    # check stays as the safety net.
    try:
        target = (paths.SKILLS_DIR / (name + ".md")).resolve()
        base = paths.SKILLS_DIR.resolve()
    except (OSError, ValueError):
        return "ERROR: that skill path is not valid."
    if target.parent != base or not target.is_file():
        available = ", ".join(n for n, _ in list_skills()) or "(none)"
        return f"(no skill named '{name}'. Available: {available})"
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"ERROR: could not read that skill ({e})."
    if len(text) > MAX_SKILL_CHARS:
        text = text[:MAX_SKILL_CHARS] + " ...[skill continues]"
    return text.strip() or "(that skill is empty)"

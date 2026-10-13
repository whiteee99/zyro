"""ZYRO's model advisor (Phase 11): match the AI model to the PC.

suggest_model() reads the machine's specs and recommends the best
qwen3 brain from those actually available in Ollama, plus a small
vision model for look_screen. switch_model is handled by the engine
(validated against installed models).
"""

import subprocess

# name -> (download size GB, comfortable RAM GB)
QWEN_MENU = [
    ("qwen3:0.6b", 0.5, 4),
    ("qwen3:1.7b", 1.4, 6),
    ("qwen3:4b", 2.5, 8),
    ("qwen3:8b", 5.0, 16),
    ("qwen3:14b", 9.0, 32),
]

VISION_MENU = [
    ("moondream", 1.7, 6),
    ("minicpm-v", 5.5, 16),
]

KNOWN_VISION = ("moondream", "minicpm", "llava", "qwen2.5vl",
                "qwen2-vl", "bakllava", "llama3.2-vision")


def installed_models():
    """Model names available in Ollama (empty list on any error)."""
    try:
        result = subprocess.run(["ollama", "list"],
                                capture_output=True, text=True,
                                errors="replace", timeout=30)
        names = []
        for line in (result.stdout or "").splitlines()[1:]:
            parts = line.split()
            if parts:
                names.append(parts[0].lower())
        return names
    except Exception:
        return []


def _installed():
    return installed_models()


def _ram_gb():
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return 8


def suggest_model(current):
    """Human-readable recommendation for this machine."""
    ram = _ram_gb()
    installed = _installed()
    if not installed:
        return ("ERROR: could not read the Ollama model list. Is "
                "Ollama installed and running?")
    best = None
    for name, size, comfy in QWEN_MENU:
        if any(n == name or n.startswith(name + "-")
               for n in installed) and ram >= comfy:
            best = name
    vision = None
    for name, size, comfy in VISION_MENU:
        if any(n.startswith(name) for n in installed):
            vision = name
            break
    lines = [f"This PC: {ram:.0f} GB RAM.",
             f"Installed models: {', '.join(sorted(installed))}."]
    if best is None:
        lines.append("No bigger qwen3 model is installed that fits "
                     "this RAM -- the current one is the right choice.")
    elif current and best.lower() == current.lower():
        lines.append(f"You are already on the best fit: {best}.")
    else:
        lines.append(f"Best fit for this PC: {best}  ->  switch with "
                     '{"tool": "switch_model", "name": "' + best + '"}'
                     " (or ask me to switch).")
    if vision:
        lines.append(f"Vision model available: {vision} "
                     "(used automatically by look_screen).")
    else:
        lines.append("No vision model installed -- ask me to install "
                     "moondream (about 1.7 GB) for screen understanding.")
    return "\n".join(lines)


def vision_model():
    """The first installed vision model, or None."""
    for name in _installed():
        if any(key in name for key in KNOWN_VISION):
            return name
    return None

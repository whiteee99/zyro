"""Settings for ZYRO's coding agent (the "ZCode-like" mode).

Everything here is a knob the owner can turn with an environment
variable, so the agent can be tuned on a slow laptop without touching
code. The defaults are chosen for this specific machine: a 4 GB
GTX 1650, 7.8 GB RAM and a free local qwen3:4b.
"""

import os
from pathlib import Path

from core import paths

# ---------- the brain ----------

# qwen3:4b (2.5 GB) is the biggest model that fits the 4 GB card AND
# still answers at a usable speed. qwen3:1.7b is ~2x faster but much
# weaker at multi-step work; switch with ZYRO_AGENT_MODEL.
MODEL = os.environ.get("ZYRO_AGENT_MODEL", "qwen3:4b")

# Ollama's default context is 4096, which is far too small for code.
# 8192 still fits in 4 GB of VRAM next to a 2.5 GB model.
NUM_CTX = int(os.environ.get("ZYRO_AGENT_CTX", "8192"))

# How many tokens one model step may write. This is a SAFETY CAP, not a
# budget: measured on this laptop, the model often spends 200-2000
# tokens working out what to do BEFORE it emits a tool call. A tight cap
# (512) cut the generation off mid-thought and no tool was ever called.
NUM_PREDICT = int(os.environ.get("ZYRO_AGENT_PREDICT", "1536"))

# qwen3 "thinks" before answering. Thinking roughly triples the wall
# time of every step. Off is fine now that the token cap is right.
THINK = os.environ.get("ZYRO_AGENT_THINK", "0") not in ("0", "", "false",
                                                        "False")

# With thinking off, a small model sometimes writes its reasoning into
# the answer instead of calling a tool. Two safety nets:
#   * anything longer than this is not kept in the chat history, so the
#     rambling cannot poison the next step;
#   * a reply that "plans out loud" instead of acting gets nudged.
STORE_CONTENT_LIMIT = 400
MAX_NUDGES = 2
NUDGE_AFTER_STEP = 3

# How many model<->tool rounds one user request may take.
MAX_STEPS = int(os.environ.get("ZYRO_AGENT_STEPS", "24"))

# When everything sent to the model -- tool schemas, system prompt and
# transcript -- passes this many estimated tokens, the oldest half of
# the transcript is summarised. This counts ALL of it: 30 tool schemas
# are ~2,500 tokens on their own, and forgetting them let the real
# context grow past the window, where Ollama silently drops messages.
COMPACT_AT_TOKENS = int(os.environ.get("ZYRO_AGENT_COMPACT", "6000"))

# Rough token estimate, same rule the chat engine uses.
CHARS_PER_TOKEN = 4

# ---------- limits on tools ----------

MAX_READ_LINES = 400          # read_file returns at most this many lines
MAX_READ_BYTES = 200_000      # refuse to read files bigger than this
MAX_LIST_ITEMS = 200          # list_files / find_files
MAX_SEARCH_HITS = 40          # search_text
MAX_WRITE_CHARS = 200_000     # write_file may replace at most this much
MAX_OUTPUT_CHARS = 4000       # command output handed back to the model
COMMAND_TIMEOUT = 120         # seconds before a command is killed
COMMAND_TIMEOUT_MAX = 900     # the model may ask for up to this
BINARY_SNIFF_BYTES = 8192     # NUL byte in this window = binary file

# How many file snapshots one session may keep for undo.
MAX_CHECKPOINTS = 200

# ---------- where the agent keeps its own data ----------

STATE_DIR = Path(paths.MEMORY_DIR) / "agent"
TRUST_FILE = STATE_DIR / "trusted.json"
SESSION_DIR = STATE_DIR / "sessions"
CHECKPOINT_DIR = STATE_DIR / "checkpoints"

# Folders that are never walked, searched or written by the agent.
DEFAULT_IGNORES = (
    ".git", ".hg", ".svn", "node_modules", "__pycache__", "venv", ".venv",
    "env", "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".idea", ".vscode", "site-packages", ".tox", ".next", ".cache",
)

# File names that are never read into the model (noise or secrets).
SECRET_NAMES = (".env", ".env.local", "id_rsa", "id_ed25519",
                "credentials.json", "secrets.json", ".netrc")


def ensure_state_dirs():
    """Create the agent's own folders (called before the first write)."""
    for folder in (STATE_DIR, SESSION_DIR, CHECKPOINT_DIR):
        folder.mkdir(parents=True, exist_ok=True)

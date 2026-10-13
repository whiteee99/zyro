"""ZYRO command line chat (Phase 6: a thin wrapper around the Engine).

All conversation logic now lives in core/engine.py and speaks in
"events". This file only turns those events into terminal prints.
The CLI always asks y/N for risky tools (it has no AUTO switch).
"""

import atexit
import os

from core import ollama_lifecycle
from core.engine import Engine, MODEL

# OLLAMA LIFECYCLE ----------------------------------------------------------
# Ollama is two processes (the "ollama.exe" daemon and the "ollama app.exe"
# tray icon). ZYRO starts the daemon when it needs a brain and stops both
# again when it exits, so a 7.8 GB laptop is never left carrying them after
# the window is closed. Set this to False to leave Ollama running for other
# programs once ZYRO is gone.
KILL_OLLAMA_ON_EXIT = True


def ask_permission(request):
    """Show a risky tool on the terminal and read the y/N answer."""
    tool = request["tool"]
    detail = (request.get("path") or request.get("app")
              or request.get("url") or request.get("window")
              or request.get("command"))
    if tool == "set_volume":
        detail = str(request.get("level")) + "%"
    if detail:
        print(f"  [tool: {tool} -> {detail}]")
    else:
        print(f"  [tool: {tool}]")
    if request.get("critical"):
        print("  [CRITICAL -- read carefully before answering]")
    if tool in ("write_file", "append_file"):
        content = request.get("content", "")
        preview = content[:200] + ("..." if len(content) > 200 else "")
        print(f"  content: {preview}")
    try:
        return input("  Allow? (y/N): ") == "y"
    except (EOFError, KeyboardInterrupt):
        return False  # no answer = no action


def save_and_bye(engine, extra_newline=False):
    """Save the session and say goodbye, exactly like the earlier phases."""
    path = engine.stop()
    if path:
        print("Session saved to", path)
    print("\nZYRO: Bye!" if extra_newline else "ZYRO: Bye!")


def main():
    # ZYRO is useless without a brain, so bring Ollama up BEFORE the first
    # request. If that fails we say so plainly instead of crashing later
    # with a connection error.
    if not ollama_lifecycle.start_ollama():
        print("Ollama not found - install it or check PATH.")
        print("  1. Download: https://ollama.com/download")
        print("  2. Then run: ollama pull " + MODEL)
        print("ZYRO cannot chat without Ollama, so it is stopping here.")
        return 1

    # Anything that ends this process -- normal exit, Ctrl+C, a crash --
    # takes Ollama with it (when the flag above allows).
    atexit.register(ollama_lifecycle.shutdown, KILL_OLLAMA_ON_EXIT)

    engine = Engine(confirm_handler=ask_permission)

    print("ZYRO is ready (model:", MODEL + "). Type 'exit' to quit.")

    # --- Phase 2: offer to continue the last saved chat ---
    found = engine.start()
    if found["newest"]:
        print(f"Found {found['count']} saved session(s). "
              f"Newest: {os.path.basename(found['newest'])}")
        if input("Continue last session? (y/N): ").strip().lower() == "y":
            remembered = engine.load_session(found["newest"])
            if remembered is None:
                print("Could not read that file -- starting fresh instead.")
            else:
                print(f"ZYRO remembered the last {remembered} messages.")

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            save_and_bye(engine, extra_newline=True)
            break

        if user_input.lower() == "exit":
            save_and_bye(engine)
            break
        if not user_input:
            continue  # ignore empty lines

        # The engine does the thinking and hands us events; we just print.
        for event in engine.send(user_input):
            kind = event["type"]
            if kind == "reply":
                print("ZYRO:", event["text"])
            elif kind == "tool":
                print("  [result sent back to ZYRO]")
            elif kind == "declined":
                print("  [declined -- ZYRO is told the user said no]")
            elif kind == "refused":
                print("  [permission refused]")
            elif kind == "notice":
                print("  " + event["text"])
            elif kind == "tokens":
                print("  [token budget] " + event["text"])


if __name__ == "__main__":
    raise SystemExit(main())
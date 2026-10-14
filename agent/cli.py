"""Terminal frontend for ZYRO's coding agent.

    venv\\Scripts\\python -m agent.cli --root D:\\myproject
    venv\\Scripts\\python -m agent.cli -r D:\\myproject -m auto-edit "run the tests"
    venv\\Scripts\\python -m agent.cli --list
    venv\\Scripts\\python -m agent.cli --resume last

Inside the prompt:

    :mode plan|ask|auto-edit|full-auto   switch how much it may do alone
    :root PATH                           work on another (trusted) folder
    :undo                                undo the last file change
    :files                               show the project map
    :sessions                            list saved sessions
    :help  :quit

Only ASCII is printed, because a Windows console is not always UTF-8.
"""

import argparse
import atexit
import os
import sys
from pathlib import Path

from core import ollama_lifecycle
from . import config, diff as diffmod, llm
from .loop import MODE_HELP, MODES, Agent
from .session import Session, transcript_preview
from .workspace import (Workspace, WorkspaceError, containing_root, trust,
                        trusted_roots, untrust)

try:                       # the app-wide switch lives with the CLI entry point
    from main import KILL_OLLAMA_ON_EXIT
except Exception:          # noqa: BLE001 - never block the agent on this
    KILL_OLLAMA_ON_EXIT = True

PROMPT = "you> "


def prepare_ollama():
    """Bring Ollama up for this run. Returns (ready, started_by_us).

    The ownership rule matters: if a ZYRO window (or the user) already
    has Ollama running, the coding agent must NOT kill it on exit -- it
    would take the other ZYRO's brain away with it. Only an Ollama this
    process started is this process's to stop.
    """
    if ollama_lifecycle.is_ollama_running():
        return True, False
    return ollama_lifecycle.start_ollama(), True


class Terminal:
    """Prints agent events and answers the approval questions."""

    def __init__(self, stream_progress=True, show_thinking=False):
        self.stream_progress = stream_progress
        self.show_thinking = show_thinking
        self.spin = 0
        self._status_open = False

    # ---- progress line (overwritten in place) ----

    def status(self, text):
        if not self.stream_progress:
            return
        marks = "|/-\\"
        self.spin = (self.spin + 1) % len(marks)
        sys.stdout.write(f"\r  {marks[self.spin]} {text[:70]:<70}")
        sys.stdout.flush()
        self._status_open = True

    def status_clear(self):
        if self._status_open:
            sys.stdout.write("\r" + " " * 74 + "\r")
            sys.stdout.flush()
            self._status_open = False

    # ---- normal output ----

    def line(self, text=""):
        self.status_clear()
        print(text)

    def dim(self, text):
        self.line("\x1b[2m" + text + "\x1b[0m" if diffmod._stdout_is_tty()
                  else text)

    # ---- events ----

    def handle(self, event, confirm):
        kind = event["type"]
        if kind == "step":
            self.status(f"step {event['n']} - thinking")
        elif kind == "thinking":
            if self.show_thinking:
                self.status("thinking: " + event["text"].replace("\n", " "))
        elif kind == "text":
            self.status("writing: " + event["text"].replace("\n", " "))
        elif kind == "step_end":
            self.status_clear()
            stats = event.get("stats") or ""
            if event.get("tools"):
                print(f"  [step: {event['tools']} tool call(s)"
                      + (f", {stats}]" if stats else "]"))
            elif stats:
                print(f"  [{stats}]")
        elif kind == "tool":
            if event.get("result") is None:
                print("  -> " + event.get("preview", event["name"]))
        elif kind == "tool_result":
            self._show_result(event["name"], event["result"])
        elif kind == "diff":
            self._show_diff(event)
        elif kind == "applied":
            print("  [saved" + ("" if event.get("ok") else " with errors")
                  + "]")
        elif kind == "command":
            risk = event.get("risk")
            print("  $ " + event["command"]
                  + (f"   [careful: {risk}]" if risk else ""))
        elif kind == "notice":
            self.dim("  [" + str(event["text"]) + "]")
        elif kind == "error":
            print("\n  !! " + str(event["text"]))
        elif kind == "final":
            text = (event.get("text") or "").strip()
            if text:
                self.line()
                self.line("ZYRO: " + text)
        return None

    def _show_diff(self, event):
        head = f"  {event['summary']}"
        self.line(head)
        body = diffmod.render(event["text"])
        for line in body.splitlines()[:200]:
            print("    " + line)
        if len(body.splitlines()) > 200:
            print("    ...[diff truncated]")

    def _show_result(self, name, result):
        if name in ("read_file", "list_files", "search_text", "find_files"):
            text = str(result)
            lines = text.splitlines()
            for line in lines[:12]:
                print("     " + line)
            if len(lines) > 12:
                print(f"     ...[{len(lines) - 12} more lines]")
        else:
            first = str(result).strip().splitlines()
            if first:
                print("     " + first[0][:100])

    # ---- approvals ----

    def approve(self, request):
        """Ask the human. Returns True only for a clear yes."""
        self.status_clear()
        kind = request.get("kind")
        self.line()
        if request.get("critical"):
            self.line("  !! CRITICAL: this one is hard to undo")
        if kind == "write":
            if request.get("created"):
                self.line(f"  NEW FILE: {request['path']}")
            for line in diffmod.render(request.get("diff", "")).splitlines():
                print("    " + line)
            question = f"  apply this change to {request['path']}? [y/N] "
        elif kind == "exec":
            self.line("  COMMAND: " + str(request.get("command", "")))
            if request.get("risk"):
                self.line("  careful: this " + request["risk"])
            question = "  run it? [y/N] "
        else:
            self.line("  ACTION: " + str(request.get("summary",
                                                      request.get("tool"))))
            question = "  do it? [y/N] "
        try:
            answer = input(question).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        return answer in ("y", "yes")


# --------------------------------------------------------------- session

def pick_root(args):
    """Decide which project folder to work on, and check it is trusted."""
    if args.root:
        candidate = Path(args.root).expanduser()
    else:
        candidate = Path.cwd()
    try:
        root = candidate.resolve()
    except (OSError, ValueError) as exc:
        print(f"cannot use that folder: {exc}")
        return None
    if not root.is_dir():
        print(f"not a folder: {root}")
        return None
    if containing_root(root):
        return root
    print(f"\nThis folder is not trusted yet:\n  {root}\n")
    print("The agent can read and change files inside a trusted folder.")
    if args.trust:
        trust(root)
        print("trusted (because you passed --trust).\n")
        return root
    try:
        answer = input("Trust this folder? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if answer not in ("y", "yes"):
        print("Nothing was trusted, so nothing can be done here.")
        return None
    trust(root)
    print("trusted.\n")
    return root


def make_agent(args, root, session=None):
    """Build the agent, wiring the terminal as the approval handler."""
    terminal = Terminal(stream_progress=not args.quiet,
                        show_thinking=args.thinking)
    if session is None:
        session = Session(root=root, mode=args.mode,
                          model=args.model or config.MODEL)
    agent = Agent(Workspace(root), session=session, mode=session.mode,
                  model=args.model or session.model,
                  confirm_handler=terminal.approve)
    return agent, terminal


def run_once(agent, terminal, prompt):
    """Run one request and print everything it does."""
    for event in agent.send(prompt):
        terminal.handle(event, terminal.approve)
    terminal.status_clear()


def repl(agent, terminal, args):
    """The interactive loop."""
    print("\nType a request, or :help for the commands. Ctrl+C stops a job.")
    while True:
        try:
            text = input("\n" + PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.startswith(":"):
            if not _command(agent, terminal, text):
                break
            continue
        try:
            run_once(agent, terminal, text)
        except KeyboardInterrupt:
            agent.cancel()
            print("\n  [stopped]")


def _command(agent, terminal, text):
    """Handle a :command. Returns False to quit."""
    parts = text[1:].split(maxsplit=1)
    name = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    if name in ("q", "quit", "exit"):
        return False
    if name in ("h", "help"):
        print("\n  :mode plan|ask|auto-edit|full-auto  how much it may do alone")
        for mode, why in MODE_HELP.items():
            print(f"      {mode:<10} {why}")
        print("  :root PATH      work on another trusted folder")
        print("  :undo           undo the last file change")
        print("  :files          show the project map")
        print("  :sessions       list saved sessions")
        print("  :quit           leave")
    elif name == "mode":
        if rest not in MODES:
            print("  modes: " + ", ".join(MODES))
        else:
            agent.set_mode(rest)
            print(f"  mode is now {rest} - {MODE_HELP[rest]}")
    elif name == "root":
        if not rest:
            print(f"  current root: {agent.workspace.root}")
        else:
            new_root = pick_root(argparse.Namespace(root=rest,
                                                    trust=False))
            if new_root:
                agent.workspace = Workspace(new_root)
                agent.session.root = str(new_root)
                agent._system_message()
                print(f"  root is now {new_root}")
    elif name == "undo":
        print("  " + agent.undo())
    elif name == "files":
        print(agent.workspace.overview(max_entries=60))
    elif name == "sessions":
        for path in Session.recent(8):
            print("  " + path.name)
    else:
        print(f"  unknown command: {name} (try :help)")
    return True


# ------------------------------------------------------------------ main

def build_parser():
    parser = argparse.ArgumentParser(
        prog="zyro-agent",
        description="A local coding agent (free, offline, Ollama-powered).")
    parser.add_argument("prompt", nargs="*",
                        help="what to do; omit it for an interactive prompt")
    parser.add_argument("-r", "--root",
                        help="project folder (default: the current folder)")
    parser.add_argument("-m", "--mode", choices=MODES, default="ask",
                        help="ask (default), plan, auto-edit or full-auto")
    parser.add_argument("--model", help="Ollama model (default: "
                                        + config.MODEL + ")")
    parser.add_argument("--trust", action="store_true",
                        help="trust --root without asking")
    parser.add_argument("--resume", help="resume a session: 'last' or a "
                                         "session file name")
    parser.add_argument("--list", action="store_true",
                        help="show trusted folders and recent sessions")
    parser.add_argument("--quiet", action="store_true",
                        help="no live progress line")
    parser.add_argument("--thinking", action="store_true",
                        help="show the model's reasoning while it works")
    parser.add_argument("--untrust", metavar="PATH",
                        help="forget a trusted folder and exit")
    parser.add_argument("--check", action="store_true",
                        help="check that Ollama and the model are ready")
    return parser


def show_lists():
    print("trusted folders:")
    roots = trusted_roots()
    if not roots:
        print("  (none yet)")
    for root in roots:
        print("  " + str(root))
    print("\nrecent sessions:")
    files = Session.recent(10)
    if not files:
        print("  (none yet)")
    for path in files:
        session = Session.load(path)
        if session is None:
            print("  " + path.name + "  (unreadable)")
            continue
        print(f"  {path.name}  [{session.mode}]  {session.root}")
        for line in transcript_preview(session, 3):
            print("      " + line)


def check_ready():
    """A friendly pre-flight: is Ollama up, is the model installed?"""
    print(f"model     : {config.MODEL}")
    print(f"context   : {config.NUM_CTX}")
    print(f"state dir : {config.STATE_DIR}")
    try:
        from ollama import list as ollama_list
        models = [m.model for m in ollama_list().models]
    except Exception as exc:  # noqa: BLE001
        print("Ollama    : NOT REACHABLE -- start the Ollama app")
        print("            (" + str(exc)[:120] + ")")
        return 1
    print("Ollama    : ready")
    print("installed : " + ", ".join(m for m in models if m))
    if not any(m == config.MODEL or m.startswith(config.MODEL + ":")
               or m.split(":")[0] == config.MODEL.split(":")[0]
               for m in models):
        print(f"\n!! {config.MODEL} is not installed. Run:")
        print(f"     ollama pull {config.MODEL}")
        return 1
    return 0


def _utf8_console():
    """Make printing survive a non-UTF-8 console.

    A Windows console is usually cp1252 and tool output is not always
    plain text: a YouTube title with an emoji in it crashed the whole
    CLI with UnicodeEncodeError. Replacing the odd character is far
    better than losing the session.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _utf8_console()
    args = build_parser().parse_args(argv)
    config.ensure_state_dirs()

    if args.check:
        return check_ready()
    if args.untrust:
        removed = untrust(args.untrust)
        print(("forgot " if removed else "was not trusted: ")
              + str(Path(args.untrust)))
        return 0
    if args.list:
        show_lists()
        return 0

    session = None
    if args.resume:
        if args.resume == "last":
            files = Session.recent(1)
            session = Session.load(files[0]) if files else None
        else:
            path = Path(args.resume)
            if not path.is_file():
                path = config.SESSION_DIR / args.resume
            session = Session.load(path)
        if session is None:
            print("could not read that session; starting a new one")
        else:
            args.root = args.root or session.root
            args.mode = session.mode
            print(f"resumed {session.id} ({session.root})")

    root = pick_root(args)
    if root is None:
        return 2

    # Ollama is the brain: start it here too, so the coding agent works
    # from a cold laptop exactly like the window does.
    ready, started_here = prepare_ollama()
    if not ready:
        print("Ollama not found - install it or check PATH.")
        print("  1. Download: https://ollama.com/download")
        print("  2. Then run: ollama pull " + config.MODEL)
        return 2
    if started_here and KILL_OLLAMA_ON_EXIT:
        atexit.register(ollama_lifecycle.stop_ollama)

    agent, terminal = make_agent(args, root, session)
    print(f"\nZYRO coding agent")
    print(f"  folder : {root}")
    print(f"  mode   : {agent.mode} - {MODE_HELP[agent.mode]}")
    print(f"  model  : {agent.model} (local, free, offline)")

    prompt = " ".join(args.prompt).strip()
    if prompt:
        run_once(agent, terminal, prompt)
        agent.session.save()
        return 0
    try:
        repl(agent, terminal, args)
    finally:
        path = agent.session.save()
        if path:
            print(f"\nsession saved: {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

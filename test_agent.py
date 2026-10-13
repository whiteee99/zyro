"""Tests for ZYRO's coding agent.

Runs with NO model and NO internet: the file tools are exercised for
real in a throwaway folder, the safety rules are checked with a fake
model, and everything that would touch the user's desktop (volume,
wallpaper, clipboard, shutdown...) is deliberately left alone.

    venv\\Scripts\\python test_agent.py            fast, offline
    venv\\Scripts\\python test_agent.py --live     also runs one real
                                                  qwen3:4b request

The agent's own state (sessions, checkpoints, facts) is redirected
into the test folder, so a test run never touches memory/.
"""

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Redirect the agent's state BEFORE the other modules import it.
from agent import config                                    # noqa: E402

SANDBOX = ROOT / "agent" / "_selftest"
STATE = SANDBOX / "state"
config.STATE_DIR = STATE
config.TRUST_FILE = STATE / "trusted.json"
config.SESSION_DIR = STATE / "sessions"
config.CHECKPOINT_DIR = STATE / "checkpoints"

from agent import diff as diffmod, llm, tools               # noqa: E402
from agent.checkpoint import Checkpoints                    # noqa: E402
from agent.loop import Agent, MODES                         # noqa: E402
from agent.session import Session                           # noqa: E402
from agent.tools import ToolContext, ToolError              # noqa: E402
from agent.workspace import Workspace, WorkspaceError       # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS  " if ok else "FAIL  ") + name
          + (f"   ({detail})" if detail and not ok else ""))


def reset_sandbox():
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    (SANDBOX / "project").mkdir(parents=True, exist_ok=True)
    (SANDBOX / "outside.txt").write_text("secret outside", encoding="utf-8")


PROJECT = SANDBOX / "project"


# ------------------------------------------------------------ 1. diff

def test_diff():
    old = "one\ntwo\nthree\n"
    new = "one\nTWO\nthree\nfour\n"
    text = diffmod.unified(old, new, "demo.txt")
    added, removed = diffmod.counts(old, new)
    check("diff shows the added line", "+four" in text)
    check("diff counts lines", (added, removed) == (2, 1),
          f"got {added}/{removed}")
    check("diff is empty when nothing changed",
          diffmod.unified(old, old) == "")
    check("diff summary is readable",
          diffmod.summary(old, new, "demo.txt") == "demo.txt: +2 -1",
          diffmod.summary(old, new, "demo.txt"))


# ------------------------------------------------------ 2. containment

def test_workspace():
    ws = Workspace(PROJECT)
    (PROJECT / "notes.txt").write_text("hello", encoding="utf-8")
    (PROJECT / ".env").write_text("KEY=1", encoding="utf-8")
    (PROJECT / "node_modules").mkdir(exist_ok=True)
    (PROJECT / "node_modules" / "junk.js").write_text("x", encoding="utf-8")

    check("an inside path resolves",
          ws.resolve("notes.txt", must_exist=True).name == "notes.txt")
    try:
        ws.resolve("../outside.txt")
        check("'..' is refused", False)
    except WorkspaceError:
        check("'..' is refused", True)
    try:
        ws.resolve(str(SANDBOX / "outside.txt"))
        check("an absolute outside path is refused", False)
    except WorkspaceError:
        check("an absolute outside path is refused", True)
    try:
        ws.resolve(".env")
        check("a secrets file is refused", False)
    except WorkspaceError:
        check("a secrets file is refused", True)
    check("ignored folders are skipped",
          all("node_modules" not in str(p) for p in ws.iter_files()))
    check("overview lists real files", "notes.txt" in ws.overview())
    check("overview hides secrets", ".env" not in ws.overview())


# ---------------------------------------------------------- 3. registry

def test_registry():
    specs = {s["name"]: s for s in tools.all_specs()}
    required = [
        "list_files", "read_file", "write_file", "append_file", "edit_file",
        "create_file", "delete_file", "rename_file", "move_file", "copy_file",
        "create_folder", "delete_folder", "rename_folder", "file_info",
        "zip_files", "unzip", "find_duplicates", "largest_files",
        "recent_files", "empty_recycle_bin", "search_files",
        "search_in_files", "system_info", "list_processes", "kill_process",
        "battery_status", "cpu_ram_usage", "disk_usage", "uptime",
        "network_info", "set_brightness", "set_volume", "mute_toggle",
        "clipboard_read", "clipboard_write", "notify", "set_wallpaper",
        "open_settings", "power_action", "set_timer", "set_alarm",
        "set_reminder", "todo_add", "todo_list", "todo_done", "open_site",
        "browser_open", "browser_click", "browser_type", "browser_close",
        "browser_scroll", "browser_back", "browser_press_key",
        "browser_get_text", "read_site", "web_search", "download_file",
        "download_video", "yt_search", "get_weather", "get_news",
        "play_music", "screenshot", "media_key", "look_screen", "look_image",
        "remember", "recall", "suggest_model", "switch_model", "run_python",
        "run_command",
    ]
    missing = [name for name in required if name not in specs]
    check("every requested tool exists", not missing, f"missing {missing}")

    bad = []
    for name, spec in specs.items():
        if spec["kind"] == "edit" and "planner" not in spec:
            bad.append(name)
        if spec["kind"] != "edit" and "handler" not in spec:
            bad.append(name)
        if not spec["description"]:
            bad.append(name)
    check("every tool is runnable", not bad, f"broken {bad}")

    critical = sorted(n for n, s in specs.items() if s["critical"])
    check("the destructive tools always ask",
          set(critical) == {"delete_file", "delete_folder", "download_video",
                            "empty_recycle_bin", "kill_process",
                            "power_action"}, str(critical))

    for mode, kind, critical_flag, expected in (
            ("plan", "read", False, False),
            ("plan", "edit", False, True),       # moot: plan mode blocks it
            ("ask", "read", False, False),
            ("ask", "edit", False, True),
            ("ask", "op", False, True),
            ("ask", "exec", False, True),
            ("auto-edit", "edit", False, False),
            ("auto-edit", "op", False, False),
            ("auto-edit", "exec", False, True),
            ("full-auto", "edit", False, False),
            ("full-auto", "exec", False, False),
            ("full-auto", "edit", True, True),   # critical beats full-auto
            ("full-auto", "op", True, True),
    ):
        spec = {"kind": kind, "critical": critical_flag, "name": "x"}
        got = tools.needs_approval(spec, mode)
        check(f"{mode:<10} {kind:<5} critical={critical_flag!s:<5} -> "
              f"{'asks' if expected else 'free'}",
              got == expected, f"got {got}")

    check("plan mode blocks anything that changes files",
          not tools.allowed_in_mode({"kind": "edit"}, "plan")
          and tools.allowed_in_mode({"kind": "read"}, "plan"))

    base = len(tools.schemas(tools.BASE_GROUPS))
    every = len(tools.schemas(None))
    check("only the core tools load by default (small context)",
          base < every, f"{base} vs {every}")


# -------------------------------------------------------- 4. file tools

def run(name, args, ctx):
    """Call a tool the way the loop does."""
    spec = tools.get(name)
    if spec["kind"] == "edit":
        change = spec["planner"](args, ctx)
        return change.apply(), change
    text_result, _ = tools.execute(spec, args, ctx)
    return text_result, None


def test_file_tools():
    ws = Workspace(PROJECT)
    ctx = ToolContext(ws, None, None)

    out, _ = run("create_folder", {"path": "docs"}, ctx)
    check("create_folder makes a folder", (PROJECT / "docs").is_dir(), out)

    result, change = run("create_file",
                         {"path": "docs/a.txt", "content": "alpha\nbeta\n"},
                         ctx)
    check("create_file writes and shows a diff",
          (PROJECT / "docs" / "a.txt").is_file() and "+alpha" in change.diff(),
          result)
    check("create_file reports it is a creation", change.created)

    try:
        run("create_file", {"path": "docs/a.txt", "content": "again"}, ctx)
        check("create_file refuses to overwrite", False)
    except ToolError as exc:
        check("create_file refuses to overwrite", "already exists" in str(exc))

    out, _ = run("append_file", {"path": "docs/a.txt", "content": "gamma"},
                 ctx)
    body = (PROJECT / "docs" / "a.txt").read_text(encoding="utf-8")
    check("append_file adds a line", body.endswith("gamma\n"), out)

    out, change = run("edit_file", {"path": "docs/a.txt", "find": "beta",
                                    "replace": "BETA"}, ctx)
    body = (PROJECT / "docs" / "a.txt").read_text(encoding="utf-8")
    check("edit_file replaces exactly one occurrence",
          "BETA" in body and "beta" not in body, out)

    try:
        run("edit_file", {"path": "docs/a.txt", "find": "nope",
                          "replace": "x"}, ctx)
        check("edit_file refuses missing text", False)
    except ToolError as exc:
        check("edit_file refuses missing text", "does not appear" in str(exc))

    out, _ = run("read_file", {"path": "docs/a.txt"}, ctx)
    check("read_file numbers the lines", "    1| alpha" in out, out[:60])

    out, _ = run("list_files", {"path": "docs"}, ctx)
    check("list_files shows the file", "a.txt" in out, out)

    out, _ = run("file_info", {"path": "docs/a.txt"}, ctx)
    check("file_info reports size and lines",
          "size" in out and "lines" in out, out[:60])

    out, _ = run("copy_file", {"path": "docs/a.txt",
                               "destination": "docs/b.txt"}, ctx)
    check("copy_file copies", (PROJECT / "docs" / "b.txt").is_file(), out)

    out, _ = run("rename_file", {"path": "docs/b.txt", "new_name": "c.txt"},
                 ctx)
    check("rename_file renames",
          (PROJECT / "docs" / "c.txt").is_file()
          and not (PROJECT / "docs" / "b.txt").exists(), out)

    out, _ = run("move_file", {"path": "docs/c.txt", "destination": "moved"},
                 ctx)
    check("move_file moves into a new folder",
          (PROJECT / "moved" / "c.txt").is_file(), out)

    (PROJECT / "docs" / "dupe1.txt").write_text("same", encoding="utf-8")
    (PROJECT / "docs" / "dupe2.txt").write_text("same", encoding="utf-8")
    out, _ = run("find_duplicates", {"folder": "docs"}, ctx)
    check("find_duplicates finds identical files",
          "dupe1.txt" in out and "dupe2.txt" in out, out[:80])

    out, _ = run("largest_files", {"folder": ".", "count": 5}, ctx)
    check("largest_files lists files", "a.txt" in out or "c.txt" in out,
          out[:80])

    out, _ = run("recent_files", {"folder": ".", "count": 5}, ctx)
    check("recent_files lists files", "txt" in out, out[:80])

    out, _ = run("search_files", {"name": "*.txt", "root": "docs"}, ctx)
    check("search_files finds by name", "a.txt" in out, out[:80])

    out, _ = run("search_in_files", {"pattern": "alpha", "root": "."}, ctx)
    check("search_in_files finds text", "a.txt:1" in out, out[:80])

    out, _ = run("zip_files", {"path": "docs", "output": "docs.zip"}, ctx)
    check("zip_files makes an archive", (PROJECT / "docs.zip").is_file(), out)

    out, _ = run("unzip", {"zip_path": "docs.zip",
                           "destination": "unpacked"}, ctx)
    check("unzip extracts",
          (PROJECT / "unpacked" / "docs" / "a.txt").is_file(), out)

    out, _ = run("run_python", {"code": "print(6*7)"}, ctx)
    check("run_python runs code", "42" in out, out[:60])

    out, _ = run("run_command", {"command": "echo hello"}, ctx)
    check("run_command runs a command", "hello" in out, out[:60])

    out, _ = run("rename_folder", {"path": "moved", "new_name": "shifted"},
                 ctx)
    check("rename_folder renames", (PROJECT / "shifted").is_dir(), out)


def test_zip_slip():
    """An archive must not be able to write outside the target folder."""
    import zipfile
    evil = PROJECT / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../../escaped.txt", "gotcha")
    ws = Workspace(PROJECT)
    ctx = ToolContext(ws, None, None)
    out, _ = run("unzip", {"zip_path": "evil.zip", "destination": "safe"},
                 ctx)
    check("unzip refuses a path-escape archive",
          out.startswith("ERROR") and "unsafe path" in out, out[:80])
    check("nothing escaped the folder",
          not (SANDBOX / "escaped.txt").exists())


# --------------------------------------------------- 5. undo/checkpoints

def test_checkpoints():
    ws = Workspace(PROJECT)
    session = Session(root=PROJECT, mode="ask")
    checkpoints = Checkpoints(session.id)
    ctx = ToolContext(ws, session, None, journal=checkpoints.journal)

    target = PROJECT / "undo_me.txt"
    target.write_text("original\n", encoding="utf-8")
    checkpoints.snapshot(target, reason="test")
    run("edit_file", {"path": "undo_me.txt", "find": "original",
                      "replace": "changed"}, ctx)
    check("the edit landed",
          "changed" in target.read_text(encoding="utf-8"))

    result = checkpoints.undo_last()
    check("undo restored the old content",
          result is not None
          and target.read_text(encoding="utf-8") == "original\n",
          str(result))

    created = PROJECT / "created_by_agent.txt"
    checkpoints.snapshot(created, reason="test-create")   # did not exist
    created.write_text("new file", encoding="utf-8")
    checkpoints.undo_last()
    check("undo removes a file the agent created", not created.exists())

    checkpoints.journal(op="move", source="a", target="b", note="test")
    check("the journal records structural changes",
          any(e["op"] == "move"
              for e in checkpoints.journal_entries()))


# ------------------------------------------------------- 6. the loop

def fake_model(script):
    """Replace llm.stream with a scripted model (no GPU time)."""
    steps = list(script)

    def stream(messages, tools=None, model=None, **kwargs):
        step = steps.pop(0) if steps else {"content": "done", "calls": []}
        for chunk in step.get("stream", []):
            yield {"kind": "text", "text": chunk}
        yield {"kind": "done", "content": step.get("content", ""),
               "thinking": "", "tool_calls": step.get("calls", []),
               "stats": {}}
    return stream


def call(name, **args):
    return {"function": {"name": name, "arguments": args}}


def run_loop(prompt, script, mode="ask", approve=True, groups=None):
    """Run one loop turn with a fake model. Returns (events, answers)."""
    ws = Workspace(PROJECT)
    session = Session(root=PROJECT, mode=mode)
    asked = []

    def confirm(request):
        asked.append(request)
        return approve

    agent = Agent(ws, session=session, mode=mode, confirm_handler=confirm,
                  groups=groups or tools.BASE_GROUPS)
    original = llm.stream
    llm.stream = fake_model(script)
    try:
        events = list(agent.send(prompt))
    finally:
        llm.stream = original
    return events, asked, agent


def test_loop():
    target = PROJECT / "loop.txt"
    if target.exists():
        target.unlink(missing_ok=True)

    # a plain answer, no tools
    events, asked, _ = run_loop("hello", [{"content": "hi there", "calls": []}])
    kinds = [e["type"] for e in events]
    check("a plain answer finishes the turn",
          "final" in kinds and "done" in kinds and not asked)
    check("the answer text reaches the frontend",
          any(e["type"] == "final" and e["text"] == "hi there"
              for e in events))

    # an approved write
    events, asked, _ = run_loop(
        "create the file",
        [{"content": "", "calls": [call("create_file", path="loop.txt",
                                        content="written by the agent\n")]},
         {"content": "created it", "calls": []}],
        approve=True)
    check("an approved write lands on disk",
          target.is_file()
          and target.read_text(encoding="utf-8").startswith("written"))
    check("the write was shown as a diff",
          any(e["type"] == "diff" for e in events))
    check("the write asked for approval", len(asked) == 1)

    # a declined write
    target.unlink(missing_ok=True)
    events, asked, _ = run_loop(
        "create the file",
        [{"content": "", "calls": [call("create_file", path="loop.txt",
                                        content="nope")]},
         {"content": "ok", "calls": []}],
        approve=False)
    check("a declined write does NOT land on disk", not target.exists())
    check("the model is told the user declined",
          any(e["type"] == "tool_result"
              and "did NOT approve" in str(e.get("result")) for e in events))

    # auto-edit writes without asking
    target.unlink(missing_ok=True)
    events, asked, _ = run_loop(
        "create the file",
        [{"content": "", "calls": [call("create_file", path="loop.txt",
                                        content="auto")]},
         {"content": "done", "calls": []}],
        mode="auto-edit")
    check("auto-edit writes without asking",
          target.is_file() and not asked)
    check("auto-edit still shows the diff",
          any(e["type"] == "diff" for e in events))

    # plan mode refuses a write
    target.unlink(missing_ok=True)
    events, asked, _ = run_loop(
        "create the file",
        [{"content": "", "calls": [call("create_file", path="loop.txt",
                                        content="plan?")]},
         {"content": "here is my plan", "calls": []}],
        mode="plan")
    check("plan mode refuses writes", not target.exists())
    check("plan mode explains the refusal",
          any(e["type"] == "notice" and "PLAN" in str(e.get("text"))
              for e in events))
    check("plan mode asks nothing", not asked)

    # a critical tool still asks in full-auto
    events, asked, _ = run_loop(
        "delete the file",
        [{"content": "", "calls": [call("delete_file", path="loop.txt")]},
         {"content": "ok", "calls": []}],
        mode="full-auto", approve=False)
    check("a critical tool asks even in full-auto", len(asked) == 1)
    check("the critical request is flagged",
          asked and asked[0].get("critical") is True)

    # an invented tool name
    events, asked, _ = run_loop(
        "do something odd",
        [{"content": "", "calls": [call("make_coffee", size="large")]},
         {"content": "sorry", "calls": []}])
    check("an unknown tool is refused politely",
          any(e["type"] == "tool_result"
              and "no tool called" in str(e.get("result")) for e in events))

    # a command needs approval in ask mode
    events, asked, _ = run_loop(
        "run it",
        [{"content": "", "calls": [call("run_command", command="echo hi")]},
         {"content": "ran it", "calls": []}],
        mode="ask", approve=False)
    check("commands ask in ask mode", len(asked) == 1)
    check("a declined command does not run",
          any(e["type"] == "tool_result"
              and "did NOT approve" in str(e.get("result")) for e in events))

    # enable_tools pulls in a group
    ws = Workspace(PROJECT)
    agent = Agent(ws, session=Session(root=PROJECT, mode="ask"),
                  mode="ask", confirm_handler=lambda r: True)
    before = len(agent.groups)
    agent.ctx.agent = agent
    spec = tools.get("enable_tools")
    text_result, _ = tools.execute(spec, {"group": "system"}, agent.ctx)
    check("enable_tools loads a group",
          "system" in agent.groups and len(agent.groups) > before, text_result)

    # the keyword router
    check("the router spots a PC question",
          "system" in tools.detect_groups("what is my battery level"))
    check("the router spots a coding question",
          not tools.detect_groups("add a hello function to utils.py"))


# --------------------------------------------------- 7. context budget

def test_context_budget():
    """The context estimate must include the tool schemas."""
    import json

    ws = Workspace(PROJECT)
    agent = Agent(ws, session=Session(root=PROJECT, mode="ask"), mode="ask")

    schema_tokens = len(json.dumps(tools.schemas(agent.groups))) // 4
    check("the estimate counts the tool schemas",
          agent._context_tokens() >= schema_tokens,
          f"{agent._context_tokens()} vs {schema_tokens}")

    # Fill the transcript past the budget, then compact.
    agent.session.messages += [{"role": "user", "content": "x" * 4000}
                               for _ in range(10)]
    before = len(agent.session.messages)
    original_complete = llm.complete
    llm.complete = lambda *a, **k: "summary of the work so far"
    try:
        note = agent._compact_if_needed()
    finally:
        llm.complete = original_complete
    check("compaction fires before the window overflows", note is not None)
    check("the system prompt survives compaction",
          agent.session.messages[0].get("role") == "system")
    check("the transcript actually shrinks",
          len(agent.session.messages) < before,
          f"{before} -> {len(agent.session.messages)}")
    check("everything still fits the context window",
          agent._context_tokens() < config.NUM_CTX,
          f"{agent._context_tokens()} of {config.NUM_CTX}")

    # A context window far too small for the loaded tools is reported once.
    original_ctx = config.NUM_CTX
    config.NUM_CTX = 1500
    try:
        small = Agent(ws, session=Session(root=PROJECT, mode="ask"),
                      mode="ask")
        warning = small._context_warning()
        check("too-small context is warned about", warning is not None,
              str(warning))
        check("the warning is only shown once",
              small._context_warning() is None)
    finally:
        config.NUM_CTX = original_ctx


def test_cli_frontend():
    """The terminal frontend, driven end to end with a fake model."""
    import contextlib
    import io

    from agent import cli

    project = SANDBOX / "cliproj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "notes.txt").write_text("hello from notes\n", encoding="utf-8")

    script = [
        {"content": "", "calls": [call("read_file", path="notes.txt")]},
        {"content": "notes.txt says hello.", "calls": []},
    ]
    original = llm.stream
    llm.stream = fake_model(script)
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            code = cli.main(["--root", str(project), "--trust", "--quiet",
                             "-m", "auto-edit", "what is in notes.txt?"])
    finally:
        llm.stream = original
    out = buffer.getvalue()

    check("the terminal frontend exits cleanly", code == 0, str(code))
    check("it shows the folder it is working in",
          str(project) in out, out[:200])
    check("it shows the tool call it made",
          "read_file" in out and "notes.txt" in out, out[:400])
    check("it shows the file contents it read",
          "hello from notes" in out, out[:400])
    check("it prints the final answer",
          "ZYRO: notes.txt says hello." in out, out[-400:])
    check("it saved the session",
          any(config.SESSION_DIR.glob("session_*.json")))


def test_cli_ollama_ownership():
    """The coding agent must not kill an Ollama it did not start."""
    from agent import cli
    from core import ollama_lifecycle

    original_running = ollama_lifecycle.is_ollama_running
    original_start = ollama_lifecycle.start_ollama
    try:
        ollama_lifecycle.is_ollama_running = lambda: True
        ready, ours = cli.prepare_ollama()
        check("an already-running Ollama is not owned by the agent",
              ready is True and ours is False)

        ollama_lifecycle.is_ollama_running = lambda: False
        ollama_lifecycle.start_ollama = lambda timeout=15: True
        ready, ours = cli.prepare_ollama()
        check("an Ollama the agent started is owned by the agent",
              ready is True and ours is True)

        ollama_lifecycle.start_ollama = lambda timeout=15: False
        ready, ours = cli.prepare_ollama()
        check("a failed start is reported as not ready",
              ready is False and ours is True)
    finally:
        ollama_lifecycle.is_ollama_running = original_running
        ollama_lifecycle.start_ollama = original_start


# --------------------------------------------------- 8. real system tools

def test_system_tools():
    ws = Workspace(PROJECT)
    ctx = ToolContext(ws, None, None)
    # Only the read-only ones: nothing here may change the user's PC.
    for name, needle in (("system_info", "RAM"),
                         ("cpu_ram_usage", "CPU"),
                         ("disk_usage", "free"),
                         ("uptime", "on for"),
                         ("network_info", "host name"),
                         ("list_processes", "processes"),
                         ("battery_status", "attery")):
        text_result, _ = tools.execute(tools.get(name), {}, ctx)
        ok = needle.lower() in text_result.lower()
        check(f"{name} answers", ok, text_result[:70])


# ----------------------------------------------------------- 8. live

def test_live():
    """One real request against the local model (opt-in)."""
    print("\n--- live run with the real model ---")
    ws = Workspace(PROJECT)
    session = Session(root=PROJECT, mode="ask")
    ideas = PROJECT / "greet.py"
    if ideas.exists():
        ideas.unlink()

    def confirm(request):
        print("   [auto-approved]", request.get("summary")
              or request.get("command"))
        return True

    agent = Agent(ws, session=session, mode="ask", confirm_handler=confirm,
                  groups=set(tools.BASE_GROUPS) | {"files"})
    prompt = ("Create a file greet.py that prints 'hello from ZYRO', then "
              "run it with run_command and tell me what it printed.")
    started = time.time()
    for event in agent.send(prompt):
        kind = event["type"]
        if kind == "step":
            print(f"   step {event['n']}...")
        elif kind == "tool":
            print("   -> " + event.get("preview", event["name"]))
        elif kind == "diff":
            print("   diff: " + event["summary"])
        elif kind == "tool_result":
            first = str(event["result"]).splitlines()
            print("   <- " + (first[0][:80] if first else ""))
        elif kind == "final":
            print("   ZYRO: " + event["text"][:300])
        elif kind == "error":
            print("   !! " + str(event["text"])[:200])
    elapsed = time.time() - started
    check("live: the model created greet.py", ideas.is_file(),
          f"{elapsed:.0f}s")
    if ideas.is_file():
        body = ideas.read_text(encoding="utf-8", errors="replace")
        check("live: the file looks like real code", "print" in body,
              body[:80])
    print(f"   (took {elapsed:.0f}s)")


def main():
    live = "--live" in sys.argv
    reset_sandbox()
    print("sandbox:", SANDBOX)
    print()
    test_diff()
    test_workspace()
    test_registry()
    test_file_tools()
    test_zip_slip()
    test_checkpoints()
    test_loop()
    test_context_budget()
    test_cli_frontend()
    test_cli_ollama_ownership()
    test_system_tools()
    if live:
        test_live()

    print()
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed:")
        for name in FAIL:
            print("  - " + name)
    shutil.rmtree(SANDBOX, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

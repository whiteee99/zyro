"""The agent loop: look, decide, act, observe, repeat.

One user request may take many model steps. Each step is:

  1. hand the model the project map + the conversation + the tools
  2. the model either answers, or asks for tool calls
  3. every tool call is checked against the mode (plan / ask /
     auto-edit / full-auto), shown as a diff or a command line, and
     only then executed
  4. the result goes back to the model as a tool message

Two rules never bend, whatever the mode:

  * a file may only be touched inside the trusted folder
  * a "critical" tool (delete, kill, shutdown, video download) always
    asks the human first

Tool groups are loaded on demand: handing a 4B model all 75 schemas
at once would eat its whole context window.
"""

import json

from . import config, diff as diffmod, llm, tools
from .checkpoint import Checkpoints
from .session import Session
from .tools import ToolContext, ToolError, ToolNotFound
from .workspace import Workspace, WorkspaceError

MODES = ("plan", "ask", "auto-edit", "full-auto")

MODE_HELP = {
    "plan": "read only -- the agent investigates and proposes a plan",
    "ask": "every change and command waits for your yes",
    "auto-edit": "file changes run freely (you still see the diff), "
                 "commands ask",
    "full-auto": "everything runs without asking except the critical "
                 "actions (delete, kill, shutdown, video download)",
}

_BASE_PROMPT = """You are ZYRO, a coding and PC agent working inside ONE project \
folder.

PROJECT FOLDER: {root}

PROJECT FILES:
{overview}

HOW TO WORK
- Look before you change anything. Use list_files, read_file, \
search_files and search_in_files.
- Never guess what a file contains -- read it.
- Make the smallest change that does the job.
- Prefer edit_file over write_file. Copy the 'find' text exactly from \
the file, with enough surrounding lines to be unique.
- Run the tests or the program with run_command to check your work.
- DO NOT explain what you are about to do. Call the tool in the SAME \
reply. The user can see every tool call, so describing it wastes \
their time.
- Never write a plan or a numbered list unless the user asked for one.
- Finish with 1-3 short sentences for the user: what you changed, and \
anything they must know. No reasoning, no restating the request.
- Never invent a file, a result or a command output.

TOOLS
You have the project tools now. For anything else -- the PC itself, \
the web, music, timers -- call enable_tools first to load that group, \
then use it. list_tools shows every group.{mode_rules}"""

_NUDGE = ("REMINDER: you did not use a tool. Do not describe your plan. "
          "If the task still needs work, call the tool NOW in this reply. "
          "If the task is finished, answer in one short sentence.")

_PLAN_MARKERS = ("step by step", "let me ", "i will ", "i need to ",
                 "first,", "first i", "plan:", "next, i", "i should ")

_PLAN_RULES = ("\n\n- You are in PLAN mode: READ ONLY. Investigate, then "
               "write a short numbered plan and stop. Do not change any file.")
_WRITE_RULES = ("\n\n- File changes are shown to the user as a diff before "
                "they are applied, so keep them small and easy to review.")


class Agent:
    """A coding session inside one trusted folder."""

    def __init__(self, workspace, session=None, mode="ask", model=None,
                 confirm_handler=None, groups=None):
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode}")
        self.workspace = workspace
        self.mode = mode
        self.model = model or config.MODEL
        self.confirm_handler = confirm_handler
        self.session = session or Session(root=workspace.root, mode=mode,
                                          model=self.model)
        self.session.mode = mode
        self.session.model = self.model
        self.checkpoints = Checkpoints(self.session.id)
        self.cancelled = False
        self._nudges = 0
        self._warned_context = False
        self._prompt = None
        self.groups = set(groups or tools.BASE_GROUPS)
        self.ctx = ToolContext(workspace, self.session, self,
                               journal=self.checkpoints.journal)
        self._system_message()

    # ---------------------------------------------------------- prompt

    def _system_message(self):
        """Build (or rebuild) the system prompt at the head of the chat."""
        mode_rules = _PLAN_RULES if self.mode == "plan" else _WRITE_RULES
        prompt = _BASE_PROMPT.format(
            root=self.workspace.root,
            overview=self.workspace.overview(),
            mode_rules=mode_rules)
        self._prompt = prompt          # measured by _context_warning()
        if self.session.messages and \
                self.session.messages[0].get("role") == "system":
            self.session.messages[0] = {"role": "system", "content": prompt}
        else:
            self.session.messages.insert(0, {"role": "system",
                                             "content": prompt})

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode}")
        self.mode = mode
        self.session.mode = mode
        self._system_message()
        return mode

    def set_model(self, model):
        self.model = model
        self.session.model = model
        return model

    # ------------------------------------------------------------ loop

    def send(self, user_text):
        """Handle one user request. Yields small event dicts."""
        self.cancelled = False
        self._nudges = 0
        self._system_message()
        eager = tools.detect_groups(user_text)
        if eager - self.groups:
            self.groups |= eager
            yield {"type": "notice",
                   "text": "loaded tool group(s): " + ", ".join(sorted(eager))}
        warning = self._context_warning()
        if warning:
            yield {"type": "notice", "text": warning}
        self.session.messages.append({"role": "user", "content": user_text})
        yield {"type": "user", "text": user_text}
        self._save()

        for step in range(1, config.MAX_STEPS + 1):
            if self.cancelled:
                yield {"type": "notice", "text": "stopped by the user"}
                yield {"type": "done"}
                return
            yield {"type": "step", "n": step}

            note = self._compact_if_needed()
            if note:
                yield {"type": "notice", "text": note}

            content = ""
            tool_calls = []
            stats = {}
            try:
                for event in llm.stream(self.session.messages,
                                        tools=tools.schemas(self.groups),
                                        model=self.model):
                    kind = event["kind"]
                    if kind == "thinking":
                        yield {"type": "thinking", "text": event["text"]}
                    elif kind == "text":
                        yield {"type": "text", "text": event["text"],
                               "provisional": True}
                    elif kind == "done":
                        content = event["content"]
                        tool_calls = event["tool_calls"]
                        stats = event["stats"]
            except llm.LLMError as exc:
                yield {"type": "error", "text": str(exc)}
                yield {"type": "done"}
                return

            message = {"role": "assistant", "content": content}
            if tool_calls:
                message["tool_calls"] = tool_calls
                # With thinking off, a small model writes its reasoning
                # into 'content'. Keeping that in the history makes the
                # next step worse, so only a short piece survives.
                if len(content) > config.STORE_CONTENT_LIMIT:
                    message["content"] = ""
            self.session.messages.append(message)

            yield {"type": "step_end", "answer": content,
                   "tools": len(tool_calls),
                   "stats": llm.stats_line(stats)}

            if not tool_calls:
                if self._should_nudge(step, content):
                    self._nudges += 1
                    self.session.messages.append({"role": "user",
                                                  "content": _NUDGE})
                    yield {"type": "notice",
                           "text": "the model explained instead of acting -- "
                                   "asking it to use a tool"}
                    self._save()
                    continue
                self._save()
                yield {"type": "final", "text": content}
                yield {"type": "done"}
                return

            for call in tool_calls:
                if self.cancelled:
                    break
                yield from self._handle_call(call)
            self._save()

        yield {"type": "notice",
               "text": f"step limit reached ({config.MAX_STEPS}); ask for "
                       "the next piece and I will continue"}
        yield {"type": "done"}

    # ----------------------------------------------------------- tools

    def _handle_call(self, call):
        """Validate, approve and run one tool call."""
        name, args = _read_call(call)
        try:
            spec = tools.get(name)
        except ToolNotFound:
            result = (f"ERROR: there is no tool called '{name}'. Available "
                      "now: " + ", ".join(sorted(
                          s["name"] for s in tools.specs_for(self.groups))))
            yield {"type": "tool", "name": name, "args": args,
                   "result": None, "preview": name}
            yield {"type": "tool_result", "name": name, "result": result}
            self._append_tool(name, result)
            return

        yield {"type": "tool", "name": name, "args": args,
               "preview": tools.describe(name, args), "result": None}

        kind = spec["kind"]
        if not tools.allowed_in_mode(spec, self.mode):
            result = (f"REFUSED: '{name}' changes things and this session is "
                      "in PLAN mode, which may only read. Ask the user to "
                      "switch mode, or just describe your plan.")
            yield {"type": "notice", "text": result}
        elif kind == "edit":
            result = yield from self._handle_edit(spec, name, args)
        else:
            result = self._handle_action(spec, name, args)

        if isinstance(result, dict):
            text_result, image = result.get("text", ""), result.get("image")
            if image:
                yield {"type": "image", "path": str(image),
                       "name": name}
            result = text_result
        yield {"type": "tool_result", "name": name, "result": result}
        self._append_tool(name, result)

    def _handle_edit(self, spec, name, args):
        """A file change: plan it, show the diff, ask, snapshot, apply."""
        planner = spec.get("planner")
        try:
            change = planner(args, self.ctx)
        except (ToolError, WorkspaceError) as exc:
            yield {"type": "notice", "text": f"rejected: {exc}"}
            return f"ERROR: {exc}"

        yield {"type": "diff", "path": change.rel, "text": change.diff(),
               "summary": change.summary(), "created": change.created}

        request = {"kind": "write", "tool": name, "path": change.rel,
                   "summary": change.summary(), "diff": change.diff(),
                   "created": change.created,
                   "critical": bool(spec.get("critical"))}
        if not self._allowed(spec, request):
            return ("The user did NOT approve this change, so the file was "
                    "left untouched. Ask them what to do instead.")

        self.checkpoints.snapshot(change.path, reason=name)
        result = change.apply()
        yield {"type": "applied", "path": change.rel,
               "ok": result.startswith("OK:")}
        return result

    def _handle_action(self, spec, name, args):
        """A read, a file operation, or a command."""
        request = {"kind": spec["kind"], "tool": name,
                   "summary": tools.describe(name, args),
                   "critical": bool(spec.get("critical"))}
        if spec["kind"] == "exec":
            request["command"] = str(args.get("command") or args.get("code")
                                     or "")[:400]
            request["risk"] = tools.coding.command_risk(request["command"])
        if not self._allowed(spec, request):
            if spec["kind"] == "read":
                return f"ERROR: '{name}' is not available in this mode."
            return ("The user did NOT approve this, so nothing was done. Do "
                    "not repeat it; find another way or explain.")

        text_result, image = tools.execute(spec, args, self.ctx)
        if image:
            return {"text": text_result, "image": image}
        return text_result

    def _should_nudge(self, step, content):
        """Did the model talk about working instead of working?

        Only early in a turn, only a couple of times, and only when the
        reply looks like thinking out loud -- so a real answer is never
        interrupted.
        """
        if self._nudges >= config.MAX_NUDGES:
            return False
        if step > config.NUDGE_AFTER_STEP:
            return False
        text = (content or "").strip()
        if not text:
            return False
        low = text.lower()
        return (len(text) > 350
                or any(marker in low for marker in _PLAN_MARKERS))

    def _allowed(self, spec, request):
        """Mode + critical flag decide whether a human must approve."""
        if not tools.needs_approval(spec, self.mode):
            return True
        if self.confirm_handler is None:
            return False
        try:
            return bool(self.confirm_handler(request))
        except Exception:  # noqa: BLE001 - a broken dialog means "no"
            return False

    def _append_tool(self, name, result):
        self.session.messages.append({
            "role": "tool",
            "content": str(result)[:config.MAX_OUTPUT_CHARS],
            "tool_name": name,
        })

    # -------------------------------------------------------- long chats

    def _compact_if_needed(self):
        """Summarise the oldest half when the chat grows too long.

        Keeps the NEWEST messages up to a token budget rather than a
        fixed count: one tool result can be 4000 characters, so "keep
        the last six messages" could still overflow the window.
        """
        if self._context_tokens() < config.COMPACT_AT_TOKENS:
            return None
        system = self.session.messages[0]
        tail = self.session.messages[1:]
        if len(tail) < 2:
            return None

        budget = int(config.COMPACT_AT_TOKENS * 0.45)
        keep = []
        used = 0
        for message in reversed(tail):
            size = _estimate([message])
            if keep and used + size > budget:
                break
            keep.append(message)
            used += size
        keep.reverse()
        if not keep:                      # never drop the current turn
            keep = tail[-1:]
        middle = tail[:len(tail) - len(keep)]
        if not middle:
            return None

        summary = self._summarise(middle)
        self.session.messages = [system, {
            "role": "user",
            "content": "[Session so far, summarised]\n" + summary,
        }] + keep
        return "older messages were summarised to keep the chat fast"

    def _context_tokens(self):
        """Everything that goes to the model: schemas + prompt + transcript.

        The loaded tool schemas are part of the request, so they have to
        be part of the budget. Leaving them out (as this did at first)
        let the real request grow past the context window, and Ollama
        then quietly drops the oldest messages -- which looks exactly
        like the model "forgetting" the task halfway through.
        """
        schema_json = json.dumps(tools.schemas(self.groups))
        return (_estimate(self.session.messages)
                + len(schema_json) // config.CHARS_PER_TOKEN)

    def _context_warning(self):
        """One-off warning when the loaded tools barely fit the window."""
        if self._warned_context:
            return None
        schema = len(json.dumps(tools.schemas(self.groups))) \
            // config.CHARS_PER_TOKEN
        prompt = len(self._prompt or "") // config.CHARS_PER_TOKEN
        if schema + prompt > config.NUM_CTX * 0.7:
            self._warned_context = True
            return (f"heads up: the loaded tools need about "
                    f"{schema + prompt} of the {config.NUM_CTX} context "
                    "tokens. Load fewer groups (list_tools shows them) or "
                    "raise ZYRO_AGENT_CTX.")
        return None

    def _summarise(self, messages):
        """Ask the model for a short progress note (fallback: a list)."""
        lines = []
        for message in messages:
            role = message.get("role")
            if role == "user":
                lines.append("USER: " + str(message.get("content", ""))[:300])
            elif role == "assistant":
                for call in message.get("tool_calls") or []:
                    name = (call.get("function", {}) or {}).get("name", "?")
                    lines.append("TOOL: " + str(name))
                if message.get("content"):
                    lines.append("SAID: " + str(message["content"])[:200])
            elif role == "tool":
                lines.append("RESULT: " + str(message.get("content", ""))[:200])
        body = "\n".join(lines)[:4000]
        ask = [{"role": "user", "content":
                "Summarise this working session in under 120 words. List the "
                "files changed, the decisions made and the work still "
                "unfinished. Plain text, no headings.\n\n" + body}]
        try:
            summary = llm.complete(ask, model=self.model, num_predict=256)
        except llm.LLMError:
            summary = ""
        if summary:
            return summary
        names = [line.split(": ", 1)[1] for line in lines
                 if line.startswith("TOOL: ")]
        return ("tools used: " + ", ".join(names[:20])) if names \
            else "(nothing yet)"

    # ------------------------------------------------------------- misc

    def undo(self):
        """Undo the newest file change. Returns a human message."""
        result = self.checkpoints.undo_last()
        if result is None:
            return "nothing to undo in this session"
        path, detail = result
        return f"{detail}: {self.workspace.rel(path)}"

    def journal(self, limit=10):
        """What the session changed besides file content."""
        return self.checkpoints.journal_entries(limit)

    def cancel(self):
        self.cancelled = True

    def _save(self):
        self.session.save()


def _read_call(call):
    """Pull (name, arguments) out of an Ollama tool call or a dict."""
    function = getattr(call, "function", None)
    if function is None and isinstance(call, dict):
        function = call.get("function", {})
    if isinstance(function, dict):
        name = function.get("name", "")
        args = function.get("arguments", {})
    else:
        name = getattr(function, "name", "")
        args = getattr(function, "arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return name, args


def _estimate(messages):
    """Rough token estimate for the transcript."""
    total = 0
    for message in messages:
        body = message.get("content")
        if isinstance(body, str):
            total += len(body) // config.CHARS_PER_TOKEN
        for call in message.get("tool_calls") or []:
            total += len(json.dumps(_call_dict(call))) // config.CHARS_PER_TOKEN
    return total


def _call_dict(call):
    if isinstance(call, dict):
        return call
    function = getattr(call, "function", None)
    return {"name": getattr(function, "name", ""),
            "arguments": str(getattr(function, "arguments", {}))}

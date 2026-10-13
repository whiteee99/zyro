"""The model connection: free local Ollama, with real tool calling.

Ollama can return structured tool calls instead of free text, which is
far more reliable than asking a small model to print JSON by hand.
This module wraps that in a generator of small events, so a terminal
and a Tkinter window can both stream it.

Nothing here talks to the internet: the model runs on this laptop.
"""

from ollama import chat

from . import config


class LLMError(Exception):
    """The model could not be reached, or the call failed."""


def stream(messages, tools=None, model=None, think=None, num_ctx=None,
           num_predict=None, temperature=0.8):
    """Run one model step and yield events as they arrive.

    temperature 0.8 is Ollama's own default for qwen3 and was measured
    to be both FASTER and more decisive than a low setting: at 0.2 the
    same request took 120s and 1215 tokens instead of 30s and 191.

    Events:
      {"kind": "text",     "text": str}      visible answer text
      {"kind": "thinking", "text": str}      qwen3 reasoning (optional)
      {"kind": "done", "content": str, "tool_calls": [...], "stats": {...}}
    """
    model = model or config.MODEL
    options = {
        "num_ctx": num_ctx or config.NUM_CTX,
        "num_predict": num_predict or config.NUM_PREDICT,
        "temperature": temperature,
    }
    if think is None:
        think = config.THINK
    kwargs = {"model": model, "messages": messages, "stream": True,
              "options": options, "think": think}
    if tools:
        kwargs["tools"] = tools

    try:
        yield from _run(kwargs)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 - translate every failure
        # Older Ollama builds reject the "think" switch for some models.
        if "think" in str(exc).lower():
            kwargs.pop("think", None)
            try:
                yield from _run(kwargs)
                return
            except Exception as exc2:  # noqa: BLE001
                raise LLMError(_explain(exc2)) from exc2
        raise LLMError(_explain(exc)) from exc


def _run(kwargs):
    """The actual streaming loop. Raises whatever Ollama raises."""
    text_parts = []
    thinking_parts = []
    tool_calls = []
    stats = {}
    for part in chat(**kwargs):
        message = getattr(part, "message", None)
        if message is not None:
            thinking = getattr(message, "thinking", None)
            if thinking:
                thinking_parts.append(thinking)
                yield {"kind": "thinking", "text": thinking}
            content = getattr(message, "content", None)
            if content:
                text_parts.append(content)
                yield {"kind": "text", "text": content}
            calls = getattr(message, "tool_calls", None)
            if calls:
                tool_calls.extend(calls)
        if getattr(part, "done", False):
            stats = {
                "eval_count": getattr(part, "eval_count", 0) or 0,
                "eval_duration": getattr(part, "eval_duration", 0) or 0,
                "prompt_eval_count": getattr(part, "prompt_eval_count", 0) or 0,
                "total_duration": getattr(part, "total_duration", 0) or 0,
            }
    yield {"kind": "done", "content": "".join(text_parts),
           "thinking": "".join(thinking_parts), "tool_calls": tool_calls,
           "stats": stats}


def complete(messages, model=None, num_ctx=None, num_predict=None,
             think=False, temperature=0.2):
    """One non-streaming answer (used for summaries). Returns text."""
    chunks = []
    for event in stream(messages, tools=None, model=model, think=think,
                        num_ctx=num_ctx, num_predict=num_predict,
                        temperature=temperature):
        if event["kind"] == "text":
            chunks.append(event["text"])
    return "".join(chunks).strip()


def _explain(exc):
    """Turn a raw client error into something a human can act on."""
    text = str(exc)
    low = text.lower()
    if "connection" in low or "refused" in low or "connect" in low:
        return ("cannot reach Ollama. Start the Ollama app (it sits in the "
                "tray) and try again. [" + text[:200] + "]")
    if "not found" in low or "no such model" in low:
        return ("that model is not installed. Run: ollama pull "
                + config.MODEL + "  [" + text[:200] + "]")
    return text[:400]


def stats_line(stats):
    """'128 tokens, 12.4 tok/s' for the status line (may be empty)."""
    count = stats.get("eval_count") or 0
    duration = stats.get("eval_duration") or 0
    if not count or not duration:
        return ""
    return f"{count} tokens, {count / (duration / 1e9):.1f} tok/s"

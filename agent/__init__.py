"""ZYRO's coding agent: a local, free, ZCode-style agent.

Nothing in here needs the internet or a paid API. The brain is a
local Ollama model (qwen3:4b by default), the hands are the tools in
this package, and every file change is shown as a diff before it is
applied and snapshotted so it can be undone.

Start here:

    venv\\Scripts\\python -m agent.cli --root D:\\myproject

or from Python:

    from agent.loop import Agent
    from agent.workspace import Workspace, trust
    trust(r"D:\\myproject")
    agent = Agent(Workspace(r"D:\\myproject"), mode="ask")
    for event in agent.send("add a hello() function to utils.py"):
        ...
"""

__all__ = ["config", "diff", "llm", "loop", "session", "tools", "workspace",
           "checkpoint"]

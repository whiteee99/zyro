# ZYRO CODE — a local coding agent

ZYRO can now do what ZCode / Claude Code / Cursor do: work inside a
project folder, read and change files, run commands, check its own
work — **free, offline, unlimited**, on the local Ollama model.

Everything here is `agent/` plus one extra file in the window
(`gui_agent.py`). It needs no API key, no subscription and no internet.

---

## Start it

**Terminal (fastest):**

```bat
cd /d D:\zyro
venv\Scripts\python.exe -m agent.cli --root D:\some\project
```

**The window:** open ZYRO as usual, click **⌨ CODE** in the top-right
corner, click the folder button, and pick a project folder. The first
time you pick a folder, ZYRO asks whether to trust it.

Useful switches:

```bat
python -m agent.cli --check                 is Ollama ready?
python -m agent.cli --list                  trusted folders + sessions
python -m agent.cli -r D:\proj -m ask "run the tests and fix what fails"
python -m agent.cli --resume last           continue the last session
```

`--mode` (or the mode buttons in the window) chooses how much ZYRO may
do on its own:

| mode | file changes | commands | notes |
|---|---|---|---|
| `plan` | never | never | read-only; it investigates and proposes a plan |
| `ask` | asks, with the diff | asks | the safe default |
| `auto-edit` | applies them (you still see the diff) | asks | good for long editing sessions |
| `full-auto` | applies them | runs them | **critical** actions still ask |

**Critical actions always ask, in every mode**: delete a file or
folder, empty the Recycle Bin, kill a process, shut down / restart /
sleep, and download a video. That rule cannot be switched off.

---

## What it can do — 74 tools

Only the project tools load at the start (a 4B model drowns in 74
schemas at once); the rest load when the request needs them, either
automatically or by the model calling `enable_tools`.

**Project (always loaded)**

- `list_files`, `read_file` (with line numbers), `write_file`,
  `create_file` (never overwrites), `append_file`, `edit_file`
- `search_files` (by name), `search_in_files` (text/regEx)
- `run_command`, `run_python`
- `remember`, `recall`, `suggest_model`, `switch_model`
- `enable_tools`, `list_tools`

**Files (20)** — `file_info`, `create_folder`, `rename_file`,
`rename_folder`, `move_file`, `copy_file`, `zip_files`, `unzip`,
`find_duplicates`, `largest_files`, `recent_files`, `delete_file`*,
`delete_folder`*, `empty_recycle_bin`*

**PC / system (17)** — `system_info`, `cpu_ram_usage`,
`battery_status`, `disk_usage`, `uptime`, `network_info`,
`list_processes`, `set_volume`, `mute_toggle`, `set_brightness`,
`clipboard_read`, `clipboard_write`, `notify` (Windows toast),
`set_wallpaper`, `open_settings`, `kill_process`*, `power_action`*

**Web & downloads (16)** — `web_search` (no API key needed),
`read_site`, `open_site`, `get_weather`, `get_news`, `download_file`
(keeps the server's own file name), `download_video`*, `yt_search`,
`browser_open`, `browser_click`, `browser_type`, `browser_scroll`,
`browser_back`, `browser_press_key`, `browser_get_text`,
`browser_close`

**Media (3)** — `screenshot`, `media_key`, `play_music`

**Vision (2)** — `look_screen`, `look_image` (answered by the local
`moondream` model, then handed to the main model as text)

**Time & lists (6)** — `set_timer`, `set_alarm`, `set_reminder`,
`todo_add`, `todo_list`, `todo_done`

\* = critical: always asks first.

---

## How it keeps you safe

1. **One trusted folder.** Every path goes through a resolver that
   refuses `..`, other drives, symlink escapes and secrets files
   (`.env`, `id_rsa`, …). Nothing outside the chosen folder is touched.
2. **Diff before write.** Every change is shown as a unified diff and,
   in `ask` mode, waits for your yes.
3. **Undo.** Every file is snapshotted before it changes, so `:undo`
   (or the UNDO button) puts it back — even deleting a file the agent
   created. Structural moves are recorded in a journal.
4. **Recycle Bin, not shredder.** Deletes go to the Windows Recycle
   Bin, so a mistake is recoverable.
5. **Critical tools always ask**, whatever the mode.
6. **Honest failures.** Every tool returns a message instead of
   raising, and the loop stops with a clear error if Ollama dies.

---

## Settings

Environment variables (set them before starting ZYRO):

| variable | default | what it does |
|---|---|---|
| `ZYRO_AGENT_MODEL` | `qwen3:4b` | which Ollama model to use |
| `ZYRO_AGENT_CTX` | `8192` | context window (see the speed note below) |
| `ZYRO_AGENT_PREDICT` | `1536` | safety cap on tokens per step |
| `ZYRO_AGENT_THINK` | `0` | `1` = let qwen3 think first (3× slower) |
| `ZYRO_AGENT_STEPS` | `24` | max tool rounds per request |
| `ZYRO_AGENT_COMPACT` | `6000` | context budget (schemas + prompt + chat) |

### The context budget counts everything

The loaded tool schemas are ~2,500 tokens on their own, and they are
part of every request. So the budget above counts **schemas + system
prompt + transcript**, and when it is reached the oldest half of the
conversation is summarised into a short note. Keeping the newest
messages is done by token budget, not by message count — one `read_file`
result can be 4,000 characters, so "keep the last 6 messages" could
still overflow the window. If the loaded tools need more than 70% of
`ZYRO_AGENT_CTX`, ZYRO says so once at the start of a turn instead of
quietly losing messages.

### Ollama lifecycle

The coding agent starts Ollama for you if it is not running, and it
applies an **ownership rule**: an Ollama this run started is stopped
again when the run ends; an Ollama that was already running (for
example, because your ZYRO window is open) is left alone. That way the
terminal agent can never take the window's brain away with it.

### Speed: two settings that actually matter

These were measured on this laptop, not guessed:

* **`ZYRO_AGENT_CTX=4096` makes it roughly twice as fast.** At 8192,
  `ollama ps` reports the model running **45% on CPU** — the context
  plus a 2.5 GB model no longer fits the 4 GB card. At 4096 it stays
  fully on the GPU. Set it if you care more about speed than long
  context.
* **Do not lower `ZYRO_AGENT_PREDICT` much below 1536.** The model
  often spends 200–2000 tokens working out what to do *before* it
  emits the tool call. A cap of 512 cut it off mid-thought and it
  never called a tool at all — that looked exactly like "the model is
  too stupid", and it was really the cap.
* **`temperature` stays at 0.8** (Ollama's own default). At 0.2 the
  same request took 120 s and 1215 tokens instead of 30 s and 191.

A full "create a file, run it, tell me the output" task takes about
2–4 minutes on this machine at 8192 context, and each step prints as
it happens so you can watch it work.

Where things are kept (all inside `memory\agent\`): `trusted.json`
(folders you allowed), `sessions\` (full transcripts, resumable),
`checkpoints\` (undo snapshots), `facts.json` (remembered facts),
`todos.json`, `reminders.json`.

---

## Tests

```bat
venv\Scripts\python.exe test_agent.py          :: 85 checks, offline, no model
venv\Scripts\python.exe test_agent.py --live   :: also runs a real request
```

The offline suite really creates, edits, zips, moves and undoes files
in a throwaway folder, and checks the whole approval matrix — that
`plan` cannot write, that a declined change never lands, and that a
critical tool still asks in `full-auto`. It never touches your desktop
(no volume, wallpaper, clipboard or shutdown tests).

---

## Honest limits

The harness is ZCode-shaped; the brain is a 4B model on a 4 GB GPU.
It is good at: reading code, small single-file edits, running commands
and reacting to errors, file tidying, searching, small scripts. It is
weak at: large multi-file refactors, long autonomous chains, and
anything needing more than ~7k tokens of context. Expect ~10-20
seconds per step. If you ever get a bigger machine (or a cheap API
key), set `ZYRO_AGENT_MODEL` and the same agent gets smarter with no
code change.

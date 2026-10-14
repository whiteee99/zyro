# ZYRO — what it can do (offline vs online), and what was wrong

Everything below was checked by **running it**, on this PC, on
2026-10-14:

| Suite | Result |
|---|---|
| `test_all_tools.py --twice` (every agent tool, twice) | **76 checked: 70 OK, 0 failed, 6 not run** |
| `test_agent.py` | **101 passed, 0 failed** |
| `test_gui.py` | **32 passed, 0 failed** |
| `test_ollama_lifecycle.py` | **18 passed, 0 failed** |
| `test_phase9.py` (original ZYRO) | **37 passed, 0 failed** |

**The short version: ZYRO works fully offline.** Only looking things up
on the web, downloading, and browsing need the internet.

---

## 1. Completely offline (55 tools + the whole interface)

### Talking to it
| Feature | Notes |
|---|---|
| Chat in the window | `qwen3:1.7b` (fast) or `qwen3:4b` (better, default for CODE) |
| Chat in the terminal | `venv\Scripts\python.exe main.py` |
| CODE mode | click **⌨ CODE**, pick a folder |
| Agent in the terminal | `python -m agent.cli --root D:\project` |
| Sessions | saved and resumable (`--resume last`) |
| Token budget | lifetime counter, warns at 80% / 95% |
| Skills | daily-briefing, file-organizer, gaming-session, video-music |
| Model advice | "which model is best for my PC?", switching between installed models |

### Writing code — CODE mode (8 tools)
`list_files` · `read_file` (line numbers) · `write_file` · `create_file`
(never overwrites) · `append_file` · `edit_file` · `run_command` ·
`run_python`
Plus diff-before-every-write, **UNDO**, trusted folders, and PLAN / ASK /
EDIT / AUTO approval modes.

### Files (14)
`file_info` · `largest_files` · `recent_files` · `find_duplicates` ·
`create_folder` · `rename_file` · `rename_folder` · `move_file` ·
`copy_file` · `zip_files` · `unzip` · `delete_file`* · `delete_folder`* ·
`empty_recycle_bin`*

\* deletes go to the **Recycle Bin** (recoverable). `empty_recycle_bin`
is the only irreversible tool ZYRO has, and it always asks first.

### Searching (2)
`search_files` (by name) · `search_in_files` (text/regex inside files)

### The PC (17)
`system_info` · `cpu_ram_usage` · `battery_status` · `disk_usage` ·
`uptime` · `network_info` · `list_processes` · `set_volume` ·
`mute_toggle` · `set_brightness` · `clipboard_read` · `clipboard_write` ·
`notify` (Windows toast) · `set_wallpaper` · `open_settings` ·
`kill_process`* · `power_action`* (lock/sleep/restart/shutdown)

### Time and lists (6)
`set_timer` · `set_alarm` (daily) · `set_reminder` · `todo_add` ·
`todo_list` · `todo_done` — each fires a real Windows notification.
The audit proved this end to end: a 1-minute reminder was set and it
fired on time.

### Media and vision (5)
`screenshot` · `media_key` · `play_music` · **`look_screen`** ·
**`look_image`**

Vision is **offline**: screenshots are described by the local
`moondream` model, then handed to the main model as text. Nothing goes
to a cloud vision service.

### Memory (4)
`remember` · `recall` · `suggest_model` · `switch_model`

### The interface
Dark low-contrast theme · chat bubbles · sidebar (skills + quick tools) ·
AUTO switch · tray icon · **Ctrl+Alt+Z** hotkey · token meter · input
box · send button · resize-safe layout.

---

## 2. Needs the internet (15 tools)

| Feature | What it does |
|---|---|
| `web_search` | real web search: titles, snippets, links (Bing RSS, no API key) |
| `read_site` | reads a page's text without opening a browser |
| `open_site` | opens a site in your own browser |
| `get_weather` | current weather + 3-day forecast (wttr.in, no key) |
| `get_news` | headlines about a topic (Google News RSS, no key) |
| `download_file` | downloads a public file, keeping the server's file name |
| `download_video`* | YouTube and 1000+ sites as mp4 or mp3 (yt-dlp) |
| `yt_search` | searches YouTube and lists results |
| `browser_open` / `_click` / `_type` / `_scroll` / `_back` / `_press_key` / `_get_text` / `_close` | drives a real visible Chromium |

\* always asks first.

**Chat-mode extras that also need internet:** `winget_search`,
`winget_install`, `update_ytdlp`, and `ollama pull <model>`.

**Models are offline once downloaded** — yours live in
`D:\ollama-models` and work with the network cable out.

---

## 3. Errors found by this audit — all fixed

| # | What was wrong | Evidence | Fix |
|---|---|---|---|
| 1 | **The window had no input box.** `ScrolledText` asks for ~724 px of height, Tk hands out space in packing order, so the input row packed after it was squeezed to zero. It only worked if you maximised the window. **This shipped in the very first commit.** | `input row mapped=0 h=1` | the bottom strip is reserved before the chat fills the rest; `test_gui.py` guards it at two sizes |
| 2 | **`web_search` returned no results.** DuckDuckGo answers bots with a warning page. | 0 result links vs **10 clean ones from Bing** | Bing RSS first, DuckDuckGo as fallback |
| 3 | **The CLI crashed on emoji.** A YouTube title contains ⭐ → `UnicodeEncodeError` killed the session. | traceback in the audit | both CLIs switch output to UTF-8 with replacement |
| 4 | **`read_site` failed with a timeout** on api.github.com while the same URL answered in 0.7 s a minute later. | audit log | one automatic retry |
| 5 | **A daemon started without `OLLAMA_MODELS` finds no models** — after moving models to D:, anything that started Ollama from an environment without that setting reported zero models. | lifecycle suite 17/18 | the setting is read from Windows and passed to the daemon |
| 6 | **Second `browser_open` always failed**: "Target page, context or browser has been closed". Stopping the Playwright driver in `browser_close` made it impossible to restart in the same process. | 5 audit failures | the driver now stays alive until ZYRO exits; open→close→open→close→open verified |
| 7 | **The vision model hogged the GPU.** moondream stayed resident for 5 minutes after a look, so the next main-model call failed with "CUDA error: out of memory". | `ollama ps` after a look | `keep_alive=0` — moondream is released the moment it answers (verified: `ollama ps` is empty right after) |
| 8 | **Orphaned `llama-server.exe` runners held the whole GPU.** Eight leftovers from crashed loads were holding **2.9 GB of the 4 GB card**; every new model then failed with OOM. | `nvidia-smi`: 985 MiB free → 3938 MiB after clearing | ZYRO's shutdown now kills `llama-server.exe` too, and the lifecycle test checks it |
| 9 | Earlier: `num_predict=512` / `temperature=0.2` stopped the model from ever calling a tool (looked like "the model is stupid") | 3 wasted live runs | 1536 / 0.8, verified end to end |

**If a model ever refuses to load with "out of memory"**, the cause is
usually leftover runners: close ZYRO (which now cleans them), or run
`taskkill /f /im llama-server.exe`.

---

## 4. Model comparison (measured today, GPU free)

| Model | Size | Speed | Tool calls? |
|---|---|---|---|
| `qwen3:4b` (default) | 2.5 GB | 13 tok/s | **yes** — called `create_file` correctly |
| `qwen2.5-coder:3b` (downloaded today) | 1.9 GB | 62 tok/s | **no** — wrote prose instead of calling the tool, twice |
| `qwen3:1.7b` | 1.4 GB | fast | weak; fine for chat, not for CODE |
| `moondream` | 1.7 GB | — | vision only |

**qwen2.5-coder:3b is fast but does not do agent work**, so the default
stays `qwen3:4b`. Remove it with `ollama rm qwen2.5-coder:3b` if you
want the 1.9 GB back.

---

## 5. Deliberately not run by the audit

| Tool | Why |
|---|---|
| `power_action` | would lock / sleep / shut down this PC (argument checking verified) |
| `empty_recycle_bin` | would permanently delete your Recycle Bin |
| `media_key` | would have pressed play/pause on your music |
| `play_music` | would have opened a player |
| `open_site` | would have opened a tab in your own browser |
| `download_video` (large) | tested with a 1 MB clip instead |

The audit restores everything it touches (volume, brightness, wallpaper,
clipboard) and deletes only its own throwaway files.

---

## 6. Known limits (not errors)

* A 4B model is a 4B model: good at single-file edits, reading code,
  running commands, reacting to errors; weak at large multi-file
  refactors and long autonomous chains.
* ~10–20 s per agent step; a small task takes minutes.
* At `ZYRO_AGENT_CTX=8192` the model partly runs on the CPU (33–45%
  measured) because it does not fit the 4 GB card. `ZYRO_AGENT_CTX=4096`
  is about twice as fast but leaves less room for conversation.
* **Run one model at a time.** Loading a second model while another is
  resident can fail with OOM on this GPU.
* Timers and reminders only fire while ZYRO is running.
* `find_duplicates` hashes files up to 512 MB fully; larger ones are
  compared by first + last megabyte.

---

## 7. Check it yourself

```bat
cd /d D:\zyro
venv\Scripts\python.exe test_all_tools.py --twice   :: every tool, twice
venv\Scripts\python.exe test_agent.py               :: agent engine   (101)
venv\Scripts\python.exe test_gui.py                 :: the window      (32)
venv\Scripts\python.exe test_ollama_lifecycle.py    :: Ollama start/stop (18)
venv\Scripts\python.exe test_phase9.py              :: original ZYRO   (37)
```

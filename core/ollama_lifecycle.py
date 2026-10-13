"""Starting and stopping Ollama together with ZYRO.

Ollama is two Windows processes:

    ollama.exe      the daemon that serves http://localhost:11434
    ollama app.exe  the tray icon (note the SPACE in the name)

On a 7.8 GB laptop those two are worth ~35 MB of RAM plus whatever
model is loaded, and nothing keeps them alive for the user after ZYRO
is closed. So: ZYRO starts the daemon when it needs a brain, and stops
both processes again on exit (KILL_OLLAMA_ON_EXIT in main.py).

Only the standard library is used here -- urllib for the health check
and subprocess for the two shell actions -- so this adds no dependency.
"""

import os
import subprocess
import time
import urllib.error
import urllib.request

# Where the daemon answers. This is Ollama's own default.
API_BASE = "http://localhost:11434"
HEALTH_URL = API_BASE + "/api/tags"

# A health check must be cheap: Ollama either answers at once or it is
# not there.
PROBE_TIMEOUT = 1.0
POLL_SECONDS = 0.5

# Kill the tray app FIRST: while it lives it can restart the daemon.
KILL_ORDER = ("ollama app.exe", "ollama.exe")

# Windows installs Ollama per user, so PATH may be missing it when ZYRO
# is started from a shortcut or the tray.
FALLBACK_EXE = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")


def is_ollama_running():
    """True when the Ollama API answers. Never raises."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=PROBE_TIMEOUT):
            return True
    except Exception:          # noqa: BLE001 - any failure means "not up"
        return False


def start_ollama(timeout=15, grace=20):
    """Make sure the daemon is up. True if the API answers afterwards.

    Does nothing when Ollama is already serving, so a user who started
    it themselves never gets a second daemon.

    timeout: how long to wait for the API to answer.
    grace:   extra seconds to keep waiting WHEN a daemon process is
             clearly running. Measured on this laptop: a cold start
             answers in about 8-9 seconds, but the first start after
             killing Ollama's own tray app can take longer. Without the
             grace we would report "failed" while Ollama was still
             coming up, and ZYRO would disable chat for no reason.
    """
    if is_ollama_running():
        return True
    command = _daemon_command()
    if command is None:
        return False
    try:
        subprocess.Popen(
            command,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=_daemon_env(),
        )
    except (OSError, ValueError):
        return False
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        if is_ollama_running():
            return True
        time.sleep(POLL_SECONDS)
    hard_stop = time.time() + max(0.0, grace)
    while time.time() < hard_stop:
        if is_ollama_running():
            return True
        if not daemon_process_running():
            return False          # nothing is starting: stop waiting
        time.sleep(POLL_SECONDS)
    return is_ollama_running()


def _daemon_env():
    """The environment a daemon we start should inherit.

    OLLAMA_MODELS matters: when the owner keeps the models on another
    drive (D:, to save space on C:), a daemon started WITHOUT that
    setting looks in the default C: folder, finds nothing, and reports
    no models at all -- which looks like "Ollama is broken". ZYRO may
    itself have been launched from a context that lacks the variable
    (a shortcut made before the change, a script, a service), so it is
    read from the owner's environment settings and passed on.
    """
    env = os.environ.copy()
    if env.get("OLLAMA_MODELS"):
        return env
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "OLLAMA_MODELS")
        if isinstance(value, str) and value.strip():
            env["OLLAMA_MODELS"] = value.strip()
    except (OSError, ImportError, ValueError):
        pass
    return env


def daemon_process_running():
    """True when an "ollama.exe" process exists (used during slow starts)."""
    try:
        result = subprocess.run(
            ["tasklist", "/fi", "imagename eq ollama.exe", "/fo", "csv", "/nh"],
            capture_output=True, text=True, errors="replace", timeout=10)
    except Exception:              # noqa: BLE001 - a failed check is "no"
        return False
    return "ollama.exe" in (result.stdout or "").lower()


def stop_ollama():
    """Kill the tray app and the daemon. Never raises.

    Returns {"stopped": [...], "not_running": [...], "errors": [...]}
    so callers (and the tests) can report exactly what happened.
    """
    report = {"stopped": [], "not_running": [], "errors": []}
    for image in KILL_ORDER:
        try:
            result = subprocess.run(
                ["taskkill", "/f", "/im", image],
                capture_output=True, text=True, errors="replace",
                timeout=20)
        except Exception as exc:            # noqa: BLE001 - report, do not raise
            report["errors"].append(f"{image}: {exc}")
            continue
        if result.returncode == 0:
            report["stopped"].append(image)
        else:
            # 128 = "process not found": it was already gone, which is fine.
            output = ((result.stdout or "") + (result.stderr or "")).lower()
            if result.returncode == 128 or "not found" in output \
                    or "no tasks" in output:
                report["not_running"].append(image)
            else:
                report["errors"].append(
                    f"{image}: {(result.stderr or result.stdout or '').strip()}")
    return report


def shutdown(enabled=True):
    """Stop Ollama only when the owner asked for it.

    Wired into atexit and into the window's close handler, so every way
    of leaving ZYRO honours the same flag.
    """
    if not enabled:
        return None
    return stop_ollama()


def describe(report):
    """One readable line about a stop_ollama() report."""
    if report is None:
        return "Ollama left running (KILL_OLLAMA_ON_EXIT is False)"
    stopped = ", ".join(report["stopped"]) or "nothing"
    parts = [f"stopped: {stopped}"]
    if report["not_running"]:
        parts.append("already gone: " + ", ".join(report["not_running"]))
    if report["errors"]:
        parts.append("errors: " + "; ".join(report["errors"]))
    return "; ".join(parts)


def _daemon_command():
    """['ollama', 'serve'], or the per-user install path, or None."""
    from shutil import which
    found = which("ollama")
    if found:
        return [found, "serve"]
    if FALLBACK_EXE and os.path.isfile(FALLBACK_EXE):
        return [FALLBACK_EXE, "serve"]
    return None

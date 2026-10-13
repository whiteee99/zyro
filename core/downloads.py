r"""ZYRO's download & software tools (Phase 9).

download_file saves any public http/https file into D:\zyro\downloads.
download_video pulls a video (or just its audio) with yt-dlp into
D:\zyro\downloads\videos. winget_search / winget_install look up and
install Windows software through winget.

Safety rules enforced here:
  - Only http/https URLs are accepted.
  - Every host is resolved BEFORE connecting and every resolved IP
    must be PUBLIC -- loopback, private, link-local, reserved and
    multicast addresses are refused (no requests to localhost or the
    internal network, cloud metadata included).
  - The connection is pinned to the validated IP, so a hostile DNS
    answer cannot re-point the request at an internal machine after
    the check (DNS rebinding).
  - Redirects must pass the very same public-URL check.
  - Saved files are forced inside D:\zyro (and its downloads folders)
    by resolved-path comparison, no matter what the URL or 'name'
    contained. Nothing is ever written to another drive.

Every function returns a plain string and catches its own errors, so
ZYRO never crashes.
"""

import http.client
import ipaddress
import os
import re
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from core import paths

# Everything ZYRO downloads lives inside the install folder.
DOWNLOAD_DIR = paths.DOWNLOAD_DIR
VIDEO_DIR = paths.VIDEO_DIR

# One download may not exceed this (bytes) -- 4 GB.
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024 * 1024

# How much tool output may come back to the model.
MAX_OUTPUT_CHARS = 2500

# Portable ffmpeg kept in <install>\tools (downloaded, never installed).
FFMPEG_DIR = paths.FFMPEG_DIR

# A newer yt-dlp.exe can be dropped into tools (update_ytdlp); it is
# preferred over the bundled module because it can be refreshed.
YTDLP_EXE = paths.PROJECT_ROOT / "tools" / "yt-dlp.exe"


class SSRFBlocked(Exception):
    """Raised when a URL/host fails the public-address safety rules."""


def assert_public_host(host):
    """Resolve a host name and refuse ANY loopback, private, link-local,
    reserved, multicast or unspecified address. Returns the list of
    validated IPs. Raises SSRFBlocked otherwise."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise SSRFBlocked(f"the host '{host}' could not be resolved")
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified):
            raise SSRFBlocked(
                f"'{host}' points at a private or reserved address")
        ips.append(ip)
    if not ips:
        raise SSRFBlocked(f"the host '{host}' has no addresses")
    return ips


def check_url(url):
    """Validate a download URL BEFORE any request is made.

    Returns (ok, value): the cleaned URL when ok, an error message
    when not. Only http/https is allowed and the host must resolve to
    public addresses only."""
    if not isinstance(url, str) or not url.strip():
        return False, "ERROR: that tool needs a 'url' web address."
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return False, ("ERROR: only http:// or https:// links can be "
                       "downloaded.")
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False, "ERROR: that is not a valid web address."
    if not host:
        return False, "ERROR: that web address has no host name."
    try:
        assert_public_host(host)
    except SSRFBlocked as e:
        return False, f"ERROR: {e} (downloads there are not allowed)."
    return True, url


# ---------- pinned, redirect-safe HTTP(S) connections ----------

class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP that connects ONLY to a pre-validated public IP. The host
    name is resolved again here, so a DNS answer that changes between
    the check and the connect (DNS rebinding) cannot slip through."""

    def connect(self):
        ips = assert_public_host(self.host)
        self.sock = socket.create_connection(
            (str(ips[0]), self.port), timeout=self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS variant: connects to the validated public IP while keeping
    the real host name for the TLS handshake (certificate + SNI)."""

    def connect(self):
        ips = assert_public_host(self.host)
        self.sock = socket.create_connection(
            (str(ips[0]), self.port), timeout=self.timeout)
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=self.host)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Every redirect target must pass the same public-URL check as
    the original link, or the download is aborted."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok, _ = check_url(newurl)
        if not ok:
            raise SSRFBlocked("redirect to a non-public address refused")
        return super().redirect_request(req, fp, code, msg, headers,
                                        newurl)


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req,
                            context=self._context)


_OPENER = urllib.request.build_opener(
    _SafeRedirectHandler(), _SafeHTTPHandler(), _SafeHTTPSHandler())


def _safe_filename(name):
    """Turn any text into a safe Windows file name (or empty string):
    path separators and reserved characters become '_', leading dots
    are stripped so '..' tricks cannot survive."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name))
    name = name.lstrip(".").strip(" .")
    return name[:120]


def _ffmpeg_exe():
    """Find the portable ffmpeg.exe under D:\\zyro\\tools, or None."""
    if not FFMPEG_DIR.exists():
        return None
    for exe in FFMPEG_DIR.rglob("ffmpeg.exe"):
        return str(exe)
    return None


def _cap(text):
    """Cap long tool output so the model's context stays small."""
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + " ...[output continues]"
    return text


def _pick_name(url, name):
    """Choose a safe file name: the 'name' argument if given, else the
    last part of the URL path, else a timestamped fallback."""
    if isinstance(name, str) and name.strip():
        safe = _safe_filename(name)
        if safe:
            return safe
    tail = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
    safe = _safe_filename(tail)
    if safe:
        return safe
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"download_{stamp}.bin"


def _contained_in(folder, filename):
    """Resolve folder/filename and allow it ONLY if it lands directly
    inside that folder (no traversal, no symlinks out, no other drive)."""
    try:
        target = (folder / filename).resolve()
        base = folder.resolve()
    except (OSError, ValueError):
        return None
    if target.parent != base:
        return None
    return target


def _server_filename(header):
    """Pull a file name out of a Content-Disposition header, or None."""
    if not header or not isinstance(header, str):
        return None
    match = re.search(r"filename\*\s*=\s*([^;]+)", header, re.IGNORECASE)
    if match:
        value = match.group(1).strip().strip('"')
        if "''" in value:            # RFC 5987: charset''encoded-name
            value = value.split("''", 1)[1]
        try:
            value = unquote(value, encoding="utf-8", errors="replace")
        except Exception:
            pass
        if value:
            return value
    match = re.search(r'filename\s*=\s*"([^"]+)"', header, re.IGNORECASE) \
        or re.search(r"filename\s*=\s*([^;]+)", header, re.IGNORECASE)
    if match:
        return match.group(1).strip().strip('"') or None
    return None


def download_file(url, name=None):
    """Download one file from a public http/https link into
    D:\\zyro\\downloads. Streams in chunks with a hard size cap."""
    return download_to(url, DOWNLOAD_DIR, name)


def download_to(url, folder, name=None, use_server_name=True):
    """Download one public file into `folder`.

    The order of preference for the file name is: the caller's 'name',
    then the name the SERVER sends in Content-Disposition, then the
    last part of the URL. Whatever is chosen, the final path is forced
    to sit directly inside `folder`.
    """
    ok, value = check_url(url)
    if not ok:
        return value
    url = value
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"ERROR: could not create the folder ({e})."
    target = None
    done = 0
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ZYRO-local-assistant"})
        with _OPENER.open(req, timeout=30) as resp:
            chosen = name
            if not (isinstance(chosen, str) and chosen.strip()) \
                    and use_server_name:
                chosen = _server_filename(
                    resp.headers.get("Content-Disposition"))
            target = _contained_in(folder, _pick_name(url, chosen))
            if target is None:
                return ("ERROR: that file name is not safe, so nothing "
                        "was saved.")
            size = resp.headers.get("Content-Length")
            if size and size.isdigit() and int(size) > MAX_DOWNLOAD_BYTES:
                return "ERROR: that file is too big (the limit is 4 GB)."
            with open(target, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if done > MAX_DOWNLOAD_BYTES:
                        f.close()
                        target.unlink(missing_ok=True)
                        return ("ERROR: the download passed 4 GB and was "
                                "stopped; the partial file was deleted.")
    except SSRFBlocked as e:
        if target is not None:
            target.unlink(missing_ok=True)
        return f"ERROR: {e}; nothing was saved."
    except (urllib.error.URLError, OSError) as e:
        if target is not None:
            target.unlink(missing_ok=True)
        return f"ERROR: the download failed ({e}); partial file removed."
    mb = done / (1024 * 1024)
    size_text = f"{mb:.1f} MB" if mb >= 1 else f"{done} bytes"
    return f"OK: saved {target.name} ({size_text}) in {folder}."


def download_video(url, kind="video"):
    """Download a video (mp4) or its audio (mp3) into the install's
    downloads\\videos folder. Uses tools\\yt-dlp.exe when present
    (refreshable with update_ytdlp), else the bundled yt-dlp module;
    ffmpeg from tools\\ffmpeg is used automatically when present."""
    ok, value = check_url(url)
    if not ok:
        return value
    url = value
    try:
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"ERROR: could not create the videos folder ({e})."
    ffmpeg = _ffmpeg_exe()
    if YTDLP_EXE.is_file():  # ------------- refreshed exe mode -----
        cmd = [str(YTDLP_EXE), url, "--no-playlist", "--no-warnings",
               "--windows-filenames", "--restrict-filenames",
               "-P", str(VIDEO_DIR)]
        if ffmpeg:
            cmd += ["--ffmpeg-location", ffmpeg]
        if kind == "audio":
            cmd += ["-x", "--audio-format", "mp3"]
        elif ffmpeg:
            cmd += ["-f", "bv*+ba/b", "--merge-output-format", "mp4"]
        else:
            cmd += ["-f", "b"]
        try:
            result = subprocess.run(cmd, capture_output=True,
                                    text=True, errors="replace",
                                    timeout=3600)
        except subprocess.TimeoutExpired:
            return ("ERROR: the video download ran past one hour "
                    "and was stopped.")
        except Exception as e:
            return f"ERROR: could not start yt-dlp ({e})."
        if result.returncode != 0:
            out = ((result.stdout or "") + "\n"
                   + (result.stderr or "")).strip()
            tail = "\n".join(out.splitlines()[-4:])
            return "ERROR: yt-dlp failed:\n" + _cap(tail)
        return _newest_video_line()
    # ------------- bundled-module mode (venv or frozen exe) --------
    try:
        import yt_dlp
    except ImportError:
        return ("ERROR: yt-dlp is missing. Run: venv\\Scripts\\python "
                "-m pip install yt-dlp (or use update_ytdlp).")
    opts = {"outtmpl": str(VIDEO_DIR / "%(title).70s.%(ext)s"),
            "noplaylist": True, "windowsfilenames": True,
            "restrictfilenames": True, "quiet": True,
            "no_warnings": True}
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    if kind == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                   "preferredcodec": "mp3"}]
    elif ffmpeg:
        opts["format"] = "bv*+ba/b"
        opts["merge_output_format"] = "mp4"
    else:
        # No ffmpeg: best pre-merged single file, lower quality but
        # it still works.
        opts["format"] = "b"
    # Run in a worker thread with a hard one-hour cap, so a stuck
    # download can never freeze the assistant.
    import threading
    outcome = {}

    def work():
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            outcome["ok"] = True
        except Exception as e:  # yt-dlp raises many error types
            outcome["err"] = str(e)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(3600)
    if "ok" not in outcome:
        err = str(outcome.get("err", "the download ran past one hour "
                                     "and was stopped"))
        last = err.strip().splitlines()[-1] if err.strip() else err
        return "ERROR: yt-dlp failed: " + _cap(last)
    return _newest_video_line()


def _newest_video_line():
    """Report what actually landed in the videos folder."""
    try:
        newest = max(VIDEO_DIR.glob("*"),
                     key=lambda p: p.stat().st_mtime)
        mb = newest.stat().st_size / (1024 * 1024)
        return f"OK: saved {newest.name} ({mb:.1f} MB) in {VIDEO_DIR}."
    except OSError:
        return "OK: yt-dlp finished. Check " + str(VIDEO_DIR) + "."


# The official yt-dlp standalone exe, refreshed by update_ytdlp().
YTDLP_UPDATE_URL = ("https://github.com/yt-dlp/yt-dlp/releases/"
                    "latest/download/yt-dlp.exe")


def update_ytdlp():
    """Fetch the newest yt-dlp.exe (via the approved download_file)
    and move it into tools\\ so video downloads survive YouTube's
    endless changes."""
    result = download_file(YTDLP_UPDATE_URL, "yt-dlp.exe")
    if not result.startswith("OK:"):
        return result
    src = DOWNLOAD_DIR / "yt-dlp.exe"
    tools = (paths.PROJECT_ROOT / "tools").resolve()
    dst = (tools / "yt-dlp.exe").resolve()
    if dst.parent != tools:
        return "ERROR: unsafe yt-dlp target path."
    try:
        tools.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
    except OSError as e:
        return f"ERROR: could not move yt-dlp into tools ({e})."
    mb = dst.stat().st_size / (1024 * 1024)
    return (f"OK: yt-dlp updated ({mb:.1f} MB) in tools. Video "
            "downloads will use it from now on.")


def winget_search(query):
    """Search Windows' winget catalogue for software."""
    if not isinstance(query, str) or not query.strip():
        return "ERROR: winget_search needs a 'query' word, like \"vlc\"."
    query = query.strip()[:80]
    try:
        result = subprocess.run(
            ["winget", "search", query, "--accept-source-agreements"],
            capture_output=True, text=True, errors="replace", timeout=120)
    except FileNotFoundError:
        return "ERROR: winget is not available on this PC."
    except subprocess.TimeoutExpired:
        return "ERROR: the winget search took too long and was stopped."
    except Exception as e:
        return f"ERROR: could not search winget ({e})."
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if not text:
        return "(winget returned no output)"
    return _cap(text)


def winget_install(app_id):
    """Install one winget package by its exact Id (e.g. VideoLAN.VLC).
    Marked CRITICAL by the permission gate, so the human always
    approves it, even in AUTO mode."""
    if not isinstance(app_id, str) or not app_id.strip():
        return ("ERROR: winget_install needs an 'app_id' from "
                "winget_search, like \"VideoLAN.VLC\".")
    app_id = app_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9._+\- ]{1,120}", app_id):
        return ("ERROR: that app_id has odd characters. Use an exact Id "
                "from winget_search, like \"VideoLAN.VLC\".")
    try:
        result = subprocess.run(
            ["winget", "install", "--id", app_id, "--exact", "--silent",
             "--accept-package-agreements",
             "--accept-source-agreements"],
            capture_output=True, text=True, errors="replace", timeout=1800)
    except FileNotFoundError:
        return "ERROR: winget is not available on this PC."
    except subprocess.TimeoutExpired:
        return ("ERROR: the install ran past 30 minutes and was stopped.")
    except Exception as e:
        return f"ERROR: could not run winget ({e})."
    out = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    tail = "\n".join(out.splitlines()[-8:])
    if result.returncode != 0:
        return (f"ERROR: winget install failed (code "
                f"{result.returncode}):\n" + _cap(tail))
    return (f"OK: {app_id} installed (or was already present).\n"
            + _cap(tail))

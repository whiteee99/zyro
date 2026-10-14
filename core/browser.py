"""ZYRO's browser control (Phase 11): a REAL, visible Chromium that
the user can watch ZYRO drive live.

browser_open   -> open a page (a real window appears)
browser_click  -> click a button/link by its visible text
browser_type   -> fill a field by its placeholder or label
browser_close  -> close the browser

After every step ZYRO receives the page state (title, address and
the visible buttons/links/fields) so it can decide the next click.
Playwright's Chromium lives in <install>\\tools\\pw-browsers.
"""

from core import paths

MAX_STATE_CHARS = 2200

# Set BEFORE playwright imports: keep the browser binaries inside the
# install folder (never C:).
import atexit
import os
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                      str(paths.PROJECT_ROOT / "tools" / "pw-browsers"))

# "pw" is the Playwright driver. It is deliberately kept alive between
# browser sessions: stopping it and starting it again in the same
# process does not work (the sync API cannot be restarted), which made
# every browser_open after a browser_close fail with "Target page,
# context or browser has been closed".
_state = {"browser": None, "page": None, "pw": None}


def _describe_page():
    """Compact state of the current page for the model."""
    page = _state["page"]
    if page is None:
        return "(no page is open)"
    try:
        title = page.title()
        url = page.url
        buttons = page.eval_on_selector_all(
            "a, button, [role=button], input[type=submit]",
            "els => els.map(e => (e.innerText || e.value || '').trim())"
            "  .filter(t => t && t.length < 40)")
        fields = page.eval_on_selector_all(
            "input, textarea",
            "els => els.map(e => e.placeholder || e.name || e.type)"
            "  .filter(t => t)")
        lines = [f"page: {title}", f"address: {url}"]
        if buttons:
            lines.append("clickable: " + " | ".join(buttons[:20]))
        if fields:
            lines.append("fields: " + " | ".join(fields[:10]))
        text = "\n".join(lines)
        return text[:MAX_STATE_CHARS]
    except Exception as e:
        return f"(page state unavailable: {e})"


def _ensure_page(timeout=45000):
    """Start the browser lazily and return the active page."""
    from playwright.sync_api import sync_playwright
    if _state["page"] is not None:
        try:
            _state["page"].title()  # liveness probe
            return _state["page"]
        except Exception:
            _state["page"] = None
    # Start the driver once and keep it: it cannot be restarted later.
    if _state["pw"] is None:
        _state["pw"] = sync_playwright().start()
    if _state["browser"] is None or not _browser_alive():
        _state["browser"] = _state["pw"].chromium.launch(headless=False)
    context = _state["browser"].new_context(locale="en-US")
    _state["page"] = context.new_page()
    return _state["page"]


def _browser_alive():
    """True when the current browser object still works.

    A browser that was closed (or crashed) leaves a dead handle behind;
    asking it for a new context raises "Target page, context or browser
    has been closed", which is how every second browser_open used to
    fail.
    """
    browser = _state["browser"]
    if browser is None:
        return False
    try:
        return bool(browser.is_connected())
    except Exception:                              # noqa: BLE001
        return False


def open_url(url):
    """Open one http/https address in the visible browser."""
    if not isinstance(url, str) or not url.strip():
        return "ERROR: browser_open needs a 'url'."
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    try:
        page = _ensure_page()
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        return "OK, page loaded.\n" + _describe_page()
    except Exception as e:
        return f"ERROR: could not open the page ({e})."


def click(text):
    """Click the first clickable element containing this text."""
    if not isinstance(text, str) or not text.strip():
        return "ERROR: browser_click needs the 'text' to click."
    if _state["page"] is None:
        return "ERROR: no page is open -- use browser_open first."
    try:
        page = _state["page"]
        target = page.get_by_text(text.strip(), exact=False).first
        if target.count() == 0:
            target = page.locator(
                f"a:has-text(\"{text.strip()}\"), "
                f"button:has-text(\"{text.strip()}\")").first
        target.click(timeout=10000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        return "OK, clicked.\n" + _describe_page()
    except Exception as e:
        return f"ERROR: could not click \"{text.strip()}\" ({e})."


def fill(label, value):
    """Fill a field found by placeholder/label/name with the value."""
    if not isinstance(label, str) or not label.strip():
        return "ERROR: browser_type needs the field's 'label'."
    if not isinstance(value, str):
        return "ERROR: browser_type needs 'value' as text."
    if _state["page"] is None:
        return "ERROR: no page is open -- use browser_open first."
    label = label.strip()
    try:
        page = _state["page"]
        target = page.get_by_placeholder(label).first
        if target.count() == 0:
            target = page.get_by_label(label, exact=False).first
        if target.count() == 0:
            target = page.locator(
                f"input[name*=\"{label}\" i], "
                f"input[type=\"search\"], input[type=\"text\"]"
            ).first
        target.fill(value, timeout=10000)
        return "OK, typed.\n" + _describe_page()
    except Exception as e:
        return f"ERROR: could not fill \"{label}\" ({e})."


def scroll(direction="down"):
    """Scroll the open page up or down by one screen."""
    if _state["page"] is None:
        return "ERROR: no page is open -- use browser_open first."
    step = 700 if str(direction).lower() != "up" else -700
    try:
        _state["page"].mouse.wheel(0, step)
        _state["page"].wait_for_timeout(400)
        return "OK, scrolled.\n" + _describe_page()
    except Exception as e:
        return f"ERROR: could not scroll ({e})."


def go_back():
    """Go back to the previous page."""
    if _state["page"] is None:
        return "ERROR: no page is open -- use browser_open first."
    try:
        _state["page"].go_back(timeout=15000)
        return "OK, went back.\n" + _describe_page()
    except Exception as e:
        return f"ERROR: could not go back ({e})."


def press_key(key="Enter"):
    """Press one key in the page (Enter, Escape, Tab, PageDown...)."""
    if _state["page"] is None:
        return "ERROR: no page is open -- use browser_open first."
    try:
        _state["page"].keyboard.press(str(key))
        _state["page"].wait_for_timeout(400)
        return f"OK, pressed {key}.\n" + _describe_page()
    except Exception as e:
        return f"ERROR: could not press {key} ({e})."


def get_text(selector="body"):
    """Read the visible text of the page, or of one CSS selector."""
    if _state["page"] is None:
        return "ERROR: no page is open -- use browser_open first."
    try:
        text = _state["page"].inner_text(selector, timeout=10000)
        text = " ".join(text.split())
        if len(text) > MAX_STATE_CHARS * 2:
            text = text[:MAX_STATE_CHARS * 2] + " ...[page continues]"
        return text or "(that element has no text)"
    except Exception as e:
        return f"ERROR: could not read the text ({e})."


def close_browser():
    """Close the browser window (the driver stays ready for next time).

    Stopping the Playwright driver here looked tidy but broke the next
    browser_open: the sync API cannot be started a second time in the
    same process, so every later attempt died with "Target page,
    context or browser has been closed". The driver is stopped once,
    when ZYRO exits (see stop_driver below).
    """
    try:
        if _state["browser"] is not None:
            _state["browser"].close()
    except Exception as e:
        _state.update({"browser": None, "page": None})
        return f"OK: browser closed (with a warning: {e})."
    _state["browser"] = None
    _state["page"] = None
    return "OK: browser closed."


def stop_driver():
    """Stop the Playwright driver. Called once, when ZYRO exits."""
    try:
        if _state.get("pw") is not None:
            _state["pw"].stop()
    except Exception:                              # noqa: BLE001
        pass
    _state.update({"pw": None, "browser": None, "page": None})


atexit.register(stop_driver)

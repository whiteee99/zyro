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
import os
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                      str(paths.PROJECT_ROOT / "tools" / "pw-browsers"))

_state = {"browser": None, "page": None}


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
    if _state["browser"] is None:
        _state["pw"] = sync_playwright().start()
        _state["browser"] = _state["pw"].chromium.launch(headless=False)
    context = _state["browser"].new_context(locale="en-US")
    _state["page"] = context.new_page()
    return _state["page"]


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


def close_browser():
    """Shut the browser down completely."""
    try:
        if _state["browser"] is not None:
            _state["browser"].close()
            _state["browser"] = None
        if _state["pw"] is not None:
            _state["pw"].stop()
            _state["pw"] = None
        _state["page"] = None
        return "OK: browser closed."
    except Exception as e:
        _state.update({"browser": None, "page": None, "pw": None})
        return f"OK: browser closed (with a warning: {e})."

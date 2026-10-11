"""VYRA Phase 4 — browser automation for free web image generation.

Drives a REAL logged-in browser (Google Gemini web) with Playwright, so VYRA
can generate images with no API key / quota. Login is persisted in a dedicated
profile under data/, so Jay only has to sign in once:

    python -m vyra.browser --login
    python -m vyra.browser --test "a neon cyberpunk fox"

Fragile by nature (it depends on Gemini's web UI, which can change). Selectors
are listed with fallbacks and every step fails loudly with a readable message.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "data" / "browser_profile"
OUTPUT_DIR = ROOT / "data" / "generated_images"

GEMINI_URL = "https://gemini.google.com/app"

# Multiple selector candidates — the first that matches wins. Gemini's DOM
# shifts over time; add new fallbacks here if generation stops finding things.
EDITOR_SELECTORS = [
    'div.ql-editor[contenteditable="true"]',
    'rich-textarea div[contenteditable="true"]',
    'div[contenteditable="true"][role="textbox"]',
    'textarea',
]
GENERATED_IMG_SELECTORS = [
    'img[src*="googleusercontent.com"]',
    'generated-image img',
    'single-image img',
    'img[alt*="generated" i]',
]
LOGIN_HINTS = ("accounts.google.com", "/signin", "ServiceLogin")

CHROMIUM_MISSING_MSG = (
    "Chromium isn't installed yet (or finished installing after you ran this). "
    "Run:  python -m playwright install chromium   then try again."
)


def _looks_like_missing_browser(exc) -> bool:
    s = str(exc).lower()
    return "executable doesn't exist" in s or "playwright install" in s


def _first_visible(page, selectors, timeout_ms: int = 15000):
    """Return the first selector that becomes visible, or None."""
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    return loc
            except Exception:
                pass
        page.wait_for_timeout(300)
    return None


def _is_logged_in(page) -> bool:
    url = (page.url or "").lower()
    if any(h in url for h in LOGIN_HINTS):
        return False
    # Logged in if a prompt editor is present on the Gemini app.
    return _first_visible(page, EDITOR_SELECTORS, timeout_ms=8000) is not None


def _launch(p, headless: bool):
    """Launch a persistent browser context. The bundled Chromium can fail to
    spawn in headful mode on some Windows setups (spawn UNKNOWN), so prefer the
    system Chrome/Edge channels and fall back to bundled Chromium last."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = ["--disable-blink-features=AutomationControlled", "--no-first-run"]
    base = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        args=args,
    )
    last_exc = None
    for channel in ("chrome", "msedge", None):
        try:
            kwargs = dict(base)
            if channel:
                kwargs["channel"] = channel
            return p.chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            last_exc = exc
            continue
    raise last_exc


def login(timeout: int = 300) -> bool:
    """Open a visible browser so Jay can sign in to Google once. Returns True
    when a logged-in Gemini session is detected (cookies then persist)."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            ctx = _launch(p, headless=False)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(GEMINI_URL, wait_until="domcontentloaded")
            print("A browser window opened. Sign in to your Google account and open "
                  "Gemini. Waiting (up to %ds)..." % timeout)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if _is_logged_in(page):
                    print("Login detected and saved. You can close this window.")
                    page.wait_for_timeout(1500)
                    ctx.close()
                    return True
                page.wait_for_timeout(1000)
            ctx.close()
            print("Timed out waiting for login.")
            return False
    except Exception as exc:
        print(CHROMIUM_MISSING_MSG if _looks_like_missing_browser(exc) else f"Login failed: {exc}")
        return False


def _wait_for_new_image(page, prior_srcs: set[str], timeout: int):
    """Poll until a generated image that wasn't present before appears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sel in GENERATED_IMG_SELECTORS:
            imgs = page.locator(sel)
            try:
                n = imgs.count()
            except Exception:
                n = 0
            for i in range(n):
                el = imgs.nth(i)
                try:
                    src = el.get_attribute("src") or ""
                except Exception:
                    continue
                if src and src not in prior_srcs and el.is_visible():
                    return el, src
        page.wait_for_timeout(800)
    return None, None


def _collect_srcs(page) -> set[str]:
    found = set()
    for sel in GENERATED_IMG_SELECTORS:
        imgs = page.locator(sel)
        try:
            for i in range(imgs.count()):
                src = imgs.nth(i).get_attribute("src")
                if src:
                    found.add(src)
        except Exception:
            pass
    return found


def _save_image(ctx, page, el, src: str, path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preferred: download the real bytes through the browser's session.
    if src.startswith("http"):
        try:
            resp = ctx.request.get(src)
            if resp.ok:
                path.write_bytes(resp.body())
                return True
        except Exception:
            pass
    # Fallback: screenshot the image element itself (works for blob:/data: too).
    try:
        el.screenshot(path=str(path))
        return path.exists()
    except Exception:
        return False


def generate_image(prompt: str, headless: bool = False, timeout: int = 120) -> str:
    """Drive Gemini web to generate an image for `prompt`; save and return the
    local file path, or a human-readable error string (never raises)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ("Browser automation needs Playwright. Install it with "
                "'pip install -r requirements-browser.txt' then "
                "'python -m playwright install chromium'.")

    prompt = (prompt or "").strip()
    if not prompt:
        return "No image prompt was given."

    try:
        with sync_playwright() as p:
            ctx = _launch(p, headless=headless)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(GEMINI_URL, wait_until="domcontentloaded")

            if not _is_logged_in(page):
                ctx.close()
                return ("Not signed in to Gemini. Run 'python -m vyra.browser "
                        "--login' once to sign in, then try again.")

            editor = _first_visible(page, EDITOR_SELECTORS, timeout_ms=15000)
            if editor is None:
                ctx.close()
                return "Couldn't find the Gemini prompt box (the web UI may have changed)."

            prior = _collect_srcs(page)
            editor.click()
            editor.type(f"Generate an image: {prompt}")
            page.keyboard.press("Enter")

            el, src = _wait_for_new_image(page, prior, timeout)
            if el is None:
                ctx.close()
                return f"Gemini didn't return an image within {timeout}s. Try again or rephrase."

            ts = time.strftime("%Y%m%d_%H%M%S")
            out = OUTPUT_DIR / f"gen_{ts}.png"
            ok = _save_image(ctx, page, el, src, out)
            ctx.close()
            if ok:
                return str(out)
            return "Generated an image but couldn't save it locally."
    except Exception as exc:
        if _looks_like_missing_browser(exc):
            return CHROMIUM_MISSING_MSG
        return f"Browser image generation failed: {exc}"


if __name__ == "__main__":
    if "--login" in sys.argv:
        login()
    elif "--test" in sys.argv:
        i = sys.argv.index("--test")
        prompt = sys.argv[i + 1] if i + 1 < len(sys.argv) else "a neon cyberpunk fox"
        print(generate_image(prompt, headless=False))
    else:
        print("Usage: python -m vyra.browser --login | --test \"<prompt>\"")

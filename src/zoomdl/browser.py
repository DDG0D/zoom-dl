"""Browser automation — Playwright-based Zoom recording URL capture."""

import time
import re
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
from rich.console import Console

from .models import RecordingInput, CapturedRecording
from .config import Config
from .errors import AuthenticationError, CaptureError
from .utils import (
    extract_password_from_url,
    extract_date_from_url,
    clean_title,
    logger,
)

console = Console()

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def capture_recording(
    recording: RecordingInput,
    config: Config,
    prompt_password: bool = True,
) -> CapturedRecording:
    """Launch a headless browser, authenticate, and capture the signed video URL.

    Args:
        recording: The recording URL and optional password.
        config: Application configuration.
        prompt_password: If True and no password available, prompt the user.

    Returns:
        CapturedRecording with the signed CloudFront URL and metadata.

    Raises:
        AuthenticationError: Wrong or missing passcode.
        CaptureError: Could not capture the video URL.
    """
    # Resolve password
    password = recording.password
    if not password:
        password = extract_password_from_url(recording.url)
    if password:
        logger.info("🔐 Passcode resolved")
    else:
        logger.debug("No passcode found in URL")

    with sync_playwright() as p:
        launch_args = {"headless": config.headless}
        if config.proxy:
            launch_args["proxy"] = {"server": config.proxy}
        browser = p.chromium.launch(**launch_args)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        try:
            return _do_capture(page, context, browser, recording, password, config, prompt_password)
        finally:
            browser.close()


def _do_capture(
    page: Page,
    context: BrowserContext,
    browser: Browser,
    recording: RecordingInput,
    password: Optional[str],
    config: Config,
    prompt_password: bool,
) -> CapturedRecording:
    """Core capture logic — runs inside the browser context."""

    # ── Request interceptor ──────────────────────────────────
    video_request_info: dict = {}

    def capture_request(request):
        url = request.url
        if "ssrweb" in url and ".mp4" in url:
            video_request_info["url"] = url
            video_request_info["headers"] = request.headers

    page.on("request", capture_request)

    # ── Step 1: Navigate ─────────────────────────────────────
    # Zoom does client-side redirects after the initial response, which
    # destroys the JS execution context.  Navigate with "commit" then
    # wait for the page to stabilise before touching the DOM.
    logger.info("🌐 Navigating to recording page...")
    try:
        page.goto(recording.url, wait_until="commit", timeout=config.page_load_timeout * 1000)
    except Exception as e:
        raise CaptureError(f"Failed to load page: {e}")

    # Let redirects finish and Vue SPA boot up
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    time.sleep(3)

    # ── Step 2: Detect passcode requirement ───────────────────
    # Poll the DOM for up to 20s.  Every call is wrapped in try/except
    # because Zoom can still navigate mid-poll.
    passcode_required = False
    passcode_input = None
    deadline = time.time() + 20

    while time.time() < deadline:
        try:
            result = page.evaluate("""() => {
                const inp = document.getElementById('passcode');
                if (inp) return 'passcode';
                const body = document.body ? document.body.innerText : '';
                if (body.toLowerCase().includes('passcode')) return 'passcode';
                const vid = document.querySelector('video');
                if (vid) return 'video';
                return null;
            }""")
        except Exception:
            # Context destroyed by navigation — wait and retry
            time.sleep(1)
            continue

        if result == 'passcode':
            passcode_required = True
            break
        if result == 'video':
            break

        time.sleep(0.5)

    logger.debug(f"Page title: {page.title()}, passcode_required={passcode_required}")

    if passcode_required:
        # Grab the input element now that the page is stable
        passcode_input = page.query_selector('#passcode') or page.query_selector('input[type="password"]')
        if not passcode_input:
            # One more attempt after a short wait
            time.sleep(1)
            passcode_input = page.query_selector('#passcode') or page.query_selector('input[type="password"]')
        if not passcode_input:
            raise CaptureError("Passcode form detected but could not find the input field")

        if not password and prompt_password:
            from rich.prompt import Prompt
            password = Prompt.ask("  Enter recording passcode")

        if not password:
            raise AuthenticationError("Recording requires a passcode but none was provided")

        logger.info("🔑 Entering passcode...")
        passcode_input.fill(password)
        time.sleep(0.5)

        submit_btn = page.query_selector('button:has-text("Watch Recording")')
        if not submit_btn:
            submit_btn = page.query_selector('button[type="submit"]')
        if submit_btn:
            submit_btn.click()
        else:
            passcode_input.press("Enter")

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        time.sleep(8)

        try:
            body_text = page.inner_text("body")
            if "Wrong passcode" in body_text or "wrong passcode" in body_text.lower():
                raise AuthenticationError("Wrong passcode — Zoom rejected the password")
        except AuthenticationError:
            raise
        except Exception:
            pass

        logger.debug(f"Post-auth page title: {page.title()}")
    else:
        # No passcode needed — wait for full page load so video requests fire
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        time.sleep(3)

    # ── Step 3: Capture video URL ────────────────────────────
    logger.info("📡 Capturing video stream URL...")

    # Fallback 1: Force video to play
    if not video_request_info:
        logger.debug("No request intercepted yet — attempting to force-play video")
        page.evaluate("""() => {
            const video = document.querySelector('video');
            if (video) { video.currentTime = 0; video.play(); }
        }""")
        time.sleep(5)

    # Fallback 2: Read video.src directly
    if not video_request_info:
        logger.debug("Still no request — trying video.src")
        video_src = page.evaluate(
            "() => { const v = document.querySelector('video'); return v ? v.src : null; }"
        )
        if video_src:
            video_request_info["url"] = video_src
            video_request_info["headers"] = {}

    if not video_request_info.get("url"):
        # Save screenshot for debugging
        try:
            page.screenshot(path="screenshot_error.png")
            logger.warning("Saved debug screenshot to screenshot_error.png")
        except Exception:
            pass
        raise CaptureError(
            "Could not capture video URL. The recording may be unavailable, "
            "or Zoom's page structure may have changed."
        )

    video_url = video_request_info["url"]
    req_headers = video_request_info.get("headers", {})
    logger.info(f"✅ Video URL captured ({len(video_url)} chars)")
    logger.debug(f"Request headers: {list(req_headers.keys())}")

    # ── Step 4: Extract metadata ─────────────────────────────
    raw_title = page.title()
    title = clean_title(raw_title)
    date = extract_date_from_url(video_url)

    logger.info(f"📹 Title: {title}")
    if date:
        logger.info(f"📅 Date: {date}")

    # ── Step 5: Collect cookies ──────────────────────────────
    cookies = context.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

    return CapturedRecording(
        input=recording,
        video_url=video_url,
        title=title,
        date=date,
        cookies=cookie_str,
        headers=req_headers,
    )


# ─── Async variant for parallel mode (Phase 3) ──────────────────

async def async_capture_recording(
    recording: RecordingInput,
    config: Config,
) -> CapturedRecording:
    """Async version of capture_recording for parallel batch downloads."""
    from playwright.async_api import async_playwright

    password = recording.password
    if not password:
        password = extract_password_from_url(recording.url)

    async with async_playwright() as p:
        launch_args = {"headless": config.headless}
        if config.proxy:
            launch_args["proxy"] = {"server": config.proxy}
        browser = await p.chromium.launch(**launch_args)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        try:
            return await _async_do_capture(page, context, browser, recording, password, config)
        finally:
            await browser.close()


async def _async_do_capture(page, context, browser, recording, password, config):
    """Async core capture logic."""
    import asyncio

    video_request_info: dict = {}

    def capture_request(request):
        url = request.url
        if "ssrweb" in url and ".mp4" in url:
            video_request_info["url"] = url
            video_request_info["headers"] = request.headers

    page.on("request", capture_request)

    # Navigate with "commit" then let redirects settle
    logger.info(f"🌐 [{recording.url[-30:]}] Navigating...")
    try:
        await page.goto(recording.url, wait_until="commit", timeout=config.page_load_timeout * 1000)
    except Exception as e:
        raise CaptureError(f"Failed to load page: {e}")

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(3)

    # Poll for passcode form or video player
    passcode_required = False
    deadline = asyncio.get_event_loop().time() + 20

    while asyncio.get_event_loop().time() < deadline:
        try:
            result = await page.evaluate("""() => {
                const inp = document.getElementById('passcode');
                if (inp) return 'passcode';
                const body = document.body ? document.body.innerText : '';
                if (body.toLowerCase().includes('passcode')) return 'passcode';
                const vid = document.querySelector('video');
                if (vid) return 'video';
                return null;
            }""")
        except Exception:
            await asyncio.sleep(1)
            continue

        if result == 'passcode':
            passcode_required = True
            break
        if result == 'video':
            break

        await asyncio.sleep(0.5)

    if passcode_required:
        passcode_input = await page.query_selector('#passcode') or await page.query_selector('input[type="password"]')
        if not passcode_input:
            await asyncio.sleep(1)
            passcode_input = await page.query_selector('#passcode') or await page.query_selector('input[type="password"]')
        if not passcode_input:
            raise CaptureError("Passcode form detected but could not find the input field")

        if not password:
            raise AuthenticationError("Recording requires a passcode but none was provided (cannot prompt in parallel mode)")

        logger.info(f"🔑 [{recording.url[-30:]}] Entering passcode...")
        await passcode_input.fill(password)
        await asyncio.sleep(0.5)

        submit_btn = await page.query_selector('button:has-text("Watch Recording")')
        if not submit_btn:
            submit_btn = await page.query_selector('button[type="submit"]')
        if submit_btn:
            await submit_btn.click()
        else:
            await passcode_input.press("Enter")

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(8)

        try:
            body_text = await page.inner_text("body")
            if "Wrong passcode" in body_text or "wrong passcode" in body_text.lower():
                raise AuthenticationError("Wrong passcode")
        except AuthenticationError:
            raise
        except Exception:
            pass
    else:
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(3)

    # Capture video URL
    logger.info(f"📡 [{recording.url[-30:]}] Capturing video URL...")

    if not video_request_info:
        await page.evaluate("""() => {
            const video = document.querySelector('video');
            if (video) { video.currentTime = 0; video.play(); }
        }""")
        await asyncio.sleep(5)

    if not video_request_info:
        video_src = await page.evaluate(
            "() => { const v = document.querySelector('video'); return v ? v.src : null; }"
        )
        if video_src:
            video_request_info["url"] = video_src
            video_request_info["headers"] = {}

    if not video_request_info.get("url"):
        raise CaptureError(f"Could not capture video URL for {recording.url[-40:]}")

    video_url = video_request_info["url"]
    raw_title = await page.title()
    title = clean_title(raw_title)
    date = extract_date_from_url(video_url)

    cookies = await context.cookies()
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

    return CapturedRecording(
        input=recording,
        video_url=video_url,
        title=title,
        date=date,
        cookies=cookie_str,
        headers=video_request_info.get("headers", {}),
    )

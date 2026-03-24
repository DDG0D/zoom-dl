"""Pure HTTP capture — no browser needed.

Reverse-engineered Zoom recording API flow:
  1. GET share page → establish session cookies
  2. GET /nws/recording/1.0/play/share-info/{share_id} → meetingId + password check
  3. POST /nws/recording/1.0/validate-context → encryptMeetId
  4. POST /nws/recording/1.0/validate-meeting-passwd → authenticate
  5. GET share-info again → play page redirect URL
  6. GET /rec/play/{play_id} → set play cookies
  7. GET /nws/recording/1.0/play/info/{play_id} → signed CloudFront mp4 URL
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx

from .models import RecordingInput, CapturedRecording
from .config import Config
from .errors import AuthenticationError, CaptureError
from .utils import extract_date_from_url, clean_title, logger

# Silence httpx's per-request INFO logs — they leak internal URLs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

COMMON_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def _extract_share_id(share_url: str) -> str:
    """Extract the share ID from a Zoom recording URL."""
    path = urlparse(share_url).path
    if "/rec/share/" in path:
        return path.split("/rec/share/")[-1]
    raise CaptureError(f"Invalid Zoom share URL: {share_url}")


def _get_base_url(share_url: str) -> str:
    parsed = urlparse(share_url)
    return f"{parsed.scheme}://{parsed.hostname}"


def _build_referer_headers(referer: str) -> dict:
    return {
        **COMMON_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": referer,
    }


def _check_pwd_result(pwd_data: dict) -> None:
    """Validate password submission response. Raises on any failure."""
    if not pwd_data.get("status"):
        error_code = pwd_data.get("errorCode", 0)
        if error_code in (3301, 3302):
            raise AuthenticationError("Wrong passcode")
        raise AuthenticationError(
            f"Password validation failed: {pwd_data.get('errorMessage')}"
        )

    result_val = pwd_data.get("result", "")
    if result_val == "needRecaptcha":
        raise AuthenticationError("Wrong passcode")
    if result_val == "captcha_error":
        raise CaptureError(
            "Zoom blocked the request (CAPTCHA/Cloudflare). "
            "Use a rotating proxy or VPN and try again."
        )
    if result_val != "viewdetailpage":
        raise CaptureError(
            f"Zoom returned unexpected response: {result_val}. "
            "Use a rotating proxy or VPN and try again."
        )


def http_capture_recording(
    recording: RecordingInput,
    config: Config,
    prompt_password: bool = True,
) -> CapturedRecording:
    """Capture a recording's signed video URL using pure HTTP requests."""
    password = recording.password
    share_url = recording.url
    base_url = _get_base_url(share_url)
    share_id = _extract_share_id(share_url)

    proxy_url = config.proxy or None
    with httpx.Client(
        timeout=httpx.Timeout(config.page_load_timeout, connect=15.0),
        follow_redirects=True,
        headers=COMMON_HEADERS,
        proxy=proxy_url,
    ) as client:
        logger.debug("step 1: loading share page")
        client.get(share_url)

        logger.debug("step 2: share-info")
        si_resp = client.get(
            f"{base_url}/nws/recording/1.0/play/share-info/{share_id}",
            params={"originDomain": urlparse(share_url).hostname},
            headers={**COMMON_HEADERS, "Referer": share_url},
        )
        si_data = si_resp.json()
        if not si_data.get("status"):
            raise CaptureError(f"Failed to access recording: {si_data.get('errorMessage')}")

        si_result = si_data["result"]
        needs_password = si_result.get("componentName") == "need-password"

        if needs_password:
            meeting_id = si_result.get("meetingId")
            if not meeting_id:
                raise CaptureError("Recording requires a passcode but server returned no context")

            logger.debug("step 3: validate-context")
            ctx_resp = client.post(
                f"{base_url}/nws/recording/1.0/validate-context",
                data={
                    "meetingId": meeting_id,
                    "fileId": "",
                    "useWhichPasswd": "meeting",
                    "sharelevel": "meeting",
                    "iet": "",
                },
                headers=_build_referer_headers(share_url),
            )
            ctx_data = ctx_resp.json()
            if not ctx_data.get("status"):
                raise CaptureError("Failed to validate recording context")

            encrypt_meet_id = ctx_data["result"]["encryptMeetId"]

            if not password and prompt_password:
                from rich.prompt import Prompt
                password = Prompt.ask("  Enter recording passcode")

            if not password:
                raise AuthenticationError("Recording requires a passcode but none was provided")

            logger.debug("step 4: validate-meeting-passwd")
            pwd_resp = client.post(
                f"{base_url}/nws/recording/1.0/validate-meeting-passwd",
                data={
                    "id": encrypt_meet_id,
                    "passwd": password,
                    "action": "viewdetailpage",
                    "recaptcha": "",
                },
                headers=_build_referer_headers(share_url),
            )
            _check_pwd_result(pwd_resp.json())

            logger.debug("step 5: authenticated share-info")
            si2_resp = client.get(
                f"{base_url}/nws/recording/1.0/play/share-info/{share_id}",
                params={"originDomain": urlparse(share_url).hostname},
                headers={**COMMON_HEADERS, "Referer": share_url},
            )
            si2_data = si2_resp.json()
            if not si2_data.get("status"):
                raise CaptureError("Failed to load recording after authentication")

            play_path = si2_data["result"].get("redirectUrl", "")
            if "/rec/play/" not in play_path:
                raise CaptureError("Recording unavailable after authentication")

            play_id = play_path.split("/rec/play/")[-1]

        else:
            play_path = si_result.get("redirectUrl", "")
            if "/rec/play/" not in play_path:
                raise CaptureError("Recording unavailable — no playback URL found")
            play_id = play_path.split("/rec/play/")[-1]

        logger.debug("step 6: loading play page")
        play_resp = client.get(
            f"{base_url}/rec/play/{play_id}",
            params={
                "canPlayFromShare": "true",
                "from": "share_recording_detail",
                "continueMode": "true",
                "componentName": "rec-play",
                "originRequestUrl": share_url,
            },
            headers={**COMMON_HEADERS, "Referer": share_url},
        )

        logger.debug("step 7: fetching video URL")
        info_resp = client.get(
            f"{base_url}/nws/recording/1.0/play/info/{play_id}",
            params={
                "canPlayFromShare": "true",
                "from": "share_recording_detail",
                "continueMode": "true",
                "componentName": "recording-play",
                "originRequestUrl": share_url,
            },
            headers={
                **COMMON_HEADERS,
                "Accept": "application/json",
                "Referer": str(play_resp.url),
            },
        )

        if info_resp.status_code != 200:
            raise CaptureError("Failed to retrieve recording info")

        info_data = info_resp.json()
        if not info_data.get("status"):
            raise CaptureError(f"Recording unavailable: {info_data.get('errorMessage')}")

        result = info_data["result"]
        video_url = result.get("viewMp4Url") or result.get("mp4Url")
        if not video_url:
            raise CaptureError("Recording has no downloadable video")

        title = clean_title(result.get("meet", {}).get("topic", "Untitled Recording"))
        date = extract_date_from_url(video_url)

        cookie_str = "; ".join(
            f"{name}={value}" for name, value in client.cookies.items()
        )

        return CapturedRecording(
            input=recording,
            video_url=video_url,
            title=title,
            date=date,
            cookies=cookie_str,
            headers={},
        )


async def async_http_capture_recording(
    recording: RecordingInput,
    config: Config,
) -> CapturedRecording:
    """Async version for parallel downloads."""
    password = recording.password
    share_url = recording.url
    base_url = _get_base_url(share_url)
    share_id = _extract_share_id(share_url)
    hostname = urlparse(share_url).hostname

    proxy_url = config.proxy or None
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(config.page_load_timeout, connect=15.0),
        follow_redirects=True,
        headers=COMMON_HEADERS,
        proxy=proxy_url,
    ) as client:
        await client.get(share_url)

        si_resp = await client.get(
            f"{base_url}/nws/recording/1.0/play/share-info/{share_id}",
            params={"originDomain": hostname},
            headers={**COMMON_HEADERS, "Referer": share_url},
        )
        si_data = si_resp.json()
        if not si_data.get("status"):
            raise CaptureError(f"Failed to access recording: {si_data.get('errorMessage')}")

        si_result = si_data["result"]
        needs_password = si_result.get("componentName") == "need-password"

        if needs_password:
            if not password:
                raise AuthenticationError(
                    "Recording requires a passcode (cannot prompt in parallel mode)"
                )

            meeting_id = si_result["meetingId"]
            ctx_resp = await client.post(
                f"{base_url}/nws/recording/1.0/validate-context",
                data={
                    "meetingId": meeting_id,
                    "fileId": "",
                    "useWhichPasswd": "meeting",
                    "sharelevel": "meeting",
                    "iet": "",
                },
                headers=_build_referer_headers(share_url),
            )
            ctx_data = ctx_resp.json()
            if not ctx_data.get("status"):
                raise CaptureError("Failed to validate recording context")

            pwd_resp = await client.post(
                f"{base_url}/nws/recording/1.0/validate-meeting-passwd",
                data={
                    "id": ctx_data["result"]["encryptMeetId"],
                    "passwd": password,
                    "action": "viewdetailpage",
                    "recaptcha": "",
                },
                headers=_build_referer_headers(share_url),
            )
            _check_pwd_result(pwd_resp.json())

            si2_resp = await client.get(
                f"{base_url}/nws/recording/1.0/play/share-info/{share_id}",
                params={"originDomain": hostname},
                headers={**COMMON_HEADERS, "Referer": share_url},
            )
            si2_data = si2_resp.json()
            play_path = si2_data["result"].get("redirectUrl", "")
            if "/rec/play/" not in play_path:
                raise CaptureError("Recording unavailable after authentication")
            play_id = play_path.split("/rec/play/")[-1]

        else:
            play_path = si_result.get("redirectUrl", "")
            if "/rec/play/" not in play_path:
                raise CaptureError("Recording unavailable — no playback URL found")
            play_id = play_path.split("/rec/play/")[-1]

        play_resp = await client.get(
            f"{base_url}/rec/play/{play_id}",
            params={
                "canPlayFromShare": "true",
                "from": "share_recording_detail",
                "continueMode": "true",
                "componentName": "rec-play",
                "originRequestUrl": share_url,
            },
            headers={**COMMON_HEADERS, "Referer": share_url},
        )

        info_resp = await client.get(
            f"{base_url}/nws/recording/1.0/play/info/{play_id}",
            params={
                "canPlayFromShare": "true",
                "from": "share_recording_detail",
                "continueMode": "true",
                "componentName": "recording-play",
                "originRequestUrl": share_url,
            },
            headers={
                **COMMON_HEADERS,
                "Accept": "application/json",
                "Referer": str(play_resp.url),
            },
        )

        info_data = info_resp.json()
        if not info_data.get("status"):
            raise CaptureError(f"Recording unavailable: {info_data.get('errorMessage')}")

        result = info_data["result"]
        video_url = result.get("viewMp4Url") or result.get("mp4Url")
        if not video_url:
            raise CaptureError("Recording has no downloadable video")

        title = clean_title(result.get("meet", {}).get("topic", "Untitled"))
        date = extract_date_from_url(video_url)
        cookie_str = "; ".join(f"{n}={v}" for n, v in client.cookies.items())

        return CapturedRecording(
            input=recording,
            video_url=video_url,
            title=title,
            date=date,
            cookies=cookie_str,
            headers={},
        )

"""Download engine — streams video files with resume, progress bar, and retry."""

import time
from pathlib import Path
from typing import Optional

import httpx
from rich.console import Console
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    TextColumn,
    SpinnerColumn,
    TaskProgressColumn,
)

from .models import CapturedRecording, DownloadResult, DownloadStatus
from .config import Config
from .errors import DownloadError
from .utils import (
    generate_smart_filename,
    get_resume_offset,
    is_valid_mp4,
    format_size,
    format_duration,
    logger,
)


console = Console()

CHUNK_SIZE = 64 * 1024  # 64KB chunks for streaming

# Headers that mimic a real browser request
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Referer": "https://us06web.zoom.us/",
}


def download_recording(
    recording: CapturedRecording,
    config: Config,
    dry_run: bool = False,
) -> DownloadResult:
    """Download a captured recording to disk.

    Args:
        recording: CapturedRecording with the signed video URL.
        config: Application configuration.
        dry_run: If True, just print the URL and return.

    Returns:
        DownloadResult with status and file info.
    """
    start_time = time.time()

    # Generate filename
    filename = generate_smart_filename(recording.title, recording.date)
    output_path = config.download_dir / filename

    if dry_run:
        console.print(f"  [bright_green]■[/bright_green] [key]URL:[/key]    [dim]{recording.video_url[:120]}...[/dim]")
        console.print(f"  [bright_green]■[/bright_green] [key]File:[/key]   [dim]{output_path}[/dim]")
        return DownloadResult(
            input=recording.input,
            status=DownloadStatus.COMPLETED,
            file_path=output_path,
            duration_seconds=time.time() - start_time,
        )

    # Skip existing
    if config.skip_existing and output_path.exists() and is_valid_mp4(output_path):
        size = output_path.stat().st_size
        logger.info(f"⏭  Already exists: {filename} ({format_size(size)})")
        return DownloadResult(
            input=recording.input,
            status=DownloadStatus.SKIPPED,
            file_path=output_path,
            file_size=size,
            duration_seconds=time.time() - start_time,
        )

    # Resume support
    resume_offset = get_resume_offset(output_path)
    if resume_offset > 0:
        logger.info(f"🔄 Resuming from {format_size(resume_offset)}")

    # Download with retry
    last_error = None
    for attempt in range(1, config.max_retries + 1):
        try:
            result = _do_download(
                recording=recording,
                output_path=output_path,
                resume_offset=resume_offset,
                config=config,
                attempt=attempt,
            )
            result.duration_seconds = time.time() - start_time
            return result
        except (httpx.NetworkError, httpx.TimeoutException, DownloadError) as e:
            last_error = e
            if attempt < config.max_retries:
                wait = config.retry_delay * attempt  # exponential-ish backoff
                logger.warning(
                    f"⚠  Attempt {attempt}/{config.max_retries} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)
                # Update resume offset in case we got partial data
                resume_offset = get_resume_offset(output_path)
            else:
                logger.error(f"❌ All {config.max_retries} attempts failed")

    return DownloadResult(
        input=recording.input,
        status=DownloadStatus.FAILED,
        file_path=output_path,
        error=str(last_error),
        duration_seconds=time.time() - start_time,
    )


def _do_download(
    recording: CapturedRecording,
    output_path: Path,
    resume_offset: int,
    config: Config,
    attempt: int,
) -> DownloadResult:
    """Execute a single download attempt with progress bar."""

    # Build headers
    headers = dict(DEFAULT_HEADERS)
    if recording.cookies:
        headers["Cookie"] = recording.cookies

    # Range header for resume or full download
    if resume_offset > 0:
        headers["Range"] = f"bytes={resume_offset}-"
    else:
        headers["Range"] = "bytes=0-"

    proxy_url = config.proxy or None
    with httpx.Client(
        timeout=httpx.Timeout(config.download_timeout, connect=30.0),
        follow_redirects=True,
        proxy=proxy_url,
    ) as client:
        with client.stream("GET", recording.video_url, headers=headers) as response:
            # Check for errors
            if response.status_code == 403:
                raise DownloadError(
                    "Access denied (403) — the signed URL may have expired. "
                    "Try running the download again to get a fresh URL."
                )
            if response.status_code == 404:
                raise DownloadError("Recording not found (404)")
            if response.status_code not in (200, 206):
                raise DownloadError(f"HTTP {response.status_code}: {response.reason_phrase}")

            # Determine total size
            content_length = response.headers.get("content-length")
            if content_length:
                total_size = int(content_length) + resume_offset
            else:
                total_size = None

            # Open file for writing (append if resuming)
            file_mode = "ab" if resume_offset > 0 else "wb"
            downloaded = resume_offset

            with open(output_path, file_mode) as f:
                with Progress(
                    TextColumn("  [bright_green]■[/bright_green]"),
                    BarColumn(
                        bar_width=40,
                        style="dim",
                        complete_style="bright_green",
                        finished_style="bold bright_green",
                        pulse_style="bright_green",
                    ),
                    TaskProgressColumn(),
                    DownloadColumn(),
                    TextColumn("[muted]·[/muted]"),
                    TransferSpeedColumn(),
                    TextColumn("[muted]·[/muted]"),
                    TimeRemainingColumn(compact=True),
                    console=console,
                    transient=True,
                ) as progress:
                    task = progress.add_task(
                        "download",
                        total=total_size,
                        completed=resume_offset,
                    )

                    for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress.update(task, completed=downloaded)

    # Validate
    file_size = output_path.stat().st_size

    if file_size < 100_000:
        # Suspiciously small — might be an error page
        try:
            content = output_path.read_text(errors="replace")[:500]
            if "AccessDenied" in content or "xml" in content.lower():
                output_path.unlink()  # Delete the error page
                raise DownloadError(
                    "CloudFront returned AccessDenied — the signed URL expired. "
                    "Re-run to get a fresh URL."
                )
        except UnicodeDecodeError:
            pass

        raise DownloadError(
            f"Downloaded file is only {format_size(file_size)} — "
            f"expected a video file. The download may have been truncated."
        )

    if not is_valid_mp4(output_path):
        logger.warning(
            f"⚠  File header doesn't look like MP4, but size is {format_size(file_size)}. "
            f"It might still be playable."
        )

    return DownloadResult(
        input=recording.input,
        status=DownloadStatus.COMPLETED,
        file_path=output_path,
        file_size=file_size,
    )


# ─── Async variant for parallel mode (Phase 3) ──────────────────

async def async_download_recording(
    recording: CapturedRecording,
    config: Config,
    progress=None,
    task_id=None,
) -> DownloadResult:
    """Async version of download_recording for parallel batch downloads."""
    start_time = time.time()

    filename = generate_smart_filename(recording.title, recording.date)
    output_path = config.download_dir / filename

    # Skip existing
    if config.skip_existing and output_path.exists() and is_valid_mp4(output_path):
        size = output_path.stat().st_size
        return DownloadResult(
            input=recording.input,
            status=DownloadStatus.SKIPPED,
            file_path=output_path,
            file_size=size,
            duration_seconds=time.time() - start_time,
        )

    resume_offset = get_resume_offset(output_path)

    # Build headers
    headers = dict(DEFAULT_HEADERS)
    if recording.cookies:
        headers["Cookie"] = recording.cookies
    headers["Range"] = f"bytes={resume_offset}-" if resume_offset > 0 else "bytes=0-"

    last_error = None
    for attempt in range(1, config.max_retries + 1):
        try:
            proxy_url = config.proxy or None
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(config.download_timeout, connect=30.0),
                follow_redirects=True,
                proxy=proxy_url,
            ) as client:
                async with client.stream("GET", recording.video_url, headers=headers) as response:
                    if response.status_code == 403:
                        raise DownloadError("Access denied (403) — signed URL may have expired")
                    if response.status_code not in (200, 206):
                        raise DownloadError(f"HTTP {response.status_code}")

                    content_length = response.headers.get("content-length")
                    total_size = int(content_length) + resume_offset if content_length else None

                    if progress and task_id is not None and total_size:
                        progress.update(task_id, total=total_size, completed=resume_offset)

                    file_mode = "ab" if resume_offset > 0 else "wb"
                    downloaded = resume_offset

                    with open(output_path, file_mode) as f:
                        async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress and task_id is not None:
                                progress.update(task_id, completed=downloaded)

            # Validate
            file_size = output_path.stat().st_size
            if file_size < 100_000:
                raise DownloadError(f"File too small: {format_size(file_size)}")

            return DownloadResult(
                input=recording.input,
                status=DownloadStatus.COMPLETED,
                file_path=output_path,
                file_size=file_size,
                duration_seconds=time.time() - start_time,
            )

        except (httpx.NetworkError, httpx.TimeoutException, DownloadError) as e:
            last_error = e
            if attempt < config.max_retries:
                import asyncio
                await asyncio.sleep(config.retry_delay * attempt)
                resume_offset = get_resume_offset(output_path)

    return DownloadResult(
        input=recording.input,
        status=DownloadStatus.FAILED,
        file_path=output_path,
        error=str(last_error),
        duration_seconds=time.time() - start_time,
    )

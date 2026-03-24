"""Batch download orchestration — sequential and parallel modes."""

import asyncio
from typing import Optional

from rich.console import Console
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    TextColumn,
    SpinnerColumn,
)
from rich.theme import Theme

from .models import RecordingInput, DownloadResult, DownloadStatus, DownloadMode
from .config import Config
from .downloader import download_recording, async_download_recording
from .errors import ZoomDLError
from .utils import format_size, format_duration, logger


def _capture_smart(recording, config, prompt_password=True):
    """Capture via pure HTTP, or browser if config.use_browser is set."""
    if config.use_browser:
        from .browser import capture_recording
        return capture_recording(recording, config, prompt_password=prompt_password)

    from .http_capture import http_capture_recording
    return http_capture_recording(recording, config, prompt_password=prompt_password)


async def _async_capture_smart(recording, config):
    """Async capture via pure HTTP, or browser if config.use_browser is set."""
    if config.use_browser:
        from .browser import async_capture_recording
        return await async_capture_recording(recording, config)

    from .http_capture import async_http_capture_recording
    return await async_http_capture_recording(recording, config)


THEME = Theme({
    "info": "dim",
    "success": "green",
    "warning": "yellow",
    "error": "red bold",
    "muted": "dim white",
    "val": "bold white",
})

console = Console(theme=THEME)


# ─── Sequential ──────────────────────────────────────────────────

def run_sequential(
    recordings: list[RecordingInput],
    config: Config,
    dry_run: bool = False,
) -> list[DownloadResult]:
    results: list[DownloadResult] = []
    total = len(recordings)

    for i, rec in enumerate(recordings, 1):
        console.print(f"\n  [val]{i}/{total}[/val]")

        try:
            console.print("  [bright_green]■[/bright_green] [muted]fetching recording details...[/muted]")
            captured = _capture_smart(rec, config, prompt_password=(not dry_run))

            console.print(f"  [bright_green]■[/bright_green] [key]Title:[/key]  [val]{captured.title}[/val]")
            if captured.date:
                console.print(f"  [bright_green]■[/bright_green] [key]Date:[/key]   [muted]{captured.date}[/muted]")

            result = download_recording(captured, config, dry_run=dry_run)
            results.append(result)
            _print_result(result)

        except ZoomDLError as e:
            logger.error(str(e))
            results.append(DownloadResult(input=rec, status=DownloadStatus.FAILED, error=str(e)))
        except Exception as e:
            logger.error(str(e))
            results.append(DownloadResult(input=rec, status=DownloadStatus.FAILED, error=str(e)))

    return results


# ─── Parallel ─────────────────────────────────────────────────────

def run_parallel(
    recordings: list[RecordingInput],
    config: Config,
    dry_run: bool = False,
) -> list[DownloadResult]:
    return asyncio.run(_async_run_parallel(recordings, config, dry_run))


async def _async_run_parallel(
    recordings: list[RecordingInput],
    config: Config,
    dry_run: bool = False,
) -> list[DownloadResult]:
    semaphore = asyncio.Semaphore(config.max_parallel)
    total = len(recordings)
    results: list[Optional[DownloadResult]] = [None] * total
    titles: list[str] = [f"recording {i+1}" for i in range(total)]

    with Progress(
        TextColumn("  [bright_green]■[/bright_green]"),
        TextColumn("{task.description}", justify="left"),
        BarColumn(
            bar_width=25,
            style="dim",
            complete_style="bright_green",
            finished_style="bold bright_green",
        ),
        DownloadColumn(),
        TextColumn("[muted]·[/muted]"),
        TransferSpeedColumn(),
        TextColumn("[muted]·[/muted]"),
        TimeRemainingColumn(compact=True),
        console=console,
    ) as progress:
        task_ids = []
        for i in range(total):
            tid = progress.add_task(f"[{i+1}/{total}] queued", total=None, visible=True)
            task_ids.append(tid)

        async def download_one(index: int, rec: RecordingInput):
            async with semaphore:
                try:
                    progress.update(task_ids[index], description=f"[{index+1}/{total}] capturing...")
                    captured = await _async_capture_smart(rec, config)
                    titles[index] = captured.title

                    if dry_run:
                        results[index] = DownloadResult(
                            input=rec, status=DownloadStatus.COMPLETED, duration_seconds=0,
                        )
                        progress.update(task_ids[index], description=f"[{index+1}/{total}] done  {captured.title[:30]}")
                        return

                    progress.update(task_ids[index], description=f"[{index+1}/{total}] {captured.title[:30]}")
                    result = await async_download_recording(
                        captured, config, progress=progress, task_id=task_ids[index],
                    )
                    results[index] = result

                    status_icon = {
                        DownloadStatus.COMPLETED: "done",
                        DownloadStatus.SKIPPED: "skipped",
                    }.get(result.status, "failed")
                    progress.update(task_ids[index], description=f"[{index+1}/{total}] {status_icon}  {captured.title[:30]}")

                except (ZoomDLError, Exception) as e:
                    logger.error(f"recording {index+1}: {e}")
                    results[index] = DownloadResult(input=rec, status=DownloadStatus.FAILED, error=str(e))
                    progress.update(task_ids[index], description=f"[{index+1}/{total}] failed")

        tasks = [download_one(i, rec) for i, rec in enumerate(recordings)]
        await asyncio.gather(*tasks)

    return [r for r in results if r is not None]


# ─── Result Formatting ───────────────────────────────────────────

def _print_result(result: DownloadResult):
    if result.status == DownloadStatus.COMPLETED:
        console.print(f"  [bright_green]■[/bright_green] [success]saved[/success] [muted]{result.file_path}[/muted]")
        if result.file_size > 0:
            console.print(f"  [bright_green]■[/bright_green] [muted]{format_size(result.file_size)} in {format_duration(result.duration_seconds)}[/muted]")
    elif result.status == DownloadStatus.SKIPPED:
        console.print(f"  [yellow]■[/yellow] [warning]skipped[/warning] [muted]{result.file_path}[/muted]")
    elif result.status == DownloadStatus.FAILED:
        console.print(f"  [red]■[/red] [error]failed:[/error] {result.error}")


def print_batch_summary(results: list[DownloadResult]):
    completed = [r for r in results if r.status == DownloadStatus.COMPLETED]
    skipped = [r for r in results if r.status == DownloadStatus.SKIPPED]
    failed = [r for r in results if r.status == DownloadStatus.FAILED]
    total_size = sum(r.file_size for r in completed)
    total_time = sum(r.duration_seconds for r in results)

    console.print()
    parts = []
    if completed:
        parts.append(f"[bright_green]■[/bright_green] [success]{len(completed)} downloaded[/success]")
    if skipped:
        parts.append(f"[yellow]■[/yellow] [warning]{len(skipped)} skipped[/warning]")
    if failed:
        parts.append(f"[red]■[/red] [error]{len(failed)} failed[/error]")

    console.print(f"  {'  '.join(parts)}")

    if total_size > 0:
        console.print(f"  [muted]{format_size(total_size)} in {format_duration(total_time)}[/muted]")

    if failed:
        console.print()
        for r in failed:
            url_snippet = r.input.url[-50:] if r.input else "unknown"
            console.print(f"  [red]■[/red] [muted]...{url_snippet}[/muted]")
            console.print(f"    [muted]{r.error}[/muted]")

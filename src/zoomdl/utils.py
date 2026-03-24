"""Utility functions — logging, filename helpers, file validation."""

import logging
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote

from rich.logging import RichHandler


logger = logging.getLogger("zoomdl")


def setup_logging(level: str = "INFO", quiet: bool = False) -> None:
    """Configure rich-powered logging for the application."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Clear existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    if quiet:
        # Only show errors
        logging.basicConfig(
            level=logging.ERROR,
            format="%(message)s",
            handlers=[RichHandler(show_time=False, show_path=False, markup=True)],
        )
    else:
        logging.basicConfig(
            level=log_level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(
                show_time=log_level <= logging.DEBUG,
                show_path=log_level <= logging.DEBUG,
                markup=True,
                rich_tracebacks=True,
            )],
        )

    # Set our logger level
    logger.setLevel(log_level)


def sanitize_filename(title: str, max_length: int = 200) -> str:
    """Convert a recording title into a safe filename.

    - Strips/replaces illegal filesystem characters
    - Replaces spaces with underscores
    - Truncates to max_length
    """
    if not title:
        return "untitled_recording"

    # Remove/replace illegal chars
    sanitized = re.sub(r'[<>:"/\\|?*]', '', title)

    # Replace spaces and multiple underscores
    sanitized = re.sub(r'\s+', '_', sanitized.strip())
    sanitized = re.sub(r'_+', '_', sanitized)

    # Remove leading/trailing underscores and dots
    sanitized = sanitized.strip('_.')

    # Truncate
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip('_')

    return sanitized or "untitled_recording"


def generate_smart_filename(title: str, date: Optional[str] = None) -> str:
    """Generate a smart filename from recording title and date.

    Examples:
        title="Intro to LAAIC", date="2026-01-20"
        → "2026-01-20_Intro_to_LAAIC.mp4"

        title="Weekly Standup", date=None
        → "Weekly_Standup.mp4"
    """
    sanitized = sanitize_filename(title)
    if date:
        return f"{date}_{sanitized}.mp4"
    return f"{sanitized}.mp4"


def extract_password_from_url(url: str) -> Optional[str]:
    """Extract passcode from a Zoom URL's ?pwd= parameter.

    Returns the raw, un-decoded value. Zoom passcodes can contain
    literal percent-sequences like %50 that must NOT be URL-decoded.
    """
    try:
        parsed = urlparse(url)
        query = parsed.query
        for part in query.split("&"):
            if part.startswith("pwd="):
                return part[4:]
    except Exception:
        pass
    return None


def extract_date_from_url(url: str) -> Optional[str]:
    """Try to extract a date from the Zoom video URL path.

    Zoom URLs often contain: /replay02/2026/01/20/...
    → returns "2026-01-20"
    """
    match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def clean_title(raw_title: str) -> str:
    """Clean a page title from Zoom.

    Removes ' - Zoom' suffix and other noise.
    """
    title = raw_title.strip()
    # Remove common Zoom suffixes
    for suffix in [" - Zoom", " – Zoom", " | Zoom"]:
        if title.endswith(suffix):
            title = title[: -len(suffix)]
    return title.strip()


def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


def is_valid_mp4(filepath: Path) -> bool:
    """Check if a file looks like a valid MP4 by inspecting its header bytes."""
    try:
        if not filepath.exists() or filepath.stat().st_size < 12:
            return False
        with open(filepath, "rb") as f:
            header = f.read(12)
        # MP4 files contain 'ftyp' in the first 12 bytes
        return b"ftyp" in header
    except (OSError, IOError):
        return False


def get_resume_offset(filepath: Path) -> int:
    """Check if a partial download exists and return byte offset to resume from.

    Returns 0 if file doesn't exist or is already a valid MP4.
    """
    if not filepath.exists():
        return 0

    size = filepath.stat().st_size
    if size == 0:
        return 0

    # If it's already a valid MP4, don't resume — it's complete
    if is_valid_mp4(filepath):
        return 0

    # Partial file — resume from current size
    return size

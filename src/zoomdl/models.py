"""Data models for Zoom Downloader."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path


class DownloadMode(Enum):
    """Download mode configuration."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


class DownloadStatus(Enum):
    """Status of a single recording download."""
    PENDING = "pending"
    CAPTURING = "capturing"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class RecordingInput:
    """A single recording to download, parsed from CLI args or urls.txt."""
    url: str
    password: Optional[str] = None  # None = auto-detect from URL or prompt user

    def __str__(self) -> str:
        return f"RecordingInput(url=...{self.url[-30:]}, password={'***' if self.password else 'None'})"


@dataclass
class CapturedRecording:
    """Result of the browser capture phase — contains the signed video URL."""
    input: RecordingInput
    video_url: str
    title: str
    date: Optional[str] = None
    cookies: str = ""
    headers: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"CapturedRecording(title='{self.title}', date={self.date}, url_len={len(self.video_url)})"


@dataclass
class DownloadResult:
    """Final result of a download attempt."""
    input: RecordingInput
    status: DownloadStatus
    file_path: Optional[Path] = None
    file_size: int = 0
    error: Optional[str] = None
    duration_seconds: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.status in (DownloadStatus.COMPLETED, DownloadStatus.SKIPPED)

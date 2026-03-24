"""Configuration management — loads settings from .env with sensible defaults."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .models import DownloadMode


@dataclass
class Config:
    """All configuration for Zoom Downloader, loaded from .env + CLI overrides."""

    # Download behavior
    download_mode: DownloadMode = DownloadMode.SEQUENTIAL
    max_parallel: int = 3
    download_dir: Path = Path("./downloads")
    skip_existing: bool = True

    # Network
    proxy: Optional[str] = None      # HTTP proxy URL, e.g. http://user:pass@host:port
    page_load_timeout: int = 30      # seconds
    download_timeout: int = 1800     # seconds (30 min)
    max_retries: int = 3
    retry_delay: int = 5             # seconds

    # Browser
    use_browser: bool = False  # False = pure HTTP (faster), True = Playwright
    headless: bool = True

    # Logging
    log_level: str = "INFO"

    def __post_init__(self):
        """Validate and normalize config values."""
        self.max_parallel = max(1, min(10, self.max_parallel))
        self.download_dir = Path(self.download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.log_level = self.log_level.upper()
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            self.log_level = "INFO"


def _parse_bool(value: str, default: bool = False) -> bool:
    """Parse a boolean from an env string."""
    if not value:
        return default
    return value.strip().lower() in ("true", "1", "yes", "on")


def _parse_int(value: Optional[str], default: int) -> int:
    """Parse an integer from an env string."""
    if not value:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def load_config(
    env_path: Optional[Path] = None,
    # CLI overrides
    cli_mode: Optional[str] = None,
    cli_workers: Optional[int] = None,
    cli_output: Optional[str] = None,
    cli_headful: bool = False,
    cli_verbose: bool = False,
    cli_quiet: bool = False,
) -> Config:
    """Load configuration from .env file, with CLI overrides taking precedence.

    Priority: CLI flags > .env values > defaults
    """
    # Load .env from project root (or specified path)
    if env_path:
        load_dotenv(env_path)
    else:
        # Search upward from CWD for .env
        load_dotenv()

    # Build config from .env
    raw_proxy = os.getenv("PROXY", "").strip() or None

    config = Config(
        download_mode=DownloadMode(os.getenv("DOWNLOAD_MODE", "sequential").strip().lower()),
        max_parallel=_parse_int(os.getenv("MAX_PARALLEL"), 3),
        download_dir=Path(os.getenv("DOWNLOAD_DIR", "./downloads")),
        skip_existing=_parse_bool(os.getenv("SKIP_EXISTING", "true"), default=True),
        proxy=raw_proxy,
        page_load_timeout=_parse_int(os.getenv("PAGE_LOAD_TIMEOUT"), 30),
        download_timeout=_parse_int(os.getenv("DOWNLOAD_TIMEOUT"), 1800),
        max_retries=_parse_int(os.getenv("MAX_RETRIES"), 3),
        retry_delay=_parse_int(os.getenv("RETRY_DELAY"), 5),
        use_browser=_parse_bool(os.getenv("USE_BROWSER", "false"), default=False),
        headless=_parse_bool(os.getenv("HEADLESS", "true"), default=True),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
    )

    # Apply CLI overrides
    if cli_mode:
        try:
            config.download_mode = DownloadMode(cli_mode.lower())
        except ValueError:
            pass  # Keep .env value

    if cli_workers is not None:
        config.max_parallel = max(1, min(10, cli_workers))

    if cli_output:
        config.download_dir = Path(cli_output)
        config.download_dir.mkdir(parents=True, exist_ok=True)

    if cli_headful:
        config.headless = False

    if cli_verbose:
        config.log_level = "DEBUG"
    elif cli_quiet:
        config.log_level = "ERROR"

    return config


def save_proxy_to_env(proxy: Optional[str], env_path: Optional[Path] = None) -> None:
    """Persist the proxy setting in the .env file so it survives restarts."""
    target = env_path or Path(".env")
    value = proxy or ""

    if target.exists():
        lines = target.read_text().splitlines()
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("PROXY=") or stripped.startswith("PROXY ="):
                lines[i] = f"PROXY={value}"
                found = True
                break
        if not found:
            lines.append(f"PROXY={value}")
        target.write_text("\n".join(lines) + "\n")
    else:
        target.write_text(f"PROXY={value}\n")

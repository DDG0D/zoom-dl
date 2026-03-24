"""Custom exceptions for Zoom Downloader."""


class ZoomDLError(Exception):
    """Base exception for all Zoom Downloader errors."""
    pass


class AuthenticationError(ZoomDLError):
    """Wrong or missing passcode."""
    pass


class CaptureError(ZoomDLError):
    """Could not capture the video URL from the browser."""
    pass


class DownloadError(ZoomDLError):
    """Download failed (network, timeout, corrupt file, etc.)."""
    pass


class ConfigError(ZoomDLError):
    """Invalid configuration."""
    pass

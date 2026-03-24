"""CLI interface — argument parsing, interactive REPL, and main dispatch."""

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from . import __version__, __app_name__
from .config import load_config, save_proxy_to_env
from .models import RecordingInput, DownloadMode
from .utils import setup_logging, extract_password_from_url, logger


THEME = Theme({
    "info": "dim",
    "success": "green",
    "warning": "yellow",
    "error": "red bold",
    "accent": "bright_cyan bold",
    "muted": "dim white",
    "key": "bright_cyan",
    "val": "bold white",
})

console = Console(theme=THEME)


# ─── Banner ───────────────────────────────────────────────────────

def print_banner():
    """Print the big stylish ASCII art banner — ZOOM DL on one line."""
    from rich.text import Text as RichText

    C = "bright_cyan bold"
    M = "bright_magenta bold"

    #          Z          O           O           M                 D          L
    art = [
        [(C,"  ███████╗"), (C," ██████╗ "), (C," ██████╗ "), (C,"███╗   ███╗"), (M,"  ██████╗ "), (M,"██╗     ")],
        [(C,"  ╚══███╔╝"), (C,"██╔═══██╗"), (C,"██╔═══██╗"), (C,"████╗ ████║"), (M,"  ██╔══██╗"), (M,"██║     ")],
        [(C,"    ███╔╝ "), (C,"██║   ██║"), (C,"██║   ██║"), (C,"██╔████╔██║"), (M,"  ██║  ██║"), (M,"██║     ")],
        [(C,"   ███╔╝  "), (C,"██║   ██║"), (C,"██║   ██║"), (C,"██║╚██╔╝██║"), (M,"  ██║  ██║"), (M,"██║     ")],
        [(C,"  ███████╗"), (C,"╚██████╔╝"), (C,"╚██████╔╝"), (C,"██║ ╚═╝ ██║"), (M,"  ██████╔╝"), (M,"███████╗")],
        [(C,"  ╚══════╝"), (C," ╚═════╝ "), (C," ╚═════╝ "), (C,"╚═╝     ╚═╝"), (M,"  ╚═════╝ "), (M,"╚══════╝")],
    ]

    console.print()

    for segments in art:
        row = RichText()
        for style, text in segments:
            row.append(text, style=style)
        console.print(row, highlight=False)

    console.print()
    bar = "  ░▒▓████████████████████████████████████████████████████████████████▓▒░"
    console.print(f"[bright_cyan]{bar}[/bright_cyan]")
    console.print()
    console.print(f"  [bold bright_white] ZOOM DOWNLOADER [/bold bright_white]  [dim]v{__version__}[/dim]  [dim bright_magenta]» grab any zoom recording, no limits[/dim bright_magenta]")
    console.print()
    console.print(f"[bright_cyan]{bar}[/bright_cyan]")
    console.print()


# ─── Argument Parser ──────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zoom_dl",
        description="Download Zoom cloud recordings from share links.",
        epilog="Examples:\n"
               "  zoom_dl --url \"https://zoom.us/rec/share/...?pwd=abc\"\n"
               "  zoom_dl --file urls.txt --mode parallel --workers 4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    source = parser.add_argument_group("source")
    source_exclusive = source.add_mutually_exclusive_group()
    source_exclusive.add_argument("-u", "--url", help="Zoom recording share URL", metavar="URL")
    source_exclusive.add_argument("-f", "--file", help="File with URLs (one per line)", metavar="FILE")

    auth = parser.add_argument_group("authentication")
    auth.add_argument("-p", "--password", help="Recording passcode", metavar="PWD")

    output = parser.add_argument_group("output")
    output.add_argument("-o", "--output", help="Output directory (default: ./downloads)", metavar="DIR")

    network = parser.add_argument_group("network")
    network.add_argument("--proxy", help="HTTP proxy (e.g. http://host:port)", metavar="URL")

    behavior = parser.add_argument_group("download")
    behavior.add_argument("-m", "--mode", choices=["sequential", "parallel"], help="Download mode")
    behavior.add_argument("-w", "--workers", type=int, help="Max parallel downloads", metavar="N")

    flags = parser.add_argument_group("flags")
    flags.add_argument("--browser", action="store_true", help="Use browser instead of HTTP (slower)")
    flags.add_argument("--headful", action="store_true", help="Show browser window (implies --browser)")
    flags.add_argument("--dry-run", action="store_true", help="Capture URL only, don't download")
    flags.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    flags.add_argument("-q", "--quiet", action="store_true", help="Errors only")
    flags.add_argument("--version", action="version", version=f"{__app_name__} v{__version__}")

    return parser


# ─── URL File Parser ──────────────────────────────────────────────

def parse_urls_file(filepath: Path) -> list:
    """Parse a URLs file into RecordingInput objects.

    Formats per line:
        https://zoom.us/rec/share/...?pwd=auto
        https://zoom.us/rec/share/... password
        https://zoom.us/rec/share/...|password with spaces
    """
    if not filepath.exists():
        console.print(f"  [error]file not found:[/error] {filepath}")
        sys.exit(1)

    recordings = []
    for line_num, line in enumerate(filepath.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        url, password = line, None
        if "|" in line:
            parts = line.split("|", 1)
            url = parts[0].strip()
            password = parts[1].strip() if len(parts) > 1 else None
        elif " " in line:
            parts = line.split(None, 1)
            url = parts[0].strip()
            password = parts[1].strip() if len(parts) > 1 else None

        if not password:
            password = extract_password_from_url(url)

        if not url.startswith("http"):
            logger.warning(f"line {line_num}: skipping invalid URL")
            continue

        recordings.append(RecordingInput(url=url, password=password))

    return recordings


# ─── Main Entry ───────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.url and not args.file:
        _run_interactive()
        return

    config = load_config(
        cli_mode=args.mode,
        cli_workers=args.workers,
        cli_output=args.output,
        cli_headful=args.headful,
        cli_verbose=args.verbose,
        cli_quiet=args.quiet,
    )

    if args.browser or args.headful:
        config.use_browser = True

    if args.proxy:
        config.proxy = args.proxy

    setup_logging(level=config.log_level, quiet=args.quiet)

    if not args.quiet:
        print_banner()

    recordings = []

    if args.url:
        password = args.password or extract_password_from_url(args.url)
        recordings.append(RecordingInput(url=args.url, password=password))

    elif args.file:
        filepath = Path(args.file)
        recordings = parse_urls_file(filepath)
        if not recordings:
            console.print("  [error]no valid URLs in file[/error]")
            sys.exit(1)
        console.print(f"  [muted]{len(recordings)} recording(s) from {filepath.name}[/muted]")

    if len(recordings) == 1:
        _run_single(recordings[0], config, dry_run=args.dry_run)
    else:
        _run_batch(recordings, config, dry_run=args.dry_run)


def _capture_smart(recording: RecordingInput, config, prompt_password: bool = True):
    """Capture via pure HTTP, or browser if --browser flag is set."""
    if config.use_browser:
        from .browser import capture_recording
        return capture_recording(recording, config, prompt_password=prompt_password)

    from .http_capture import http_capture_recording
    return http_capture_recording(recording, config, prompt_password=prompt_password)


def _run_single(recording: RecordingInput, config, dry_run: bool = False):
    from .downloader import download_recording
    from .errors import ZoomDLError
    from .utils import format_size, format_duration

    try:
        console.print("  [bright_green]■[/bright_green] [muted]fetching recording details...[/muted]")
        captured = _capture_smart(recording, config)

        console.print(f"  [bright_green]■[/bright_green] [key]Title:[/key]  [val]{captured.title}[/val]")
        if captured.date:
            console.print(f"  [bright_green]■[/bright_green] [key]Date:[/key]   [muted]{captured.date}[/muted]")
        console.print()

        result = download_recording(captured, config, dry_run=dry_run)

        if result.status.value == "completed":
            console.print(f"\n  [bright_green]■[/bright_green] [success]saved[/success] [muted]{result.file_path}[/muted]")
            if result.file_size > 0:
                console.print(f"  [bright_green]■[/bright_green] [muted]{format_size(result.file_size)} in {format_duration(result.duration_seconds)}[/muted]")
        elif result.status.value == "skipped":
            console.print(f"  [yellow]■[/yellow] [warning]skipped[/warning] [muted]{result.file_path}[/muted]")
        elif result.status.value == "failed":
            console.print(f"  [red]■[/red] [error]failed:[/error] {result.error}")
            sys.exit(1)

    except ZoomDLError as e:
        console.print(f"  [red]■[/red] [error]{e}[/error]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n  [yellow]■[/yellow] [warning]interrupted[/warning]")
        sys.exit(130)
    except Exception as e:
        console.print(f"  [red]■[/red] [error]{e}[/error]")
        logger.debug("traceback:", exc_info=True)
        sys.exit(1)


def _run_batch(recordings: list, config, dry_run: bool = False):
    from .batch import run_sequential, run_parallel, print_batch_summary

    try:
        if config.download_mode == DownloadMode.PARALLEL:
            results = run_parallel(recordings, config, dry_run=dry_run)
        else:
            results = run_sequential(recordings, config, dry_run=dry_run)
        print_batch_summary(results)

        failed = [r for r in results if r.status.value == "failed"]
        if failed:
            sys.exit(1)

    except KeyboardInterrupt:
        console.print("\n  [warning]interrupted[/warning]")
        sys.exit(130)
    except Exception as e:
        console.print(f"  [error]{e}[/error]")
        logger.debug("traceback:", exc_info=True)
        sys.exit(1)


# ─── Interactive REPL ─────────────────────────────────────────────

SLASH_COMMANDS = [
    ("/config",   "open settings editor"),
    ("/mode",     "toggle sequential / parallel"),
    ("/workers",  "set parallel workers  (/workers N)"),
    ("/output",   "set output directory  (/output DIR)"),
    ("/proxy",    "setup proxy  (/proxy or /proxy URL)"),
    ("/browser",  "toggle HTTP / browser capture"),
    ("/headful",  "toggle browser visibility"),
    ("/batch",    "batch download multiple URLs"),
    ("/verbose",  "toggle debug logging"),
    ("/env",      "reload settings from .env"),
    ("/clear",    "clear screen"),
    ("/help",     "show CLI flags"),
    ("/quit",     "exit"),
]


def _build_prompt_session():
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style

    class SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor.strip()
            if not text.startswith("/"):
                return
            for cmd, desc in SLASH_COMMANDS:
                if cmd.startswith(text):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=cmd,
                        display_meta=desc,
                    )

    bindings = KeyBindings()

    @bindings.add("?", eager=True)
    def _show_help(event):
        event.current_buffer.insert_text("?")
        event.current_buffer.validate_and_handle()

    style = Style.from_dict({
        "prompt":                                    "ansibrightcyan bold",
        "completion-menu":                           "bg:#1a1a2e #e0e0e0",
        "completion-menu.completion":                "bg:#1a1a2e #e0e0e0",
        "completion-menu.completion.current":         "bg:#16213e #00d4ff bold",
        "completion-menu.meta.completion":            "bg:#1a1a2e #666666 italic",
        "completion-menu.meta.completion.current":    "bg:#16213e #888888 italic",
        "scrollbar.background":                      "bg:#1a1a2e",
        "scrollbar.button":                          "bg:#16213e",
    })

    return PromptSession(
        completer=SlashCompleter(),
        complete_while_typing=True,
        key_bindings=bindings,
        style=style,
    )


def _status_line(config):
    """One-line status showing current mode and output dir."""
    mode = config.download_mode.value
    workers = f"/{config.max_parallel}w" if config.download_mode == DownloadMode.PARALLEL else ""
    capture = "browser" if config.use_browser else "http"
    out = config.download_dir
    proxy_tag = f" · proxy" if config.proxy else ""
    return f"  [muted]{capture}{proxy_tag} · {mode}{workers} · {out}[/muted]"


def _print_help():
    """Clean, minimal help output."""
    console.print()
    console.print("  [accent]Usage[/accent]")
    console.print()
    console.print("    Paste a Zoom URL to download immediately.")
    console.print("    Type [key]/[/key] to see available commands.")
    console.print()
    console.print("  [accent]Commands[/accent]")
    console.print()
    for cmd, desc in SLASH_COMMANDS:
        console.print(f"    [key]{cmd:<14s}[/key] [muted]{desc}[/muted]")
    console.print()
    console.print("  [accent]Quick Actions[/accent]")
    console.print()
    console.print(f"    [key]{'?':<14s}[/key] [muted]show this help[/muted]")
    console.print(f"    [key]{'exit':<14s}[/key] [muted]quit[/muted]")
    console.print(f"    [key]{'Ctrl+C':<14s}[/key] [muted]quit[/muted]")
    console.print()


def _print_config(config):
    """Show current configuration as a clean list."""
    from rich.table import Table

    table = Table(show_header=True, header_style="bold", show_edge=False, box=None, padding=(0, 2))
    table.add_column("Setting", style="bright_cyan")
    table.add_column("Value", style="bold white")

    table.add_row("Download Mode", config.download_mode.value)
    table.add_row("Max Parallel", str(config.max_parallel))
    table.add_row("Output Dir", str(config.download_dir))
    table.add_row("Proxy", _mask_proxy_url(config.proxy) if config.proxy else "off")
    table.add_row("Skip Existing", "on" if config.skip_existing else "off")
    table.add_row("Headless", "on" if config.headless else "off")
    table.add_row("Page Timeout", f"{config.page_load_timeout}s")
    table.add_row("Download Timeout", f"{config.download_timeout}s")
    table.add_row("Max Retries", str(config.max_retries))
    table.add_row("Retry Delay", f"{config.retry_delay}s")
    table.add_row("Log Level", config.log_level)

    panel = Panel(table, title="[bold bright_cyan]Configuration[/bold bright_cyan]",
                  border_style="dim", padding=(1, 2))
    console.print(panel)


# ─── Interactive Config Editor ────────────────────────────────────

CONFIG_SETTINGS = [
    ("download_mode",     "Download Mode",        "cycle",  ["sequential", "parallel"]),
    ("max_parallel",      "Max Parallel",         "number", (1, 10)),
    ("download_dir",      "Output Directory",     "path",   None),
    ("proxy",             "Proxy",                "text",   None),
    ("skip_existing",     "Skip Existing",        "toggle", None),
    ("headless",          "Headless Browser",     "toggle", None),
    ("page_load_timeout", "Page Timeout (s)",     "number", (5, 120)),
    ("download_timeout",  "Download Timeout (s)", "number", (60, 7200)),
    ("max_retries",       "Max Retries",          "number", (0, 10)),
    ("retry_delay",       "Retry Delay (s)",      "number", (1, 60)),
    ("log_level",         "Log Level",            "cycle",  ["DEBUG", "INFO", "WARNING", "ERROR"]),
]


def _interactive_config(config):
    """Full-screen navigable settings editor.

    ↑↓ navigate, Enter toggle/edit, ←→ cycle, Esc to exit.
    """
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout

    selected_idx = 0
    editing_idx = -1
    edit_buffer = ""
    error_msg = ""
    total = len(CONFIG_SETTINGS)

    def _val(key):
        val = getattr(config, key)
        if key == "download_mode":
            return val.value
        if key == "headless":
            return "on" if val else "off"
        if key == "skip_existing":
            return "on" if val else "off"
        if key == "proxy":
            return _mask_proxy_url(val) if val else "off"
        return str(val)

    def _hint(stype):
        if stype == "toggle":
            return "enter toggle"
        if stype == "cycle":
            return "←→ cycle"
        return "enter to edit"

    def _render():
        lines = []
        lines.append(("bold", "\n  Settings\n"))
        lines.append(("class:muted", "  ↑↓ navigate  enter edit  ←→ cycle  esc back\n\n"))

        for i, (key, label, stype, opts) in enumerate(CONFIG_SETTINGS):
            is_sel = i == selected_idx
            is_edit = i == editing_idx
            marker = "› " if is_sel else "  "
            lbl = f"{label:<24s}"
            val = _val(key)

            if is_edit:
                line_text = f"  {marker}{lbl} {edit_buffer}█"
                if is_sel:
                    lines.append(("bg:#1a1a2e bold #00d4ff", line_text))
                else:
                    lines.append(("", line_text))
            elif is_sel:
                lines.append(("bg:#1a1a2e bold #00d4ff", f"  {marker}{lbl} "))
                lines.append(("bg:#1a1a2e bold #ffffff", val))
                lines.append(("bg:#1a1a2e #555555", f"  {_hint(stype)}"))
            else:
                lines.append(("#888888", f"  {marker}{lbl} "))
                lines.append(("#cccccc", val))

            lines.append(("", "\n"))

        if error_msg:
            lines.append(("", "\n"))
            lines.append(("ansired bold", f"  {error_msg}"))

        lines.append(("", "\n"))
        return lines

    kb = KeyBindings()

    def _cycle_setting(direction):
        key, label, stype, opts = CONFIG_SETTINGS[selected_idx]
        if stype == "toggle":
            setattr(config, key, not getattr(config, key))
        elif stype == "cycle":
            current = getattr(config, key)
            current_val = current.value if key == "download_mode" else current
            idx = opts.index(current_val) if current_val in opts else 0
            new_val = opts[(idx + direction) % len(opts)]
            if key == "download_mode":
                config.download_mode = DownloadMode(new_val)
            else:
                setattr(config, key, new_val)
            if key == "log_level":
                setup_logging(level=new_val)

    @kb.add("up")
    def _up(event):
        nonlocal selected_idx, error_msg
        if editing_idx >= 0:
            return
        error_msg = ""
        selected_idx = (selected_idx - 1) % total

    @kb.add("down")
    def _down(event):
        nonlocal selected_idx, error_msg
        if editing_idx >= 0:
            return
        error_msg = ""
        selected_idx = (selected_idx + 1) % total

    @kb.add("left")
    def _left(event):
        nonlocal error_msg
        if editing_idx >= 0:
            return
        error_msg = ""
        _cycle_setting(-1)

    @kb.add("right")
    def _right(event):
        nonlocal error_msg
        if editing_idx >= 0:
            return
        error_msg = ""
        _cycle_setting(1)

    @kb.add("enter")
    def _enter(event):
        nonlocal editing_idx, edit_buffer, error_msg
        key, label, stype, opts = CONFIG_SETTINGS[selected_idx]
        error_msg = ""

        if stype in ("toggle", "cycle"):
            _cycle_setting(1)
            return

        if editing_idx >= 0:
            if stype == "number":
                lo, hi = opts
                try:
                    val = int(edit_buffer)
                    if lo <= val <= hi:
                        setattr(config, key, val)
                    else:
                        error_msg = f"must be {lo}–{hi}"
                except ValueError:
                    error_msg = "enter a number"
            elif stype == "path":
                if edit_buffer.strip():
                    try:
                        p = Path(edit_buffer.strip())
                        p.mkdir(parents=True, exist_ok=True)
                        config.download_dir = p
                    except Exception as e:
                        error_msg = str(e)
            elif stype == "text":
                raw = edit_buffer.strip()
                new_val = raw if raw and raw.lower() not in ("off", "none", "") else None
                setattr(config, key, new_val)
                if key == "proxy":
                    save_proxy_to_env(new_val)
            editing_idx = -1
            edit_buffer = ""
        else:
            editing_idx = selected_idx
            current_val = getattr(config, key)
            edit_buffer = str(current_val) if current_val is not None else ""

    @kb.add("escape")
    def _escape(event):
        nonlocal editing_idx, edit_buffer, error_msg
        if editing_idx >= 0:
            editing_idx = -1
            edit_buffer = ""
            error_msg = ""
        else:
            event.app.exit()

    @kb.add("c-c")
    def _ctrl_c(event):
        event.app.exit()

    @kb.add("q")
    def _quit(event):
        nonlocal edit_buffer
        if editing_idx >= 0:
            edit_buffer += "q"
        else:
            event.app.exit()

    @kb.add("backspace")
    def _backspace(event):
        nonlocal edit_buffer
        if editing_idx >= 0:
            edit_buffer = edit_buffer[:-1]

    @kb.add("<any>")
    def _any_key(event):
        nonlocal edit_buffer
        if editing_idx >= 0:
            ch = event.data
            if ch.isprintable() and len(ch) == 1:
                edit_buffer += ch

    body = HSplit([
        Window(content=FormattedTextControl(_render), always_hide_cursor=True),
    ])

    app = Application(layout=Layout(body), key_bindings=kb, full_screen=False, mouse_support=False)
    app.run()
    return config


# ─── Interactive Download ─────────────────────────────────────────

def _do_interactive_download(url: str, password, config):
    from .downloader import download_recording
    from .utils import format_size, format_duration

    recording = RecordingInput(url=url, password=password)

    console.print("  [bright_green]■[/bright_green] [muted]fetching recording details...[/muted]")
    captured = _capture_smart(recording, config, prompt_password=True)

    console.print(f"  [bright_green]■[/bright_green] [key]Title:[/key]  [val]{captured.title}[/val]")
    if captured.date:
        console.print(f"  [bright_green]■[/bright_green] [key]Date:[/key]   [muted]{captured.date}[/muted]")
    console.print()

    result = download_recording(captured, config)

    if result.status.value == "completed":
        console.print(f"\n  [bright_green]■[/bright_green] [success]saved[/success] [muted]{result.file_path}[/muted]")
        if result.file_size > 0:
            console.print(f"  [bright_green]■[/bright_green] [muted]{format_size(result.file_size)} in {format_duration(result.duration_seconds)}[/muted]")
    elif result.status.value == "skipped":
        console.print(f"  [yellow]■[/yellow] [warning]already exists[/warning] [muted]{result.file_path}[/muted]")
    else:
        console.print(f"  [red]■[/red] [error]failed:[/error] {result.error}")


# ─── Proxy Helpers ────────────────────────────────────────────────

def _mask_proxy_url(url: str) -> str:
    """Mask password in a proxy URL for display: http://user:****@host:port"""
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    if parsed.password:
        masked = parsed._replace(
            netloc=f"{parsed.username}:****@{parsed.hostname}"
            + (f":{parsed.port}" if parsed.port else "")
        )
        return urlunparse(masked)
    return url


def _interactive_proxy_setup(config):
    """Guided proxy setup — prompts for host, port, and optional credentials."""
    from rich.prompt import Prompt

    if config.proxy:
        masked = _mask_proxy_url(config.proxy)
        console.print(f"  [bright_green]■[/bright_green] [muted]current proxy: {masked}[/muted]")
        console.print()

    console.print("  [accent]Proxy Setup[/accent]")
    console.print("  [muted]Leave blank to skip a field. Type [/muted][key]off[/key][muted] to disable.[/muted]")
    console.print()

    host = Prompt.ask("  [key]Host[/key] [muted](e.g. 127.0.0.1 or proxy.example.com)[/muted]", default="").strip()

    if not host:
        if config.proxy:
            console.print("  [muted]proxy unchanged[/muted]")
        else:
            console.print("  [muted]no proxy set[/muted]")
        return config

    if host.lower() in ("off", "none", "disable", "clear"):
        config.proxy = None
        save_proxy_to_env(None)
        console.print("  [bright_green]■[/bright_green] [success]proxy disabled[/success]")
        return config

    port = Prompt.ask("  [key]Port[/key] [muted](e.g. 8080)[/muted]", default="").strip()
    user = Prompt.ask("  [key]Username[/key] [muted](blank if none)[/muted]", default="").strip()
    pwd = ""
    if user:
        pwd = Prompt.ask("  [key]Password[/key] [muted](blank if none)[/muted]", password=True, default="").strip()

    # Build the URL
    if user and pwd:
        from urllib.parse import quote
        auth = f"{quote(user, safe='')}:{quote(pwd, safe='')}@"
    elif user:
        from urllib.parse import quote
        auth = f"{quote(user, safe='')}@"
    else:
        auth = ""

    proxy_url = f"http://{auth}{host}"
    if port:
        proxy_url += f":{port}"

    config.proxy = proxy_url
    save_proxy_to_env(proxy_url)

    masked = _mask_proxy_url(proxy_url)
    console.print(f"\n  [bright_green]■[/bright_green] [success]proxy set:[/success] [muted]{masked}[/muted]")
    console.print(f"  [muted]saved to .env — persists across restarts[/muted]")
    return config


# ─── Slash Command Handler ────────────────────────────────────────

def _handle_slash_command(user_input: str, config):
    """Handle slash commands. Returns (config, should_break)."""
    parts = user_input.split()
    cmd = parts[0] if parts else user_input

    if cmd in ("/quit", "/exit"):
        return config, True

    if cmd == "/config":
        config = _interactive_config(config)
        return config, False

    if cmd == "/mode":
        if config.download_mode == DownloadMode.SEQUENTIAL:
            config.download_mode = DownloadMode.PARALLEL
            console.print(f"  [success]parallel[/success] [muted](max {config.max_parallel} workers)[/muted]")
        else:
            config.download_mode = DownloadMode.SEQUENTIAL
            console.print(f"  [success]sequential[/success]")
        return config, False

    if cmd == "/workers":
        if len(parts) == 2 and parts[1].isdigit():
            n = max(1, min(10, int(parts[1])))
            config.max_parallel = n
            console.print(f"  [success]workers set to {n}[/success]")
        else:
            console.print("  [muted]usage: /workers <1-10>[/muted]")
        return config, False

    if cmd == "/output":
        if len(parts) >= 2:
            new_dir = Path(" ".join(parts[1:]).strip())
            try:
                new_dir.mkdir(parents=True, exist_ok=True)
                config.download_dir = new_dir
                console.print(f"  [success]output dir:[/success] {new_dir}")
            except Exception as e:
                console.print(f"  [error]{e}[/error]")
        else:
            console.print(f"  [muted]current: {config.download_dir}[/muted]")
        return config, False

    if cmd == "/proxy":
        if len(parts) >= 2:
            val = " ".join(parts[1:]).strip()
            if val.lower() in ("off", "none", "clear", "disable", ""):
                config.proxy = None
                save_proxy_to_env(None)
                console.print("  [bright_green]■[/bright_green] [success]proxy disabled[/success]")
            else:
                config.proxy = val
                save_proxy_to_env(val)
                _mask = _mask_proxy_url(val)
                console.print(f"  [bright_green]■[/bright_green] [success]proxy set:[/success] [muted]{_mask}[/muted]")
        else:
            config = _interactive_proxy_setup(config)
        return config, False

    if cmd == "/browser":
        config.use_browser = not config.use_browser
        mode = "browser (playwright)" if config.use_browser else "http (no browser)"
        console.print(f"  [success]capture: {mode}[/success]")
        return config, False

    if cmd == "/headful":
        config.headless = not config.headless
        config.use_browser = True
        state = "headless" if config.headless else "headful"
        console.print(f"  [success]browser: {state}[/success]")
        return config, False

    if cmd == "/verbose":
        if config.log_level == "DEBUG":
            config.log_level = "INFO"
            setup_logging(level="INFO")
            console.print(f"  [success]verbose off[/success]")
        else:
            config.log_level = "DEBUG"
            setup_logging(level="DEBUG")
            console.print(f"  [success]verbose on[/success]")
        return config, False

    if cmd == "/env":
        config = load_config()
        setup_logging(level=config.log_level)
        console.print(f"  [success]reloaded from .env[/success]")
        return config, False

    if cmd == "/version":
        console.print(f"  [muted]{__app_name__} v{__version__}[/muted]")
        return config, False

    if cmd == "/clear":
        console.clear()
        print_banner()
        return config, False

    if cmd == "/help":
        build_parser().print_help()
        return config, False

    if cmd == "/batch":
        _interactive_batch(config)
        return config, False

    console.print(f"  [error]unknown command:[/error] {cmd}")
    console.print(f"  [muted]type / to see commands[/muted]")
    return config, False


# ─── Interactive REPL ─────────────────────────────────────────────

def _run_interactive():
    """REPL-style interactive mode.

    - Paste a URL to download
    - Type / for command completion
    - Type ? for help
    """
    from prompt_toolkit.formatted_text import ANSI

    config = load_config()
    setup_logging(level=config.log_level)
    session = _build_prompt_session()

    print_banner()
    console.print("  Paste a Zoom link to download, or type [key]?[/key] for help.")
    console.print(_status_line(config))
    console.print()

    prompt_text = ANSI("\033[36m  ❯ \033[0m")

    while True:
        try:
            user_input = session.prompt(prompt_text).strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            break

        if not user_input:
            continue

        if user_input == "?":
            _print_help()
            continue

        if user_input in ("exit", "quit", "q"):
            break

        if user_input.startswith("/"):
            config, should_break = _handle_slash_command(user_input, config)
            if should_break:
                break
            continue

        if user_input.startswith("http"):
            url = user_input
            password = extract_password_from_url(url)
            if password:
                console.print(f"  [muted]passcode detected[/muted]")
            console.print()

            try:
                _do_interactive_download(url, password, config)
            except Exception as e:
                console.print(f"  [error]{e}[/error]")

            console.print()
            console.print(_status_line(config))
            console.print()
            continue

        console.print(f"  [muted]unrecognized input — type ? for help[/muted]")


# ─── Batch Mode ───────────────────────────────────────────────────

def _interactive_batch(config):
    """Interactively collect URLs then download them all."""
    console.print()
    console.print("  [accent]Batch Mode[/accent]")
    console.print("  [muted]Paste URLs one per line. Formats:[/muted]")
    console.print("  [muted]  URL   URL password   URL|password[/muted]")
    console.print("  [muted]Type done to start, cancel to abort.[/muted]")
    console.print()

    recordings = []
    while True:
        try:
            line = console.input(f"  [key]{len(recordings)+1:>3}[/key] [muted]›[/muted] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("  [muted]cancelled[/muted]")
            return

        if not line:
            continue
        if line.lower() == "cancel":
            console.print("  [muted]cancelled[/muted]")
            return
        if line.lower() == "done":
            break

        url, password = line, None
        if "|" in line:
            parts = line.split("|", 1)
            url, password = parts[0].strip(), parts[1].strip()
        elif " " in line:
            parts = line.split(None, 1)
            url, password = parts[0].strip(), parts[1].strip()

        if not password:
            password = extract_password_from_url(url)

        if not url.startswith("http"):
            console.print("    [error]invalid URL[/error]")
            continue

        recordings.append(RecordingInput(url=url, password=password))
        console.print(f"    [success]added[/success] [muted]({len(recordings)} queued)[/muted]")

    if not recordings:
        console.print("  [muted]nothing to download[/muted]")
        return

    mode = config.download_mode.value
    workers = f", {config.max_parallel} workers" if config.download_mode == DownloadMode.PARALLEL else ""
    console.print(f"\n  downloading {len(recordings)} recording(s) [muted]({mode}{workers})[/muted]\n")

    from .batch import run_sequential, run_parallel, print_batch_summary

    try:
        if config.download_mode == DownloadMode.PARALLEL:
            results = run_parallel(recordings, config)
        else:
            results = run_sequential(recordings, config)
        print_batch_summary(results)
    except Exception as e:
        console.print(f"  [error]{e}[/error]")

    console.print()


if __name__ == "__main__":
    main()

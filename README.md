<p align="center">
  <br />
  <strong>ZOOM DL</strong>
  <br />
  <em>Download Zoom cloud recordings from share links — no limits, no browser required.</em>
  <br /><br />
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-22c55e?style=flat-square" alt="License: MIT"></a>
  <a href="#features"><img src="https://img.shields.io/badge/mode-HTTP%20%7C%20Browser-8b5cf6?style=flat-square" alt="HTTP + Browser"></a>
</p>

---

## What is this?

A command-line tool that downloads Zoom cloud recordings from share links. Paste a URL, enter the passcode if needed, and the recording lands on your disk — as a full-quality `.mp4`.

Works with **password-protected** recordings, handles **batch downloads**, supports **resume**, **retry**, and **proxy** — all from your terminal.

## Features

- **Pure HTTP capture** — no browser needed, fast and lightweight
- **Browser fallback** — Playwright-based automation when HTTP is blocked
- **Interactive REPL** — paste URLs, manage settings, all in one session
- **Batch downloads** — from a file or interactively, sequential or parallel
- **Resume interrupted downloads** — picks up where it left off
- **Auto-detect passcodes** — reads `?pwd=` from the URL automatically
- **Proxy support** — HTTP proxy with auth, persists across sessions
- **Smart filenames** — auto-names from meeting topic + date
- **Progress bar** — speed, ETA, percentage in your terminal
- **Retry with backoff** — handles network failures gracefully
- **`.env` configuration** — all settings in one file

## Quick Start

### Prerequisites

- Python 3.9 or higher
- pip (Python package manager)

### Installation

```bash
# Clone the repository
git clone https://github.com/DDG0D/zoom-dl.git
cd zoom-dl

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate    # macOS / Linux
# venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# (Optional) Install browser engine — only needed if using --browser mode
playwright install chromium
```

### Configuration

```bash
# Copy the example config
cp .env.example .env

# Edit as needed (all settings are optional — defaults work fine)
```

### Download a recording

```bash
# Passcode auto-detected from the URL
python zoom_dl.py --url "https://zoom.us/rec/share/abc123?pwd=mypasscode"

# Passcode provided separately
python zoom_dl.py --url "https://zoom.us/rec/share/abc123" --password "secretpass"

# Interactive mode — just run without arguments
python zoom_dl.py
```

## Usage

### Interactive Mode (recommended)

Launch without arguments for the full interactive experience:

```bash
python zoom_dl.py
```

You get a REPL where you can:
- **Paste URLs** to download immediately
- **Type `/`** to see all commands
- **Type `?`** for help

```
  ███████╗  ██████╗  ██████╗ ███╗   ███╗  ██████╗ ██╗
  ╚══███╔╝ ██╔═══██╗██╔═══██╗████╗ ████║  ██╔══██╗██║
    ███╔╝  ██║   ██║██║   ██║██╔████╔██║  ██║  ██║██║
   ███╔╝   ██║   ██║██║   ██║██║╚██╔╝██║  ██║  ██║██║
  ███████╗ ╚██████╔╝╚██████╔╝██║ ╚═╝ ██║  ██████╔╝███████╗
  ╚══════╝  ╚═════╝  ╚═════╝ ╚═╝     ╚═╝  ╚═════╝ ╚══════╝

  Paste a Zoom link to download, or type ? for help.
  http · sequential · ./downloads

  ❯ https://zoom.us/rec/share/abc123?pwd=auto
  ■ fetching recording details...
  ■ Title:  Weekly Team Standup
  ■ Date:   2026-03-20

  ■ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 234.7 MB · 6.2 MB/s · 0:00

  ■ saved downloads/2026-03-20_Weekly_Team_Standup.mp4
  ■ 234.7 MB in 38s
```

#### REPL Commands

| Command | Description |
|---------|-------------|
| `/proxy` | Interactive proxy setup (persists to `.env`) |
| `/proxy URL` | Set proxy directly (e.g. `/proxy http://host:port`) |
| `/proxy off` | Disable proxy |
| `/mode` | Toggle sequential / parallel download mode |
| `/workers N` | Set parallel worker count (1–10) |
| `/output DIR` | Change output directory |
| `/browser` | Toggle HTTP / browser capture |
| `/headful` | Toggle browser visibility |
| `/batch` | Enter batch mode (paste multiple URLs) |
| `/config` | Open interactive settings editor |
| `/verbose` | Toggle debug logging |
| `/env` | Reload settings from `.env` |
| `/clear` | Clear screen |
| `/help` | Show CLI flags |
| `/quit` | Exit |

### CLI Mode

#### Single recording

```bash
python zoom_dl.py --url "https://zoom.us/rec/share/abc123"
python zoom_dl.py --url "https://zoom.us/rec/share/abc123" --password "pass"
python zoom_dl.py --url "https://zoom.us/rec/share/abc123" --proxy http://host:port
```

#### Batch download

Create a `urls.txt` file:

```text
# One URL per line. Lines starting with # are comments.

# Passcode auto-detected from ?pwd=
https://zoom.us/rec/share/abc123?pwd=auto_detected

# URL + password (space-separated)
https://zoom.us/rec/share/def456 my_password

# URL + password with special chars (pipe-separated)
https://zoom.us/rec/share/ghi789|my password here
```

Then run:

```bash
# Sequential (one at a time)
python zoom_dl.py --file urls.txt

# Parallel (multiple at once)
python zoom_dl.py --file urls.txt --mode parallel --workers 4
```

### All CLI Flags

| Flag | Description |
|------|-------------|
| `-u, --url URL` | Zoom recording share URL |
| `-f, --file FILE` | Text file with URLs (one per line) |
| `-p, --password PWD` | Recording passcode |
| `-o, --output DIR` | Output directory (default: `./downloads`) |
| `--proxy URL` | HTTP proxy (e.g. `http://host:port` or `http://user:pass@host:port`) |
| `-m, --mode MODE` | `sequential` or `parallel` |
| `-w, --workers N` | Max parallel downloads (1–10) |
| `--browser` | Use Playwright browser instead of HTTP |
| `--headful` | Show browser window (implies `--browser`) |
| `--dry-run` | Capture signed URL only, don't download |
| `-v, --verbose` | Debug logging |
| `-q, --quiet` | Errors only |
| `--version` | Show version |

## Proxy Support

Useful when Zoom blocks requests with CAPTCHA or Cloudflare challenges.

### Setting a proxy

**Interactive setup** (recommended — prompts for host, port, username, password):

```bash
# In the REPL:
❯ /proxy
```

**One-liner:**

```bash
# In the REPL:
❯ /proxy http://127.0.0.1:8080
❯ /proxy http://user:pass@proxy.example.com:3128

# Or via CLI flag:
python zoom_dl.py --url "..." --proxy http://127.0.0.1:8080

# Or in .env:
PROXY=http://user:pass@proxy.example.com:3128
```

**Disabling:**

```bash
❯ /proxy off
```

Proxy settings are **saved to `.env`** automatically and persist across restarts. Credentials are masked in all terminal output.

## Configuration

All settings can be configured via `.env`, CLI flags, or interactively in the REPL.

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `DOWNLOAD_MODE` | `sequential` | `sequential` or `parallel` |
| `MAX_PARALLEL` | `3` | Concurrent downloads in parallel mode (1–10) |
| `DOWNLOAD_DIR` | `./downloads` | Output directory |
| `SKIP_EXISTING` | `true` | Skip already-downloaded files |
| `PROXY` | _(none)_ | HTTP proxy URL |
| `USE_BROWSER` | `false` | Use Playwright browser instead of HTTP |
| `HEADLESS` | `true` | Run browser in headless mode |
| `PAGE_LOAD_TIMEOUT` | `30` | Page load timeout in seconds |
| `DOWNLOAD_TIMEOUT` | `1800` | Download timeout in seconds (30 min) |
| `MAX_RETRIES` | `3` | Retry attempts on failure |
| `RETRY_DELAY` | `5` | Base delay between retries in seconds |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

**Priority:** CLI flags > `.env` values > built-in defaults.

## How It Works

Zoom DL operates in two capture modes:

### HTTP Mode (default)

The default and fastest mode. Makes direct HTTP requests to Zoom's internal API to retrieve the signed CloudFront video URL — no browser needed.

1. Loads the share page to establish session cookies
2. Queries Zoom's recording API for meeting metadata
3. Authenticates with the passcode if required
4. Retrieves the signed MP4 URL from the play info API
5. Downloads the full video with resume and retry support

### Browser Mode (`--browser`)

Falls back to Playwright-controlled Chromium. Useful when Zoom's anti-bot measures block HTTP requests.

1. Launches headless Chromium via Playwright
2. Navigates to the share page and enters the passcode
3. Intercepts the browser's network request to capture the signed video URL
4. Downloads the MP4 using the captured URL

Switch between modes with `--browser` flag or `/browser` in the REPL.

## Project Structure

```
zoom-dl/
├── zoom_dl.py              # Entry point
├── src/zoomdl/
│   ├── __init__.py         # Version and metadata
│   ├── cli.py              # CLI parser, interactive REPL, banner
│   ├── config.py           # Configuration loading from .env
│   ├── http_capture.py     # Pure HTTP recording capture
│   ├── browser.py          # Playwright browser capture (fallback)
│   ├── downloader.py       # Download engine (resume, progress, retry)
│   ├── batch.py            # Batch orchestration (sequential + parallel)
│   ├── models.py           # Data classes and enums
│   ├── errors.py           # Custom exception hierarchy
│   └── utils.py            # Logging, filename helpers, validation
├── .env.example            # Configuration template
├── requirements.txt        # Python dependencies
├── LICENSE                 # MIT License
└── README.md               # This file
```

## Troubleshooting

### "Zoom blocked the request (CAPTCHA/Cloudflare)"

Zoom detected automated access. Solutions:

1. **Use a proxy:** `/proxy` in the REPL or `--proxy http://host:port`
2. **Use a rotating proxy** for repeated downloads
3. **Switch to browser mode:** `--browser` (slower but bypasses some blocks)
4. **Use a VPN** to change your IP

### "Wrong passcode"

The recording password is incorrect. Double-check:
- Special characters (e.g. `%`, `$`, `!`) may need quoting in your shell
- Use `--password` flag or let the tool prompt you interactively

### "Access denied (403) — signed URL expired"

The download URL has a time-limited signature. Just re-run the command — it will fetch a fresh URL.

### Download stalls or is very slow

- Check your network connection
- Try a proxy or VPN
- The download engine automatically retries on failure (configurable via `MAX_RETRIES`)

## Requirements

- **Python** 3.9+
- **Dependencies** (installed via `pip install -r requirements.txt`):
  - `httpx` — HTTP client for capture and download
  - `rich` — Terminal UI (progress bars, styled output)
  - `python-dotenv` — `.env` file loading
  - `prompt_toolkit` — Interactive REPL with completion
  - `playwright` — Browser automation (optional, only for `--browser` mode)

## License

MIT — see [LICENSE](LICENSE) for details.

---

<p align="center">
  <sub>Built for personal use. Not affiliated with Zoom Video Communications, Inc.</sub>
</p>

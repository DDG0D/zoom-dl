# Contributing

Thanks for your interest in contributing to Zoom DL.

## Getting Started

```bash
# Clone and set up dev environment
git clone https://github.com/DDG0D/zoom-dl.git
cd zoom-dl
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Development

```bash
# Run the tool
python zoom_dl.py

# Run with debug logging
python zoom_dl.py -v

# Dry run (captures URL without downloading)
python zoom_dl.py --url "..." --dry-run
```

## Project Layout

All source code lives in `src/zoomdl/`:

| Module | Purpose |
|--------|---------|
| `cli.py` | Argument parsing, interactive REPL, banner |
| `config.py` | Configuration from `.env` with CLI overrides |
| `http_capture.py` | Pure HTTP recording capture (default) |
| `browser.py` | Playwright browser capture (fallback) |
| `downloader.py` | Download engine with resume, progress, retry |
| `batch.py` | Sequential and parallel batch orchestration |
| `models.py` | Data classes and enums |
| `errors.py` | Custom exception hierarchy |
| `utils.py` | Shared helpers: logging, filenames, validation |

## Guidelines

- Keep the code readable and well-typed
- Test changes against a real Zoom recording URL
- Don't commit `.env`, credentials, or real URLs
- Update the README if you add user-facing features

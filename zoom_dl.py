#!/usr/bin/env python3
"""Zoom Downloader — Entry point.

Usage:
    python zoom_dl.py --url "https://zoom.us/rec/share/..."
    python zoom_dl.py --url "https://zoom.us/rec/share/..." --password "mypass"
    python zoom_dl.py --file urls.txt
    python zoom_dl.py --file urls.txt --mode parallel --workers 4
    python zoom_dl.py --help
"""

import sys
import os

# Add src/ to path so we can import zoomdl
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from zoomdl.cli import main

if __name__ == "__main__":
    main()

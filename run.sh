#!/usr/bin/env bash
# Run EinkMapTiles from source on Linux/macOS.
# Requirements: Python 3.10+, pip install -r requirements.txt

set -e
cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
    echo "Python 3 not found. Install it with your package manager." >&2
    exit 1
fi

# Install dependencies if not already present
python3 -c "import eink_map_tiles" 2>/dev/null || pip3 install -r requirements.txt

python3 launch.py

#!/usr/bin/env bash
# Launch script for Foss49Key Relay & Reverse Proxy Gateway
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
export PYTHONPATH="$DIR/..:$PYTHONPATH"
python3 "$DIR/relay_server.py" "$@"


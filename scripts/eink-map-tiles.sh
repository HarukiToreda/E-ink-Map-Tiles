#!/usr/bin/env bash

set -euo pipefail

script_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
app_root="$(cd -- "$script_root/.." && pwd)"
desktop_root="$app_root/src"
web_root="$app_root/webui"
ui="tkinter"
web_host="127.0.0.1"
web_port="8765"
open_browser=true
allow_remote=false
web_option_used=false
unknown_arguments=()

usage() {
    cat <<'EOF'
Usage: ./scripts/eink-map-tiles.sh [--ui=tkinter|web] [options]

Interfaces:
  --ui=tkinter          Start the original Python/Tk application (default)
  --ui=web              Start the browser application with Node.js and Vite

Web options:
  --host HOST           Bind address (default: 127.0.0.1)
  --port PORT           Preferred port (default: 8765)
  --no-open             Do not open the browser automatically
  --allow-remote        Permit a non-loopback bind address

General options:
  -h, --help            Show this help
EOF
}

require_value() {
    local option="$1"
    local value="${2-}"
    if [[ -z "$value" ]]; then
        echo "eink-map-tiles: $option requires a value" >&2
        exit 2
    fi
}

while (($#)); do
    case "$1" in
        --ui)
            require_value "$1" "${2-}"
            ui="$2"
            shift 2
            ;;
        --ui=*)
            ui="${1#*=}"
            shift
            ;;
        --host)
            require_value "$1" "${2-}"
            web_host="$2"
            web_option_used=true
            shift 2
            ;;
        --host=*)
            web_host="${1#*=}"
            require_value "--host" "$web_host"
            web_option_used=true
            shift
            ;;
        --port)
            require_value "$1" "${2-}"
            web_port="$2"
            web_option_used=true
            shift 2
            ;;
        --port=*)
            web_port="${1#*=}"
            require_value "--port" "$web_port"
            web_option_used=true
            shift
            ;;
        --no-open)
            open_browser=false
            web_option_used=true
            shift
            ;;
        --allow-remote)
            allow_remote=true
            web_option_used=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            unknown_arguments+=("$1")
            shift
            ;;
    esac
done

if [[ "$ui" != "tkinter" && "$ui" != "web" ]]; then
    echo "eink-map-tiles: --ui must be 'tkinter' or 'web'" >&2
    exit 2
fi

if ((${#unknown_arguments[@]})); then
    echo "eink-map-tiles: unrecognized arguments: ${unknown_arguments[*]}" >&2
    exit 2
fi

if [[ ! "$web_port" =~ ^[0-9]+$ ]] || ((10#$web_port < 1 || 10#$web_port > 65535)); then
    echo "eink-map-tiles: --port must be an integer from 1 through 65535" >&2
    exit 2
fi

if [[ "$ui" == "tkinter" ]]; then
    if [[ "$web_option_used" == true ]]; then
        echo "eink-map-tiles: --host, --port, --no-open, and --allow-remote require --ui=web" >&2
        exit 2
    fi

    if [[ -x "$app_root/.venv/bin/python" ]]; then
        app_python="$app_root/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        app_python="$(command -v python3)"
    else
        echo "eink-map-tiles: Python 3 was not found" >&2
        exit 1
    fi

    if [[ ! -f "$desktop_root/eink_map_tiles/desktop_app.py" ]]; then
        echo "eink-map-tiles: desktop application source is missing from \"$desktop_root\"" >&2
        exit 1
    fi

    PYTHONPATH="$desktop_root${PYTHONPATH:+:$PYTHONPATH}" \
        exec "$app_python" -m eink_map_tiles.desktop_app
fi

case "$web_host" in
    127.0.0.1|localhost|::1|'[::1]') ;;
    *)
        if [[ "$allow_remote" != true ]]; then
            echo "eink-map-tiles: non-loopback binding requires --allow-remote" >&2
            exit 2
        fi
        ;;
esac

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "eink-map-tiles: Node.js 22 or newer and npm are required for --ui=web" >&2
    exit 1
fi

node_major="$(node --eval 'process.stdout.write(process.versions.node.split(".")[0])')"
if ((node_major < 22)); then
    echo "eink-map-tiles: Node.js 22 or newer is required (found $(node --version))" >&2
    exit 1
fi

vite_entry="$web_root/node_modules/vite/bin/vite.js"
if [[ ! -d "$web_root/node_modules" ]]; then
    echo "E-ink Map Tiles: installing Web UI dependencies with npm ci..."
    npm --prefix "$web_root" ci
fi

if [[ ! -f "$vite_entry" ]]; then
    echo "eink-map-tiles: Web UI dependencies are incomplete" >&2
    echo "Remove \"$web_root/node_modules\" and launch Web mode again" >&2
    exit 1
fi

vite_arguments=(--host "$web_host" --port "$web_port")
if [[ "$open_browser" == true ]]; then
    vite_arguments+=(--open)
fi

npm --prefix "$web_root" run build
exec node "$vite_entry" preview "$web_root" "${vite_arguments[@]}"

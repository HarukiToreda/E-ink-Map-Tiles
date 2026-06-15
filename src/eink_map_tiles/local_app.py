from __future__ import annotations

import io
import json
import sys
import tempfile
import webbrowser
from contextlib import redirect_stdout
from datetime import datetime
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import cli


HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def project_docs_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", Path.cwd())) / "docs"
        if bundled.exists():
            return bundled
    return Path(__file__).resolve().parents[2] / "docs"


def default_output_root(style: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_style = "".join(char if char.isalnum() or char in "._-" else "-" for char in style) or "osm-eink"
    return Path.home() / "Downloads" / "EinkMapTiles" / f"{safe_style}-{timestamp}"


class LocalAppHandler(SimpleHTTPRequestHandler):
    server_version = "EinkMapTilesLocal/0.1"

    def do_GET(self) -> None:
        if self.path == "/api/status":
            self.send_json({"localApp": True})
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/api/export":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        try:
            payload = self.read_json_body()
            result = self.run_export(payload)
        except Exception as exc:  # noqa: BLE001 - API should return readable local-app errors.
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self.send_json(result)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("Request body is empty")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def run_export(self, job: dict[str, Any]) -> dict[str, Any]:
        url_template = str(job.get("urlTemplate") or "").strip()
        if not url_template:
            raise ValueError("Add a legal tile URL template before exporting locally.")
        if "{z}" not in url_template or "{x}" not in url_template or "{y}" not in url_template:
            raise ValueError("Tile URL template must include {z}, {x}, and {y}.")

        style = str(job.get("style") or "osm-eink")
        output_root = default_output_root(style)
        output_root.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="eink-map-tiles-job-") as temp_dir:
            job_path = Path(temp_dir) / "inkhud-tile-job.json"
            job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")

            stdout = io.StringIO()
            argv = ["--job", str(job_path), "--output", str(output_root), "--zip"]
            with redirect_stdout(stdout):
                exit_code = cli.main(argv)
            if exit_code:
                raise RuntimeError(f"Export failed with exit code {exit_code}")

        zip_path = output_root.with_suffix(".zip")
        return {
            "outputPath": str(output_root),
            "zipPath": str(zip_path) if zip_path.exists() else None,
            "log": stdout.getvalue(),
        }

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[local-app] {self.address_string()} - {format % args}")


def run(host: str = HOST, port: int = DEFAULT_PORT, open_browser: bool = True) -> int:
    docs_dir = project_docs_dir()
    if not docs_dir.exists():
        raise SystemExit(f"Could not find docs directory: {docs_dir}")

    handler = partial(LocalAppHandler, directory=str(docs_dir))
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{server.server_port}/"
    print(f"E-ink Map Tiles local app: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the local E-ink Map Tiles app.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser automatically")
    args = parser.parse_args(argv)
    return run(host=args.host, port=args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    raise SystemExit(main())

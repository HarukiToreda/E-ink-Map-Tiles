from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "eink-map-tiles.sh"
POWERSHELL_LAUNCHER = ROOT / "scripts" / "eink-map-tiles.ps1"


def run_launcher(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(LAUNCHER), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_help_describes_both_independent_runtimes() -> None:
    result = run_launcher("--help")

    assert result.returncode == 0
    assert "--ui=tkinter" in result.stdout
    assert "--ui=web" in result.stdout
    assert "Python/Tk" in result.stdout
    assert "Node.js and Vite" in result.stdout


def test_platform_launchers_expose_the_same_options_and_runtime_steps() -> None:
    shell = LAUNCHER.read_text(encoding="utf-8")
    powershell = POWERSHELL_LAUNCHER.read_text(encoding="utf-8")

    for option in ("--ui", "--host", "--port", "--no-open", "--allow-remote"):
        assert option in shell
        assert option in powershell
    for runtime_step in ('"src"', "npm ci", '"run" "build"', "preview"):
        assert runtime_step in powershell


def test_unknown_ui_is_rejected() -> None:
    result = run_launcher("--ui=terminal")

    assert result.returncode == 2
    assert "--ui must be 'tkinter' or 'web'" in result.stderr


def test_web_rejects_remote_binding_without_explicit_permission() -> None:
    result = run_launcher("--ui=web", "--host", "0.0.0.0", "--no-open")

    assert result.returncode == 2
    assert "non-loopback binding requires --allow-remote" in result.stderr


def test_tkinter_rejects_web_server_options() -> None:
    result = run_launcher("--ui=tkinter", "--port", "9000")

    assert result.returncode == 2
    assert "require --ui=web" in result.stderr


def test_default_executes_desktop_module_from_src(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    desktop_root = app_root / "src"
    fake_python = app_root / ".venv" / "bin" / "python"
    launcher = app_root / "scripts" / "eink-map-tiles.sh"
    command_log = tmp_path / "desktop-command.log"
    (desktop_root / "eink_map_tiles").mkdir(parents=True)
    (desktop_root / "eink_map_tiles" / "desktop_app.py").touch()
    fake_python.parent.mkdir(parents=True)
    launcher.parent.mkdir()
    shutil.copy2(LAUNCHER, launcher)
    fake_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" "$PYTHONPATH" > "$COMMAND_LOG"
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    result = subprocess.run(
        [str(launcher)],
        cwd=app_root,
        env={**os.environ, "COMMAND_LOG": str(command_log)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    command, python_path = command_log.read_text(encoding="utf-8").splitlines()
    assert command == "-m eink_map_tiles.desktop_app"
    assert python_path.split(":", 1)[0] == str(desktop_root)


def test_web_installs_missing_dependencies_before_build_and_preview(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    web_root = app_root / "webui"
    fake_bin = tmp_path / "bin"
    launcher = app_root / "scripts" / "eink-map-tiles.sh"
    command_log = tmp_path / "commands.log"
    web_root.mkdir(parents=True)
    fake_bin.mkdir()
    launcher.parent.mkdir()
    shutil.copy2(LAUNCHER, launcher)

    fake_node = fake_bin / "node"
    fake_node.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1-}" == "--eval" ]]; then
    printf '22'
    exit 0
fi
printf 'node %s\\n' "$*" >> "$COMMAND_LOG"
""",
        encoding="utf-8",
    )
    fake_node.chmod(0o755)

    fake_npm = fake_bin / "npm"
    fake_npm.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'npm %s\\n' "$*" >> "$COMMAND_LOG"
if [[ "${*: -1}" == "ci" ]]; then
    mkdir -p "$WEB_ROOT/node_modules/vite/bin"
    : > "$WEB_ROOT/node_modules/vite/bin/vite.js"
fi
""",
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)

    environment = {
        **os.environ,
        "COMMAND_LOG": str(command_log),
        "WEB_ROOT": str(web_root),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
    }
    result = subprocess.run(
        [str(launcher), "--ui=web", "--no-open"],
        cwd=app_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "installing Web UI dependencies with npm ci" in result.stdout
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert commands == [
        f"npm --prefix {web_root} ci",
        f"npm --prefix {web_root} run build",
        f"node {web_root}/node_modules/vite/bin/vite.js preview {web_root} --host 127.0.0.1 --port 8765",
    ]

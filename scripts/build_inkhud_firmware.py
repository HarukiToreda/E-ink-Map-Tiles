#!/usr/bin/env python3
"""
build_inkhud_firmware.py

Copies a MapTile.h into the Meshtastic firmware repo and builds
firmware for every InkHUD-capable device via PlatformIO.

Usage:
    python scripts/build_inkhud_firmware.py --tile MapTile.h --firmware c:/firmware
    python scripts/build_inkhud_firmware.py --tile MapTile.h --firmware c:/firmware --env tlora-t3s3-epaper-inkhud
    python scripts/build_inkhud_firmware.py --tile MapTile.h --firmware c:/firmware --list
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# All InkHUD PlatformIO environments, grouped by chip family.
# env          – PlatformIO environment name (pio run -e <env>)
# label        – human-friendly device name shown in output
# flash_mb     – total flash in MB (for context only)
# ---------------------------------------------------------------------------
INKHUD_TARGETS = [
    # ── ESP32-S3 ────────────────────────────────────────────────────────────
    {
        "env":      "tlora-t3s3-epaper-inkhud",
        "label":    "LilyGO T3S3 ePaper (4 MB)",
        "flash_mb": 4,
        "chip":     "esp32s3",
    },
    {
        "env":      "t5s3_epaper_inkhud",
        "label":    "LilyGO T5S3 ePaper (16 MB)",
        "flash_mb": 16,
        "chip":     "esp32s3",
    },
    {
        "env":      "heltec-wireless-paper-inkhud",
        "label":    "Heltec Wireless Paper (8 MB)",
        "flash_mb": 8,
        "chip":     "esp32s3",
    },
    {
        "env":      "heltec-vision-master-e213-inkhud",
        "label":    "Heltec Vision Master E213 (8 MB)",
        "flash_mb": 8,
        "chip":     "esp32s3",
    },
    {
        "env":      "heltec-vision-master-e290-inkhud",
        "label":    "Heltec Vision Master E290 (8 MB)",
        "flash_mb": 8,
        "chip":     "esp32s3",
    },
    {
        "env":      "mini-epaper-s3-inkhud",
        "label":    "Mini ePaper S3 (4 MB)",
        "flash_mb": 4,
        "chip":     "esp32s3",
    },
    # ── nRF52840 ────────────────────────────────────────────────────────────
    {
        "env":      "t-echo-inkhud",
        "label":    "LilyGO T-Echo (1 MB)",
        "flash_mb": 1,
        "chip":     "nrf52840",
    },
    {
        "env":      "nrf52_promicro_diy-inkhud",
        "label":    "nRF52 ProMicro DIY (1 MB)",
        "flash_mb": 1,
        "chip":     "nrf52840",
    },
    {
        "env":      "thinknode_m1-inkhud",
        "label":    "Elecrow ThinkNode M1 (1 MB)",
        "flash_mb": 1,
        "chip":     "nrf52840",
    },
    {
        "env":      "heltec-mesh-node-t114-inkhud",
        "label":    "Heltec Mesh Node T114 (1 MB)",
        "flash_mb": 1,
        "chip":     "nrf52840",
    },
    {
        "env":      "heltec-mesh-pocket-5000-inkhud",
        "label":    "Heltec Mesh Pocket 5000 mAh (1 MB)",
        "flash_mb": 1,
        "chip":     "nrf52840",
    },
    {
        "env":      "heltec-mesh-pocket-10000-inkhud",
        "label":    "Heltec Mesh Pocket 10000 mAh (1 MB)",
        "flash_mb": 1,
        "chip":     "nrf52840",
    },
    {
        "env":      "heltec-mesh-solar-inkhud",
        "label":    "Heltec Mesh Solar (1 MB)",
        "flash_mb": 1,
        "chip":     "nrf52840",
    },
    {
        "env":      "seeed_wio_tracker_L1_eink-inkhud",
        "label":    "Seeed Wio Tracker L1 eink (1 MB)",
        "flash_mb": 1,
        "chip":     "nrf52840",
    },
]

MAPTILE_DEST = Path("src/graphics/niche/InkHUD/Applets/Bases/Map/MapTile.h")


def find_pio(firmware_root: Path | None = None) -> str:
    """Locate the pio / platformio executable."""
    import os, glob as _glob

    # 1. System PATH
    for candidate in ("pio", "platformio"):
        found = shutil.which(candidate)
        if found:
            return found

    home = Path.home()
    candidates = []

    # 2. pip user install (AppData\Roaming\Python\PythonXXX\Scripts)
    roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    for scripts in _glob.glob(str(roaming / "Python" / "Python*" / "Scripts")):
        candidates += [Path(scripts) / "pio.exe", Path(scripts) / "platformio.exe"]

    # 3. ~/.platformio/penv (classic PlatformIO Core install)
    candidates += [
        home / ".platformio" / "penv" / "Scripts" / "pio.exe",
        home / ".platformio" / "penv" / "Scripts" / "platformio.exe",
        home / ".platformio" / "penv" / "bin" / "pio",
    ]

    # 4. VS Code PlatformIO extension bundled penv
    ext_root = home / ".vscode" / "extensions"
    if ext_root.is_dir():
        for ext_dir in sorted(ext_root.glob("platformio.platformio-ide-*"), reverse=True):
            for subpath in ("penv/Scripts/pio.exe", "penv/bin/pio",
                            ".venv/Scripts/pio.exe", ".venv/bin/pio"):
                candidates.append(ext_dir / subpath)

    # 5. Firmware repo local .venv (if provided)
    if firmware_root:
        for subpath in (".venv/Scripts/pio.exe", ".venv/bin/pio",
                        "penv/Scripts/pio.exe", "penv/bin/pio"):
            candidates.append(firmware_root / subpath)

    for p in candidates:
        if p.exists():
            return str(p)
    return ""


def validate_args(args) -> None:
    tile = Path(args.tile)
    if not tile.exists():
        sys.exit(f"Error: MapTile.h not found: {tile}")
    if not tile.name.endswith(".h"):
        sys.exit(f"Error: --tile must be a .h header file, got: {tile}")

    fw = Path(args.firmware)
    if not fw.is_dir():
        sys.exit(f"Error: firmware repo not found: {fw}")
    if not (fw / "platformio.ini").exists():
        sys.exit(f"Error: {fw} does not look like a PlatformIO project (no platformio.ini)")


def install_tile(tile_src: Path, firmware_root: Path, dry_run: bool = False) -> Path:
    dest = firmware_root / MAPTILE_DEST
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Copying {tile_src} → {dest}")
    if not dry_run:
        shutil.copy2(tile_src, dest)
    return dest


def build_env(pio: str, firmware_root: Path, env: str, label: str, log_dir: Path) -> bool:
    log_file = log_dir / f"{env}.log"
    print(f"\n{'─'*60}")
    print(f"  Building: {label}")
    print(f"  Env:      {env}")
    print(f"  Log:      {log_file}")
    print(f"{'─'*60}")

    t0 = time.time()
    with open(log_file, "w", encoding="utf-8") as fh:
        result = subprocess.run(
            [pio, "run", "-e", env],
            cwd=firmware_root,
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
    elapsed = time.time() - t0

    if result.returncode == 0:
        print(f"  ✓  SUCCESS  ({elapsed:.0f}s)")
        return True
    else:
        print(f"  ✗  FAILED   ({elapsed:.0f}s)  — see {log_file}")
        # Print last 20 lines of log to help diagnose
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-20:]:
            print(f"     {line}")
        return False


def collect_artifacts(firmware_root: Path, env: str, out_dir: Path) -> list[Path]:
    """Copy .bin / .uf2 build outputs to out_dir."""
    build_dir = firmware_root / ".pio" / "build" / env
    copied = []
    for pattern in ("*.bin", "*.uf2", "*.hex"):
        for f in build_dir.glob(pattern):
            dest = out_dir / f"{env}_{f.name}"
            shutil.copy2(f, dest)
            copied.append(dest)
    return copied


def main():
    parser = argparse.ArgumentParser(
        description="Build Meshtastic InkHUD firmware for all supported devices."
    )
    parser.add_argument(
        "--tile", "-t", required=True,
        help="Path to the MapTile.h file generated by EinkMapTiles",
    )
    parser.add_argument(
        "--firmware", "-f", default="c:/firmware",
        help="Path to the Meshtastic firmware repo (default: c:/firmware)",
    )
    parser.add_argument(
        "--env", "-e", action="append", metavar="ENV",
        help="Build only this environment (may be repeated). Default: all targets.",
    )
    parser.add_argument(
        "--out", "-o", default=None,
        help="Output directory for built firmware files (default: next to MapTile.h)",
    )
    parser.add_argument(
        "--list", "-l", action="store_true",
        help="List all known InkHUD targets and exit.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Copy MapTile.h but do not run any builds.",
    )
    args = parser.parse_args()

    if args.list:
        print("InkHUD build targets:\n")
        for t in INKHUD_TARGETS:
            print(f"  {t['env']:<45} {t['label']}")
        return

    validate_args(args)

    pio = find_pio()
    if not pio:
        sys.exit(
            "Error: PlatformIO CLI ('pio') not found.\n"
            "Install it: https://docs.platformio.org/en/latest/core/installation/"
        )

    tile_src = Path(args.tile).resolve()
    firmware_root = Path(args.firmware).resolve()
    out_dir = Path(args.out).resolve() if args.out else tile_src.parent / "firmware_builds"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = out_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    # Filter targets if --env specified
    if args.env:
        env_set = set(args.env)
        targets = [t for t in INKHUD_TARGETS if t["env"] in env_set]
        unknown = env_set - {t["env"] for t in targets}
        if unknown:
            sys.exit(f"Error: unknown env(s): {', '.join(sorted(unknown))}\nRun --list to see valid targets.")
    else:
        targets = INKHUD_TARGETS

    print(f"\nInkHUD Firmware Builder")
    print(f"  MapTile.h : {tile_src}")
    print(f"  Firmware  : {firmware_root}")
    print(f"  Output    : {out_dir}")
    print(f"  Targets   : {len(targets)}")

    # Install tile
    print(f"\n[1/3] Installing MapTile.h...")
    install_tile(tile_src, firmware_root, dry_run=args.dry_run)

    if args.dry_run:
        print("\nDry run — skipping builds.")
        return

    # Build
    print(f"\n[2/3] Building {len(targets)} target(s)...")
    passed, failed = [], []
    for t in targets:
        ok = build_env(pio, firmware_root, t["env"], t["label"], log_dir)
        if ok:
            passed.append(t)
        else:
            failed.append(t)

    # Collect artifacts
    print(f"\n[3/3] Collecting firmware artifacts...")
    all_artifacts = []
    for t in passed:
        artifacts = collect_artifacts(firmware_root, t["env"], out_dir)
        for a in artifacts:
            print(f"  {a.name}")
        all_artifacts.extend(artifacts)

    # Summary
    print(f"\n{'='*60}")
    print(f"  Built:  {len(passed)}/{len(targets)} targets")
    if failed:
        print(f"  Failed: {len(failed)}")
        for t in failed:
            print(f"    ✗ {t['label']} ({t['env']})")
    if all_artifacts:
        print(f"  Output: {out_dir}")
    print(f"{'='*60}\n")

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
InkHUD Firmware Builder — fully standalone Windows EXE.
On first launch, downloads a portable Python and installs PlatformIO locally.
Clones/updates the Meshtastic firmware repo automatically.
No system-level prerequisites required.
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).parent))
from build_inkhud_firmware import INKHUD_TARGETS, MAPTILE_DEST

# ── App data paths ─────────────────────────────────────────────────────────
APP_DATA    = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "InkHUDBuilder"
TOOLS_DIR   = APP_DATA / "tools"
PYTHON_DIR  = TOOLS_DIR / "python"
PIO_EXE     = PYTHON_DIR / "Scripts" / "pio.exe"
PIP_EXE     = PYTHON_DIR / "Scripts" / "pip.exe"
PYTHON_EXE  = PYTHON_DIR / "python.exe"
FIRMWARE_DIR = APP_DATA / "firmware"

FIRMWARE_REPO = "https://github.com/meshtastic/firmware.git"
FIRMWARE_BRANCH = "develop"

PYTHON_URL  = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip"
GETPIP_URL  = "https://bootstrap.pypa.io/get-pip.py"


def _force_rmtree(path: Path) -> None:
    """Remove a directory tree, clearing read-only flags first (needed for .git on Windows)."""
    import stat
    def _on_error(func, fpath, _exc):
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except Exception:
            pass
    if path.exists():
        shutil.rmtree(path, onerror=_on_error)

# ── Colours ────────────────────────────────────────────────────────────────
C_BG      = "#0f172a"
C_PANEL   = "#1e293b"
C_BORDER  = "#334155"
C_TEXT    = "#f1f5f9"
C_MUTED   = "#94a3b8"
C_ACCENT  = "#14b8a6"
C_BTN     = "#334155"
C_BTN_HV  = "#475569"
C_SUCCESS = "#22c55e"
C_FAIL    = "#ef4444"
C_WARN    = "#f59e0b"


# ── First-run setup ────────────────────────────────────────────────────────

def pio_ready() -> bool:
    return PIO_EXE.exists() and PYTHON_EXE.exists()


def git_available() -> bool:
    return shutil.which("git") is not None


def _download(url: str, dest: Path, progress_cb=None) -> None:
    with urllib.request.urlopen(url, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        dest.parent.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total:
                    progress_cb(downloaded / total)


def setup_pio(log_cb, progress_cb):
    """Download portable Python, install pip, install platformio. Runs in a thread."""
    try:
        # Wipe any partial previous install so read-only/locked files don't block us
        if TOOLS_DIR.exists():
            log_cb("Cleaning up previous (incomplete) install…", "warn")
            _force_rmtree(TOOLS_DIR)
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Download Python embeddable
        py_zip = TOOLS_DIR / "python.zip"
        log_cb("── Step 1/4: Downloading portable Python 3.12 ──", "step")
        log_cb(f"  Source: {PYTHON_URL}")
        last_pct = [-1]
        def py_progress(p):
            pct = int(p * 100)
            if pct != last_pct[0] and pct % 10 == 0:
                log_cb(f"  {pct}%…")
                last_pct[0] = pct
            progress_cb(p * 0.35, f"Downloading Python… {pct}%")
        _download(PYTHON_URL, py_zip, py_progress)
        log_cb("  Download complete.", "ok")

        # 2. Extract
        log_cb("── Step 2/4: Extracting Python ──", "step")
        progress_cb(0.35, "Extracting Python…")
        if PYTHON_DIR.exists():
            _force_rmtree(PYTHON_DIR)
        with zipfile.ZipFile(py_zip, "r") as z:
            z.extractall(PYTHON_DIR)
        py_zip.unlink()
        for pth in PYTHON_DIR.glob("python*._pth"):
            text = pth.read_text()
            text = text.replace("#import site", "import site")
            pth.write_text(text)
        log_cb(f"  Extracted to {PYTHON_DIR}", "ok")

        # 3. Download + install pip
        log_cb("── Step 3/4: Installing pip ──", "step")
        get_pip = TOOLS_DIR / "get-pip.py"
        log_cb(f"  Source: {GETPIP_URL}")
        _download(GETPIP_URL, get_pip,
                  lambda p: progress_cb(0.40 + p * 0.05, "Downloading pip…"))
        log_cb("  Running get-pip.py…")
        progress_cb(0.46, "Installing pip…")
        result = subprocess.run(
            [str(PYTHON_EXE), str(get_pip), "--no-warn-script-location"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        get_pip.unlink()
        if result.returncode != 0:
            out = (result.stdout or result.stderr or "").strip()
            raise RuntimeError(f"get-pip failed (exit {result.returncode}):\n{out}")
        log_cb("  pip installed.", "ok")

        # 4. Install PlatformIO
        log_cb("── Step 4/4: Installing PlatformIO ──", "step")
        log_cb("  Running: pip install platformio")
        log_cb("  This downloads ~30 MB and may take a minute…", "warn")
        progress_cb(0.50, "Installing PlatformIO…")
        # Use --prefix to force install into the embedded Python, and set
        # PYTHONNOUSERSITE so pip doesn't resolve deps from the system user site.
        pio_env = os.environ.copy()
        pio_env["PYTHONNOUSERSITE"] = "1"
        pio_env.pop("PYTHONPATH", None)
        pio_env.pop("PYTHONUSERBASE", None)
        # setuptools and wheel must be present before pip can build anything
        log_cb("  Installing setuptools + wheel…", "warn")
        pre = subprocess.run(
            [str(PIP_EXE), "install", "setuptools", "wheel",
             "--prefix", str(PYTHON_DIR), "--no-warn-script-location"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=pio_env, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if pre.returncode != 0:
            raise RuntimeError(f"setuptools install failed:\n{pre.stdout.strip()[-600:]}")
        log_cb("  setuptools + wheel installed.", "ok")

        proc = subprocess.Popen(
            [str(PIP_EXE), "install", "platformio", "esptool",
             "--prefix", str(PYTHON_DIR),
             "--no-warn-script-location"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=pio_env, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        pip_lines = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                pip_lines.append(line)
                log_cb(f"  {line}")
        proc.wait()
        if proc.returncode != 0:
            tail = "\n".join(pip_lines[-8:]) if pip_lines else "(no output)"
            raise RuntimeError(f"pip install failed (exit {proc.returncode}):\n{tail}")
        progress_cb(1.0, "Setup complete.")
        log_cb("── Setup complete. PlatformIO is ready. ──", "ok")
        return True

    except Exception as exc:
        log_cb(f"Setup failed: {exc}", "fail")
        return str(exc)


class SetupDialog(tk.Toplevel):
    """Shown on first run to download and install PlatformIO."""

    def __init__(self, parent, on_done):
        super().__init__(parent)
        self.title("First-time setup")
        self.configure(background=C_BG)
        self.resizable(True, False)
        self.minsize(480, 0)
        self.grab_set()
        self._on_done = on_done
        self.columnconfigure(0, weight=1)

        tk.Label(self, text="InkHUD Firmware Builder — First-time setup",
                 bg=C_BG, fg=C_TEXT,
                 font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, pady=(18, 4), padx=24, sticky="w")
        tk.Label(self,
                 text="Downloading a portable Python environment and PlatformIO (~60 MB).\n"
                      "This happens once — subsequent launches are instant.",
                 bg=C_BG, fg=C_MUTED, font=("Segoe UI", 9),
                 justify="left").grid(row=1, column=0, padx=24, pady=(0, 10), sticky="w")

        # Log pane
        log_wrap = tk.Frame(self, bg=C_BORDER, padx=1, pady=1)
        log_wrap.grid(row=2, column=0, padx=24, sticky="ew")
        log_wrap.columnconfigure(0, weight=1)
        self._log_text = tk.Text(
            log_wrap, background=C_PANEL, foreground=C_TEXT,
            font=("Consolas", 8), relief="flat", height=10,
            wrap="word",
        )
        log_sb = ttk.Scrollbar(log_wrap, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_sb.set)
        self._log_text.grid(row=0, column=0, sticky="ew")
        log_sb.grid(row=0, column=1, sticky="ns")
        self._log_text.tag_configure("ok",   foreground=C_SUCCESS)
        self._log_text.tag_configure("warn", foreground=C_WARN)
        self._log_text.tag_configure("fail", foreground=C_FAIL)
        self._log_text.tag_configure("step", foreground=C_ACCENT, font=("Consolas", 8, "bold"))

        # Progress bar
        self._bar = ttk.Progressbar(self, style="TProgressbar",
                                    mode="determinate", maximum=1)
        self._bar.grid(row=3, column=0, padx=24, sticky="ew", pady=(10, 4))

        self._status_var = tk.StringVar(value="Starting…")
        tk.Label(self, textvariable=self._status_var, bg=C_BG, fg=C_MUTED,
                 font=("Segoe UI", 8)).grid(row=4, column=0, padx=24, pady=(0, 16), sticky="w")

        self.after(200, self._start)

    def _write(self, msg: str, tag: str = ""):
        """Must be called on the main thread only."""
        self._log_text.insert("end", msg + "\n", tag)
        self._log_text.see("end")
        self._status_var.set(msg)

    def _start(self):
        def log(msg, tag=""):
            # after() is safe to call from any thread; callback runs on main thread
            self.after(0, lambda m=msg, t=tag: self._write(m, t))

        def progress(frac, label=None):
            self.after(0, lambda f=frac: self._bar.configure(value=f))
            if label:
                self.after(0, lambda l=label: self._status_var.set(l))

        def run():
            result = setup_pio(log, progress)
            self.after(0, lambda: self._finish(result))

        threading.Thread(target=run, daemon=True).start()

    def _finish(self, result):
        self.grab_release()
        self.destroy()
        self._on_done(result is True, result if result is not True else None)


# ── Main app ───────────────────────────────────────────────────────────────

class BuilderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("InkHUD Firmware Builder")
        self.configure(background=C_BG)
        self.resizable(True, True)
        self.minsize(680, 520)

        self._build_thread: threading.Thread | None = None
        self._cancel_flag = threading.Event()
        self._pio_proc: subprocess.Popen | None = None
        self._log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._selected_target: dict | None = None

        self._configure_styles()
        self._build_ui()
        self._poll_log()
        self._refresh_ports()

        self.after(200, self._check_first_run)

    def _check_first_run(self):
        if not pio_ready():
            self._build_btn.configure(state="disabled")
            self._upload_btn.configure(state="disabled")
            SetupDialog(self, self._on_setup_done)

    def _on_setup_done(self, ok: bool, error: str | None = None):
        if ok:
            self._build_btn.configure(state="normal")
            self._upload_btn.configure(state="normal")
            self._update_setup_status()
            self._emit("PlatformIO ready. Select a target and MapTile.h to begin.", "ok")
        else:
            detail = f"\n\nError: {error}" if error else ""
            self._emit(f"Setup failed: {error or 'unknown error'}", "fail")
            messagebox.showerror("Setup failed",
                                 f"Could not install PlatformIO.{detail}\n\n"
                                 "Check your internet connection and restart the app.")

    # ── Styles ────────────────────────────────────────────────────────────

    def _configure_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", font=("Segoe UI", 9),
                    background=C_BG, foreground=C_TEXT,
                    bordercolor=C_BORDER, relief="flat")
        s.configure("TFrame", background=C_BG)
        s.configure("Panel.TFrame", background=C_PANEL)
        s.configure("TLabel", background=C_BG, foreground=C_TEXT)
        s.configure("Muted.TLabel", background=C_BG, foreground=C_MUTED)
        s.configure("Head.TLabel", background=C_PANEL, foreground=C_TEXT,
                    font=("Segoe UI", 9, "bold"))
        s.configure("TEntry", fieldbackground=C_PANEL, foreground=C_TEXT,
                    insertcolor=C_TEXT, bordercolor=C_BORDER)
        s.configure("TCombobox", fieldbackground=C_PANEL, foreground=C_TEXT,
                    selectbackground=C_PANEL, selectforeground=C_TEXT,
                    arrowcolor=C_MUTED, bordercolor=C_BORDER)
        s.map("TCombobox", fieldbackground=[("readonly", C_PANEL)])
        s.configure("TScrollbar", background=C_BTN, troughcolor=C_PANEL,
                    bordercolor=C_BORDER, arrowcolor=C_MUTED)
        s.configure("TProgressbar", troughcolor=C_PANEL, background=C_ACCENT)
        s.configure("TCheckbutton", background=C_PANEL, foreground=C_TEXT,
                    indicatorcolor=C_BTN, focuscolor=C_PANEL)
        s.map("TCheckbutton", indicatorcolor=[("selected", C_ACCENT)])

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)

        # Top panel: MapTile.h + setup status
        top = ttk.Frame(self, style="Panel.TFrame", padding=10)
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="MapTile.h", style="Head.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10))
        _TILE_PLACEHOLDER = "Generate MapTile.h from the EinkMapTiles tool, then browse here…"
        self._tile_entry = ttk.Entry(top, foreground=C_MUTED)
        self._tile_entry.insert(0, _TILE_PLACEHOLDER)
        self._tile_entry.grid(row=0, column=1, sticky="ew")

        def _tile_focus_in(_e):
            if self._tile_entry.get() == _TILE_PLACEHOLDER:
                self._tile_entry.delete(0, "end")
                self._tile_entry.configure(foreground=C_TEXT)
        def _tile_focus_out(_e):
            if not self._tile_entry.get().strip():
                self._tile_entry.configure(foreground=C_MUTED)
                self._tile_entry.insert(0, _TILE_PLACEHOLDER)
        self._tile_entry.bind("<FocusIn>", _tile_focus_in)
        self._tile_entry.bind("<FocusOut>", _tile_focus_out)
        self._btn(top, "Browse…", self._browse_tile).grid(row=0, column=2, padx=(6, 0))

        # Firmware repo info row
        fw_info = tk.Frame(top, bg=C_PANEL)
        fw_info.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        fw_info.columnconfigure(2, weight=1)
        tk.Label(fw_info, text="Firmware", bg=C_PANEL, fg=C_MUTED,
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self._branch_var = tk.StringVar(value=FIRMWARE_BRANCH)
        branch_combo = ttk.Combobox(fw_info, textvariable=self._branch_var,
                                    values=["develop", "master"],
                                    state="readonly", width=10)
        branch_combo.grid(row=0, column=1, padx=(0, 10))
        branch_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_fw_status())
        self._fw_status_var = tk.StringVar(value="")
        tk.Label(fw_info, textvariable=self._fw_status_var, bg=C_PANEL, fg=C_MUTED,
                 font=("Segoe UI", 8)).grid(row=0, column=2, sticky="w")
        self._update_fw_status()

        # Setup status row
        setup_row = tk.Frame(top, bg=C_PANEL)
        setup_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        setup_row.columnconfigure(0, weight=1)
        self._setup_status = tk.Label(setup_row, text="", bg=C_PANEL, fg=C_MUTED,
                                      font=("Segoe UI", 8))
        self._setup_status.grid(row=0, column=0, sticky="w")
        self._clean_btn = self._btn(setup_row, "Clean all", self._clean_setup, small=True)
        self._clean_btn.grid(row=0, column=1)
        self._update_setup_status()

        # Device selection — single grouped dropdown
        dev_frame = ttk.Frame(self, style="Panel.TFrame", padding=(10, 10))
        dev_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        dev_frame.columnconfigure(1, weight=1)

        ttk.Label(dev_frame, text="Target device", style="Head.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10))

        # Build flat list with group headers (headers start with "─")
        _HDR = "─"
        esp_targets = [t for t in INKHUD_TARGETS if t["chip"] == "esp32s3"]
        nrf_targets = [t for t in INKHUD_TARGETS if t["chip"] == "nrf52840"]
        combo_values = (
            [f"{_HDR} ESP32-S3 {_HDR*30}"]
            + [f"  ● {t['label']}" for t in esp_targets]
            + [f"{_HDR} nRF52840 {_HDR*30}"]
            + [f"  ◆ {t['label']}" for t in nrf_targets]
        )
        # Map display label → target dict (headers map to None)
        self._combo_targets = {}
        for v, t in zip(combo_values[1:1+len(esp_targets)], esp_targets):
            self._combo_targets[v] = t
        for v, t in zip(combo_values[2+len(esp_targets):], nrf_targets):
            self._combo_targets[v] = t

        self._device_var = tk.StringVar()
        self._device_combo = ttk.Combobox(dev_frame, textvariable=self._device_var,
                                          values=combo_values, state="readonly", width=48)
        self._device_combo.grid(row=0, column=1, sticky="ew")
        self._device_combo.bind("<<ComboboxSelected>>", self._on_device_select)

        # Flash options
        flash_frame = ttk.Frame(self, style="Panel.TFrame", padding=(10, 8))
        flash_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
        flash_frame.columnconfigure(1, weight=1)
        flash_frame.columnconfigure(3, weight=2)

        self._upload_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(flash_frame, text="Flash after build",
                        variable=self._upload_var,
                        command=self._on_upload_toggle).grid(row=0, column=0, sticky="w")

        self._port_label = ttk.Label(flash_frame, text="COM port", style="Head.TLabel")
        self._port_label.grid(row=0, column=2, sticky="e", padx=(20, 6))
        self._port_var = tk.StringVar()
        self._port_combo = ttk.Combobox(flash_frame, textvariable=self._port_var,
                                        state="readonly", width=38)
        self._port_combo.grid(row=0, column=3, sticky="ew")
        self._refresh_btn = self._btn(flash_frame, "↻", self._refresh_ports, small=True)
        self._refresh_btn.grid(row=0, column=4, padx=(6, 0))

        # Actions
        actions = ttk.Frame(self, padding=(10, 4))
        actions.grid(row=3, column=0, sticky="ew")
        actions.columnconfigure(3, weight=1)

        self._build_btn = self._btn(actions, "⬡  Build", self._start_build, accent=True)
        self._build_btn.grid(row=0, column=0)
        self._upload_btn = self._btn(actions, "⬆  Upload", self._start_upload)
        self._upload_btn.grid(row=0, column=1, padx=(8, 0))
        self._cancel_btn = self._btn(actions, "Cancel", self._cancel_build)
        self._cancel_btn.grid(row=0, column=2, padx=(8, 0))
        self._cancel_btn.configure(state="disabled")
        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(actions, textvariable=self._status_var,
                  style="Muted.TLabel").grid(row=0, column=3, sticky="e")

        self._progress = ttk.Progressbar(self, mode="indeterminate")
        self._progress.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 2))
        self._progress.grid_remove()

        # Log
        log_frame = ttk.Frame(self, padding=(10, 4, 10, 10))
        log_frame.grid(row=5, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self._log = tk.Text(
            log_frame, background=C_PANEL, foreground=C_TEXT,
            insertbackground=C_TEXT, relief="flat", wrap="word",
            font=("Consolas", 8), state="disabled", height=10,
        )
        self._log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(log_frame, orient="vertical", command=self._log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._log.configure(yscrollcommand=sb.set)
        self._log.tag_configure("ok",    foreground=C_SUCCESS)
        self._log.tag_configure("fail",  foreground=C_FAIL)
        self._log.tag_configure("head",  foreground=C_ACCENT)
        self._log.tag_configure("muted", foreground=C_MUTED)
        self._log.tag_configure("warn",  foreground=C_WARN)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _btn(self, parent, text, cmd, accent=False, small=False, **kw):
        bg    = C_ACCENT if accent else C_BTN
        hover = "#0d9488" if accent else C_BTN_HV
        fg    = C_BG if accent else C_TEXT
        pad   = (5, 2) if small else (14, 6)
        b = tk.Button(parent, text=text, command=cmd,
                      background=bg, foreground=fg,
                      activebackground=hover, activeforeground=fg,
                      relief="flat", bd=0, padx=pad[0], pady=pad[1],
                      cursor="hand2", **kw)
        b.bind("<Enter>", lambda _e, b=b: b.configure(background=hover))
        b.bind("<Leave>", lambda _e, b=b: b.configure(background=bg))
        return b

    def _emit(self, msg: str, tag: str = ""):
        self._log_queue.put((msg, tag))

    def _poll_log(self):
        try:
            while True:
                msg, tag = self._log_queue.get_nowait()
                self._log.configure(state="normal")
                self._log.insert("end", msg + "\n", tag)
                self._log.see("end")
                self._log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(80, self._poll_log)

    def _browse_tile(self):
        p = filedialog.askopenfilename(
            title="Select MapTile.h",
            filetypes=[("C header", "*.h"), ("All files", "*.*")])
        if p:
            self._tile_entry.configure(foreground=C_TEXT)
            self._tile_entry.delete(0, "end")
            self._tile_entry.insert(0, p)
            self._tile_var.set(p)

    def _update_fw_status(self):
        branch = self._branch_var.get() if hasattr(self, "_branch_var") else FIRMWARE_BRANCH
        if (FIRMWARE_DIR / ".git").exists():
            try:
                result = subprocess.run(
                    ["git", "-C", str(FIRMWARE_DIR), "log", "-1", "--format=%h %s"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                commit = result.stdout.strip() if result.returncode == 0 else "unknown"
                self._fw_status_var.set(f"meshtastic/firmware — {commit}")
            except Exception:
                self._fw_status_var.set(f"meshtastic/firmware ({branch})")
        else:
            self._fw_status_var.set("Will clone meshtastic/firmware before first build")

    def _update_setup_status(self):
        if pio_ready():
            size_mb = sum(f.stat().st_size for f in TOOLS_DIR.rglob("*") if f.is_file()) / 1e6
            self._setup_status.configure(
                text=f"PlatformIO installed  ({size_mb:.0f} MB in {TOOLS_DIR})",
                fg=C_MUTED,
            )
            self._clean_btn.configure(state="normal")
        else:
            self._setup_status.configure(
                text="PlatformIO not installed — will download automatically.",
                fg=C_WARN,
            )
            self._clean_btn.configure(state="disabled")

    def _clean_setup(self):
        msg = (
            f"Delete the local PlatformIO installation and firmware clone?\n\n"
            f"  {APP_DATA}\n\n"
            "PlatformIO toolchain caches in ~/.platformio are not affected.\n"
            "Everything will be re-downloaded on next build."
        )
        if not messagebox.askyesno("Clean all", msg):
            return
        try:
            _force_rmtree(APP_DATA)
        except Exception as exc:
            messagebox.showerror("Error", f"Could not remove {APP_DATA}:\n{exc}")
            return
        self._build_btn.configure(state="disabled")
        self._emit("Cleaned. Restart the app to re-install.", "warn")
        self._update_setup_status()
        self._update_fw_status()

    def _on_device_select(self, _event=None):
        val = self._device_var.get()
        if val.startswith("─"):
            # Header row selected — revert to previous target label or clear
            prev = self._selected_target
            self._device_var.set(
                next((k for k, v in self._combo_targets.items() if v == prev), "")
            )
            return
        self._selected_target = self._combo_targets.get(val)

    def _on_upload_toggle(self):
        pass

    def _selected_port(self) -> str:
        """Return the raw COM port string (e.g. 'COM4') for the current dropdown selection."""
        label = self._port_var.get().strip()
        return getattr(self, "_port_map", {}).get(label, label)

    def _refresh_ports(self):
        try:
            import serial.tools.list_ports
            infos = serial.tools.list_ports.comports()
        except ImportError:
            infos = []
        # Build "COM4 — Device Name" labels; store mapping back to raw port
        self._port_map: dict[str, str] = {}
        labels = []
        for p in sorted(infos, key=lambda x: x.device):
            desc = p.description or p.device
            # Strip redundant port name that some drivers repeat in description
            if p.device.lower() in desc.lower():
                label = desc
            else:
                label = f"{p.device} — {desc}"
            self._port_map[label] = p.device
            labels.append(label)
        self._port_combo["values"] = labels
        if labels and not self._port_var.get():
            self._port_var.set(labels[0])

    # ── Firmware repo ─────────────────────────────────────────────────────

    def _sync_firmware(self) -> bool:
        """Clone or pull the firmware repo. Returns True on success."""
        if not git_available():
            self._emit("Error: git not found in PATH. Install Git for Windows.", "fail")
            return False

        branch = self._branch_var.get()

        if not (FIRMWARE_DIR / ".git").exists():
            self._emit(f"Cloning meshtastic/firmware ({branch})…", "head")
            self._emit("This may take a few minutes on first use.", "muted")
            rc = self._run_git([
                "clone", "--depth=1", "--branch", branch,
                "--recurse-submodules", "--shallow-submodules",
                FIRMWARE_REPO, str(FIRMWARE_DIR),
            ], cwd=APP_DATA)
        else:
            self._emit(f"Updating meshtastic/firmware ({branch})…", "head")
            rc = self._run_git(
                ["fetch", "--depth=1", "origin", branch],
                cwd=FIRMWARE_DIR,
            )
            if rc == 0:
                rc = self._run_git(
                    ["reset", "--hard", "FETCH_HEAD"],
                    cwd=FIRMWARE_DIR,
                )
            if rc == 0:
                self._run_git(
                    ["submodule", "update", "--init", "--recursive", "--depth=1"],
                    cwd=FIRMWARE_DIR,
                )
            if rc != 0:
                # Repo is corrupt or from a different remote — wipe and re-clone
                self._emit("Repo damaged, re-cloning from scratch…", "warn")
                _force_rmtree(FIRMWARE_DIR)
                rc = self._run_git([
                    "clone", "--depth=1", "--branch", branch,
                    "--recurse-submodules", "--shallow-submodules",
                    FIRMWARE_REPO, str(FIRMWARE_DIR),
                ], cwd=APP_DATA)

        if rc == 0:
            self.after(0, self._update_fw_status)
        return rc == 0

    def _run_git(self, args: list[str], cwd: Path) -> int:
        cwd.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.Popen(
                ["git"] + args, cwd=cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self._emit(f"  {line}", "muted")
                if self._cancel_flag.is_set():
                    proc.terminate()
                    return -1
            proc.wait()
            return proc.returncode
        except Exception as exc:
            self._emit(f"git error: {exc}", "fail")
            return -1

    # ── Build ─────────────────────────────────────────────────────────────

    def _start_build(self):
        _PLACEHOLDER = "Generate MapTile.h from the EinkMapTiles tool, then browse here…"
        tile = self._tile_entry.get().strip()
        if tile == _PLACEHOLDER:
            tile = ""
        if tile and not Path(tile).exists():
            messagebox.showwarning("Missing file", f"MapTile.h not found:\n{tile}")
            return
        tile_src = Path(tile).resolve() if tile else None
        if self._selected_target is None:
            messagebox.showwarning("No target", "Select a target device.")
            return

        do_upload = self._upload_var.get()
        port = self._selected_port() if do_upload else None
        if do_upload and not port:
            messagebox.showwarning("No port", "Select a COM port to flash to.")
            return

        if not pio_ready():
            messagebox.showerror("Not ready", "PlatformIO setup incomplete. Restart the app.")
            return

        target  = self._selected_target
        out_dir = tile_src.parent / "firmware_builds" if tile_src else APP_DATA / "firmware_builds"
        log_dir = out_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        self._kill_pio()
        self._cancel_flag.clear()
        self._build_btn.configure(state="disabled")
        self._upload_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._progress.grid()
        self._progress.start(12)
        action = "Building + Flashing" if port else "Building"
        self._status_var.set(f"{action} {target['label']}…")

        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

        threading.Thread(
            target=self._run_build,
            args=(tile_src, target, port, out_dir, log_dir),
            daemon=True,
        ).start()

    def _start_upload(self):
        """Flash a previously built .bin file without rebuilding."""
        port = self._selected_port()
        if not port:
            messagebox.showerror("No port", "Select a COM port to upload to.")
            return

        # Let user pick a .bin file, defaulting to the output folder
        target = self._selected_target
        default_dir = str(APP_DATA / "firmware_builds")
        bin_path = filedialog.askopenfilename(
            title="Select firmware .bin to upload",
            initialdir=default_dir,
            filetypes=[("Binary files", "*.bin"), ("All files", "*.*")],
        )
        if not bin_path:
            return

        self._cancel_flag.clear()
        self._build_btn.configure(state="disabled")
        self._upload_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._progress.grid()
        self._progress.start(12)
        self._status_var.set(f"Uploading to {port}…")
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

        # Infer chip: use selected target if available, else read mt.json, else auto-detect
        chip = target["chip"] if target else None
        if not chip:
            import json as _j
            p = Path(bin_path)
            mt = p.with_suffix(".mt.json")
            if not mt.exists():
                hits = list(p.parent.glob("*.mt.json"))
                mt = hits[0] if hits else None
            if mt:
                try:
                    chip = _j.loads(mt.read_text()).get("mcu", "auto")
                except Exception:
                    chip = "auto"
            else:
                chip = "auto"

        threading.Thread(
            target=self._run_upload,
            args=(Path(bin_path), port, chip),
            daemon=True,
        ).start()

    def _run_upload(self, bin_file: Path, port: str, chip: str):
        import json as _json

        self._emit(f"Uploading {bin_file.name} → {port}", "head")

        if chip == "nrf52840":
            self._emit("nRF52 devices use UF2 drag-and-drop flashing.", "warn")
            self._emit("Double-tap reset to enter bootloader, then copy the .uf2 file to the drive.", "warn")
            candidates = list(bin_file.parent.glob("*.uf2"))
            if candidates:
                self._emit(f"UF2 file: {candidates[0]}", "muted")
            self.after(0, self._build_done, True)
            return

        # Resolve what to actually flash.
        # Meshtastic produces a .factory.bin (merged: bootloader+partitions+app at 0x0).
        # If user picked the regular .bin, look for the matching .factory.bin alongside it.
        # Fall back to the mt.json partition table if available.
        flash_file = bin_file
        flash_addr = "0x0"

        if not bin_file.name.endswith(".factory.bin"):
            # Look for a .factory.bin with the same stem in the same folder
            factory = bin_file.with_name(bin_file.name.replace(".bin", ".factory.bin"))
            if not factory.exists():
                # Search the build dir for any .factory.bin
                candidates = list(bin_file.parent.glob("*.factory.bin"))
                factory = candidates[0] if candidates else None

            if factory and factory.exists():
                self._emit(f"Using factory image: {factory.name}", "muted")
                flash_file = factory
                flash_addr = "0x0"
            else:
                # Read .mt.json to find the correct offset for the app partition
                mt_json = bin_file.with_suffix(".mt.json")
                if not mt_json.exists():
                    candidates = list(bin_file.parent.glob("*.mt.json"))
                    mt_json = candidates[0] if candidates else None
                if mt_json:
                    try:
                        meta = _json.loads(mt_json.read_text())
                        for part in meta.get("part", []):
                            if part.get("name") == "app0":
                                flash_addr = part["offset"]
                                break
                    except Exception:
                        flash_addr = "0x10000"
                else:
                    flash_addr = "0x10000"
                self._emit(f"No factory image found — flashing app at {flash_addr}", "warn")

        # Determine chip arg for esptool (auto = let esptool detect)
        chip_map = {"esp32s3": "esp32s3", "esp32": "esp32", "auto": "auto"}
        chip_arg = chip_map.get(chip, "auto")

        cmd = [
            str(PYTHON_EXE), "-m", "esptool",
            "--chip", chip_arg,
            "--port", port,
            "--baud", "921600",
            "--before", "default_reset",
            "--after", "hard_reset",
            "write_flash", "-z",
            flash_addr, str(flash_file),
        ]
        self._emit(f"esptool {' '.join(cmd[5:])}", "muted")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self._emit(line, "muted")
                if self._cancel_flag.is_set():
                    proc.terminate()
                    self.after(0, self._build_done, False)
                    return
            proc.wait()
            if proc.returncode == 0:
                self._emit("✓ Upload complete", "ok")
                self.after(0, self._build_done, True)
            else:
                self._emit("✗ Upload failed", "fail")
                self.after(0, self._build_done, False)
        except Exception as exc:
            self._emit(f"Error: {exc}", "fail")
            self.after(0, self._build_done, False)

    def _cancel_build(self):
        self._cancel_flag.set()
        self._kill_pio()
        self._cancel_btn.configure(state="disabled")
        self._status_var.set("Cancelling…")

    def _run_build(self, tile_src, target, upload_port, out_dir, log_dir):
        env = target["env"]

        # 1. Sync firmware repo
        if not self._sync_firmware():
            self._emit("Aborting — could not sync firmware repo.", "fail")
            self.after(0, self._build_done, False)
            return

        if self._cancel_flag.is_set():
            self.after(0, self._build_done, False)
            return

        fw_root = FIRMWARE_DIR

        # 2. Install MapTile.h (optional)
        if tile_src:
            dest = fw_root / MAPTILE_DEST
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._emit(f"Installing MapTile.h → {MAPTILE_DEST}", "muted")
            shutil.copy2(tile_src, dest)
        else:
            self._emit("No MapTile.h provided — building with existing repo file.", "warn")

        # 3. Build (and optionally flash) in a single pio run invocation.
        # Using two separate pio run calls would rebuild from scratch each time
        # because BUILD_EPOCH changes between invocations and invalidates SCons cache.
        self._emit(f"\nBuilding: {target['label']}", "head")
        self._emit(f"Env: {env}", "muted")
        if target["chip"] == "esp32s3":
            self._emit("Note: first build downloads ESP32 toolchain (~500 MB) if not cached.", "warn")
        else:
            self._emit("Note: first build downloads nRF52 toolchain (~300 MB) if not cached.", "warn")

        log_file = log_dir / f"{env}.log"
        t0 = time.time()

        pio_args = ["-e", env]
        if upload_port:
            self._emit(f"Will flash to {upload_port} after build.", "muted")
            self.after(0, lambda: self._status_var.set(f"Building + Flashing {target['label']}…"))
            pio_args += ["-t", "upload", f"--upload-port={upload_port}"]

        rc = self._run_pio(pio_args, fw_root, log_file)
        elapsed = time.time() - t0

        if rc != 0:
            label = "Build + Flash" if upload_port else "Build"
            self._emit(f"\n✗ {label} failed ({elapsed:.0f}s) — see {log_file}", "fail")
            self._tail_log(log_file)
            self.after(0, self._build_done, False)
            return

        if upload_port:
            self._emit(f"\n✓ Build + Flash complete ({elapsed:.0f}s)", "ok")
        else:
            self._emit(f"\n✓ Build succeeded ({elapsed:.0f}s)", "ok")

        out_dir.mkdir(exist_ok=True)
        for pattern in ("*.bin", "*.uf2", "*.hex", "*.mt.json"):
            for f in (fw_root / ".pio" / "build" / env).glob(pattern):
                dst = out_dir / f"{env}_{f.name}"
                shutil.copy2(f, dst)
                self._emit(f"Saved: {dst.name}", "muted")

        self.after(0, self._build_done, True)

    def _fix_espidf_pyyaml(self) -> bool:
        """Install pyyaml into any .espidf-* venvs under C:\\PlatformIO\\penv if missing."""
        pio_penv = Path("C:/PlatformIO/penv")
        if not pio_penv.is_dir():
            return False
        fixed = False
        for venv in pio_penv.glob(".espidf-*"):
            py = venv / "Scripts" / "python.exe"
            if not py.exists():
                continue
            # Check if pyyaml is already present
            check = subprocess.run(
                [str(py), "-c", "import yaml"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True,
            )
            if check.returncode == 0:
                continue
            self._emit(f"Auto-fixing: installing pyyaml into {venv.name}…", "warn")
            # Bootstrap pip if missing, then install pyyaml
            subprocess.run(
                [str(py), "-c", "import ensurepip; ensurepip.bootstrap()"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True,
            )
            subprocess.run(
                [str(py), "-m", "pip", "install", "pyyaml", "-q"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True,
            )
            self._emit(f"  pyyaml installed into {venv.name}", "ok")
            fixed = True
        return fixed

    def _kill_pio(self):
        """Kill the running PlatformIO process tree (terminates esptool children too)."""
        proc = self._pio_proc
        if proc and proc.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                proc.terminate()
        self._pio_proc = None

    def _run_pio(self, extra_args: list[str], cwd: Path, log_file: Path) -> int:
        cmd = [str(PYTHON_EXE), "-m", "platformio", "run"] + extra_args
        pio_env = os.environ.copy()
        pio_env["PYTHONIOENCODING"] = "utf-8"
        pio_env["PYTHONUTF8"] = "1"
        for attempt in range(2):
            try:
                with open(log_file, "w", encoding="utf-8") as fh:
                    proc = subprocess.Popen(
                        cmd, cwd=cwd, env=pio_env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                    )
                    self._pio_proc = proc
                    log_lines = []
                    for line in proc.stdout:
                        line = line.rstrip()
                        fh.write(line + "\n")
                        fh.flush()
                        log_lines.append(line)
                        if line:
                            self._emit(line, "muted")
                        if self._cancel_flag.is_set():
                            self._kill_pio()
                            return -1
                    proc.wait()
                    self._pio_proc = None
                if proc.returncode != 0 and attempt == 0:
                    # Check for missing pyyaml in espidf venv
                    log_text = "\n".join(log_lines)
                    if "from yaml import" in log_text or "No module named 'yaml'" in log_text:
                        if self._fix_espidf_pyyaml():
                            self._emit("Retrying build after pyyaml fix…", "warn")
                            continue
                return proc.returncode
            except Exception as exc:
                self._emit(f"Error: {exc}", "fail")
                return -1
        return proc.returncode

    def _tail_log(self, log_file: Path, lines: int = 25):
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in text[-lines:]:
                self._emit(f"  {line}", "fail")
        except Exception:
            pass

    def _build_done(self, success: bool):
        self._build_btn.configure(state="normal")
        self._upload_btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        self._progress.stop()
        self._progress.grid_remove()
        self._status_var.set("Done." if success else "Failed — check log.")


def main():
    app = BuilderApp()
    app.mainloop()


if __name__ == "__main__":
    main()

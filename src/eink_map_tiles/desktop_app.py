from __future__ import annotations

import io
import json
import math
import os
import queue
import tempfile
import threading
import tkinter as tk
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from . import cli


DEFAULT_OUTPUT_BASE = Path.home() / "Downloads" / "EinkMapTiles"
DEFAULT_ELEMENTS = list(cli.MAP_ELEMENTS)
ELEMENT_LABELS = {
    "land": "Land",
    "water": "Water",
    "roads": "Roads",
    "highways": "Highways",
    "paths": "Paths",
    "buildings": "Buildings",
    "boundaries": "Boundaries",
    "labels": "Labels",
    "pois": "POI",
    "transit": "Transit",
}
PREVIEW_RASTER_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
SOURCE_PRESETS = {
    "OpenFreeMap open vector tiles": {
        "source": "openfreemap-vector",
        "url": cli.OPENFREEMAP_VECTOR_TEMPLATE,
        "help": "Default open map source. No setup needed.",
    },
    "Local TileServer GL raster": {
        "source": "xyz",
        "url": "http://127.0.0.1:8080/styles/basic/{z}/{x}/{y}.png",
        "help": "Advanced. Use when you are running TileServer GL locally with a legal .mbtiles file.",
    },
    "Custom XYZ PNG URL": {
        "source": "xyz",
        "url": "",
        "help": "Use only a local/self-hosted source or provider URL that explicitly allows offline export.",
    },
}


class QueueWriter(io.TextIOBase):
    def __init__(self, messages: queue.Queue[str]) -> None:
        self.messages = messages

    def write(self, text: str) -> int:
        if text:
            self.messages.put(text)
        return len(text)

    def flush(self) -> None:
        return None


class DesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("E-ink Map Tiles")
        self.geometry("1220x760")
        self.minsize(900, 560)

        self.messages: queue.Queue[str] = queue.Queue()
        self.export_thread: threading.Thread | None = None
        self.preview_thread: threading.Thread | None = None
        self.preview_pending = False
        self.last_output: Path | None = None
        self.preview_image: tk.PhotoImage | None = None
        self.map_center_lat = 39.5
        self.map_center_lon = -98.35
        self.map_zoom = 4
        self.map_drag_start: tuple[int, int] | None = None
        self.map_drag_center: tuple[float, float] | None = None
        self.preview_render_id = 0
        self.preview_after_id: str | None = None
        self.live_update_after_id: str | None = None
        self.preview_tile_cache: dict[tuple, Any] = {}

        self.vars = self.make_vars()
        self.configure_styles()
        self.build_ui()
        self.bind_live_controls()
        self.apply_source_preset()
        self.estimate_tiles()
        self.after(700, self.refresh_preview)
        self.poll_messages()

    def make_vars(self) -> dict[str, tk.Variable]:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        variables: dict[str, tk.Variable] = {
            "source_preset": tk.StringVar(value="OpenFreeMap open vector tiles"),
            "source": tk.StringVar(value="openfreemap-vector"),
            "source_help": tk.StringVar(value=SOURCE_PRESETS["OpenFreeMap open vector tiles"]["help"]),
            "url": tk.StringVar(value=SOURCE_PRESETS["OpenFreeMap open vector tiles"]["url"]),
            "permission": tk.BooleanVar(value=True),
            "west": tk.StringVar(value="-125.000000"),
            "south": tk.StringVar(value="24.000000"),
            "east": tk.StringVar(value="-66.000000"),
            "north": tk.StringVar(value="50.000000"),
            "center_lat": tk.StringVar(value="39.500000"),
            "center_lon": tk.StringVar(value="-98.350000"),
            "radius_km": tk.StringVar(value="1500"),
            "min_zoom": tk.StringVar(value="4"),
            "max_zoom": tk.StringVar(value="8"),
            "style": tk.StringVar(value="osm-eink"),
            "layout": tk.StringVar(value="inkhud-dev"),
            "mode": tk.StringVar(value="mono"),
            "brightness": tk.DoubleVar(value=0.8),
            "contrast": tk.DoubleVar(value=1.3),
            "threshold": tk.IntVar(value=201),
            "output": tk.StringVar(value=str(DEFAULT_OUTPUT_BASE / f"osm-eink-{timestamp}")),
            "tile_count": tk.StringVar(value="Estimate: not calculated"),
            "preview_status": tk.StringVar(value="Loading OpenFreeMap overview preview..."),
            "status": tk.StringVar(value="Ready"),
        }
        for element in cli.MAP_ELEMENTS:
            variables[f"element_{element}"] = tk.BooleanVar(value=element in DEFAULT_ELEMENTS)
        return variables

    def configure_styles(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.configure(background="#edf2ee")
        style = ttk.Style(self)
        for theme in ("vista", "xpnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure(".", font=("Segoe UI", 9))
        style.configure("TFrame", background="#edf2ee")
        style.configure("Panel.TFrame", background="#ffffff", relief="flat")
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("TLabelframe", background="#ffffff", bordercolor="#d3ddd5", relief="solid")
        style.configure("TLabelframe.Label", background="#edf2ee", foreground="#102019", font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background="#ffffff", foreground="#102019", font=("Segoe UI", 9))
        style.configure("Shell.TLabel", background="#edf2ee", foreground="#334139")
        style.configure("Title.TLabel", background="#edf2ee", foreground="#06130f", font=("Segoe UI", 21, "bold"))
        style.configure("Section.TLabel", background="#ffffff", foreground="#06130f", font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", background="#ffffff", foreground="#536158", wraplength=330)
        style.configure("MapHint.TLabel", background="#ffffff", foreground="#536158", wraplength=620)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    def section_frame(self, parent: tk.Misc, title: str) -> tk.Frame:
        frame = tk.Frame(parent, background="#ffffff", highlightbackground="#d7e2db", highlightthickness=1, borderwidth=0)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title, style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))
        return frame

    def flat_button(self, parent: tk.Misc, text: str, command, primary: bool = False, width: int | None = None) -> tk.Button:
        bg = "#0f766e" if primary else "#f7faf7"
        fg = "#ffffff" if primary else "#102019"
        active = "#0b5f59" if primary else "#e8eee9"
        return tk.Button(
            parent,
            text=text,
            command=command,
            width=width or 0,
            background=bg,
            foreground=fg,
            activebackground=active,
            activeforeground=fg,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#c7d3cb",
            padx=12,
            pady=7,
            font=("Segoe UI", 9, "bold" if primary else "normal"),
            cursor="hand2",
        )

    def build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="E-ink Map Tiles", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Select an area, preview e-paper map tiles, then export an offline bundle.",
            style="Shell.TLabel",
        ).grid(row=0, column=1, sticky="e", padx=(20, 4))

        body = ttk.Frame(root)
        body.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        preview_panel = ttk.Frame(body, style="Panel.TFrame", padding=0)
        preview_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(0, weight=1)
        self.build_preview(preview_panel).grid(row=0, column=0, sticky="nsew")

        controls = self.build_scrollable_controls(body)
        controls.columnconfigure(0, weight=1)

        self.build_actions(controls).grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.build_source(controls).grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.build_area(controls).grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.build_settings(controls).grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self.build_elements(controls).grid(row=4, column=0, sticky="ew", pady=(0, 10))
        self.log = tk.Text(controls, height=1)
        self.log.grid_remove()

    def bind_live_controls(self) -> None:
        preview_keys = ("mode", "brightness", "contrast", "threshold", "source", "url")
        for key in preview_keys:
            self.vars[key].trace_add("write", lambda *_args: self.queue_live_update(preview=True, estimate=False))

        export_keys = ("min_zoom", "max_zoom", "style", "layout")
        for key in export_keys:
            self.vars[key].trace_add("write", lambda *_args: self.queue_live_update(preview=False, estimate=True))

        area_keys = ("west", "south", "east", "north")
        for key in area_keys:
            self.vars[key].trace_add("write", lambda *_args: self.queue_live_update(preview=True, estimate=True))

        for element in cli.MAP_ELEMENTS:
            self.vars[f"element_{element}"].trace_add("write", lambda *_args: self.queue_live_update(preview=True, estimate=False))

    def queue_live_update(self, preview: bool, estimate: bool) -> None:
        if self.live_update_after_id is not None:
            try:
                self.after_cancel(self.live_update_after_id)
            except tk.TclError:
                pass

        def run_update() -> None:
            self.live_update_after_id = None
            if estimate:
                self.estimate_tiles(show_errors=False)
            if preview:
                self.schedule_preview(delay_ms=180)

        self.live_update_after_id = self.after(250, run_update)

    def build_scrollable_controls(self, parent: ttk.Frame) -> ttk.Frame:
        shell = ttk.Frame(parent, style="Panel.TFrame")
        shell.grid(row=0, column=1, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        canvas = tk.Canvas(shell, background="#ffffff", highlightthickness=0, borderwidth=0, width=430)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        controls = ttk.Frame(canvas, style="Panel.TFrame", padding=12)
        window_id = canvas.create_window((0, 0), window=controls, anchor="nw")

        def resize_controls(_event=None) -> None:
            canvas.itemconfigure(window_id, width=canvas.winfo_width())
            canvas.configure(scrollregion=canvas.bbox("all"))

        controls.bind("<Configure>", resize_controls)
        canvas.bind("<Configure>", resize_controls)

        def wheel(event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
        self.controls_canvas = canvas
        return controls

    def build_source(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = self.section_frame(parent, "Map Source")
        content = ttk.Frame(frame, style="Card.TFrame", padding=(14, 0, 14, 14))
        content.grid(row=1, column=0, sticky="ew")
        content.columnconfigure(0, weight=1)

        ttk.Label(content, text="Source preset").grid(row=0, column=0, sticky="w")
        preset = ttk.Combobox(
            content,
            textvariable=self.vars["source_preset"],
            values=list(SOURCE_PRESETS),
            state="readonly",
        )
        preset.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        preset.bind("<<ComboboxSelected>>", lambda _event: self.apply_source_preset())

        ttk.Label(content, textvariable=self.vars["source_help"], style="Hint.TLabel").grid(row=2, column=0, sticky="ew")

        self.source_url_label = ttk.Label(content, text="Source URL")
        self.source_url_entry = ttk.Entry(content, textvariable=self.vars["url"])
        self.source_url_label.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.source_url_entry.grid(row=4, column=0, sticky="ew", pady=(4, 0))

        ttk.Checkbutton(
            content,
            text="I will keep required map attribution with exported tiles.",
            variable=self.vars["permission"],
        ).grid(row=5, column=0, sticky="w", pady=(8, 0))
        return frame

    def build_area(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = self.section_frame(parent, "Area")
        content = ttk.Frame(frame, style="Card.TFrame", padding=(14, 0, 14, 14))
        content.grid(row=1, column=0, sticky="ew")
        content.columnconfigure(1, weight=1)
        content.columnconfigure(3, weight=1)

        ttk.Label(content, text="Center lat").grid(row=0, column=0, sticky="w")
        ttk.Entry(content, textvariable=self.vars["center_lat"], width=12).grid(row=0, column=1, sticky="ew", padx=(6, 10))
        ttk.Label(content, text="Center lon").grid(row=0, column=2, sticky="w")
        ttk.Entry(content, textvariable=self.vars["center_lon"], width=12).grid(row=0, column=3, sticky="ew", padx=(6, 0))

        ttk.Label(content, text="Radius km").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(content, textvariable=self.vars["radius_km"], width=12).grid(row=1, column=1, sticky="ew", padx=(6, 10), pady=(8, 0))
        self.flat_button(content, "Set BBox From Center", self.set_bbox_from_center).grid(
            row=1,
            column=2,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

        ttk.Label(content, text="BBox").grid(row=2, column=0, sticky="w", pady=(10, 0))
        bbox_grid = ttk.Frame(content, style="Card.TFrame")
        bbox_grid.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        for column in range(4):
            bbox_grid.columnconfigure(column, weight=1)
        for index, (label, key) in enumerate((("W", "west"), ("S", "south"), ("E", "east"), ("N", "north"))):
            ttk.Label(bbox_grid, text=label).grid(row=0, column=index, sticky="w")
            ttk.Entry(bbox_grid, textvariable=self.vars[key], width=10).grid(row=1, column=index, sticky="ew", padx=(0 if index == 0 else 4, 4))
        return frame

    def build_settings(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = self.section_frame(parent, "Export Settings")
        content = ttk.Frame(frame, style="Card.TFrame", padding=(14, 0, 14, 14))
        content.grid(row=1, column=0, sticky="ew")
        content.columnconfigure(1, weight=1)
        content.columnconfigure(3, weight=1)

        ttk.Label(content, text="Min zoom").grid(row=0, column=0, sticky="w")
        ttk.Entry(content, textvariable=self.vars["min_zoom"], width=8).grid(row=0, column=1, sticky="ew", padx=(6, 10))
        ttk.Label(content, text="Max zoom").grid(row=0, column=2, sticky="w")
        ttk.Entry(content, textvariable=self.vars["max_zoom"], width=8).grid(row=0, column=3, sticky="ew", padx=(6, 0))

        ttk.Label(content, text="Mode").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(
            content,
            textvariable=self.vars["mode"],
            values=["mono", "grayscale", "palette", "original"],
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="ew", padx=(6, 10), pady=(8, 0))

        ttk.Label(content, text="Layout").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Combobox(
            content,
            textvariable=self.vars["layout"],
            values=["inkhud-dev", "style-root", "single-map", "meshtastic-sd"],
            state="readonly",
            width=16,
        ).grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=(8, 0))

        ttk.Label(content, text="Style").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(content, textvariable=self.vars["style"], width=12).grid(row=2, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=(8, 0))

        ttk.Label(content, text="Brightness").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Scale(content, from_=0.6, to=1.6, variable=self.vars["brightness"], orient="horizontal").grid(
            row=3,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(6, 10),
            pady=(10, 0),
        )
        ttk.Label(content, textvariable=self.vars["brightness"]).grid(row=3, column=3, sticky="w", pady=(10, 0))

        ttk.Label(content, text="Contrast").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Scale(content, from_=0.6, to=3.0, variable=self.vars["contrast"], orient="horizontal").grid(
            row=4,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(6, 10),
            pady=(10, 0),
        )
        ttk.Label(content, textvariable=self.vars["contrast"]).grid(row=4, column=3, sticky="w", pady=(10, 0))

        ttk.Label(content, text="Mono threshold").grid(row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Scale(content, from_=80, to=230, variable=self.vars["threshold"], orient="horizontal").grid(
            row=5,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(6, 10),
            pady=(10, 0),
        )
        ttk.Label(content, textvariable=self.vars["threshold"]).grid(row=5, column=3, sticky="w", pady=(10, 0))

        ttk.Label(content, text="Output").grid(row=6, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(content, textvariable=self.vars["output"]).grid(row=7, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.flat_button(content, "Browse", self.choose_output).grid(row=7, column=3, sticky="ew", padx=(8, 0), pady=(4, 0))
        return frame

    def build_elements(self, parent: ttk.Frame) -> tk.Frame:
        frame = self.section_frame(parent, "Map Elements")
        content = ttk.Frame(frame, style="Card.TFrame", padding=(14, 0, 14, 14))
        content.grid(row=1, column=0, sticky="ew")
        for column in range(2):
            content.columnconfigure(column, weight=1)

        for index, element in enumerate(cli.MAP_ELEMENTS):
            ttk.Checkbutton(
                content,
                text=ELEMENT_LABELS.get(element, element.title()),
                variable=self.vars[f"element_{element}"],
            ).grid(row=index // 2, column=index % 2, sticky="w", pady=3)

        buttons = ttk.Frame(content, style="Card.TFrame")
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        self.flat_button(buttons, "All", lambda: self.set_all_elements(True), primary=True).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.flat_button(buttons, "None", lambda: self.set_all_elements(False)).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        return frame

    def build_log(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Output Log", padding=12)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, textvariable=self.vars["tile_count"]).grid(row=0, column=0, sticky="w")
        self.log = tk.Text(frame, height=12, wrap="word", font=("Consolas", 9))
        self.log.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=1, column=1, sticky="ns", pady=(8, 0))
        self.log.configure(yscrollcommand=scroll.set)
        return frame

    def build_preview(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = self.section_frame(parent, "Map Preview")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        top = ttk.Frame(frame, style="Card.TFrame", padding=(14, 0, 14, 10))
        top.grid(row=1, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Label(top, textvariable=self.vars["preview_status"], style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        self.flat_button(top, "-", lambda: self.zoom_map(-1), width=3).grid(row=0, column=1, padx=(8, 3))
        self.flat_button(top, "+", lambda: self.zoom_map(1), width=3).grid(row=0, column=2, padx=3)
        self.flat_button(top, "Use View", self.use_map_view, primary=True).grid(row=0, column=3, padx=3)
        self.preview_button = self.flat_button(top, "Refresh", self.refresh_preview)
        self.preview_button.grid(row=0, column=4, padx=(3, 0))

        self.map_canvas = tk.Canvas(
            frame,
            background="#dfe5df",
            highlightthickness=0,
            borderwidth=0,
        )
        self.map_canvas.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.map_canvas.create_text(360, 260, text="Loading OpenFreeMap preview...", fill="#17211b", tags=("loading",))
        self.map_canvas.bind("<ButtonPress-1>", self.start_map_drag)
        self.map_canvas.bind("<B1-Motion>", self.drag_map)
        self.map_canvas.bind("<ButtonRelease-1>", self.end_map_drag)
        self.map_canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.map_canvas.bind("<Configure>", lambda _event: self.schedule_preview())
        return frame

    def build_actions(self, parent: ttk.Frame) -> ttk.Frame:
        frame = self.section_frame(parent, "Export")
        content = ttk.Frame(frame, style="Card.TFrame", padding=(14, 0, 14, 14))
        content.grid(row=1, column=0, sticky="ew")
        for column in range(3):
            content.columnconfigure(column, weight=1)
        ttk.Label(content, textvariable=self.vars["tile_count"], style="Hint.TLabel").grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(content, textvariable=self.vars["status"], style="Hint.TLabel").grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        self.flat_button(content, "Estimate", self.estimate_tiles).grid(row=2, column=0, sticky="ew", padx=(0, 6))
        self.export_button = self.flat_button(content, "Export Tiles", self.export_tiles, primary=True)
        self.export_button.grid(row=2, column=1, sticky="ew", padx=6)
        self.flat_button(content, "Open Folder", self.open_output_folder).grid(row=2, column=2, sticky="ew", padx=(6, 0))
        return frame

    def apply_source_preset(self) -> None:
        preset = SOURCE_PRESETS.get(str(self.vars["source_preset"].get()), SOURCE_PRESETS["Custom XYZ PNG URL"])
        self.vars["source"].set(preset["source"])
        self.vars["source_help"].set(preset["help"])
        if preset["url"]:
            self.vars["url"].set(preset["url"])
        if preset["source"] == "openfreemap-vector":
            self.vars["permission"].set(True)
            self.source_url_label.grid_remove()
            self.source_url_entry.grid_remove()
        else:
            self.source_url_label.grid()
            self.source_url_entry.grid()

    def selected_elements(self) -> list[str]:
        return [element for element in cli.MAP_ELEMENTS if bool(self.vars[f"element_{element}"].get())]

    def set_all_elements(self, enabled: bool) -> None:
        for element in cli.MAP_ELEMENTS:
            self.vars[f"element_{element}"].set(enabled)
        self.queue_live_update(preview=True, estimate=False)

    def set_bbox_from_center(self) -> None:
        try:
            bbox = cli.bbox_from_center(
                float(self.vars["center_lat"].get()),
                float(self.vars["center_lon"].get()),
                float(self.vars["radius_km"].get()),
            )
        except Exception as exc:  # noqa: BLE001 - show validation errors in GUI.
            messagebox.showerror("Invalid center area", str(exc))
            return
        self.vars["west"].set(f"{bbox.west:.6f}")
        self.vars["south"].set(f"{bbox.south:.6f}")
        self.vars["east"].set(f"{bbox.east:.6f}")
        self.vars["north"].set(f"{bbox.north:.6f}")
        self.estimate_tiles()
        self.map_center_lat = (bbox.south + bbox.north) / 2
        self.map_center_lon = self.center_lon(bbox)
        self.schedule_preview()

    def use_map_view(self) -> None:
        bbox = self.current_map_bbox()
        self.vars["west"].set(f"{bbox.west:.6f}")
        self.vars["south"].set(f"{bbox.south:.6f}")
        self.vars["east"].set(f"{bbox.east:.6f}")
        self.vars["north"].set(f"{bbox.north:.6f}")
        self.vars["center_lat"].set(f"{self.map_center_lat:.6f}")
        self.vars["center_lon"].set(f"{self.map_center_lon:.6f}")
        self.estimate_tiles()
        self.schedule_preview()

    def zoom_map(self, delta: int) -> None:
        self.map_zoom = cli.clamp(self.map_zoom + delta, 2, 14)
        self.draw_preview_placeholder(f"Zoom {self.map_zoom}. Loading map...")
        self.schedule_preview(delay_ms=450)

    def start_map_drag(self, event) -> None:
        self.map_drag_start = (event.x, event.y)
        self.map_drag_center = (self.map_center_lon, self.map_center_lat)

    def drag_map(self, event) -> None:
        if not self.map_drag_start or not self.map_drag_center:
            return
        start_x, start_y = self.map_drag_start
        center_lon, center_lat = self.map_drag_center
        center_px, center_py = self.lon_lat_to_world_pixel(center_lon, center_lat, self.map_zoom)
        new_lon, new_lat = self.world_pixel_to_lon_lat(center_px - (event.x - start_x), center_py - (event.y - start_y), self.map_zoom)
        self.map_center_lon = cli.normalize_lon(new_lon)
        self.map_center_lat = max(min(new_lat, cli.MAX_MERCATOR_LAT), -cli.MAX_MERCATOR_LAT)
        self.shift_current_preview(event.x - start_x, event.y - start_y)

    def end_map_drag(self, _event) -> None:
        self.map_drag_start = None
        self.map_drag_center = None
        self.schedule_preview(delay_ms=250)

    def on_mouse_wheel(self, event) -> None:
        self.zoom_map(1 if event.delta > 0 else -1)

    def schedule_preview(self, delay_ms: int = 350) -> None:
        self.preview_render_id += 1
        if self.preview_after_id is not None:
            try:
                self.after_cancel(self.preview_after_id)
            except tk.TclError:
                pass
        self.preview_after_id = self.after(delay_ms, self.refresh_preview)

    def choose_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(DEFAULT_OUTPUT_BASE))
        if selected:
            self.vars["output"].set(selected)

    def build_job(self) -> dict[str, Any]:
        bbox = cli.parse_bbox(
            ",".join(
                [
                    self.vars["west"].get(),
                    self.vars["south"].get(),
                    self.vars["east"].get(),
                    self.vars["north"].get(),
                ]
            )
        )
        zooms = cli.parse_zooms(f"{self.vars['min_zoom'].get()}-{self.vars['max_zoom'].get()}")
        url_template = self.vars["url"].get().strip()
        return {
            "bbox": {"west": bbox.west, "south": bbox.south, "east": bbox.east, "north": bbox.north},
            "zooms": zooms,
            "style": self.vars["style"].get().strip() or "osm-eink",
            "source": self.vars["source"].get(),
            "mode": self.vars["mode"].get(),
            "brightness": float(self.vars["brightness"].get()),
            "contrast": float(self.vars["contrast"].get()),
            "threshold": int(float(self.vars["threshold"].get())),
            "elements": {
                "include": self.selected_elements(),
                "exclude": [element for element in cli.MAP_ELEMENTS if element not in self.selected_elements()],
            },
            "layout": self.vars["layout"].get(),
            "urlTemplate": url_template,
            "attribution": cli.DEFAULT_ATTRIBUTION,
        }

    def estimate_tiles(self, show_errors: bool = True) -> None:
        try:
            job = self.build_job()
            bbox = cli.BBox(**job["bbox"])
            tiles = cli.tiles_for_bbox(bbox, job["zooms"])
        except Exception as exc:  # noqa: BLE001 - show validation errors in GUI.
            if show_errors:
                messagebox.showerror("Invalid export settings", str(exc))
            return
        self.vars["tile_count"].set(f"Estimate: {len(tiles):,} tiles across zooms {job['zooms'][0]}-{job['zooms'][-1]}")
        self.vars["status"].set("Estimate updated")

    def refresh_preview(self) -> None:
        if self.preview_thread and self.preview_thread.is_alive():
            self.preview_pending = True
            return
        self.preview_after_id = None
        self.preview_pending = False
        try:
            job = self.build_job()
            self.validate_tile_url(job["urlTemplate"])
        except Exception as exc:  # noqa: BLE001 - show validation errors in GUI.
            messagebox.showerror("Cannot preview", str(exc))
            return

        self.preview_button.configure(state="disabled")
        self.preview_render_id += 1
        render_id = self.preview_render_id
        self.vars["preview_status"].set(f"Loading map view at zoom {self.map_zoom}...")
        self.preview_thread = threading.Thread(target=self.load_preview, args=(job, render_id), daemon=True)
        self.preview_thread.start()

    def load_preview(self, job: dict[str, Any], render_id: int) -> None:
        try:
            image = self.make_preview_image(job)
            self.after(0, lambda: self.show_preview_image(image, render_id))
        except Exception as exc:  # noqa: BLE001 - report worker errors in GUI.
            self.after(0, lambda: self.preview_failed(str(exc)))
        finally:
            self.after(0, self.finish_preview_thread)

    def finish_preview_thread(self) -> None:
        self.preview_button.configure(state="normal")
        if self.preview_pending:
            self.preview_pending = False
            self.schedule_preview(delay_ms=200)

    def make_preview_image(self, job: dict[str, Any]):
        from PIL import Image, ImageDraw

        bbox = cli.BBox(**job["bbox"])
        zoom = self.map_zoom
        tile_size = 256
        width = max(self.map_canvas.winfo_width(), 320)
        height = max(self.map_canvas.winfo_height(), 260)
        center_world_x, center_world_y = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, zoom)
        left_world = center_world_x - width / 2
        top_world = center_world_y - height / 2
        first_x = math.floor(left_world / tile_size)
        first_y = math.floor(top_world / tile_size)
        last_x = math.floor((left_world + width) / tile_size)
        last_y = math.floor((top_world + height) / tile_size)
        n = 2**zoom
        canvas = Image.new("RGB", (width, height), "#dfe5df")

        tile_jobs = []
        for x in range(first_x, last_x + 1):
            for y in range(first_y, last_y + 1):
                if y < 0 or y >= n:
                    continue
                tile_id = cli.Tile(z=zoom, x=x % n, y=y)
                paste_x = round(x * tile_size - left_world)
                paste_y = round(y * tile_size - top_world)
                tile_jobs.append((tile_id, paste_x, paste_y))

        def render_tile(tile_job):
            tile_id, paste_x, paste_y = tile_job
            if job["source"] == "openfreemap-vector":
                url = cli.tile_url(PREVIEW_RASTER_TEMPLATE, tile_id)
                image = self.fetch_preview_tile(url)
            else:
                url = cli.tile_url(job["urlTemplate"], tile_id)
                image = self.fetch_preview_tile(url)
            image = self.convert_preview_tile(image, job)
            return paste_x, paste_y, image.convert("RGB")

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(render_tile, tile_job) for tile_job in tile_jobs]
            for future in as_completed(futures):
                paste_x, paste_y, tile_image = future.result()
                canvas.paste(tile_image, (paste_x, paste_y))

        self.draw_preview_bbox(canvas, bbox, zoom, left_world, top_world)
        self.draw_preview_attribution(canvas)
        return canvas

    def draw_preview_attribution(self, canvas) -> None:
        from PIL import ImageDraw, ImageFont

        draw = ImageDraw.Draw(canvas)
        text = "(c) OpenStreetMap contributors - preview only"
        font = ImageFont.load_default()
        box = draw.textbbox((0, 0), text, font=font)
        width = box[2] - box[0] + 10
        height = box[3] - box[1] + 8
        x = canvas.width - width - 8
        y = canvas.height - height - 8
        draw.rectangle([x, y, x + width, y + height], fill="#ffffff", outline="#b8c4bc")
        draw.text((x + 5, y + 4), text, fill="#17211b", font=font)

    def draw_preview_bbox(self, canvas, bbox: cli.BBox, zoom: int, left_world: float, top_world: float) -> None:
        from PIL import ImageDraw

        bbox_left_world, bbox_top_world = self.lon_lat_to_world_pixel(bbox.west, bbox.north, zoom)
        bbox_right_world, bbox_bottom_world = self.lon_lat_to_world_pixel(bbox.east, bbox.south, zoom)
        left = bbox_left_world - left_world
        right = bbox_right_world - left_world
        top = bbox_top_world - top_world
        bottom = bbox_bottom_world - top_world
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(
            [max(0, left), max(0, top), min(canvas.width - 1, right), min(canvas.height - 1, bottom)],
            outline="#0f766e",
            width=3,
        )

    def lon_lat_to_world_pixel(self, lon: float, lat: float, z: int) -> tuple[float, float]:
        lat = max(min(lat, cli.MAX_MERCATOR_LAT), -cli.MAX_MERCATOR_LAT)
        scale = 256 * (2**z)
        x = (lon + 180.0) / 360.0 * scale
        lat_rad = math.radians(lat)
        y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * scale
        return x, y

    def world_pixel_to_lon_lat(self, x: float, y: float, z: int) -> tuple[float, float]:
        scale = 256 * (2**z)
        lon = (x / scale) * 360.0 - 180.0
        mercator = math.pi * (1 - 2 * y / scale)
        lat = math.degrees(math.atan(math.sinh(mercator)))
        return cli.normalize_lon(lon), lat

    def current_map_bbox(self) -> cli.BBox:
        width = max(self.map_canvas.winfo_width(), 320)
        height = max(self.map_canvas.winfo_height(), 260)
        center_x, center_y = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, self.map_zoom)
        west, north = self.world_pixel_to_lon_lat(center_x - width / 2, center_y - height / 2, self.map_zoom)
        east, south = self.world_pixel_to_lon_lat(center_x + width / 2, center_y + height / 2, self.map_zoom)
        return cli.BBox(west=west, south=south, east=east, north=north)

    def draw_preview_placeholder(self, text: str) -> None:
        self.map_canvas.delete("all")
        width = max(self.map_canvas.winfo_width(), 320)
        height = max(self.map_canvas.winfo_height(), 260)
        self.map_canvas.create_rectangle(0, 0, width, height, fill="#edf2ee", outline="")
        self.map_canvas.create_text(width / 2, height / 2, text=text, fill="#102019", font=("Segoe UI", 11), justify="center")

    def draw_zoom_badge(self) -> None:
        self.map_canvas.create_oval(12, 12, 48, 48, fill="#ffffff", outline="#d7e2db", width=1, tags=("zoom-badge",))
        self.map_canvas.create_text(30, 30, text=str(self.map_zoom), fill="#102019", font=("Segoe UI", 12, "bold"), tags=("zoom-badge",))

    def shift_current_preview(self, dx: int, dy: int) -> None:
        if self.preview_image is None:
            self.draw_preview_placeholder("Release to render map...")
            return
        self.map_canvas.coords("map-image", dx, dy)
        self.map_canvas.delete("zoom-badge")
        self.draw_zoom_badge()

    def render_preview_vector_tile(self, tile: cli.Tile):
        from PIL import Image

        cache_key = ("openfreemap-vector", tile.z, tile.x, tile.y)
        cached = self.preview_tile_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        with tempfile.TemporaryDirectory(prefix="eink-map-preview-") as temp_dir:
            tile_path = Path(temp_dir) / "tile.png"
            cli.render_openfreemap_tile(tile, tile_path, cli.DEFAULT_USER_AGENT, timeout=12, retries=2, elements=DEFAULT_ELEMENTS)
            with Image.open(tile_path) as image:
                rendered = image.convert("RGBA")
        self.preview_tile_cache[cache_key] = rendered.copy()
        return rendered

    def fetch_preview_tile(self, url: str):
        from PIL import Image

        cache_key = ("xyz", url)
        cached = self.preview_tile_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        request = urllib.request.Request(url, headers={"User-Agent": cli.DEFAULT_USER_AGENT})
        with urllib.request.urlopen(request, timeout=12) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status} for {url}")
            data = response.read()
        image = Image.open(BytesIO(data)).convert("RGBA")
        self.preview_tile_cache[cache_key] = image.copy()
        return image

    def convert_preview_tile(self, image, job: dict[str, Any]):
        from PIL import Image, ImageEnhance

        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image).convert("RGB")
        image = ImageEnhance.Brightness(image).enhance(float(job["brightness"]))
        image = ImageEnhance.Contrast(image).enhance(float(job["contrast"]))
        mode = job["mode"]
        gray = image.convert("L")
        if mode == "mono":
            # Keep the interactive picker legible. Export still uses the true 1-bit mono conversion.
            threshold = int(job["threshold"])
            return gray.point(
                lambda pixel: 246
                if pixel >= threshold + 42
                else 218
                if pixel >= threshold + 18
                else 172
                if pixel >= threshold
                else 112
                if pixel >= threshold - 28
                else 48
                if pixel >= threshold - 70
                else 18
            )
        if mode == "grayscale":
            return gray
        if mode == "palette":
            return gray.quantize(colors=16)
        return image

    def show_preview_image(self, image, render_id: int) -> None:
        from PIL import ImageTk

        if render_id != self.preview_render_id:
            return
        self.preview_image = ImageTk.PhotoImage(image)
        self.map_canvas.delete("all")
        self.map_canvas.create_image(0, 0, image=self.preview_image, anchor="nw", tags=("map-image",))
        self.draw_zoom_badge()
        self.vars["preview_status"].set("Drag to pan, wheel or +/- to zoom, Use View to set export area.")

    def preview_failed(self, error: str) -> None:
        self.draw_preview_placeholder("Preview unavailable.\n\nCheck your internet connection, then click Refresh.")
        self.preview_image = None
        self.vars["preview_status"].set(f"Preview failed: {error}")

    def validate_tile_url(self, url_template: str) -> None:
        if self.vars["source"].get() == "openfreemap-vector":
            return
        if not url_template:
            raise ValueError("Choose a source preset or enter an XYZ PNG tile URL.")
        if "{z}" not in url_template or "{x}" not in url_template or "{y}" not in url_template:
            raise ValueError("Tile URL must include {z}, {x}, and {y}.")

    def center_lon(self, bbox: cli.BBox) -> float:
        if bbox.west <= bbox.east:
            return (bbox.west + bbox.east) / 2
        return cli.normalize_lon((bbox.west + bbox.east + 360) / 2)

    def export_tiles(self) -> None:
        if self.export_thread and self.export_thread.is_alive():
            return
        try:
            job = self.build_job()
            self.validate_export(job)
        except Exception as exc:  # noqa: BLE001 - show validation errors in GUI.
            messagebox.showerror("Cannot export", str(exc))
            return

        output = Path(self.vars["output"].get()).expanduser()
        self.last_output = output
        self.log.delete("1.0", "end")
        self.export_button.configure(state="disabled")
        self.vars["status"].set("Exporting...")
        self.export_thread = threading.Thread(target=self.run_export, args=(job, output), daemon=True)
        self.export_thread.start()

    def validate_export(self, job: dict[str, Any]) -> None:
        self.validate_tile_url(job["urlTemplate"])
        if not bool(self.vars["permission"].get()):
            raise ValueError("Confirm that exported tiles will keep required attribution.")

    def run_export(self, job: dict[str, Any], output: Path) -> None:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="eink-map-tiles-job-") as temp_dir:
                job_path = Path(temp_dir) / "inkhud-tile-job.json"
                job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
                writer = QueueWriter(self.messages)
                argv = ["--job", str(job_path), "--output", str(output), "--zip"]
                with redirect_stdout(writer):
                    exit_code = cli.main(argv)
                if exit_code:
                    raise RuntimeError(f"Export failed with exit code {exit_code}")
            self.messages.put(f"\nDone. Output: {output}\nZIP: {output.with_suffix('.zip')}\n")
            self.after(0, lambda: self.vars["status"].set("Export complete"))
        except Exception as exc:  # noqa: BLE001 - report worker errors in GUI.
            self.messages.put(f"\nExport failed: {exc}\n")
            self.after(0, lambda: self.vars["status"].set("Export failed"))
        finally:
            self.after(0, lambda: self.export_button.configure(state="normal"))

    def open_output_folder(self) -> None:
        path = self.last_output or Path(self.vars["output"].get()).expanduser()
        folder = path if path.is_dir() else path.parent
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Open output folder failed", str(exc))

    def poll_messages(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            self.log.insert("end", message)
            self.log.see("end")
        self.after(100, self.poll_messages)


def main() -> int:
    app = DesktopApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

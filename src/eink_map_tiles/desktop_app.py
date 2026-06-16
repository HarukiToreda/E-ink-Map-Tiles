from __future__ import annotations

import io
import json
import hashlib
import math
import os
import queue
import re
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
DEFAULT_BRIGHTNESS = 0.99
DEFAULT_CONTRAST = 1.15
DEFAULT_THRESHOLD = 120
DESKTOP_RATE_LIMIT_SECONDS = 0.05
PREVIEW_CACHE_DAYS = 7
PREVIEW_CACHE_SECONDS = PREVIEW_CACHE_DAYS * 24 * 60 * 60
PREVIEW_CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache"))) / "EinkMapTiles" / "preview-tiles"
DEFAULT_ELEMENTS = [element for element in cli.MAP_ELEMENTS if element not in {"buildings", "pois"}]
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
SOURCE_PRESETS = {
    "OpenFreeMap open vector tiles": {
        "source": "openfreemap-vector",
        "url": cli.OPENFREEMAP_VECTOR_TEMPLATE,
        "help": "Default open map source. No setup needed.",
    }
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


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command,
        background: str,
        foreground: str,
        activebackground: str,
        border: str,
        min_width: int,
        height: int,
        font: tuple[str, int, str] | tuple[str, int],
    ) -> None:
        try:
            parent_background = str(parent.cget("background"))  # type: ignore[attr-defined]
        except tk.TclError:
            parent_background = "#ffffff"
        super().__init__(
            parent,
            width=min_width,
            height=height,
            background=parent_background,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        self.button_text = text
        self.command = command
        self.fill = background
        self.foreground = foreground
        self.active_fill = activebackground
        self.border = border
        self.min_width = min_width
        self.button_height = height
        self.button_font = font
        self.state = "normal"
        self.is_hovered = False
        self.bind("<Configure>", lambda _event: self.redraw())
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        self.bind("<ButtonRelease-1>", self.on_click)
        self.redraw()

    def configure(self, cnf=None, **kwargs):  # type: ignore[override]
        if "state" in kwargs:
            self.state = kwargs.pop("state")
        if "text" in kwargs:
            self.button_text = kwargs.pop("text")
        result = super().configure(cnf or {}, **kwargs)
        self.redraw()
        return result

    config = configure

    def on_enter(self, _event) -> None:
        self.is_hovered = True
        self.redraw()

    def on_leave(self, _event) -> None:
        self.is_hovered = False
        self.redraw()

    def on_click(self, _event) -> None:
        if self.state != "disabled" and self.command:
            self.command()

    def redraw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), self.min_width)
        height = max(self.winfo_height(), self.button_height)
        radius = min(8, height // 2)
        fill = self.active_fill if self.is_hovered and self.state != "disabled" else self.fill
        text_fill = self.foreground if self.state != "disabled" else "#8a948d"
        if self.state == "disabled":
            fill = "#eef2ef"
        self.round_rect(1, 1, width - 2, height - 2, radius, fill=fill, outline=self.border)
        self.create_text(width / 2, height / 2, text=self.button_text, fill=text_fill, font=self.button_font)

    def round_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=12, **kwargs)


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
        self.export_total = 0
        self.collapsible_sections: dict[str, dict[str, Any]] = {}
        self.threshold_widgets: list[tk.Widget] = []
        self.threshold_grid_options: dict[tk.Widget, dict[str, Any]] = {}

        self.vars = self.make_vars()
        self.configure_styles()
        self.build_ui()
        self.update_mode_sensitive_controls()
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
            "mode": tk.StringVar(value="grayscale"),
            "brightness": tk.DoubleVar(value=DEFAULT_BRIGHTNESS),
            "contrast": tk.DoubleVar(value=DEFAULT_CONTRAST),
            "threshold": tk.DoubleVar(value=DEFAULT_THRESHOLD),
            "output": tk.StringVar(value=str(DEFAULT_OUTPUT_BASE / f"osm-eink-{timestamp}")),
            "tile_count": tk.StringVar(value="Estimate: not calculated"),
            "preview_status": tk.StringVar(value="Loading preview..."),
            "status": tk.StringVar(value="Ready"),
            "progress_text": tk.StringVar(value="No export running"),
            "progress_value": tk.DoubleVar(value=0),
            "brightness_text": tk.StringVar(value=f"{DEFAULT_BRIGHTNESS:.2f}"),
            "contrast_text": tk.StringVar(value=f"{DEFAULT_CONTRAST:.2f}"),
            "threshold_text": tk.StringVar(value=f"{DEFAULT_THRESHOLD:.0f}"),
            "collapse_map_source": tk.BooleanVar(value=False),
            "collapse_area": tk.BooleanVar(value=False),
            "collapse_export_settings": tk.BooleanVar(value=True),
            "collapse_map_elements": tk.BooleanVar(value=True),
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
        style.configure("Title.TLabel", background="#edf2ee", foreground="#06130f", font=("Segoe UI", 19, "bold"))
        style.configure("Section.TLabel", background="#ffffff", foreground="#06130f", font=("Segoe UI", 9, "bold"))
        style.configure("Hint.TLabel", background="#ffffff", foreground="#536158", wraplength=330)
        style.configure("MapHint.TLabel", background="#ffffff", foreground="#536158", wraplength=620)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    def section_frame(self, parent: tk.Misc, title: str) -> tk.Frame:
        frame = tk.Frame(parent, background="#ffffff", highlightbackground="#d7e2db", highlightthickness=1, borderwidth=0)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title, style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=10, pady=(7, 4))
        return frame

    def collapsible_section(self, parent: tk.Misc, title: str, variable_name: str) -> tuple[tk.Frame, ttk.Frame]:
        frame = tk.Frame(parent, background="#ffffff", highlightbackground="#d7e2db", highlightthickness=1, borderwidth=0)
        frame.columnconfigure(0, weight=1)
        header = ttk.Frame(frame, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(5, 4))
        header.columnconfigure(1, weight=1)

        expanded = bool(self.vars[variable_name].get())
        toggle = self.flat_button(header, "v" if expanded else ">", lambda: self.toggle_section(variable_name), width=2)
        toggle.grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(header, text=title, style="Section.TLabel").grid(row=0, column=1, sticky="w")

        content = ttk.Frame(frame, style="Card.TFrame", padding=(10, 0, 10, 8))
        self.collapsible_sections[variable_name] = {"content": content, "toggle": toggle}
        if expanded:
            content.grid(row=1, column=0, sticky="ew")
        return frame, content

    def toggle_section(self, variable_name: str) -> None:
        self.vars[variable_name].set(not bool(self.vars[variable_name].get()))
        self.apply_section_state(variable_name)

    def apply_section_state(self, variable_name: str) -> None:
        section = self.collapsible_sections[variable_name]
        content = section["content"]
        toggle = section["toggle"]
        if bool(self.vars[variable_name].get()):
            content.grid(row=1, column=0, sticky="ew")
            toggle.configure(text="v")
        else:
            content.grid_remove()
            toggle.configure(text=">")
        if hasattr(self, "controls_canvas"):
            self.after_idle(lambda: self.controls_canvas.configure(scrollregion=self.controls_canvas.bbox("all")))

    def flat_button(self, parent: tk.Misc, text: str, command, primary: bool = False, width: int | None = None) -> tk.Button:
        bg = "#0f766e" if primary else "#f7faf7"
        fg = "#ffffff" if primary else "#102019"
        active = "#0b5f59" if primary else "#e8eee9"
        min_width = 28 if width else max(74, len(text) * 8 + 22)
        if width:
            min_width = max(28, width * 13 + 8)
        return RoundedButton(
            parent,
            text=text,
            command=command,
            background=bg,
            foreground=fg,
            activebackground=active,
            border="#c7d3cb",
            min_width=min_width,
            height=28,
            font=("Segoe UI", 9, "bold" if primary else "normal"),
        )

    def build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
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
        ).grid(row=0, column=1, sticky="e", padx=(16, 2))

        body = ttk.Frame(root)
        body.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        preview_panel = ttk.Frame(body, style="Panel.TFrame", padding=0)
        preview_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(0, weight=1)
        self.build_preview(preview_panel).grid(row=0, column=0, sticky="nsew")

        controls = self.build_scrollable_controls(body)
        controls.columnconfigure(0, weight=1)

        self.build_actions(controls).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.build_source(controls).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.build_area(controls).grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.build_settings(controls).grid(row=3, column=0, sticky="ew", pady=(0, 6))
        self.build_elements(controls).grid(row=4, column=0, sticky="ew", pady=(0, 6))

    def bind_live_controls(self) -> None:
        preview_keys = ("mode", "brightness", "contrast", "threshold", "source", "url")
        for key in preview_keys:
            self.vars[key].trace_add("write", lambda *_args: self.queue_live_update(preview=True, estimate=False))
        self.vars["brightness"].trace_add("write", lambda *_args: self.update_slider_labels())
        self.vars["contrast"].trace_add("write", lambda *_args: self.update_slider_labels())
        self.vars["threshold"].trace_add("write", lambda *_args: self.update_slider_labels())
        self.vars["mode"].trace_add("write", lambda *_args: self.update_mode_sensitive_controls())

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

    def update_slider_labels(self) -> None:
        self.vars["brightness_text"].set(f"{float(self.vars['brightness'].get()):.2f}")
        self.vars["contrast_text"].set(f"{float(self.vars['contrast'].get()):.2f}")
        if self.vars["mode"].get() == "mono":
            self.vars["threshold_text"].set(f"{float(self.vars['threshold'].get()):.0f}")
        else:
            self.vars["threshold_text"].set("")

    def update_mode_sensitive_controls(self) -> None:
        visible = self.vars["mode"].get() == "mono"
        for widget in self.threshold_widgets:
            if visible:
                widget.grid(**self.threshold_grid_options[widget])
            else:
                widget.grid_remove()
        self.update_slider_labels()

    def build_scrollable_controls(self, parent: ttk.Frame) -> ttk.Frame:
        shell = ttk.Frame(parent, style="Panel.TFrame")
        shell.grid(row=0, column=1, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        canvas = tk.Canvas(shell, background="#ffffff", highlightthickness=0, borderwidth=0, width=420)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        controls = ttk.Frame(canvas, style="Panel.TFrame", padding=8)
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
        frame, content = self.collapsible_section(parent, "Map Source", "collapse_map_source")
        content.columnconfigure(0, weight=1)

        ttk.Label(content, text="Source preset").grid(row=0, column=0, sticky="w")
        preset = ttk.Combobox(
            content,
            textvariable=self.vars["source_preset"],
            values=list(SOURCE_PRESETS),
            state="readonly",
        )
        preset.grid(row=1, column=0, sticky="ew", pady=(2, 4))
        preset.bind("<<ComboboxSelected>>", lambda _event: self.apply_source_preset())

        ttk.Label(content, textvariable=self.vars["source_help"], style="Hint.TLabel").grid(row=2, column=0, sticky="ew")

        self.source_url_label = ttk.Label(content, text="Source URL")
        self.source_url_entry = ttk.Entry(content, textvariable=self.vars["url"])
        self.source_url_label.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.source_url_entry.grid(row=4, column=0, sticky="ew", pady=(2, 0))

        ttk.Checkbutton(
            content,
            text="I will keep required map attribution with exported tiles.",
            variable=self.vars["permission"],
        ).grid(row=5, column=0, sticky="w", pady=(4, 0))
        return frame

    def build_area(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame, content = self.collapsible_section(parent, "Area", "collapse_area")
        content.columnconfigure(1, weight=1)
        content.columnconfigure(3, weight=1)

        ttk.Label(content, text="Center lat").grid(row=0, column=0, sticky="w")
        ttk.Entry(content, textvariable=self.vars["center_lat"], width=12).grid(row=0, column=1, sticky="ew", padx=(6, 10))
        ttk.Label(content, text="Center lon").grid(row=0, column=2, sticky="w")
        ttk.Entry(content, textvariable=self.vars["center_lon"], width=12).grid(row=0, column=3, sticky="ew", padx=(6, 0))

        ttk.Label(content, text="Radius km").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(content, textvariable=self.vars["radius_km"], width=12).grid(row=1, column=1, sticky="ew", padx=(6, 10), pady=(4, 0))
        self.flat_button(content, "Set BBox From Center", self.set_bbox_from_center).grid(
            row=1,
            column=2,
            columnspan=2,
            sticky="ew",
            pady=(4, 0),
        )

        ttk.Label(content, text="BBox").grid(row=2, column=0, sticky="w", pady=(6, 0))
        bbox_grid = ttk.Frame(content, style="Card.TFrame")
        bbox_grid.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        for column in range(4):
            bbox_grid.columnconfigure(column, weight=1)
        for index, (label, key) in enumerate((("W", "west"), ("S", "south"), ("E", "east"), ("N", "north"))):
            ttk.Label(bbox_grid, text=label).grid(row=0, column=index, sticky="w")
            ttk.Entry(bbox_grid, textvariable=self.vars[key], width=10).grid(row=1, column=index, sticky="ew", padx=(0 if index == 0 else 4, 4))
        return frame

    def build_settings(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame, content = self.collapsible_section(parent, "Export Settings", "collapse_export_settings")
        content.columnconfigure(1, weight=1)
        content.columnconfigure(3, weight=1)

        ttk.Label(content, text="Min zoom").grid(row=0, column=0, sticky="w")
        ttk.Entry(content, textvariable=self.vars["min_zoom"], width=8).grid(row=0, column=1, sticky="ew", padx=(6, 10))
        ttk.Label(content, text="Max zoom").grid(row=0, column=2, sticky="w")
        ttk.Entry(content, textvariable=self.vars["max_zoom"], width=8).grid(row=0, column=3, sticky="ew", padx=(6, 0))

        ttk.Label(content, text="Mode").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Combobox(
            content,
            textvariable=self.vars["mode"],
            values=["mono", "grayscale", "palette", "original"],
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="ew", padx=(6, 10), pady=(4, 0))

        ttk.Label(content, text="Layout").grid(row=1, column=2, sticky="w", pady=(4, 0))
        ttk.Combobox(
            content,
            textvariable=self.vars["layout"],
            values=["inkhud-dev", "style-root", "single-map", "meshtastic-sd"],
            state="readonly",
            width=16,
        ).grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=(4, 0))

        ttk.Label(content, text="Style").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(content, textvariable=self.vars["style"], width=12).grid(row=2, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=(4, 0))

        ttk.Label(content, text="Brightness").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Scale(content, from_=0.6, to=1.6, variable=self.vars["brightness"], orient="horizontal").grid(
            row=3,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(6, 10),
            pady=(6, 0),
        )
        ttk.Label(content, textvariable=self.vars["brightness_text"]).grid(row=3, column=3, sticky="w", pady=(6, 0))

        ttk.Label(content, text="Contrast").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Scale(content, from_=0.6, to=3.0, variable=self.vars["contrast"], orient="horizontal").grid(
            row=4,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(6, 10),
            pady=(6, 0),
        )
        ttk.Label(content, textvariable=self.vars["contrast_text"]).grid(row=4, column=3, sticky="w", pady=(6, 0))

        threshold_label = ttk.Label(content, text="Mono threshold")
        threshold_label.grid(row=5, column=0, sticky="w", pady=(6, 0))
        threshold_scale = ttk.Scale(content, from_=80, to=230, variable=self.vars["threshold"], orient="horizontal")
        threshold_scale.grid(
            row=5,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(6, 10),
            pady=(6, 0),
        )
        threshold_value = ttk.Label(content, textvariable=self.vars["threshold_text"])
        threshold_value.grid(row=5, column=3, sticky="w", pady=(6, 0))
        self.threshold_widgets = [threshold_label, threshold_scale, threshold_value]
        self.threshold_grid_options = {
            threshold_label: {"row": 5, "column": 0, "sticky": "w", "pady": (6, 0)},
            threshold_scale: {
                "row": 5,
                "column": 1,
                "columnspan": 2,
                "sticky": "ew",
                "padx": (6, 10),
                "pady": (6, 0),
            },
            threshold_value: {"row": 5, "column": 3, "sticky": "w", "pady": (6, 0)},
        }

        ttk.Label(content, text="Output").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(content, textvariable=self.vars["output"]).grid(row=6, column=1, columnspan=2, sticky="ew", padx=(6, 8), pady=(6, 0))
        self.flat_button(content, "Browse", self.choose_output).grid(row=6, column=3, sticky="ew", pady=(6, 0))
        return frame

    def build_elements(self, parent: ttk.Frame) -> tk.Frame:
        frame, content = self.collapsible_section(parent, "Map Elements", "collapse_map_elements")
        element_columns = 3
        for column in range(element_columns):
            content.columnconfigure(column, weight=1)

        for index, element in enumerate(cli.MAP_ELEMENTS):
            ttk.Checkbutton(
                content,
                text=ELEMENT_LABELS.get(element, element.title()),
                variable=self.vars[f"element_{element}"],
            ).grid(row=index // element_columns, column=index % element_columns, sticky="w", pady=1)

        buttons = ttk.Frame(content, style="Card.TFrame")
        buttons.grid(row=math.ceil(len(cli.MAP_ELEMENTS) / element_columns), column=0, columnspan=element_columns, sticky="ew", pady=(4, 0))
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
        self.preview_status_canvas = tk.Canvas(top, height=34, background="#ffffff", highlightthickness=0, borderwidth=0)
        self.preview_status_canvas.grid(row=0, column=0, sticky="ew")
        self.preview_status_text = self.preview_status_canvas.create_text(
            0,
            4,
            text=self.vars["preview_status"].get(),
            fill="#536158",
            font=("Segoe UI", 9),
            anchor="nw",
            width=520,
        )
        self.preview_status_canvas.bind("<Configure>", self.resize_preview_status)
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

    def resize_preview_status(self, event) -> None:
        self.preview_status_canvas.itemconfigure(self.preview_status_text, width=max(event.width - 4, 120))

    def set_preview_status(self, text: str) -> None:
        self.vars["preview_status"].set(text)
        if hasattr(self, "preview_status_canvas"):
            self.preview_status_canvas.itemconfigure(self.preview_status_text, text=text)

    def build_actions(self, parent: ttk.Frame) -> ttk.Frame:
        frame = self.section_frame(parent, "Export")
        content = ttk.Frame(frame, style="Card.TFrame", padding=(10, 0, 10, 8))
        content.grid(row=1, column=0, sticky="ew")
        for column in range(4):
            content.columnconfigure(column, weight=1)
        ttk.Label(content, textvariable=self.vars["tile_count"], style="Hint.TLabel").grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 2))
        ttk.Label(content, textvariable=self.vars["status"], style="Hint.TLabel").grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        self.flat_button(content, "Estimate", self.estimate_tiles).grid(row=2, column=0, sticky="ew", padx=(0, 5))
        self.export_button = self.flat_button(content, "Export Tiles", self.export_tiles, primary=True)
        self.export_button.grid(row=2, column=1, sticky="ew", padx=5)
        self.flat_button(content, "Folder", self.open_output_folder).grid(row=2, column=2, sticky="ew", padx=5)
        self.flat_button(content, "About", self.show_about_licenses).grid(row=2, column=3, sticky="ew", padx=(5, 0))
        self.progress_bar = ttk.Progressbar(content, variable=self.vars["progress_value"], maximum=1, mode="determinate")
        self.progress_bar.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 2))
        ttk.Label(content, textvariable=self.vars["progress_text"], style="Hint.TLabel").grid(row=4, column=0, columnspan=4, sticky="ew")
        self.log = tk.Text(
            content,
            height=3,
            wrap="word",
            font=("Consolas", 8),
            background="#f7faf7",
            relief="flat",
            borderwidth=0,
        )
        self.log.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.log.grid_remove()
        return frame

    def apply_source_preset(self) -> None:
        preset = SOURCE_PRESETS.get(str(self.vars["source_preset"].get()), SOURCE_PRESETS["OpenFreeMap open vector tiles"])
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

    def show_about_licenses(self) -> None:
        messagebox.showinfo(
            "About / Licenses",
            "\n".join(
                [
                    "E-ink Map Tiles is MIT licensed.",
                    "",
                    "Map data is derived from OpenStreetMap and must retain attribution:",
                    "(c) OpenStreetMap contributors, ODbL 1.0.",
                    "",
                    "Default exports use OpenFreeMap vector tiles and local rendering.",
                    "The preview uses the same local vector renderer as OpenFreeMap exports.",
                    "",
                    "Bundled libraries include Pillow, mapbox-vector-tile, Shapely, pyclipper, protobuf, and NumPy.",
                    "See NOTICE.md in the repository or release folder for dependency license notes.",
                    "",
                    "Each exported bundle includes manifest.json and ATTRIBUTION.txt.",
                ]
            ),
        )

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

    def zoom_map(self, delta: int, anchor: tuple[int, int] | None = None) -> None:
        old_zoom = self.map_zoom
        new_zoom = cli.clamp(old_zoom + delta, 2, 14)
        if new_zoom == old_zoom:
            return

        if anchor is not None:
            width = max(self.map_canvas.winfo_width(), 320)
            height = max(self.map_canvas.winfo_height(), 260)
            anchor_x, anchor_y = anchor
            old_center_x, old_center_y = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, old_zoom)
            anchor_world_x = old_center_x - width / 2 + anchor_x
            anchor_world_y = old_center_y - height / 2 + anchor_y
            anchor_lon, anchor_lat = self.world_pixel_to_lon_lat(anchor_world_x, anchor_world_y, old_zoom)

            new_anchor_x, new_anchor_y = self.lon_lat_to_world_pixel(anchor_lon, anchor_lat, new_zoom)
            new_center_x = new_anchor_x - anchor_x + width / 2
            new_center_y = new_anchor_y - anchor_y + height / 2
            new_lon, new_lat = self.world_pixel_to_lon_lat(new_center_x, new_center_y, new_zoom)
            self.map_center_lon = cli.normalize_lon(new_lon)
            self.map_center_lat = max(min(new_lat, cli.MAX_MERCATOR_LAT), -cli.MAX_MERCATOR_LAT)

        self.map_zoom = new_zoom
        self.set_preview_status(f"Rendering export preview z{self.map_zoom}...")
        if self.preview_image is None:
            self.draw_preview_placeholder(f"Rendering export preview z{self.map_zoom}...")
        else:
            self.map_canvas.delete("zoom-badge")
            self.draw_zoom_badge()
        self.schedule_preview(delay_ms=250)

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
        self.zoom_map(1 if event.delta > 0 else -1, anchor=(event.x, event.y))

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
            "colors": 256,
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
        exact = True
        self.set_preview_status(f"Rendering export preview z{self.map_zoom}...")
        self.preview_thread = threading.Thread(target=self.load_preview, args=(job, render_id, exact), daemon=True)
        self.preview_thread.start()

    def load_preview(self, job: dict[str, Any], render_id: int, exact: bool) -> None:
        try:
            image = self.make_preview_image(job, exact=exact)
            self.after(0, lambda: self.show_preview_image(image, render_id, exact))
        except Exception as exc:  # noqa: BLE001 - report worker errors in GUI.
            self.after(0, lambda: self.preview_failed(str(exc)))
        finally:
            self.after(0, self.finish_preview_thread)

    def finish_preview_thread(self) -> None:
        self.preview_button.configure(state="normal")
        if self.preview_pending:
            self.preview_pending = False
            self.schedule_preview(delay_ms=200)

    def make_preview_image(self, job: dict[str, Any], exact: bool = False):
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
            if exact and job["source"] == "openfreemap-vector":
                image = self.render_preview_vector_tile(tile_id, job)
                image = self.convert_preview_tile(image, job, exact=True)
            else:
                url = cli.tile_url(job["urlTemplate"], tile_id)
                image = self.fetch_preview_tile(url)
                image = self.convert_preview_tile(image, job, exact=True)
            return paste_x, paste_y, image.convert("RGB")

        max_workers = 6
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(render_tile, tile_job) for tile_job in tile_jobs]
            for future in as_completed(futures):
                paste_x, paste_y, tile_image = future.result()
                canvas.paste(tile_image, (paste_x, paste_y))

        self.draw_preview_bbox(canvas, bbox, zoom, left_world, top_world)
        self.draw_preview_attribution(canvas, exact=exact and job["source"] == "openfreemap-vector")
        return canvas

    def draw_preview_attribution(self, canvas, exact: bool = False) -> None:
        from PIL import ImageDraw, ImageFont

        draw = ImageDraw.Draw(canvas)
        text = "(c) OpenStreetMap contributors - export preview"
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

    def render_preview_vector_tile(self, tile: cli.Tile, job: dict[str, Any]):
        from PIL import Image

        elements = tuple(job["elements"]["include"])
        cache_key = ("openfreemap-vector", tile.z, tile.x, tile.y, elements)
        cached = self.preview_tile_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        with tempfile.TemporaryDirectory(prefix="eink-map-preview-") as temp_dir:
            tile_path = Path(temp_dir) / "tile.png"
            cli.render_openfreemap_tile(tile, tile_path, cli.DEFAULT_USER_AGENT, timeout=12, retries=2, elements=list(elements))
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

        cache_path = self.preview_cache_path(url)
        data = self.read_preview_cache(cache_path)
        if data is None:
            request = urllib.request.Request(url, headers={"User-Agent": cli.DEFAULT_USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=12) as response:
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status} for {url}")
                    data = response.read()
                self.write_preview_cache(cache_path, data)
            except Exception:
                data = self.read_preview_cache(cache_path, allow_expired=True)
                if data is None:
                    raise
        image = Image.open(BytesIO(data)).convert("RGBA")
        self.preview_tile_cache[cache_key] = image.copy()
        return image

    def preview_cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return PREVIEW_CACHE_DIR / digest[:2] / f"{digest}.png"

    def read_preview_cache(self, cache_path: Path, allow_expired: bool = False) -> bytes | None:
        try:
            age = datetime.now().timestamp() - cache_path.stat().st_mtime
            if not allow_expired and age > PREVIEW_CACHE_SECONDS:
                return None
            return cache_path.read_bytes()
        except OSError:
            return None

    def write_preview_cache(self, cache_path: Path, data: bytes) -> None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(data)
        except OSError:
            return

    def convert_preview_tile(self, image, job: dict[str, Any], exact: bool = False):
        from PIL import Image, ImageEnhance

        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image).convert("RGB")
        image = ImageEnhance.Brightness(image).enhance(float(job["brightness"]))
        image = ImageEnhance.Contrast(image).enhance(float(job["contrast"]))
        mode = job["mode"]
        gray = image.convert("L")
        if mode == "mono":
            threshold = int(job["threshold"])
            if exact:
                return gray.point(lambda pixel: 255 if pixel >= threshold else 0, mode="1")
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
            colors = max(2, min(int(job.get("colors", 256)), 256))
            return image.quantize(colors=colors)
        return image

    def show_preview_image(self, image, render_id: int, exact: bool = False) -> None:
        from PIL import ImageTk

        if render_id != self.preview_render_id:
            return
        self.preview_image = ImageTk.PhotoImage(image)
        self.map_canvas.delete("all")
        self.map_canvas.create_image(0, 0, image=self.preview_image, anchor="nw", tags=("map-image",))
        self.draw_zoom_badge()
        self.set_preview_status(f"Export preview z{self.map_zoom}: matches downloaded tile rendering.")

    def preview_failed(self, error: str) -> None:
        self.draw_preview_placeholder("Preview unavailable.\n\nCheck your internet connection, then click Refresh.")
        self.preview_image = None
        self.set_preview_status(f"Preview failed: {error}")

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
        self.log.grid()
        self.reset_export_progress(job)
        self.export_button.configure(state="disabled")
        self.vars["status"].set("Exporting...")
        self.export_thread = threading.Thread(target=self.run_export, args=(job, output), daemon=True)
        self.export_thread.start()

    def reset_export_progress(self, job: dict[str, Any]) -> None:
        bbox = cli.BBox(**job["bbox"])
        self.export_total = len(cli.tiles_for_bbox(bbox, job["zooms"]))
        self.vars["progress_value"].set(0)
        self.progress_bar.configure(maximum=max(self.export_total, 1), mode="determinate")
        self.vars["progress_text"].set(f"Exporting 0 / {self.export_total:,} tiles...")

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
                argv = [
                    "--job",
                    str(job_path),
                    "--output",
                    str(output),
                    "--zip",
                    "--rate-limit",
                    str(DESKTOP_RATE_LIMIT_SECONDS),
                ]
                with redirect_stdout(writer):
                    exit_code = cli.main(argv)
                if exit_code:
                    raise RuntimeError(f"Export failed with exit code {exit_code}")
            self.messages.put(f"\nDone. Output: {output}\nZIP: {output.with_suffix('.zip')}\n")
            self.after(0, self.finish_export_success)
        except Exception as exc:  # noqa: BLE001 - report worker errors in GUI.
            self.messages.put(f"\nExport failed: {exc}\n")
            self.after(0, lambda: self.finish_export_failed(str(exc)))
        finally:
            self.after(0, lambda: self.export_button.configure(state="normal"))

    def finish_export_success(self) -> None:
        self.vars["status"].set("Export complete")
        self.vars["progress_value"].set(self.export_total)
        self.vars["progress_text"].set(f"Complete: {self.export_total:,} tiles exported")

    def finish_export_failed(self, error: str) -> None:
        self.vars["status"].set("Export failed")
        self.vars["progress_text"].set(f"Export failed: {error}")

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
            if not self.log.grid_info():
                self.log.grid()
            self.log.insert("end", message)
            self.log.see("end")
            self.update_export_progress_from_message(message)
        self.after(100, self.poll_messages)

    def update_export_progress_from_message(self, message: str) -> None:
        for completed_text, total_text in re.findall(r"\[(\d+)/(\d+)\]", message):
            completed = int(completed_text)
            total = int(total_text)
            self.export_total = total
            self.progress_bar.configure(maximum=max(total, 1), mode="determinate")
            self.vars["progress_value"].set(completed)
            self.vars["progress_text"].set(f"Exporting {completed:,} / {total:,} tiles...")


def main() -> int:
    app = DesktopApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

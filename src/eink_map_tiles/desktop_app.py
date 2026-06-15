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
DEFAULT_ELEMENTS = ["land", "water", "roads", "highways", "boundaries", "labels"]
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
        self.geometry("1180x700")
        self.minsize(1040, 650)

        self.messages: queue.Queue[str] = queue.Queue()
        self.export_thread: threading.Thread | None = None
        self.preview_thread: threading.Thread | None = None
        self.last_output: Path | None = None
        self.preview_image: tk.PhotoImage | None = None
        self.map_center_lat = 39.5
        self.map_center_lon = -98.35
        self.map_zoom = 4
        self.map_drag_start: tuple[int, int] | None = None
        self.map_drag_center: tuple[float, float] | None = None
        self.preview_render_id = 0
        self.preview_after_id: str | None = None
        self.preview_tile_cache: dict[tuple, Any] = {}

        self.vars = self.make_vars()
        self.configure_styles()
        self.build_ui()
        self.apply_source_preset()
        self.estimate_tiles()
        self.after(700, self.refresh_preview)
        self.poll_messages()

    def make_vars(self) -> dict[str, tk.Variable]:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return {
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
            "brightness": tk.DoubleVar(value=0.95),
            "contrast": tk.DoubleVar(value=1.4),
            "threshold": tk.IntVar(value=201),
            "output": tk.StringVar(value=str(DEFAULT_OUTPUT_BASE / f"osm-eink-{timestamp}")),
            "tile_count": tk.StringVar(value="Estimate: not calculated"),
            "preview_status": tk.StringVar(value="Loading OpenFreeMap overview preview..."),
            "status": tk.StringVar(value="Ready"),
        }

    def configure_styles(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2ec")
        style.configure("Panel.TFrame", background="#ffffff", relief="flat")
        style.configure("TLabelframe", background="#ffffff", bordercolor="#c7d0c8", relief="solid")
        style.configure("TLabelframe.Label", background="#eef2ec", foreground="#17211b", font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background="#ffffff", foreground="#17211b", font=("Segoe UI", 9))
        style.configure("Shell.TLabel", background="#eef2ec", foreground="#17211b")
        style.configure("Title.TLabel", background="#eef2ec", font=("Segoe UI", 20, "bold"))
        style.configure("Hint.TLabel", background="#ffffff", foreground="#58645c", wraplength=320)
        style.configure("MapHint.TLabel", background="#eef2ec", foreground="#58645c", wraplength=700)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), foreground="#ffffff", background="#146c5f")
        style.map("Accent.TButton", background=[("active", "#0d4f47")])

    def build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        ttk.Label(root, text="E-ink Map Tiles", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            root,
            text="Select an area, preview e-paper map tiles, then export an offline bundle.",
            style="Shell.TLabel",
        ).grid(row=0, column=0, sticky="e", padx=(0, 4))

        body = ttk.Frame(root)
        body.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        preview_panel = ttk.Frame(body, style="Panel.TFrame", padding=12)
        preview_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(1, weight=1)
        self.build_preview(preview_panel).grid(row=0, column=0, rowspan=2, sticky="nsew")

        controls = ttk.Frame(body, style="Panel.TFrame", padding=12)
        controls.grid(row=0, column=1, sticky="nsew")
        controls.columnconfigure(0, weight=1)

        self.build_actions(controls).grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.build_source(controls).grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.build_area(controls).grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.build_settings(controls).grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self.log = tk.Text(controls, height=1)
        self.log.grid_remove()

    def build_source(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Map Source", padding=12)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Source preset").grid(row=0, column=0, sticky="w")
        preset = ttk.Combobox(
            frame,
            textvariable=self.vars["source_preset"],
            values=list(SOURCE_PRESETS),
            state="readonly",
        )
        preset.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        preset.bind("<<ComboboxSelected>>", lambda _event: self.apply_source_preset())

        ttk.Label(frame, textvariable=self.vars["source_help"], style="Hint.TLabel").grid(row=2, column=0, sticky="ew")

        self.source_url_label = ttk.Label(frame, text="Source URL")
        self.source_url_entry = ttk.Entry(frame, textvariable=self.vars["url"])
        self.source_url_label.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.source_url_entry.grid(row=4, column=0, sticky="ew", pady=(4, 0))

        ttk.Checkbutton(
            frame,
            text="I will keep required map attribution with exported tiles.",
            variable=self.vars["permission"],
        ).grid(row=5, column=0, sticky="w", pady=(8, 0))
        return frame

    def build_area(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Area", padding=12)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        ttk.Label(frame, text="Center lat").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.vars["center_lat"], width=12).grid(row=0, column=1, sticky="ew", padx=(6, 10))
        ttk.Label(frame, text="Center lon").grid(row=0, column=2, sticky="w")
        ttk.Entry(frame, textvariable=self.vars["center_lon"], width=12).grid(row=0, column=3, sticky="ew", padx=(6, 0))

        ttk.Label(frame, text="Radius km").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.vars["radius_km"], width=12).grid(row=1, column=1, sticky="ew", padx=(6, 10), pady=(8, 0))
        ttk.Button(frame, text="Set BBox From Center", command=self.set_bbox_from_center).grid(
            row=1,
            column=2,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

        ttk.Label(frame, text="BBox").grid(row=2, column=0, sticky="w", pady=(10, 0))
        bbox_grid = ttk.Frame(frame)
        bbox_grid.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        for column in range(4):
            bbox_grid.columnconfigure(column, weight=1)
        for index, (label, key) in enumerate((("W", "west"), ("S", "south"), ("E", "east"), ("N", "north"))):
            ttk.Label(bbox_grid, text=label).grid(row=0, column=index, sticky="w")
            ttk.Entry(bbox_grid, textvariable=self.vars[key], width=10).grid(row=1, column=index, sticky="ew", padx=(0 if index == 0 else 4, 4))
        return frame

    def build_settings(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Export Settings", padding=12)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        ttk.Label(frame, text="Min zoom").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.vars["min_zoom"], width=8).grid(row=0, column=1, sticky="ew", padx=(6, 10))
        ttk.Label(frame, text="Max zoom").grid(row=0, column=2, sticky="w")
        ttk.Entry(frame, textvariable=self.vars["max_zoom"], width=8).grid(row=0, column=3, sticky="ew", padx=(6, 0))

        ttk.Label(frame, text="Mode").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(
            frame,
            textvariable=self.vars["mode"],
            values=["mono", "grayscale", "palette", "original"],
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="ew", padx=(6, 10), pady=(8, 0))

        ttk.Label(frame, text="Layout").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Combobox(
            frame,
            textvariable=self.vars["layout"],
            values=["inkhud-dev", "style-root", "single-map", "meshtastic-sd"],
            state="readonly",
            width=16,
        ).grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=(8, 0))

        ttk.Label(frame, text="Style").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.vars["style"], width=12).grid(row=2, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=(8, 0))

        ttk.Label(frame, text="Brightness").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Scale(frame, from_=0.6, to=1.6, variable=self.vars["brightness"], orient="horizontal").grid(
            row=3,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(6, 10),
            pady=(10, 0),
        )
        ttk.Label(frame, textvariable=self.vars["brightness"]).grid(row=3, column=3, sticky="w", pady=(10, 0))

        ttk.Label(frame, text="Contrast").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Scale(frame, from_=0.6, to=3.0, variable=self.vars["contrast"], orient="horizontal").grid(
            row=4,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(6, 10),
            pady=(10, 0),
        )
        ttk.Label(frame, textvariable=self.vars["contrast"]).grid(row=4, column=3, sticky="w", pady=(10, 0))

        ttk.Label(frame, text="Mono threshold").grid(row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Scale(frame, from_=80, to=230, variable=self.vars["threshold"], orient="horizontal").grid(
            row=5,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(6, 10),
            pady=(10, 0),
        )
        ttk.Label(frame, textvariable=self.vars["threshold"]).grid(row=5, column=3, sticky="w", pady=(10, 0))

        ttk.Label(frame, text="Output").grid(row=6, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self.vars["output"]).grid(row=7, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        ttk.Button(frame, text="Browse", command=self.choose_output).grid(row=7, column=3, sticky="ew", padx=(8, 0), pady=(4, 0))
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
        frame = ttk.LabelFrame(parent, text="Map Preview", padding=12)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        top = ttk.Frame(frame)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Label(top, textvariable=self.vars["preview_status"], style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(top, text="-", width=3, command=lambda: self.zoom_map(-1)).grid(row=0, column=1, padx=(8, 3))
        ttk.Button(top, text="+", width=3, command=lambda: self.zoom_map(1)).grid(row=0, column=2, padx=3)
        ttk.Button(top, text="Use View", command=self.use_map_view).grid(row=0, column=3, padx=3)
        self.preview_button = ttk.Button(top, text="Refresh", command=self.refresh_preview)
        self.preview_button.grid(row=0, column=4, padx=(3, 0))

        self.map_canvas = tk.Canvas(
            frame,
            background="#dde3dd",
            highlightthickness=1,
            highlightbackground="#17211b",
            borderwidth=1,
        )
        self.map_canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.map_canvas.create_text(360, 260, text="Loading OpenFreeMap preview...", fill="#17211b", tags=("loading",))
        self.map_canvas.bind("<ButtonPress-1>", self.start_map_drag)
        self.map_canvas.bind("<B1-Motion>", self.drag_map)
        self.map_canvas.bind("<ButtonRelease-1>", self.end_map_drag)
        self.map_canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.map_canvas.bind("<Configure>", lambda _event: self.schedule_preview())
        return frame

    def build_actions(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        for column in range(3):
            frame.columnconfigure(column, weight=1)
        ttk.Label(frame, textvariable=self.vars["tile_count"], style="Hint.TLabel").grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(frame, textvariable=self.vars["status"], style="Hint.TLabel").grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Button(frame, text="Estimate", command=self.estimate_tiles).grid(row=2, column=0, sticky="ew", padx=(0, 6))
        self.export_button = ttk.Button(frame, text="Export Tiles", style="Accent.TButton", command=self.export_tiles)
        self.export_button.grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Button(frame, text="Open Folder", command=self.open_output_folder).grid(row=2, column=2, sticky="ew", padx=(6, 0))
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
                "include": DEFAULT_ELEMENTS,
                "exclude": [element for element in cli.MAP_ELEMENTS if element not in DEFAULT_ELEMENTS],
            },
            "layout": self.vars["layout"].get(),
            "urlTemplate": url_template,
            "attribution": cli.DEFAULT_ATTRIBUTION,
        }

    def estimate_tiles(self) -> None:
        try:
            job = self.build_job()
            bbox = cli.BBox(**job["bbox"])
            tiles = cli.tiles_for_bbox(bbox, job["zooms"])
        except Exception as exc:  # noqa: BLE001 - show validation errors in GUI.
            messagebox.showerror("Invalid export settings", str(exc))
            return
        self.vars["tile_count"].set(f"Estimate: {len(tiles):,} tiles across zooms {job['zooms'][0]}-{job['zooms'][-1]}")
        self.vars["status"].set("Estimate updated")

    def refresh_preview(self) -> None:
        if self.preview_thread and self.preview_thread.is_alive():
            self.schedule_preview(delay_ms=500)
            return
        self.preview_after_id = None
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
            self.after(0, lambda: self.preview_button.configure(state="normal"))

    def make_preview_image(self, job: dict[str, Any]):
        from PIL import Image, ImageDraw

        bbox = cli.BBox(**job["bbox"])
        zoom = self.map_zoom
        tile_size = 256
        width = max(self.map_canvas.winfo_width(), 640)
        height = max(self.map_canvas.winfo_height(), 520)
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
                image = self.render_preview_vector_tile(tile_id)
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
        return canvas

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
            outline="#000000",
            width=4,
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
        width = max(self.map_canvas.winfo_width(), 640)
        height = max(self.map_canvas.winfo_height(), 520)
        center_x, center_y = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, self.map_zoom)
        west, north = self.world_pixel_to_lon_lat(center_x - width / 2, center_y - height / 2, self.map_zoom)
        east, south = self.world_pixel_to_lon_lat(center_x + width / 2, center_y + height / 2, self.map_zoom)
        return cli.BBox(west=west, south=south, east=east, north=north)

    def draw_preview_placeholder(self, text: str) -> None:
        self.map_canvas.delete("all")
        width = max(self.map_canvas.winfo_width(), 640)
        height = max(self.map_canvas.winfo_height(), 520)
        self.map_canvas.create_rectangle(0, 0, width, height, fill="#eef2ec", outline="#17211b")
        self.map_canvas.create_text(width / 2, height / 2, text=text, fill="#17211b", font=("Segoe UI", 11), justify="center")

    def draw_zoom_badge(self) -> None:
        self.map_canvas.create_oval(10, 10, 44, 44, fill="#ffffff", outline="#17211b")
        self.map_canvas.create_text(27, 27, text=str(self.map_zoom), fill="#000000", font=("Segoe UI", 12, "bold"))

    def shift_current_preview(self, dx: int, dy: int) -> None:
        if self.preview_image is None:
            self.draw_preview_placeholder("Release to render map...")
            return
        self.map_canvas.delete("drag-preview")
        self.map_canvas.create_image(dx, dy, image=self.preview_image, anchor="nw", tags=("drag-preview",))
        self.draw_zoom_badge()

    def render_preview_vector_tile(self, tile: cli.Tile):
        from PIL import Image

        cache_key = ("openfreemap-vector", tile.z, tile.x, tile.y)
        cached = self.preview_tile_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        with tempfile.TemporaryDirectory(prefix="eink-map-preview-") as temp_dir:
            tile_path = Path(temp_dir) / "tile.png"
            cli.render_openfreemap_tile(tile, tile_path, cli.DEFAULT_USER_AGENT, timeout=12, retries=2)
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
        if mode == "mono":
            return image.convert("L").point(lambda pixel: 255 if pixel >= int(job["threshold"]) else 0, mode="1")
        if mode == "grayscale":
            return image.convert("L")
        if mode == "palette":
            return image.quantize(colors=256)
        return image

    def show_preview_image(self, image, render_id: int) -> None:
        from PIL import ImageTk

        if render_id != self.preview_render_id:
            return
        self.preview_image = ImageTk.PhotoImage(image)
        self.map_canvas.delete("all")
        self.map_canvas.create_image(0, 0, image=self.preview_image, anchor="nw")
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

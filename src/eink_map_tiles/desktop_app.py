from __future__ import annotations

import io
import json
import os
import queue
import tempfile
import threading
import tkinter as tk
import urllib.request
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
        "help": "Default. Downloads OpenFreeMap vector tiles for the selected area and renders e-paper PNGs locally.",
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
        self.geometry("1080x900")
        self.minsize(920, 720)

        self.messages: queue.Queue[str] = queue.Queue()
        self.export_thread: threading.Thread | None = None
        self.preview_thread: threading.Thread | None = None
        self.last_output: Path | None = None
        self.preview_image: tk.PhotoImage | None = None

        self.vars = self.make_vars()
        self.configure_styles()
        self.build_ui()
        self.apply_source_preset()
        self.estimate_tiles()
        self.poll_messages()

    def make_vars(self) -> dict[str, tk.Variable]:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return {
            "source_preset": tk.StringVar(value="OpenFreeMap open vector tiles"),
            "source": tk.StringVar(value="openfreemap-vector"),
            "source_help": tk.StringVar(value=SOURCE_PRESETS["OpenFreeMap open vector tiles"]["help"]),
            "url": tk.StringVar(value=SOURCE_PRESETS["OpenFreeMap open vector tiles"]["url"]),
            "permission": tk.BooleanVar(value=True),
            "west": tk.StringVar(value="-122.55"),
            "south": tk.StringVar(value="47.45"),
            "east": tk.StringVar(value="-122.15"),
            "north": tk.StringVar(value="47.75"),
            "center_lat": tk.StringVar(value="47.6062"),
            "center_lon": tk.StringVar(value="-122.3321"),
            "radius_km": tk.StringVar(value="10"),
            "min_zoom": tk.StringVar(value="6"),
            "max_zoom": tk.StringVar(value="12"),
            "style": tk.StringVar(value="osm-eink"),
            "layout": tk.StringVar(value="inkhud-dev"),
            "mode": tk.StringVar(value="mono"),
            "brightness": tk.DoubleVar(value=0.95),
            "contrast": tk.DoubleVar(value=1.4),
            "threshold": tk.IntVar(value=201),
            "output": tk.StringVar(value=str(DEFAULT_OUTPUT_BASE / f"osm-eink-{timestamp}")),
            "tile_count": tk.StringVar(value="Estimate: not calculated"),
            "preview_status": tk.StringVar(value="Click Refresh Preview to download a small OpenFreeMap sample."),
            "status": tk.StringVar(value="Ready"),
        }

    def configure_styles(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f6f1")
        style.configure("TLabelframe", background="#f4f6f1")
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background="#f4f6f1", font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Hint.TLabel", foreground="#58645c", wraplength=880)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    def build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(5, weight=1)
        root.rowconfigure(6, weight=1)

        ttk.Label(root, text="E-ink Map Tiles", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            root,
            text="Local-only desktop exporter. Pick an area, use a source you are allowed to export from, and create an e-paper tile bundle.",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="ew", pady=(4, 12))

        self.build_source(root).grid(row=2, column=0, sticky="ew", pady=6)
        self.build_area(root).grid(row=3, column=0, sticky="ew", pady=6)
        self.build_settings(root).grid(row=4, column=0, sticky="ew", pady=6)
        self.build_preview(root).grid(row=5, column=0, sticky="nsew", pady=6)
        self.build_log(root).grid(row=6, column=0, sticky="nsew", pady=6)
        self.build_actions(root).grid(row=7, column=0, sticky="ew", pady=(8, 0))

    def build_source(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Legal Tile Source", padding=12)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        ttk.Label(frame, text="Source preset").grid(row=0, column=0, sticky="w", padx=(0, 8))
        preset = ttk.Combobox(
            frame,
            textvariable=self.vars["source_preset"],
            values=list(SOURCE_PRESETS),
            state="readonly",
        )
        preset.grid(row=0, column=1, sticky="ew")
        preset.bind("<<ComboboxSelected>>", lambda _event: self.apply_source_preset())
        ttk.Button(frame, text="Source Help", command=self.show_source_help).grid(row=0, column=2, sticky="ew", padx=(8, 0))

        ttk.Label(frame, text="Source URL").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(frame, textvariable=self.vars["url"]).grid(row=1, column=1, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(frame, textvariable=self.vars["source_help"], style="Hint.TLabel").grid(
            row=1,
            column=3,
            sticky="w",
            padx=(10, 0),
            pady=(8, 0),
        )
        ttk.Checkbutton(
            frame,
            text="I will keep required map attribution with exported tiles.",
            variable=self.vars["permission"],
        ).grid(row=2, column=1, columnspan=3, sticky="w", pady=(8, 0))
        return frame

    def build_area(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Area", padding=12)
        for column in range(8):
            frame.columnconfigure(column, weight=1)

        labels = [
            ("West", "west"),
            ("South", "south"),
            ("East", "east"),
            ("North", "north"),
        ]
        for index, (label, key) in enumerate(labels):
            ttk.Label(frame, text=label).grid(row=0, column=index * 2, sticky="w")
            ttk.Entry(frame, textvariable=self.vars[key], width=12).grid(row=0, column=index * 2 + 1, sticky="ew", padx=(4, 10))

        ttk.Label(frame, text="Center lat").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self.vars["center_lat"], width=12).grid(row=1, column=1, sticky="ew", padx=(4, 10), pady=(10, 0))
        ttk.Label(frame, text="Center lon").grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self.vars["center_lon"], width=12).grid(row=1, column=3, sticky="ew", padx=(4, 10), pady=(10, 0))
        ttk.Label(frame, text="Radius km").grid(row=1, column=4, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self.vars["radius_km"], width=12).grid(row=1, column=5, sticky="ew", padx=(4, 10), pady=(10, 0))
        ttk.Button(frame, text="Set BBox From Center", command=self.set_bbox_from_center).grid(
            row=1,
            column=6,
            columnspan=2,
            sticky="ew",
            pady=(10, 0),
        )
        return frame

    def build_settings(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Export Settings", padding=12)
        for column in range(8):
            frame.columnconfigure(column, weight=1)

        fields = [
            ("Min zoom", "min_zoom", 0),
            ("Max zoom", "max_zoom", 2),
            ("Style", "style", 4),
        ]
        for label, key, column in fields:
            ttk.Label(frame, text=label).grid(row=0, column=column, sticky="w")
            ttk.Entry(frame, textvariable=self.vars[key], width=12).grid(row=0, column=column + 1, sticky="ew", padx=(4, 10))

        ttk.Label(frame, text="Mode").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Combobox(
            frame,
            textvariable=self.vars["mode"],
            values=["mono", "grayscale", "palette", "original"],
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="ew", padx=(4, 10), pady=(10, 0))

        ttk.Label(frame, text="Layout").grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Combobox(
            frame,
            textvariable=self.vars["layout"],
            values=["inkhud-dev", "style-root", "single-map", "meshtastic-sd"],
            state="readonly",
            width=16,
        ).grid(row=1, column=3, sticky="ew", padx=(4, 10), pady=(10, 0))

        ttk.Label(frame, text="Brightness").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Scale(frame, from_=0.6, to=1.6, variable=self.vars["brightness"], orient="horizontal").grid(
            row=2,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(4, 10),
            pady=(12, 0),
        )
        ttk.Label(frame, textvariable=self.vars["brightness"]).grid(row=2, column=3, sticky="w", pady=(12, 0))

        ttk.Label(frame, text="Contrast").grid(row=2, column=4, sticky="w", pady=(12, 0))
        ttk.Scale(frame, from_=0.6, to=3.0, variable=self.vars["contrast"], orient="horizontal").grid(
            row=2,
            column=5,
            columnspan=2,
            sticky="ew",
            padx=(4, 10),
            pady=(12, 0),
        )
        ttk.Label(frame, textvariable=self.vars["contrast"]).grid(row=2, column=7, sticky="w", pady=(12, 0))

        ttk.Label(frame, text="Mono threshold").grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Scale(frame, from_=80, to=230, variable=self.vars["threshold"], orient="horizontal").grid(
            row=3,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(4, 10),
            pady=(12, 0),
        )
        ttk.Label(frame, textvariable=self.vars["threshold"]).grid(row=3, column=3, sticky="w", pady=(12, 0))

        ttk.Label(frame, text="Output").grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.vars["output"]).grid(row=4, column=1, columnspan=5, sticky="ew", padx=(4, 10), pady=(12, 0))
        ttk.Button(frame, text="Browse", command=self.choose_output).grid(row=4, column=6, columnspan=2, sticky="ew", pady=(12, 0))
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
        frame = ttk.LabelFrame(parent, text="Preview", padding=12)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        top = ttk.Frame(frame)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Label(top, textvariable=self.vars["preview_status"], style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        self.preview_button = ttk.Button(top, text="Refresh Preview", command=self.refresh_preview)
        self.preview_button.grid(row=0, column=1, padx=(8, 0))

        self.preview_label = tk.Label(
            frame,
            text="Preview appears here after a legal tile source is reachable.",
            bg="#eef2ec",
            fg="#17211b",
            anchor="center",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 10),
        )
        self.preview_label.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        return frame

    def build_actions(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, textvariable=self.vars["status"], style="Hint.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(frame, text="Estimate Tiles", command=self.estimate_tiles).grid(row=0, column=1, padx=6)
        self.export_button = ttk.Button(frame, text="Export Tiles", style="Accent.TButton", command=self.export_tiles)
        self.export_button.grid(row=0, column=2, padx=6)
        ttk.Button(frame, text="Open Output Folder", command=self.open_output_folder).grid(row=0, column=3, padx=6)
        return frame

    def apply_source_preset(self) -> None:
        preset = SOURCE_PRESETS.get(str(self.vars["source_preset"].get()), SOURCE_PRESETS["Custom XYZ PNG URL"])
        self.vars["source"].set(preset["source"])
        self.vars["source_help"].set(preset["help"])
        if preset["url"]:
            self.vars["url"].set(preset["url"])
        if preset["source"] == "openfreemap-vector":
            self.vars["permission"].set(True)

    def show_source_help(self) -> None:
        messagebox.showinfo(
            "Tile source help",
            "\n".join(
                [
                    "This app is local-only, but it still needs map data from a legal source.",
                    "",
                    "The default source downloads OpenFreeMap vector tiles and renders them locally into e-paper PNGs.",
                    "",
                    "No tile URL is needed for the default OpenFreeMap source.",
                    "",
                    "Advanced users can switch to a local TileServer GL raster URL or a custom XYZ PNG URL.",
                    "",
                    "Do not use tile.openstreetmap.org for offline exports.",
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
            return
        try:
            job = self.build_job()
            self.validate_tile_url(job["urlTemplate"])
        except Exception as exc:  # noqa: BLE001 - show validation errors in GUI.
            messagebox.showerror("Cannot preview", str(exc))
            return

        self.preview_button.configure(state="disabled")
        self.vars["preview_status"].set("Loading preview tiles...")
        self.preview_thread = threading.Thread(target=self.load_preview, args=(job,), daemon=True)
        self.preview_thread.start()

    def load_preview(self, job: dict[str, Any]) -> None:
        try:
            image = self.make_preview_image(job)
            self.after(0, lambda: self.show_preview_image(image))
        except Exception as exc:  # noqa: BLE001 - report worker errors in GUI.
            self.after(0, lambda: self.preview_failed(str(exc)))
        finally:
            self.after(0, lambda: self.preview_button.configure(state="normal"))

    def make_preview_image(self, job: dict[str, Any]):
        from PIL import Image

        bbox = cli.BBox(**job["bbox"])
        zoom = max(job["zooms"])
        center_lon = self.center_lon(bbox)
        center_lat = (bbox.south + bbox.north) / 2
        center_x, center_y = cli.lonlat_to_tile(center_lon, center_lat, zoom)
        grid_size = 3
        tile_size = 256
        n = 2**zoom
        canvas = Image.new("RGB", (tile_size * grid_size, tile_size * grid_size), "#f7f8f4")

        for dx in range(-1, 2):
            for dy in range(-1, 2):
                x = cli.clamp(center_x + dx, 0, n - 1)
                y = cli.clamp(center_y + dy, 0, n - 1)
                tile_id = cli.Tile(z=zoom, x=x, y=y)
                if job["source"] == "openfreemap-vector":
                    tile = self.render_preview_vector_tile(tile_id)
                else:
                    url = cli.tile_url(job["urlTemplate"], tile_id)
                    tile = self.fetch_preview_tile(url)
                tile = self.convert_preview_tile(tile, job)
                canvas.paste(tile.convert("RGB"), ((dx + 1) * tile_size, (dy + 1) * tile_size))

        canvas.thumbnail((620, 320))
        return canvas

    def render_preview_vector_tile(self, tile: cli.Tile):
        from PIL import Image

        with tempfile.TemporaryDirectory(prefix="eink-map-preview-") as temp_dir:
            tile_path = Path(temp_dir) / "tile.png"
            cli.render_openfreemap_tile(tile, tile_path, cli.DEFAULT_USER_AGENT, timeout=12, retries=2)
            with Image.open(tile_path) as image:
                return image.convert("RGBA")

    def fetch_preview_tile(self, url: str):
        from PIL import Image

        request = urllib.request.Request(url, headers={"User-Agent": cli.DEFAULT_USER_AGENT})
        with urllib.request.urlopen(request, timeout=12) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status} for {url}")
            data = response.read()
        return Image.open(BytesIO(data)).convert("RGBA")

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

    def show_preview_image(self, image) -> None:
        from PIL import ImageTk

        self.preview_image = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self.preview_image, text="")
        self.vars["preview_status"].set("Preview updated with current e-paper settings.")

    def preview_failed(self, error: str) -> None:
        self.preview_label.configure(
            image="",
            text="Preview unavailable.\n\nStart the selected local tile source, then click Refresh Preview.",
        )
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

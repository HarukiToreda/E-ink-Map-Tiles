from __future__ import annotations

import io
import json
import lz4.block
import math
import queue
import re
import tempfile
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from . import cli


DEFAULT_OUTPUT_BASE = Path.home() / "Downloads" / "EinkMapTiles"
DESKTOP_RATE_LIMIT_SECONDS = 0.05
DESKTOP_TILE_LAYOUT = "inkhud-dev"
INKHUD_DEFAULT_BRIGHTNESS = 1.03
INKHUD_DEFAULT_CONTRAST = 2.41
MIN_PREVIEW_ZOOM = 2
MAX_PREVIEW_ZOOM = cli.TOPO_MAX_DETAIL_ZOOM
NORMAL_PREVIEW_MAX_ZOOM = cli.OPENFREEMAP_MAX_DETAIL_ZOOM
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
DEFAULT_SOURCE_NAME = "OpenFreeMap open vector tiles"
DEFAULT_SOURCE_HELP = "Default open vector source. The app renders preview and export tiles locally."


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
        self.preview_rendered_width: int = 0
        self.preview_rendered_height: int = 0
        self.live_update_after_id: str | None = None
        self.preview_tile_cache: dict[tuple, Any] = {}
        self.export_total = 0
        self.collapsible_sections: dict[str, dict[str, Any]] = {}
        self.threshold_widgets: list[tk.Widget] = []
        self.threshold_grid_options: dict[tk.Widget, dict[str, Any]] = {}
        self.applying_style_preset = False
        self.syncing_view_bounds = False
        self.applying_mode_defaults = False
        self.brightness_user_changed = False
        self.contrast_user_changed = False
        self.inkhud2_selected_tiles: dict[int, set[tuple[int, int]]] = {}

        self.vars = self.make_vars()
        self.configure_styles()
        self.build_ui()
        self.update_mode_sensitive_controls()
        self.bind_live_controls()
        self.sync_view_area(update_estimate=False)
        self.estimate_tiles()
        self.update_inkhud_flash_bars()
        self.after(700, self.refresh_preview)
        self.poll_messages()

    def make_vars(self) -> dict[str, tk.Variable]:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        variables: dict[str, tk.Variable] = {
            "source": tk.StringVar(value="openfreemap-vector"),
            "source_help": tk.StringVar(value=DEFAULT_SOURCE_HELP),
            "url": tk.StringVar(value=cli.OPENFREEMAP_VECTOR_TEMPLATE),
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
            "style": tk.StringVar(value=cli.DEFAULT_STYLE),
            "mode": tk.StringVar(value="grayscale"),
            "brightness": tk.DoubleVar(value=cli.DEFAULT_BRIGHTNESS),
            "contrast": tk.DoubleVar(value=cli.DEFAULT_CONTRAST),
            "threshold": tk.DoubleVar(value=cli.DEFAULT_THRESHOLD),
            "output": tk.StringVar(value=str(DEFAULT_OUTPUT_BASE / f"osm-eink-{timestamp}")),
            "tile_count": tk.StringVar(value="Estimate: not calculated"),
            "preview_status": tk.StringVar(value="Loading preview..."),
            "status": tk.StringVar(value="Ready"),
            "progress_text": tk.StringVar(value="No export running"),
            "progress_value": tk.DoubleVar(value=0),
            "brightness_text": tk.StringVar(value=f"{cli.DEFAULT_BRIGHTNESS:.2f}"),
            "contrast_text": tk.StringVar(value=f"{cli.DEFAULT_CONTRAST:.2f}"),
            "threshold_text": tk.StringVar(value=f"{cli.DEFAULT_THRESHOLD:.0f}"),
            "collapse_map_source": tk.BooleanVar(value=False),
            "collapse_area": tk.BooleanVar(value=False),
            "collapse_export_settings": tk.BooleanVar(value=True),
            "collapse_map_elements": tk.BooleanVar(value=True),
            "show_inkhud_coverage": tk.BooleanVar(value=False),
            "inkhud_grid": tk.StringVar(value="4x4"),
        }
        for element in cli.MAP_ELEMENTS:
            variables[f"element_{element}"] = tk.BooleanVar(value=element in cli.DEFAULT_INCLUDE_ELEMENTS)
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
        preview_keys = ("mode", "brightness", "contrast", "threshold", "source", "url", "style")
        for key in preview_keys:
            self.vars[key].trace_add("write", lambda *_args: self.queue_live_update(preview=True, estimate=False))
        self.vars["brightness"].trace_add("write", lambda *_args: self.on_brightness_changed())
        self.vars["contrast"].trace_add("write", lambda *_args: self.on_contrast_changed())
        self.vars["threshold"].trace_add("write", lambda *_args: self.update_slider_labels())
        self.vars["mode"].trace_add("write", lambda *_args: self.update_mode_sensitive_controls())
        self.vars["mode"].trace_add("write", lambda *_args: self.update_inkhud_flash_bars())
        self.vars["mode"].trace_add("write", lambda *_args: self.draw_inkhud_coverage_overlay())
        self.vars["style"].trace_add("write", lambda *_args: self.apply_style_preset())

        export_keys = ("min_zoom", "max_zoom", "inkhud_grid")
        for key in export_keys:
            self.vars[key].trace_add("write", lambda *_args: self.queue_live_update(preview=False, estimate=True))
            self.vars[key].trace_add("write", lambda *_args: self.update_inkhud_flash_bars())
            self.vars[key].trace_add("write", lambda *_args: self.draw_inkhud_coverage_overlay())

        area_keys = ("west", "south", "east", "north")
        for key in area_keys:
            self.vars[key].trace_add("write", lambda *_args: self.queue_live_update(preview=True, estimate=True))

        for element in cli.MAP_ELEMENTS:
            self.vars[f"element_{element}"].trace_add("write", lambda *_args: self.element_changed())

    def element_changed(self) -> None:
        if not self.applying_style_preset:
            self.queue_live_update(preview=True, estimate=False)

    def apply_style_preset(self) -> None:
        style = self.vars["style"].get()
        selected = cli.DEFAULT_TOPO_ELEMENTS if cli.is_topo_style(style) else cli.DEFAULT_INCLUDE_ELEMENTS
        self.map_zoom = min(self.map_zoom, self.max_preview_zoom_for_style(style))
        self.applying_style_preset = True
        try:
            for element in cli.MAP_ELEMENTS:
                self.vars[f"element_{element}"].set(element in selected)
        finally:
            self.applying_style_preset = False
        self.queue_live_update(preview=True, estimate=True)

    def queue_live_update(self, preview: bool, estimate: bool) -> None:
        if self.syncing_view_bounds:
            return
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

    def max_preview_zoom_for_style(self, style: str | None = None) -> int:
        style = self.vars["style"].get() if style is None else style
        return MAX_PREVIEW_ZOOM if cli.supports_vector_overzoom(style) else NORMAL_PREVIEW_MAX_ZOOM

    def update_slider_labels(self) -> None:
        self.vars["brightness_text"].set(f"{float(self.vars['brightness'].get()):.2f}")
        self.vars["contrast_text"].set(f"{float(self.vars['contrast'].get()):.2f}")
        if self.vars["mode"].get() == "mono":
            self.vars["threshold_text"].set(f"{float(self.vars['threshold'].get()):.0f}")
        else:
            self.vars["threshold_text"].set("")

    def on_brightness_changed(self) -> None:
        if not self.applying_mode_defaults:
            self.brightness_user_changed = True
        self.update_slider_labels()

    def on_contrast_changed(self) -> None:
        if not self.applying_mode_defaults:
            self.contrast_user_changed = True
        self.update_slider_labels()

    def should_apply_brightness_default(self) -> bool:
        return not self.brightness_user_changed or math.isclose(float(self.vars["brightness"].get()), cli.DEFAULT_BRIGHTNESS, abs_tol=0.005)

    def should_apply_contrast_default(self) -> bool:
        return not self.contrast_user_changed or math.isclose(float(self.vars["contrast"].get()), cli.DEFAULT_CONTRAST, abs_tol=0.005)

    def apply_inkhud_defaults_if_unchanged(self) -> None:
        apply_brightness = self.should_apply_brightness_default()
        apply_contrast = self.should_apply_contrast_default()
        if not apply_brightness and not apply_contrast:
            return

        self.applying_mode_defaults = True
        try:
            if apply_brightness:
                self.vars["brightness"].set(INKHUD_DEFAULT_BRIGHTNESS)
                self.brightness_user_changed = False
            if apply_contrast:
                self.vars["contrast"].set(INKHUD_DEFAULT_CONTRAST)
                self.contrast_user_changed = False
        finally:
            self.applying_mode_defaults = False
        self.update_slider_labels()

    def update_mode_sensitive_controls(self) -> None:
        mode = self.vars["mode"].get()
        visible = mode == "mono"
        for widget in self.threshold_widgets:
            if visible:
                widget.grid(**self.threshold_grid_options[widget])
            else:
                widget.grid_remove()
        # InkHUD / InkHUD2 mode: uncheck Land so water renders through (matches export behavior)
        if mode in ("inkhud", "inkhud2"):
            self.apply_inkhud_defaults_if_unchanged()
            self.vars["element_land"].set(False)
        # InkHUD2: hide min/max zoom fields, show zoom checkboxes instead
        is_inkhud2 = mode == "inkhud2"
        for widget in getattr(self, "zoom_range_widgets", []):
            if is_inkhud2:
                widget.grid_remove()
            else:
                widget.grid()
        if hasattr(self, "inkhud2_zoom_frame"):
            if is_inkhud2:
                self.inkhud2_zoom_frame.grid()
                self.update_inkhud2_info()
            else:
                self.inkhud2_zoom_frame.grid_remove()
                self.map_canvas.delete("tile-selection", "tile-grid")
        # Update export button label
        if hasattr(self, "inkhud_button"):
            label = "⬡ Export for InkHUD2" if is_inkhud2 else "⬡ Export for InkHUD"
            self.inkhud_button.configure(text=label)
        self.update_slider_labels()

    def update_inkhud2_info(self) -> None:
        if not hasattr(self, "inkhud2_zoom_frame"):
            return
        frame = self.inkhud2_zoom_frame
        for child in frame.winfo_children():
            child.destroy()

        total = sum(len(v) for v in self.inkhud2_selected_tiles.values())
        zoom_count = sum(1 for v in self.inkhud2_selected_tiles.values() if v)
        kb = total * 256 * 256 // 8 // 1024

        ttk.Label(frame, text="Click tiles on the map to select areas for export.", style="Hint.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        summary = f"{total} tile(s) across {zoom_count} zoom(s) — {kb} KB" if total else "No tiles selected."
        ttk.Label(frame, text=summary, style="Hint.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(1, 4)
        )
        self.flat_button(frame, "Add 3×3 here", self._add_3x3_tiles).grid(row=2, column=0, sticky="ew", padx=(0, 3))
        self.flat_button(frame, "Clear all", self._clear_inkhud2_tiles).grid(row=2, column=1, sticky="ew", padx=(3, 0))

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

        ttk.Label(content, text=DEFAULT_SOURCE_NAME, style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(content, textvariable=self.vars["source_help"], style="Hint.TLabel").grid(row=1, column=0, sticky="ew", pady=(2, 4))

        ttk.Checkbutton(
            content,
            text="I will keep required map attribution with exported tiles.",
            variable=self.vars["permission"],
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))
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
        self.flat_button(content, "Fit Center Area", self.set_bbox_from_center).grid(
            row=1,
            column=2,
            columnspan=2,
            sticky="ew",
            pady=(4, 0),
        )

        ttk.Label(content, text="Visible BBox").grid(row=2, column=0, sticky="w", pady=(6, 0))
        bbox_grid = ttk.Frame(content, style="Card.TFrame")
        bbox_grid.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        for column in range(4):
            bbox_grid.columnconfigure(column, weight=1)
        for index, (label, key) in enumerate((("W", "west"), ("S", "south"), ("E", "east"), ("N", "north"))):
            ttk.Label(bbox_grid, text=label).grid(row=0, column=index, sticky="w")
            ttk.Entry(bbox_grid, textvariable=self.vars[key], width=10, state="readonly").grid(
                row=1,
                column=index,
                sticky="ew",
                padx=(0 if index == 0 else 4, 4),
            )
        return frame

    def build_settings(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame, content = self.collapsible_section(parent, "Export Settings", "collapse_export_settings")
        content.columnconfigure(1, weight=1)
        content.columnconfigure(3, weight=1)

        self.zoom_range_label_min = ttk.Label(content, text="Min zoom")
        self.zoom_range_label_min.grid(row=0, column=0, sticky="w")
        self.zoom_range_entry_min = ttk.Entry(content, textvariable=self.vars["min_zoom"], width=8)
        self.zoom_range_entry_min.grid(row=0, column=1, sticky="ew", padx=(6, 10))
        self.zoom_range_label_max = ttk.Label(content, text="Max zoom")
        self.zoom_range_label_max.grid(row=0, column=2, sticky="w")
        self.zoom_range_entry_max = ttk.Entry(content, textvariable=self.vars["max_zoom"], width=8)
        self.zoom_range_entry_max.grid(row=0, column=3, sticky="ew", padx=(6, 0))
        self.zoom_range_widgets = [
            self.zoom_range_label_min, self.zoom_range_entry_min,
            self.zoom_range_label_max, self.zoom_range_entry_max,
        ]

        # InkHUD2: zoom checkboxes (hidden by default, shown when mode=inkhud2)
        self.inkhud2_zoom_frame = ttk.Frame(content, style="Card.TFrame")
        self.inkhud2_zoom_frame.grid(row=0, column=0, columnspan=4, sticky="ew")
        self.inkhud2_zoom_frame.grid_remove()

        ttk.Label(content, text="Mode").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Combobox(
            content,
            textvariable=self.vars["mode"],
            values=["mono", "grayscale", "inkhud", "inkhud2", "palette", "original"],
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="ew", padx=(6, 10), pady=(4, 0))

        ttk.Label(content, text="Style").grid(row=1, column=2, sticky="w", pady=(4, 0))
        ttk.Combobox(
            content,
            textvariable=self.vars["style"],
            values=["osm-eink", "osm-eink-topo"],
            state="readonly",
            width=16,
        ).grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=(4, 0))

        ttk.Label(content, text="Grid").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.grid_combo = ttk.Combobox(
            content, textvariable=self.vars["inkhud_grid"],
            values=["4x4", "3x3", "2x2"], state="readonly", width=6,
        )
        self.grid_combo.grid(row=2, column=1, sticky="w", padx=(6, 10), pady=(4, 0))
        ttk.Label(content, text="Tiles per zoom level", style="Hint.TLabel").grid(
            row=2, column=2, columnspan=2, sticky="w", pady=(4, 0)
        )

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
        self.preview_button = self.flat_button(top, "Refresh", self.refresh_preview)
        self.preview_button.grid(row=0, column=3, padx=(3, 0))

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
        self.flash_bars_canvas = tk.Canvas(content, height=44, background="#ffffff", highlightthickness=0)
        self.flash_bars_canvas.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 4))
        self.flash_bars_canvas.bind("<Configure>", lambda _e: self.draw_flash_bars(None))
        ttk.Label(content, textvariable=self.vars["status"], style="Hint.TLabel").grid(row=2, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        self.flat_button(content, "Estimate", lambda: self.estimate_tiles(update_bars=True)).grid(row=2, column=0, sticky="ew", padx=(0, 5))
        self.export_button = self.flat_button(content, "Export Tiles", self.export_tiles, primary=True)
        self.export_button.grid(row=2, column=1, sticky="ew", padx=5)
        self.flat_button(content, "Folder", self.open_output_folder).grid(row=2, column=2, sticky="ew", padx=5)
        self.flat_button(content, "About", self.show_about_licenses).grid(row=2, column=3, sticky="ew", padx=(5, 0))
        self.inkhud_button = self.flat_button(content, "⬡ Export for InkHUD", self.export_for_inkhud)
        self.inkhud_button.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.coverage_toggle = ttk.Checkbutton(
            content, text="Coverage", variable=self.vars["show_inkhud_coverage"],
            command=self.draw_inkhud_coverage_overlay,
        )
        self.coverage_toggle.grid(row=3, column=3, sticky="ew", padx=(5, 0), pady=(6, 0))
        self.progress_bar = ttk.Progressbar(content, variable=self.vars["progress_value"], maximum=1, mode="determinate")
        self.progress_bar.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        self.cancel_button = self.flat_button(content, "Cancel", self.cancel_export)
        self.cancel_button.grid(row=4, column=3, sticky="ew", padx=(5, 0), pady=(8, 2))
        self.cancel_button.grid_remove()
        ttk.Label(content, textvariable=self.vars["progress_text"], style="Hint.TLabel").grid(row=5, column=0, columnspan=4, sticky="ew")
        self.log = tk.Text(
            content,
            height=3,
            wrap="word",
            font=("Consolas", 8),
            background="#f7faf7",
            relief="flat",
            borderwidth=0,
        )
        self.log.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.log.grid_remove()
        return frame

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
        self.map_center_lat = (bbox.south + bbox.north) / 2
        self.map_center_lon = self.center_lon(bbox)
        self.map_zoom = self.zoom_to_fit_bbox(bbox)
        self.sync_view_area()
        self.schedule_preview()

    def sync_view_area(self, update_estimate: bool = True) -> None:
        if not hasattr(self, "map_canvas"):
            return
        bbox = self.current_map_bbox()
        self.syncing_view_bounds = True
        try:
            self.vars["west"].set(f"{bbox.west:.6f}")
            self.vars["south"].set(f"{bbox.south:.6f}")
            self.vars["east"].set(f"{bbox.east:.6f}")
            self.vars["north"].set(f"{bbox.north:.6f}")
            self.vars["center_lat"].set(f"{self.map_center_lat:.6f}")
            self.vars["center_lon"].set(f"{self.map_center_lon:.6f}")
        finally:
            self.syncing_view_bounds = False
        if self.vars["mode"].get() == "inkhud2":
            self.update_inkhud2_info()
        elif self.vars["mode"].get() == "inkhud":
            self.update_inkhud_flash_bars()
        if update_estimate:
            self.estimate_tiles(show_errors=False)

    def zoom_to_fit_bbox(self, bbox: cli.BBox) -> int:
        width = max(self.map_canvas.winfo_width(), 320)
        height = max(self.map_canvas.winfo_height(), 260)
        max_zoom = self.max_preview_zoom_for_style()
        for zoom in range(max_zoom, MIN_PREVIEW_ZOOM - 1, -1):
            left, top = self.lon_lat_to_world_pixel(bbox.west, bbox.north, zoom)
            right, bottom = self.lon_lat_to_world_pixel(bbox.east, bbox.south, zoom)
            if bbox.east < bbox.west:
                right += 256 * (2**zoom)
            if abs(right - left) <= width * 0.86 and abs(bottom - top) <= height * 0.86:
                return zoom
        return MIN_PREVIEW_ZOOM

    def zoom_map(self, delta: int, anchor: tuple[int, int] | None = None) -> None:
        old_zoom = self.map_zoom
        new_zoom = cli.clamp(old_zoom + delta, MIN_PREVIEW_ZOOM, self.max_preview_zoom_for_style())
        if new_zoom == old_zoom:
            return

        if anchor is not None:
            width = self.preview_rendered_width or max(self.map_canvas.winfo_width(), 320)
            height = self.preview_rendered_height or max(self.map_canvas.winfo_height(), 260)
            anchor_x, anchor_y = anchor
            old_center_x, old_center_y = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, old_zoom)
            anchor_world_x = old_center_x - width / 2 + anchor_x
            anchor_world_y = old_center_y - height / 2 + anchor_y
            anchor_lon, anchor_lat = self.world_pixel_to_lon_lat(anchor_world_x, anchor_world_y, old_zoom)
            self.map_center_lon = cli.normalize_lon(anchor_lon)
            self.map_center_lat = max(min(anchor_lat, cli.MAX_MERCATOR_LAT), -cli.MAX_MERCATOR_LAT)

        self.map_zoom = new_zoom
        self.sync_view_area()
        self.set_preview_status(f"Rendering export preview z{self.map_zoom}...")
        if self.preview_image is None:
            self.draw_preview_placeholder(f"Rendering export preview z{self.map_zoom}...")
        else:
            self.map_canvas.delete("zoom-badge", "center-marker")
            self.draw_zoom_badge()
            self.draw_center_marker()
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

    def end_map_drag(self, event) -> None:
        if self.map_drag_start is not None:
            dx = event.x - self.map_drag_start[0]
            dy = event.y - self.map_drag_start[1]
            moved = (dx * dx + dy * dy) ** 0.5
            self.map_drag_start = None
            self.map_drag_center = None
            if moved < 5 and self.vars["mode"].get() == "inkhud2":
                self.toggle_inkhud2_tile(event.x, event.y)
                return
        else:
            self.map_drag_start = None
            self.map_drag_center = None
        self.sync_view_area()
        self.schedule_preview(delay_ms=250)

    def on_mouse_wheel(self, event) -> None:
        self.zoom_map(1 if event.delta > 0 else -1, anchor=(event.x, event.y))

    def schedule_preview(self, delay_ms: int = 350) -> None:
        self.sync_view_area(update_estimate=False)
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
        bbox = self.current_map_bbox()
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
            "layout": DESKTOP_TILE_LAYOUT,
            "urlTemplate": url_template,
            "attribution": cli.DEFAULT_ATTRIBUTION,
            "canvas_width": max(self.map_canvas.winfo_width(), 320),
            "canvas_height": max(self.map_canvas.winfo_height(), 260),
        }

    # Flash budgets: (available_for_tiles_bytes, label)
    # ESP32-S3: app0 partition = 0x330000 (3,342,336 B), InkHUD firmware ~2.2 MB → ~1.1 MB free
    # nRF52840: usable flash = 0xC6000 (811,008 B) after SoftDevice, firmware ~720 KB → ~88 KB free
    FLASH_TARGETS = [
        (1_100_000, "ESP32-S3 (8 MB flash)"),
        (  87_232,  "nRF52840 (1 MB flash)"),
    ]

    def draw_flash_bars(self, tile_bytes: int | None = None, upper_bound: bool = False) -> None:
        c = self.flash_bars_canvas
        c.delete("all")
        w = c.winfo_width()
        if w < 10:
            return
        if tile_bytes is None:
            tile_bytes = getattr(self, "_last_tile_bytes", None)
            upper_bound = getattr(self, "_last_tile_upper_bound", False)
        if tile_bytes is None:
            return
        self._last_tile_bytes = tile_bytes
        self._last_tile_upper_bound = upper_bound

        bar_h = 14
        label_w = 120
        bar_w = w - label_w - 8
        y0 = 2

        for available, label in self.FLASH_TARGETS:
            fill_ratio = min(tile_bytes / available, 1.0)
            used_px = int(fill_ratio * bar_w)

            if fill_ratio < 0.6:
                color = "#3a9e5f"
            elif fill_ratio < 0.85:
                color = "#e0a020"
            else:
                color = "#c0392b"

            kb = tile_bytes / 1024
            avail_kb = available / 1024
            pct = (tile_bytes / available) * 100
            bound_tag = "≤ " if upper_bound else ""
            size_text = f"{bound_tag}{kb:.0f} / {avail_kb:.0f} KB ({bound_tag}{pct:.0f}%)"

            # Label left of bar
            c.create_text(0, y0 + bar_h // 2, anchor="w", text=label,
                          font=("Segoe UI", 8), fill="#536158")
            # Background track
            c.create_rectangle(label_w, y0, label_w + bar_w, y0 + bar_h,
                                fill="#e8ede9", outline="#d3ddd5")
            # Fill
            if used_px > 0:
                c.create_rectangle(label_w, y0, label_w + used_px, y0 + bar_h,
                                   fill=color, outline="")
            # Size text centered inside the bar track
            c.create_text(label_w + bar_w // 2, y0 + bar_h // 2, anchor="center",
                          text=size_text, font=("Segoe UI", 8), fill="#1a2e22")

            y0 += bar_h + 5

    def update_inkhud_flash_bars(self) -> None:
        mode = self.vars["mode"].get()
        if mode == "inkhud":
            try:
                min_zoom = int(self.vars["min_zoom"].get())
                max_zoom = int(self.vars["max_zoom"].get())
            except ValueError:
                return
            num_zooms = max(0, max_zoom - min_zoom + 1)
            g = int(self.vars["inkhud_grid"].get()[0])  # "4x4" -> 4
            estimated = int(num_zooms * g * g * 256 * 256 // 8 * 0.45)
            self.draw_flash_bars(estimated, upper_bound=True)
            self.vars["tile_count"].set(f"InkHUD: {num_zooms} zoom(s) {g}×{g} — ≈{estimated // 1024} KB (LZ4 est.)")
        elif mode == "inkhud2":
            total = sum(len(v) for v in self.inkhud2_selected_tiles.values())
            estimated = int(total * 256 * 256 // 8 * 0.45)
            zoom_count = sum(1 for v in self.inkhud2_selected_tiles.values() if v)
            self.draw_flash_bars(estimated, upper_bound=True)
            self.vars["tile_count"].set(f"InkHUD2: {total} tile(s) across {zoom_count} zoom(s) — ≈{estimated // 1024} KB (LZ4 est.)")

    def estimate_tiles(self, show_errors: bool = True, update_bars: bool = False) -> None:
        try:
            job = self.build_job()
            bbox = cli.BBox(**job["bbox"])
            tile_count = cli.count_tiles_for_bbox(bbox, job["zooms"])
        except Exception as exc:  # noqa: BLE001 - show validation errors in GUI.
            if show_errors:
                messagebox.showerror("Invalid export settings", str(exc))
            return

        if self.vars["mode"].get() in ("inkhud", "inkhud2"):
            self.update_inkhud_flash_bars()
            return
        else:
            self.vars["tile_count"].set(f"Estimate: {tile_count:,} tiles across zooms {job['zooms'][0]}-{job['zooms'][-1]}")
        self.vars["status"].set("Estimate updated")

        # Flash bars update only on explicit Estimate click (InkHUD/InkHUD2 bars use a separate live path)
        if update_bars and self.vars["mode"].get() not in ("inkhud", "inkhud2"):
            self.draw_flash_bars(tile_count * 256 * 256 // 8)

    def refresh_preview(self) -> None:
        if self.preview_thread and self.preview_thread.is_alive():
            self.preview_pending = True
            return
        self.preview_after_id = None
        self.preview_pending = False
        try:
            job = self.build_job()
        except Exception as exc:  # noqa: BLE001 - show validation errors in GUI.
            messagebox.showerror("Cannot preview", str(exc))
            return

        self.preview_button.configure(state="disabled")
        self.preview_render_id += 1
        render_id = self.preview_render_id
        self.set_preview_status(f"Rendering export preview z{self.map_zoom}...")
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
        width = job.get("canvas_width") or max(self.map_canvas.winfo_width(), 320)
        height = job.get("canvas_height") or max(self.map_canvas.winfo_height(), 260)
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
            image = self.render_preview_vector_tile(tile_id, job)
            image = self.convert_preview_tile(image, job)
            return paste_x, paste_y, image.convert("RGB")

        max_workers = 6
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
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
        return self.map_bbox_at_zoom(self.map_zoom)

    def toggle_inkhud2_tile(self, cx: int, cy: int) -> None:
        zoom = self.map_zoom
        width = max(self.map_canvas.winfo_width(), 320)
        height = max(self.map_canvas.winfo_height(), 260)
        cx_world, cy_world = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, zoom)
        tx = int((cx_world - width / 2 + cx) / 256)
        ty = int((cy_world - height / 2 + cy) / 256)
        tiles = self.inkhud2_selected_tiles.setdefault(zoom, set())
        tile = (tx, ty)
        if tile in tiles:
            tiles.discard(tile)
            if not tiles:
                del self.inkhud2_selected_tiles[zoom]
        else:
            tiles.add(tile)
        self.draw_tile_selection_overlay()
        self.draw_tile_grid_overlay()
        self.update_inkhud_flash_bars()
        self.update_inkhud2_info()

    def _add_3x3_tiles(self) -> None:
        z = self.map_zoom
        tx, ty = cli.lonlat_to_tile(self.map_center_lon, self.map_center_lat, z)
        tiles = self.inkhud2_selected_tiles.setdefault(z, set())
        for ddx in range(-1, 2):
            for ddy in range(-1, 2):
                tiles.add((tx + ddx, ty + ddy))
        self.draw_tile_selection_overlay()
        self.draw_tile_grid_overlay()
        self.update_inkhud_flash_bars()
        self.update_inkhud2_info()

    def _clear_inkhud2_tiles(self) -> None:
        self.inkhud2_selected_tiles.clear()
        self.map_canvas.delete("tile-selection")
        self.update_inkhud_flash_bars()
        self.update_inkhud2_info()

    def draw_tile_grid_overlay(self) -> None:
        self.map_canvas.delete("tile-grid")
        if self.vars["mode"].get() != "inkhud2":
            return
        zoom = self.map_zoom
        width = max(self.map_canvas.winfo_width(), 320)
        height = max(self.map_canvas.winfo_height(), 260)
        cx_world, cy_world = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, zoom)
        left_world = cx_world - width / 2
        top_world  = cy_world - height / 2
        tx_min = int(left_world / 256)
        ty_min = int(top_world / 256)
        tx_max = int((left_world + width) / 256) + 1
        ty_max = int((top_world + height) / 256) + 1
        for tx in range(tx_min, tx_max + 1):
            x = tx * 256 - left_world
            self.map_canvas.create_line(x, 0, x, height, fill="#777777", width=1, dash=(3, 6), tags=("tile-grid",))
        for ty in range(ty_min, ty_max + 1):
            y = ty * 256 - top_world
            self.map_canvas.create_line(0, y, width, y, fill="#777777", width=1, dash=(3, 6), tags=("tile-grid",))

    def draw_tile_selection_overlay(self) -> None:
        self.map_canvas.delete("tile-selection")
        if self.vars["mode"].get() != "inkhud2" or not self.inkhud2_selected_tiles:
            return
        view_zoom = self.map_zoom
        width = max(self.map_canvas.winfo_width(), 320)
        height = max(self.map_canvas.winfo_height(), 260)
        cx_world, cy_world = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, view_zoom)
        left_world = cx_world - width / 2
        top_world  = cy_world - height / 2
        for z, tiles in self.inkhud2_selected_tiles.items():
            if z < view_zoom:
                continue  # hide zoomed-out tiles when viewing at finer detail
            scale = 2 ** (view_zoom - z)  # >1 when zoomed in past tile zoom, <1 when zoomed out
            tile_px = 256 * scale
            for tx, ty in tiles:
                x0 = tx * tile_px - left_world
                y0 = ty * tile_px - top_world
                x1, y1 = x0 + tile_px, y0 + tile_px
                if x1 < 0 or x0 > width or y1 < 0 or y0 > height:
                    continue
                self.map_canvas.create_rectangle(
                    x0, y0, x1, y1,
                    fill="#3a9e5f", stipple="gray25", outline="#1a6e40", width=2,
                    tags=("tile-selection",)
                )
                if tile_px > 24:
                    self.map_canvas.create_text(
                        max(x0 + 3, 0), max(y0 + 2, 0), anchor="nw",
                        text=f"z{z}", fill="#0a4020", font=("Segoe UI", 8, "bold"),
                        tags=("tile-selection",)
                    )

    @staticmethod
    def _build_tile_header(tile_data: list[tuple[int, int, int, list[int]]], style: str, label: str, extra_comments: list[str] | None = None) -> tuple[str, int]:
        """Compress tile_data with LZ4 and return (header_text, total_compressed_bytes).

        tile_data: list of (zoom, tx, ty, raw_bytes)
        Returns the full map_tile.h content and the total compressed byte count.
        """
        zoom_set = sorted(set(t[0] for t in tile_data))
        compressed: list[bytes] = []
        for _, _, _, raw in tile_data:
            compressed.append(lz4.block.compress(bytes(raw), store_size=False))

        total_bytes = sum(len(c) for c in compressed)

        zoom_arr = ", ".join(str(t[0]) for t in tile_data)
        tx_arr   = ", ".join(str(t[1]) for t in tile_data)
        ty_arr   = ", ".join(str(t[2]) for t in tile_data)
        size_arr = ", ".join(str(len(c)) for c in compressed)

        lines = [
            "#pragma once",
            "#include <stdint.h>",
            "",
            f"// {style} {label}: {len(tile_data)} tiles, zooms [{', '.join(str(z) for z in zoom_set)}]",
            f"// Each tile is 256x256px = 8192 bytes uncompressed, stored here as LZ4 blocks.",
            f"// Byte layout is COLUMN-MAJOR: bytes are packed as [bx=0..31][y=0..255], not row-major.",
            f"// To read pixel (px, py): byte = tile[(px/8)*256 + py], bit = px%8",
            f"// Firmware: search map_tile_zooms/tx/ty for (zoom,tx,ty), decompress map_tile_data[i]",
            f"// using map_tile_sizes[i] bytes into an 8192-byte buffer, then read pixels from buffer.",
        ]
        if extra_comments:
            lines.extend(f"// {c}" for c in extra_comments)
        lines += [
            "",
            f"static const int map_tile_count = {len(tile_data)};",
            f"static const int map_tile_zooms[] = {{ {zoom_arr} }};",
            f"static const int map_tile_tx[]    = {{ {tx_arr} }};",
            f"static const int map_tile_ty[]    = {{ {ty_arr} }};",
            f"static const int map_tile_sizes[] = {{ {size_arr} }};",
            "",
        ]
        for idx, ((z, tx, ty, _), cdata) in enumerate(zip(tile_data, compressed)):
            lines.append(f"static const uint8_t map_tile_data_{idx}[] = {{  // z{z}/{tx}/{ty}, {len(cdata)} bytes compressed")
            for i in range(0, len(cdata), 16):
                lines.append("    " + ", ".join(f"0x{b:02X}" for b in cdata[i : i + 16]) + ",")
            lines.append("};")
            lines.append("")
        ptr_list = ", ".join(f"map_tile_data_{i}" for i in range(len(tile_data)))
        lines.append(f"static const uint8_t* const map_tile_data[] = {{ {ptr_list} }};")

        return "\n".join(lines), total_bytes

    @staticmethod
    def _inkhud_grid_origin(lon: float, lat: float, z: int) -> tuple[int, int]:
        """Return (gx0, gy0) — top-left tile of the 4×4 export grid at zoom z.

        The grid center is snapped to the nearest tile boundary so the map
        center falls within ±128 world-pixels of the visual center of the box.
        This is the same logic used by both the export and the overlay.
        """
        n = 2 ** z
        cx = (lon + 180.0) / 360.0 * n
        cy = (1.0 - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
        gx_center = round(cx)
        gy_center = round(cy)
        return gx_center - 2, gy_center - 2

    def draw_inkhud_coverage_overlay(self) -> None:
        self.map_canvas.delete("inkhud-coverage")
        if self.vars["mode"].get() != "inkhud":
            return
        if not self.vars["show_inkhud_coverage"].get():
            return
        try:
            min_zoom = int(self.vars["min_zoom"].get())
            max_zoom = int(self.vars["max_zoom"].get())
        except (ValueError, Exception):
            return

        view_zoom = self.map_zoom
        width = max(self.map_canvas.winfo_width(), 320)
        height = max(self.map_canvas.winfo_height(), 260)
        cx_world, cy_world = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, view_zoom)
        left_world = cx_world - width / 2
        top_world  = cy_world - height / 2

        colors = ["#e63946", "#f4a261", "#2a9d8f", "#457b9d", "#6a4c93", "#e9c46a"]

        g = int(self.vars["inkhud_grid"].get()[0])
        half = g // 2

        for i, z in enumerate(range(min_zoom, max_zoom + 1)):
            tx, ty = cli.lonlat_to_tile(self.map_center_lon, self.map_center_lat, z)
            gx0, gy0 = tx - half, ty - half
            gx1, gy1 = gx0 + g, gy0 + g

            scale = 2 ** (view_zoom - z)
            tile_px = 256 * scale

            x0 = gx0 * tile_px - left_world
            y0 = gy0 * tile_px - top_world
            x1 = gx1 * tile_px - left_world
            y1 = gy1 * tile_px - top_world

            color = colors[i % len(colors)]
            self.map_canvas.create_rectangle(
                x0, y0, x1, y1,
                fill="", outline=color, width=3, dash=(8, 4),
                tags=("inkhud-coverage",)
            )
            label_x = max(x0 + 4, 2)
            label_y = max(y0 + 2, 2)
            self.map_canvas.create_text(
                label_x, label_y, anchor="nw",
                text=f"z{z}", fill=color, font=("Segoe UI", 9, "bold"),
                tags=("inkhud-coverage",)
            )

    def _inkhud2_coverage_bbox(self, base_zoom: int) -> cli.BBox:
        """The 3x3 tile geographic bbox centered on the map center at base_zoom — identical to what InkHUD exports."""
        clng, clat = self.map_center_lon, self.map_center_lat
        tx, ty = cli.lonlat_to_tile(clng, clat, base_zoom)
        n = 2 ** base_zoom
        eps = 1e-6
        west  = (tx - 1) / n * 360 - 180
        east  = (tx + 2) / n * 360 - 180 - eps
        north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty - 1) / n))))
        south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + 2) / n)))) + eps
        return cli.BBox(west=west, south=south, east=east, north=north)

    def map_bbox_at_zoom(self, zoom: int) -> cli.BBox:
        width = max(self.map_canvas.winfo_width(), 320)
        height = max(self.map_canvas.winfo_height(), 260)
        center_x, center_y = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, zoom)
        west, north = self.world_pixel_to_lon_lat(center_x - width / 2, center_y - height / 2, zoom)
        east, south = self.world_pixel_to_lon_lat(center_x + width / 2, center_y + height / 2, zoom)
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

    def draw_center_marker(self) -> None:
        width = max(self.map_canvas.winfo_width(), 320)
        height = max(self.map_canvas.winfo_height(), 260)
        x = width / 2
        y = height / 2
        self.map_canvas.create_oval(x - 6, y - 6, x + 6, y + 6, outline="#0f766e", width=2, tags=("center-marker",))
        self.map_canvas.create_line(x - 14, y, x - 8, y, fill="#0f766e", width=2, tags=("center-marker",))
        self.map_canvas.create_line(x + 8, y, x + 14, y, fill="#0f766e", width=2, tags=("center-marker",))
        self.map_canvas.create_line(x, y - 14, x, y - 8, fill="#0f766e", width=2, tags=("center-marker",))
        self.map_canvas.create_line(x, y + 8, x, y + 14, fill="#0f766e", width=2, tags=("center-marker",))

    def shift_current_preview(self, dx: int, dy: int) -> None:
        if self.preview_image is None:
            self.draw_preview_placeholder("Release to render map...")
            return
        self.map_canvas.coords("map-image", dx, dy)
        self.map_canvas.delete("zoom-badge", "center-marker", "tile-grid", "tile-selection")
        self.draw_zoom_badge()
        self.draw_center_marker()

    def render_preview_vector_tile(self, tile: cli.Tile, job: dict[str, Any]):
        elements = tuple(job["elements"]["include"])
        cache_key = ("openfreemap-vector", tile.z, tile.x, tile.y, job.get("style", "osm-eink"), elements)
        cached = self.preview_tile_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        rendered = cli.render_openfreemap_image(
            tile,
            cli.DEFAULT_USER_AGENT,
            timeout=12,
            retries=2,
            elements=list(elements),
            style=str(job.get("style", "osm-eink")),
        ).convert("RGBA")
        self.preview_tile_cache[cache_key] = rendered.copy()
        return rendered

    def convert_preview_tile(self, image, job: dict[str, Any]):
        from PIL import Image, ImageEnhance

        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image).convert("RGB")
        mode = job["mode"]

        if mode in ("inkhud", "inkhud2"):
            return cli.inkhud_process(image, float(job["contrast"]), float(job["brightness"])).convert("RGB")

        image = ImageEnhance.Brightness(image).enhance(float(job["brightness"]))
        image = ImageEnhance.Contrast(image).enhance(float(job["contrast"]))
        gray = image.convert("L")
        if mode == "mono":
            threshold = int(job["threshold"])
            return gray.point(lambda pixel: 255 if pixel >= threshold else 0, mode="1")
        if mode == "grayscale":
            return gray
        if mode == "palette":
            colors = max(2, min(int(job.get("colors", 256)), 256))
            return image.quantize(colors=colors)
        return image

    def show_preview_image(self, image, render_id: int) -> None:
        from PIL import ImageTk

        if render_id != self.preview_render_id:
            return
        self.preview_image = ImageTk.PhotoImage(image)
        self.preview_rendered_width = image.width
        self.preview_rendered_height = image.height
        self.map_canvas.delete("all")
        self.map_canvas.create_image(0, 0, image=self.preview_image, anchor="nw", tags=("map-image",))
        self.draw_zoom_badge()
        self.draw_center_marker()
        self.draw_tile_grid_overlay()
        self.draw_tile_selection_overlay()
        self.draw_inkhud_coverage_overlay()
        self.set_preview_status(f"Export preview z{self.map_zoom}: matches downloaded tile rendering.")

    def preview_failed(self, error: str) -> None:
        self.draw_preview_placeholder("Preview unavailable.\n\nCheck your internet connection, then click Refresh.")
        self.preview_image = None
        self.set_preview_status(f"Preview failed: {error}")

    def center_lon(self, bbox: cli.BBox) -> float:
        if bbox.west <= bbox.east:
            return (bbox.west + bbox.east) / 2
        return cli.normalize_lon((bbox.west + bbox.east + 360) / 2)

    def cancel_export(self) -> None:
        if hasattr(self, "_cancel_event"):
            self._cancel_event.set()
        self.cancel_button.grid_remove()
        self.vars["status"].set("Cancelling...")

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
        self._cancel_event = threading.Event()
        self.export_button.configure(state="disabled")
        self.cancel_button.grid()
        self.vars["status"].set("Exporting...")
        self.export_thread = threading.Thread(target=self.run_export, args=(job, output, self._cancel_event), daemon=True)
        self.export_thread.start()

    def reset_export_progress(self, job: dict[str, Any]) -> None:
        bbox = cli.BBox(**job["bbox"])
        self.export_total = cli.count_tiles_for_bbox(bbox, job["zooms"])
        self.vars["progress_value"].set(0)
        self.progress_bar.configure(maximum=max(self.export_total, 1), mode="determinate")
        self.vars["progress_text"].set(f"Exporting 0 / {self.export_total:,} tiles...")

    def validate_export(self, job: dict[str, Any]) -> None:
        if not bool(self.vars["permission"].get()):
            raise ValueError("Confirm that exported tiles will keep required attribution.")
        max_zoom = max(job["zooms"])
        if not cli.supports_vector_overzoom(job["style"]) and max_zoom > cli.OPENFREEMAP_MAX_DETAIL_ZOOM:
            raise ValueError(
                "OpenFreeMap map detail currently stops at zoom 14. "
                "Use osm-eink for crisp generalized map overzoom, "
                "or osm-eink-topo for terrain-focused exports."
            )
        if cli.supports_vector_overzoom(job["style"]) and max_zoom > MAX_PREVIEW_ZOOM:
            raise ValueError(f"Overzoom exports are supported up to zoom {cli.OVERZOOM_MAX_DETAIL_ZOOM}.")

    def run_export(self, job: dict[str, Any], output: Path, cancel_event: threading.Event) -> None:
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
                    exit_code = cli.main(argv, cancel_event=cancel_event)
                if exit_code == 2:
                    self.after(0, self.finish_export_cancelled)
                    return
                if exit_code:
                    raise RuntimeError(f"Export failed with exit code {exit_code}")
            self.messages.put(f"\nDone. Output: {output}\nZIP: {output.with_suffix('.zip')}\n")
            self.after(0, self.finish_export_success)
        except Exception as exc:  # noqa: BLE001 - report worker errors in GUI.
            self.messages.put(f"\nExport failed: {exc}\n")
            self.after(0, lambda: self.finish_export_failed(str(exc)))
        finally:
            self.after(0, lambda: self.export_button.configure(state="normal"))
            self.after(0, self.cancel_button.grid_remove)

    def finish_export_success(self) -> None:
        self.vars["status"].set("Export complete")
        self.vars["progress_value"].set(self.export_total)
        self.vars["progress_text"].set(f"Complete: {self.export_total:,} tiles exported")

    def finish_export_cancelled(self) -> None:
        self.vars["status"].set("Export cancelled")
        self.vars["progress_text"].set("Export cancelled")

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

    def export_for_inkhud(self) -> None:
        if self.export_thread and self.export_thread.is_alive():
            return
        if self.vars["mode"].get() == "inkhud2":
            self.export_for_inkhud2()
            return

        self.apply_inkhud_defaults_if_unchanged()
        clat = self.map_center_lat
        clng = self.map_center_lon

        try:
            min_zoom = int(self.vars["min_zoom"].get())
            max_zoom = int(self.vars["max_zoom"].get())
        except ValueError:
            min_zoom = max_zoom = self.map_zoom

        # Compute per-zoom tile origins and bboxes (gxg grid centered on map center)
        g = int(self.vars["inkhud_grid"].get()[0])
        half = g // 2
        zoom_specs = []
        eps = 1e-6
        for z in range(min_zoom, max_zoom + 1):
            tx, ty = cli.lonlat_to_tile(clng, clat, z)
            n = 2**z
            west  = (tx - half) / n * 360 - 180
            east  = (tx - half + g) / n * 360 - 180 - eps
            north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty - half) / n))))
            south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty - half + g) / n)))) + eps
            zoom_specs.append({"zoom": z, "tx": tx, "ty": ty,
                                "bbox": {"west": west, "south": south, "east": east, "north": north}})

        # Build a combined job covering all zooms with the widest bbox (min_zoom)
        try:
            job = self.build_job()
            self.validate_export(job)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Cannot export", str(exc))
            return
        job["bbox"]   = zoom_specs[0]["bbox"]
        job["zooms"]  = list(range(min_zoom, max_zoom + 1))
        job["layout"] = DESKTOP_TILE_LAYOUT
        # Remove land layer so water renders through correctly (land sits on top of water)
        job["elements"]["include"] = [e for e in job["elements"]["include"] if e != "land"]
        job["elements"]["exclude"] = list(set(job["elements"]["exclude"]) | {"land"})

        # Ask where to save map_tile.h
        fw_default = Path(r"C:\firmware\src\graphics\niche\InkHUD\Applets\Bases\Map")
        initial_dir = str(fw_default) if fw_default.exists() else str(Path.home())
        save_path = filedialog.asksaveasfilename(
            title="Save map_tile.h for InkHUD firmware",
            defaultextension=".h",
            initialfile="map_tile.h",
            initialdir=initial_dir,
            filetypes=[("C header files", "*.h")],
        )
        if not save_path:
            return

        self.log.delete("1.0", "end")
        self.log.grid()
        self.reset_export_progress(job)
        self._cancel_event = threading.Event()
        self.inkhud_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.cancel_button.grid()
        self.vars["status"].set("Exporting for InkHUD...")
        self._last_zoom_specs = zoom_specs
        self.export_thread = threading.Thread(
            target=self._run_inkhud_export,
            args=(job, zoom_specs, Path(save_path), self._cancel_event),
            daemon=True,
        )
        self.export_thread.start()

    def export_for_inkhud2(self) -> None:
        self.apply_inkhud_defaults_if_unchanged()

        if not any(self.inkhud2_selected_tiles.values()):
            messagebox.showwarning("No tiles selected", "Click tiles on the map to select areas for export.")
            return

        # Compute bbox covering all selected tiles so the downloader fetches everything needed
        west = south = east = north = None
        all_zooms = sorted(self.inkhud2_selected_tiles.keys())
        for z, tiles in self.inkhud2_selected_tiles.items():
            n = 2 ** z
            for tx, ty in tiles:
                w = tx / n * 360 - 180
                e = (tx + 1) / n * 360 - 180
                nn = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
                ss = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + 1) / n))))
                west  = min(west,  w)  if west  is not None else w
                east  = max(east,  e)  if east  is not None else e
                north = max(north, nn) if north is not None else nn
                south = min(south, ss) if south is not None else ss

        try:
            job = self.build_job()
            job["bbox"]  = {"west": west, "south": south, "east": east, "north": north}
            job["zooms"] = all_zooms
            self.validate_export(job)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Cannot export", str(exc))
            return
        job["layout"] = DESKTOP_TILE_LAYOUT
        job["elements"]["include"] = [e for e in job["elements"]["include"] if e != "land"]
        job["elements"]["exclude"] = list(set(job["elements"]["exclude"]) | {"land"})

        fw_default = Path(r"C:\firmware\src\graphics\niche\InkHUD\Applets\Bases\Map")
        initial_dir = str(fw_default) if fw_default.exists() else str(Path.home())
        save_path = filedialog.asksaveasfilename(
            title="Save map_tile.h for InkHUD2 firmware",
            defaultextension=".h",
            initialfile="map_tile.h",
            initialdir=initial_dir,
            filetypes=[("C header files", "*.h")],
        )
        if not save_path:
            return

        total_tiles = sum(len(v) for v in self.inkhud2_selected_tiles.values())
        self.log.delete("1.0", "end")
        self.log.grid()
        self.export_total = total_tiles
        self.vars["progress_value"].set(0)
        self.progress_bar.configure(maximum=max(total_tiles, 1), mode="determinate")
        self.vars["progress_text"].set(f"Exporting 0 / {total_tiles:,} tiles...")
        self._cancel_event = threading.Event()
        self.inkhud_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.cancel_button.grid()
        self.vars["status"].set("Exporting for InkHUD2...")
        selected_snapshot = {z: set(tiles) for z, tiles in self.inkhud2_selected_tiles.items()}
        self.export_thread = threading.Thread(
            target=self._run_inkhud2_export,
            args=(job, selected_snapshot, Path(save_path), self._cancel_event),
            daemon=True,
        )
        self.export_thread.start()

    def _run_inkhud2_export(self, job: dict[str, Any], selected: dict[int, set[tuple[int, int]]], save_path: Path, cancel_event: threading.Event | None = None) -> None:
        from PIL import Image

        style = job["style"]
        # Flatten to sorted list: (zoom, tx, ty)
        tile_list = [(z, tx, ty) for z in sorted(selected) for tx, ty in sorted(selected[z])]

        try:
            with tempfile.TemporaryDirectory(prefix="inkhud2-export-") as temp_dir:
                temp_out = Path(temp_dir)
                job_path = temp_out / "job.json"
                job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")

                writer = QueueWriter(self.messages)
                argv = ["--job", str(job_path), "--output", str(temp_out), "--rate-limit", str(DESKTOP_RATE_LIMIT_SECONDS)]
                with redirect_stdout(writer):
                    exit_code = cli.main(argv, cancel_event=cancel_event)
                if exit_code == 2:
                    self.after(0, self.finish_export_cancelled)
                    return
                if exit_code:
                    raise RuntimeError(f"Tile download failed (exit code {exit_code})")

                # Convert each tile individually to 1-bit
                tile_data: list[tuple[int, int, int, list[int]]] = []  # (zoom, tx, ty, raw)
                for i, (z, tx, ty) in enumerate(tile_list):
                    if cancel_event and cancel_event.is_set():
                        self.after(0, self.finish_export_cancelled)
                        return
                    tile_path = temp_out / "tiles" / style / str(z) / str(tx) / f"{ty}.png"
                    rgb = Image.open(tile_path).convert("RGB") if tile_path.exists() else Image.new("RGB", (256, 256), (255, 255, 255))
                    bw = cli.inkhud_process(rgb, float(job["contrast"]), float(job["brightness"]))
                    raw: list[int] = []
                    for bx in range(32):
                        for y in range(256):
                            byte = 0
                            for bit in range(8):
                                if bw.getpixel((bx * 8 + bit, y)) == 0:
                                    byte |= 1 << bit
                            raw.append(byte)
                    tile_data.append((z, tx, ty, raw))
                    self.messages.put(f"  [{i+1}/{len(tile_list)}] z{z}/{tx}/{ty}: {len(raw):,} bytes\n")

            header, total_bytes = self._build_tile_header(tile_data, style, "InkHUD2 sparse export")
            uncompressed = len(tile_data) * 8192
            ratio = total_bytes / uncompressed * 100 if uncompressed else 100
            self.messages.put(f"  compressed: {total_bytes:,} bytes ({ratio:.0f}% of {uncompressed:,} uncompressed)\n")

            save_path.write_text(header, encoding="utf-8")
            self.messages.put(f"__TILE_TOTAL_BYTES__:{total_bytes}\n")
            self.messages.put(f"\nmap_tile.h saved to: {save_path}\n")
            self.after(0, self.finish_export_success)
            self.after(0, lambda: messagebox.showinfo(
                "InkHUD2 Export Complete",
                f"map_tile.h saved to:\n{save_path}\n\n{len(tile_data)} tiles exported.\nRebuild and flash your InkHUD2 firmware to apply.",
            ))
        except Exception as exc:  # noqa: BLE001
            self.messages.put(f"\nInkHUD2 export failed: {exc}\n")
            self.after(0, lambda: self.finish_export_failed(str(exc)))
        finally:
            self.after(0, lambda: self.inkhud_button.configure(state="normal"))
            self.after(0, lambda: self.export_button.configure(state="normal"))
            self.after(0, self.cancel_button.grid_remove)

    def _inkhud_process(self, rgb_image: "Image.Image", contrast: float, brightness: float) -> "Image.Image":
        """Shared inkhud pipeline used by both preview and export — always identical."""
        import numpy as np
        from PIL import Image as _Image, ImageEnhance, ImageFilter
        # Detect water by blue dominance before grayscale (osm-eink water = light blue ~#aad3df)
        arr_rgb = np.array(rgb_image.convert("RGB"), dtype=np.int16)
        water_mask = (arr_rgb[:, :, 2] - arr_rgb[:, :, 0]) > 25
        gray = rgb_image.convert("L")
        gray = ImageEnhance.Contrast(gray).enhance(contrast)
        gray = ImageEnhance.Brightness(gray).enhance(brightness)
        sharp = gray.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=2))
        result = np.array(self._bayer_dither(sharp), dtype=np.uint8)
        result[water_mask] = 0  # Force water solid black
        return _Image.fromarray(result, mode="L")

    @staticmethod
    def _bayer_dither(img: "Image.Image") -> "Image.Image":
        """3-level posterize + Bayer dither.
        <=140 → solid black (water, roads, labels, building outlines)
        141-205 → light Bayer dither (building interiors, soft shading)
        >205 → solid white (background/land)
        """
        import numpy as np
        from PIL import Image as _Image
        bayer = np.array([
            [ 0,  8,  2, 10],
            [12,  4, 14,  6],
            [ 3, 11,  1,  9],
            [15,  7, 13,  5],
        ], dtype=np.float32) * (255.0 / 16.0)
        arr = np.array(img, dtype=np.float32)
        # Only dither a narrow band of very light grays (building interiors).
        # Water, text, roads (<=175) → solid black. Background (>215) → solid white.
        quantized = np.where(arr <= 175, 0.0,
                    np.where(arr <= 215, 170.0, 255.0))
        h, w = quantized.shape
        pattern = np.tile(bayer, (h // 4 + 1, w // 4 + 1))[:h, :w]
        dithered = np.where(quantized < pattern, 0, 255).astype(np.uint8)
        result = np.where(quantized >= 255, 255, np.where(quantized <= 0, 0, dithered)).astype(np.uint8)
        return _Image.fromarray(result, mode="L")

    def _run_inkhud_export(self, job: dict[str, Any], zoom_specs: list[dict], save_path: Path, cancel_event: threading.Event | None = None) -> None:
        from PIL import Image, ImageEnhance, ImageFilter

        clat = self.map_center_lat
        clng = self.map_center_lon
        g = int(self.vars["inkhud_grid"].get()[0])
        cols, rows = g, g
        style = job["style"]
        min_zoom = zoom_specs[0]["zoom"]
        max_zoom = zoom_specs[-1]["zoom"]

        try:
            with tempfile.TemporaryDirectory(prefix="inkhud-export-") as temp_dir:
                temp_out = Path(temp_dir)
                job_path = temp_out / "job.json"
                job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")

                writer = QueueWriter(self.messages)
                argv = [
                    "--job", str(job_path),
                    "--output", str(temp_out),
                    "--rate-limit", str(DESKTOP_RATE_LIMIT_SECONDS),
                ]
                with redirect_stdout(writer):
                    exit_code = cli.main(argv, cancel_event=cancel_event)
                if exit_code == 2:
                    self.after(0, self.finish_export_cancelled)
                    return
                if exit_code:
                    raise RuntimeError(f"Tile download failed (exit code {exit_code})")

                # Process each tile in the grid per zoom individually at full 256x256
                tile_data: list[tuple[int, int, int, list[int]]] = []  # (zoom, tx, ty, raw)
                for spec in zoom_specs:
                    z = spec["zoom"]
                    x0, y0 = spec["tx"] - half, spec["ty"] - half
                    for dy in range(rows):
                        for dx in range(cols):
                            tx, ty = x0 + dx, y0 + dy
                            tile_path = temp_out / "tiles" / style / str(z) / str(tx) / f"{ty}.png"
                            rgb = Image.open(tile_path).convert("RGB") if tile_path.exists() else Image.new("RGB", (256, 256), (255, 255, 255))
                            bw = cli.inkhud_process(rgb, float(job["contrast"]), float(job["brightness"]))
                            raw: list[int] = []
                            for bx in range(32):
                                for y in range(256):
                                    byte = 0
                                    for bit in range(8):
                                        if bw.getpixel((bx * 8 + bit, y)) == 0:
                                            byte |= 1 << bit
                                    raw.append(byte)
                            tile_data.append((z, tx, ty, raw))
                    self.messages.put(f"  zoom {z}: {rows * cols} tiles, {rows * cols * 8192:,} bytes\n")

            header, total_bytes = self._build_tile_header(
                tile_data, style, "InkHUD sparse export",
                extra_comments=[f"center: lat={clat:.6f} lng={clng:.6f}"],
            )
            uncompressed = len(tile_data) * 8192
            ratio = total_bytes / uncompressed * 100 if uncompressed else 100
            self.messages.put(f"  compressed: {total_bytes:,} bytes ({ratio:.0f}% of {uncompressed:,} uncompressed)\n")

            save_path.write_text(header, encoding="utf-8")
            self.messages.put(f"__TILE_TOTAL_BYTES__:{total_bytes}\n")
            self.messages.put(f"\nmap_tile.h saved to: {save_path}\n")
            self.after(0, self.finish_export_success)
            self.after(0, lambda: messagebox.showinfo(
                "InkHUD Export Complete",
                f"map_tile.h saved to:\n{save_path}\n\nRebuild and flash your InkHUD firmware to apply.",
            ))
        except Exception as exc:  # noqa: BLE001
            self.messages.put(f"\nInkHUD export failed: {exc}\n")
            self.after(0, lambda: self.finish_export_failed(str(exc)))
        finally:
            self.after(0, lambda: self.inkhud_button.configure(state="normal"))
            self.after(0, lambda: self.export_button.configure(state="normal"))
            self.after(0, self.cancel_button.grid_remove)

    def poll_messages(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            if message.startswith("__TILE_TOTAL_BYTES__:"):
                actual_bytes = int(message.split(":")[1])
                self.draw_flash_bars(actual_bytes, upper_bound=False)
                num_zooms = len(getattr(self, "_last_zoom_specs", []) or [])
                mode_label = "InkHUD2" if self.vars["mode"].get() == "inkhud2" else "InkHUD"
                self.vars["tile_count"].set(
                    f"{mode_label}: {num_zooms} zoom(s) — {actual_bytes // 1024} KB"
                )
                continue
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

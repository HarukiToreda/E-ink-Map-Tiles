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

from . import core as cli


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
USGS_TOPO_TEMPLATE = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}"
USGS_TOPO_MAX_ZOOM = 16

SOURCES = {
    "openfreemap-vector": {
        "label": "OpenFreeMap open vector tiles",
        "help": "Default open vector source. The app renders preview and export tiles locally.",
        "url_template": None,
        "max_zoom": MAX_PREVIEW_ZOOM,
    },
    "usgs-topo": {
        "label": "USGS National Map Topo (US only)",
        "help": "Public domain pre-rendered topo tiles from the USGS National Map. US coverage only.",
        "url_template": USGS_TOPO_TEMPLATE,
        "max_zoom": USGS_TOPO_MAX_ZOOM,
    },
}
DEFAULT_SOURCE_NAME = SOURCES["openfreemap-vector"]["label"]
DEFAULT_SOURCE_HELP = SOURCES["openfreemap-vector"]["help"]



class QueueWriter(io.TextIOBase):
    def __init__(self, messages: queue.Queue[str]) -> None:
        self.messages = messages

    def write(self, text: str) -> int:
        if text:
            self.messages.put(text)
        return len(text)

    def flush(self) -> None:
        return None


def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


class ToggleSwitch(tk.Canvas):
    """Pill-shaped on/off toggle — PIL-rendered at 3× for smooth anti-aliased edges."""
    W, H, S = 42, 24, 3   # display size and supersampling scale

    def __init__(self, parent, variable: tk.BooleanVar, command=None, bg: str = "#1e293b"):
        super().__init__(parent, width=self.W, height=self.H,
                         background=bg, highlightthickness=0, borderwidth=0, cursor="hand2")
        self._var = variable
        self._cmd = command
        self._bg = bg
        self._photo = None
        self._var.trace_add("write", lambda *_: self.redraw())
        self.bind("<ButtonRelease-1>", self._toggle)
        self.redraw()

    def _toggle(self, _e=None):
        self._var.set(not self._var.get())
        if self._cmd:
            self._cmd()

    def redraw(self):
        from PIL import Image as _Image, ImageDraw, ImageTk
        s = self.S
        W, H = self.W * s, self.H * s
        on = bool(self._var.get())
        track = "#14b8a6" if on else "#334155"
        img = _Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        r = H // 2
        d.ellipse([0, 0, H - 1, H - 1], fill=track)
        d.ellipse([W - H, 0, W - 1, H - 1], fill=track)
        d.rectangle([r, 0, W - r, H], fill=track)
        pad = 4 * s
        tx = W - H + pad if on else pad
        d.ellipse([tx, pad, tx + H - pad * 2 - 1, H - pad - 1], fill="white")
        out = img.resize((self.W, self.H), _Image.LANCZOS)
        bg_img = _Image.new("RGBA", (self.W, self.H), _hex_to_rgb(self._bg) + (255,))
        final = _Image.alpha_composite(bg_img, out)
        self._photo = ImageTk.PhotoImage(final)
        self.delete("all")
        self.create_image(0, 0, image=self._photo, anchor="nw")


class PillSlider(tk.Canvas):
    """Pill-track slider — PIL-rendered at 3× for smooth anti-aliased edges."""
    H = 24
    TH = 6   # track thickness
    S = 3    # supersampling scale

    def __init__(self, parent, variable: tk.DoubleVar, from_: float, to: float,
                 command=None, bg: str = "#1e293b"):
        super().__init__(parent, height=self.H, background=bg,
                         highlightthickness=0, borderwidth=0, cursor="hand2")
        self._var = variable
        self._from = from_
        self._to = to
        self._cmd = command
        self._bg = bg
        self._photo = None
        self._dragging = False
        self._var.trace_add("write", lambda *_: self.redraw())
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _frac(self):
        span = self._to - self._from
        return max(0.0, min(1.0, (self._var.get() - self._from) / span)) if span else 0.0

    def _set_from_x(self, x):
        w = max(self.winfo_width(), 1)
        pad = self.H // 2
        frac = max(0.0, min(1.0, (x - pad) / max(1, w - pad * 2)))
        self._var.set(round(self._from + frac * (self._to - self._from), 4))
        if self._cmd:
            self._cmd(self._var.get())

    def _on_press(self, e): self._dragging = True; self._set_from_x(e.x)
    def _on_drag(self, e):
        if self._dragging: self._set_from_x(e.x)
    def _on_release(self, e): self._dragging = False

    def redraw(self):
        from PIL import Image as _Image, ImageDraw, ImageTk
        s = self.S
        w = max(self.winfo_width(), 100)
        W, H = w * s, self.H * s
        th = self.TH * s
        pad = (self.H // 2) * s
        ty = H // 2
        frac = self._frac()
        fill_x = int(pad + frac * (W - pad * 2))

        img = _Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # background track
        r = th // 2
        d.ellipse([pad - r, ty - r, pad + r, ty + r], fill="#334155")
        d.ellipse([W - pad - r, ty - r, W - pad + r, ty + r], fill="#334155")
        d.rectangle([pad, ty - r, W - pad, ty + r], fill="#334155")
        # filled track
        if fill_x > pad:
            d.ellipse([pad - r, ty - r, pad + r, ty + r], fill="#14b8a6")
            d.ellipse([fill_x - r, ty - r, fill_x + r, ty + r], fill="#14b8a6")
            d.rectangle([pad, ty - r, fill_x, ty + r], fill="#14b8a6")
        # thumb
        tr = (self.H // 2 - 2) * s
        d.ellipse([fill_x - tr, ty - tr, fill_x + tr, ty + tr], fill="white", outline="#14b8a6", width=s * 2)

        out = img.resize((w, self.H), _Image.LANCZOS)
        bg_rgb = _hex_to_rgb(self._bg) + (255,)
        bg_img = _Image.new("RGBA", (w, self.H), bg_rgb)
        final = _Image.alpha_composite(bg_img, out)
        self._photo = ImageTk.PhotoImage(final)
        self.delete("all")
        self.create_image(0, 0, image=self._photo, anchor="nw")


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
        text_fill = self.foreground if self.state != "disabled" else "#475569"
        if self.state == "disabled":
            fill = "#1e293b"
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
        self._apply_dark_titlebar()

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
        self.markers: list[dict] = []  # [{"lat", "lon", "icon", "min_zoom", "max_zoom"}]
        self.marker_placing = False
        self._editing_marker_index: int | None = None
        self._dragging_marker: bool = False
        self._icon_cache: dict[str, Any] = {}
        self._marker_photo_refs: list[Any] = []

        self.vars = self.make_vars()
        self.configure_styles()
        self.build_ui()
        self.update_mode_sensitive_controls()
        self.update_elements_state()
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
            "marker_icon": tk.StringVar(value="parking"),
            "marker_min_zoom": tk.StringVar(value="14"),
            "marker_max_zoom": tk.StringVar(value="16"),
            "marker_label_text": tk.StringVar(value=""),
            "marker_label_font_size": tk.StringVar(value="12"),
            "collapse_markers": tk.BooleanVar(value=True),
        }
        for element in cli.MAP_ELEMENTS:
            variables[f"element_{element}"] = tk.BooleanVar(value=element in cli.DEFAULT_INCLUDE_ELEMENTS)
        return variables

    def _apply_dark_titlebar(self) -> None:
        try:
            import ctypes
            hwnd = self.winfo_id()
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 20H1+)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
        except Exception:
            pass

    # ── Design tokens ─────────────────────────────────────────────────────────
    C_BG        = "#0f172a"   # sidebar dark navy
    C_PANEL     = "#1e293b"   # sidebar card / section bg
    C_CARD      = "#1e293b"   # inner card bg
    C_BORDER    = "#334155"   # subtle border
    C_TEXT      = "#f1f5f9"   # primary text on dark
    C_MUTED     = "#94a3b8"   # secondary/hint text on dark
    C_ACCENT    = "#14b8a6"   # teal primary
    C_ACCENT_HV = "#0d9488"   # teal hover
    C_BTN       = "#334155"   # default button bg
    C_BTN_HV    = "#475569"   # default button hover
    C_DANGER    = "#ef4444"   # delete / warning
    C_MAP_BG    = "#f8fafc"   # map panel background

    def configure_styles(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.configure(background=self.C_BG)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 9), background=self.C_BG, foreground=self.C_TEXT)
        style.configure("TFrame", background=self.C_BG)
        style.configure("Panel.TFrame", background=self.C_BG)
        style.configure("Card.TFrame", background=self.C_PANEL)
        style.configure("TLabelframe", background=self.C_PANEL, bordercolor=self.C_BORDER, relief="solid")
        style.configure("TLabelframe.Label", background=self.C_BG, foreground=self.C_TEXT, font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=self.C_PANEL, foreground=self.C_TEXT, font=("Segoe UI", 9))
        style.configure("Shell.TLabel", background=self.C_BG, foreground=self.C_MUTED)
        style.configure("Title.TLabel", background=self.C_BG, foreground=self.C_TEXT, font=("Segoe UI", 15, "bold"))
        style.configure("Section.TLabel", background=self.C_PANEL, foreground=self.C_TEXT, font=("Segoe UI", 9, "bold"))
        style.configure("Hint.TLabel", background=self.C_PANEL, foreground=self.C_MUTED, wraplength=330)
        style.configure("MapHint.TLabel", background=self.C_MAP_BG, foreground="#475569", wraplength=620)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        # Inputs
        style.configure("TEntry", fieldbackground=self.C_BG, foreground=self.C_TEXT,
                        insertcolor=self.C_TEXT, bordercolor=self.C_BORDER, lightcolor=self.C_BORDER,
                        darkcolor=self.C_BORDER, relief="flat")
        style.configure("TSpinbox", fieldbackground=self.C_BG, foreground=self.C_TEXT,
                        bordercolor=self.C_BORDER, arrowcolor=self.C_MUTED,
                        lightcolor=self.C_BORDER, darkcolor=self.C_BORDER)
        style.configure("TCombobox", fieldbackground=self.C_BG, foreground=self.C_TEXT,
                        selectbackground=self.C_ACCENT, selectforeground="#ffffff",
                        bordercolor=self.C_BORDER, arrowcolor=self.C_MUTED,
                        lightcolor=self.C_BORDER, darkcolor=self.C_BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", self.C_BG)])
        # Checkbutton
        style.configure("TCheckbutton", background=self.C_PANEL, foreground=self.C_TEXT,
                        indicatorcolor=self.C_BG, indicatorrelief="flat")
        style.map("TCheckbutton",
                  background=[("active", self.C_PANEL)],
                  indicatorcolor=[("selected", self.C_ACCENT), ("!selected", self.C_BTN)])
        # Scale
        style.configure("TScale", background=self.C_PANEL, troughcolor=self.C_BTN,
                        slidercolor=self.C_ACCENT, bordercolor=self.C_BORDER)
        # Scrollbar
        style.configure("TScrollbar", background=self.C_BTN, troughcolor=self.C_PANEL,
                        bordercolor=self.C_BORDER, arrowcolor=self.C_MUTED)
        style.map("TScrollbar", background=[("active", self.C_BTN_HV)])

    def section_frame(self, parent: tk.Misc, title: str) -> tk.Frame:
        frame = tk.Frame(parent, background=self.C_PANEL,
                         highlightbackground=self.C_BORDER, highlightthickness=1, borderwidth=0)
        frame.columnconfigure(0, weight=1)
        hdr = tk.Frame(frame, background=self.C_PANEL)
        hdr.grid(row=0, column=0, sticky="ew")
        accent = tk.Frame(hdr, background=self.C_ACCENT, width=3)
        accent.grid(row=0, column=0, sticky="ns", padx=(0, 8), pady=2)
        ttk.Label(hdr, text=title, style="Section.TLabel").grid(row=0, column=1, sticky="w", pady=(8, 6))
        return frame

    def collapsible_section(self, parent: tk.Misc, title: str, variable_name: str) -> tuple[tk.Frame, ttk.Frame]:
        frame = tk.Frame(parent, background=self.C_PANEL,
                         highlightbackground=self.C_BORDER, highlightthickness=1, borderwidth=0)
        frame.columnconfigure(0, weight=1)
        header = tk.Frame(frame, background=self.C_PANEL)
        header.grid(row=0, column=0, sticky="ew", pady=(2, 2))
        header.columnconfigure(2, weight=1)

        accent = tk.Frame(header, background=self.C_ACCENT, width=3)
        accent.grid(row=0, column=0, sticky="ns", padx=(0, 8), pady=2)

        expanded = bool(self.vars[variable_name].get())
        toggle = self.flat_button(header, "▾" if expanded else "▸", lambda: self.toggle_section(variable_name), width=2)
        toggle.grid(row=0, column=1, sticky="w", padx=(0, 4))
        ttk.Label(header, text=title, style="Section.TLabel").grid(row=0, column=2, sticky="w", pady=(7, 5))

        content = ttk.Frame(frame, style="Card.TFrame", padding=(12, 2, 12, 10))
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
        bg     = self.C_ACCENT   if primary else self.C_BTN
        fg     = "#ffffff"       if primary else self.C_TEXT
        active = self.C_ACCENT_HV if primary else self.C_BTN_HV
        border = self.C_ACCENT   if primary else self.C_BORDER
        min_width = 28 if width else max(80, len(text) * 8 + 24)
        if width:
            min_width = max(28, width * 13 + 8)
        return RoundedButton(
            parent,
            text=text,
            command=command,
            background=bg,
            foreground=fg,
            activebackground=active,
            border=border,
            min_width=min_width,
            height=30,
            font=("Segoe UI", 9, "bold" if primary else "normal"),
        )

    def build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        body = ttk.Frame(root)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)

        preview_panel = tk.Frame(body, background=self.C_MAP_BG, bd=0)
        preview_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(0, weight=1)
        self.build_preview(preview_panel).grid(row=0, column=0, sticky="nsew")

        controls = self.build_scrollable_controls(body)
        controls.columnconfigure(0, weight=1)

        self.build_actions(controls).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.build_source(controls).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.build_area(controls).grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.build_settings(controls).grid(row=3, column=0, sticky="ew", pady=(0, 6))
        self.elements_outer, self.elements_content = self.build_elements(controls)
        self.elements_outer.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        self.build_markers_section(controls).grid(row=5, column=0, sticky="ew", pady=(0, 6))

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
        source = self.vars["source"].get()
        if source != "openfreemap-vector":
            return SOURCES.get(source, {}).get("max_zoom", MAX_PREVIEW_ZOOM)
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
            self.vars["min_zoom"].set("8")
            self.vars["max_zoom"].set("13")
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
        if hasattr(self, "flash_bars_canvas"):
            if mode in ("inkhud", "inkhud2"):
                self.flash_bars_canvas.grid()
            else:
                self.flash_bars_canvas.grid_remove()
        self.update_slider_labels()

    def update_inkhud2_info(self) -> None:
        if not hasattr(self, "inkhud2_zoom_frame"):
            return
        frame = self.inkhud2_zoom_frame
        for child in frame.winfo_children():
            child.destroy()

        total = sum(len(v) for v in self.inkhud2_selected_tiles.values())
        zoom_count = sum(1 for v in self.inkhud2_selected_tiles.values() if v)
        kb = total * 1500 // 1024  # ~1.5 KB/tile after LZ4 compression (est.)

        ttk.Label(frame, text="Click tiles on the map to select areas for export.", style="Hint.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        summary = f"{total} tile(s) across {zoom_count} zoom(s) — ~{kb} KB" if total else "No tiles selected."
        ttk.Label(frame, text=summary, style="Hint.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(1, 4)
        )
        grid_label = f"Add {self.vars['inkhud_grid'].get()} here"
        self.flat_button(frame, grid_label, self._add_grid_tiles).grid(row=2, column=0, sticky="ew", padx=(0, 3))
        self.flat_button(frame, "Clear all", self._clear_inkhud2_tiles).grid(row=2, column=1, sticky="ew", padx=(3, 0))

    def build_scrollable_controls(self, parent: ttk.Frame) -> ttk.Frame:
        shell = ttk.Frame(parent, style="Panel.TFrame")
        shell.grid(row=0, column=1, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        canvas = tk.Canvas(shell, background=self.C_BG, highlightthickness=0, borderwidth=0, width=420)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        controls = ttk.Frame(canvas, style="Panel.TFrame", padding=(6, 6, 6, 6))
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

        source_combo = ttk.Combobox(
            content,
            values=[info["label"] for info in SOURCES.values()],
            state="readonly",
        )
        source_combo.set(SOURCES[self.vars["source"].get()]["label"])
        source_combo.grid(row=0, column=0, sticky="ew", pady=(0, 2))

        def on_source_selected(_event):
            label = source_combo.get()
            key = next(k for k, v in SOURCES.items() if v["label"] == label)
            self.vars["source"].set(key)
            self.vars["source_help"].set(SOURCES[key]["help"])
            self.map_zoom = min(self.map_zoom, SOURCES[key]["max_zoom"])
            self.update_elements_state()
            self.queue_live_update(preview=True, estimate=True)

        source_combo.bind("<<ComboboxSelected>>", on_source_selected)

        ttk.Label(content, textvariable=self.vars["source_help"], style="Hint.TLabel").grid(row=1, column=0, sticky="ew", pady=(0, 4))

        perm_row = ttk.Frame(content, style="Card.TFrame")
        perm_row.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ToggleSwitch(perm_row, variable=self.vars["permission"], bg=self.C_PANEL).grid(row=0, column=0, padx=(0, 8))
        ttk.Label(perm_row, text="I will keep required map attribution.", style="Hint.TLabel").grid(row=0, column=1, sticky="w")
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
            values=["8x8", "6x6", "5x5", "4x4", "3x3", "2x2"], state="readonly", width=6,
        )
        self.grid_combo.grid(row=2, column=1, sticky="w", padx=(6, 10), pady=(4, 0))
        ttk.Label(content, text="Tiles per zoom level", style="Hint.TLabel").grid(
            row=2, column=2, columnspan=2, sticky="w", pady=(4, 0)
        )

        ttk.Label(content, text="Brightness").grid(row=3, column=0, sticky="w", pady=(6, 0))
        PillSlider(content, variable=self.vars["brightness"], from_=0.6, to=1.6, bg=self.C_PANEL).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(6, 10), pady=(6, 0))
        ttk.Label(content, textvariable=self.vars["brightness_text"]).grid(row=3, column=3, sticky="w", pady=(6, 0))

        ttk.Label(content, text="Contrast").grid(row=4, column=0, sticky="w", pady=(6, 0))
        PillSlider(content, variable=self.vars["contrast"], from_=0.6, to=3.0, bg=self.C_PANEL).grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=(6, 10), pady=(6, 0))
        ttk.Label(content, textvariable=self.vars["contrast_text"]).grid(row=4, column=3, sticky="w", pady=(6, 0))

        threshold_label = ttk.Label(content, text="Mono threshold")
        threshold_label.grid(row=5, column=0, sticky="w", pady=(6, 0))
        threshold_scale = PillSlider(content, variable=self.vars["threshold"], from_=80, to=230, bg=self.C_PANEL)
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

    def build_elements(self, parent: ttk.Frame) -> tuple[tk.Frame, ttk.Frame]:
        frame, content = self.collapsible_section(parent, "Map Elements", "collapse_map_elements")
        element_columns = 3
        for column in range(element_columns):
            content.columnconfigure(column, weight=1)

        for index, element in enumerate(cli.MAP_ELEMENTS):
            cell = ttk.Frame(content, style="Card.TFrame")
            cell.grid(row=index // element_columns, column=index % element_columns, sticky="w", pady=3)
            ToggleSwitch(cell, variable=self.vars[f"element_{element}"],
                         bg=self.C_PANEL).grid(row=0, column=0, padx=(0, 6))
            ttk.Label(cell, text=ELEMENT_LABELS.get(element, element.title()),
                      style="Hint.TLabel").grid(row=0, column=1, sticky="w")

        buttons = ttk.Frame(content, style="Card.TFrame")
        buttons.grid(row=math.ceil(len(cli.MAP_ELEMENTS) / element_columns), column=0, columnspan=element_columns, sticky="ew", pady=(4, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        self.flat_button(buttons, "All", lambda: self.set_all_elements(True), primary=True).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.flat_button(buttons, "None", lambda: self.set_all_elements(False)).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        return frame, content

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
        frame = tk.Frame(parent, background=self.C_PANEL,
                         highlightbackground=self.C_BORDER, highlightthickness=1, borderwidth=0)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        # Single compact header row: accent bar + title + zoom buttons
        hdr = tk.Frame(frame, background=self.C_PANEL)
        hdr.grid(row=0, column=0, sticky="ew", padx=0)
        hdr.columnconfigure(1, weight=1)
        accent = tk.Frame(hdr, background=self.C_ACCENT, width=3)
        accent.grid(row=0, column=0, sticky="ns", padx=(0, 8), pady=2)
        ttk.Label(hdr, text="Map Preview", style="Section.TLabel").grid(row=0, column=1, sticky="w", pady=(6, 4))
        self.flat_button(hdr, "-", lambda: self.zoom_map(-1), width=3).grid(row=0, column=2, padx=(0, 3), pady=(4, 2))
        self.flat_button(hdr, "+", lambda: self.zoom_map(1), width=3).grid(row=0, column=3, padx=3, pady=(4, 2))
        self.preview_button = self.flat_button(hdr, "Refresh", self.refresh_preview)
        self.preview_button.grid(row=0, column=4, padx=(3, 10), pady=(4, 2))

        self.map_canvas = tk.Canvas(
            frame,
            background="#dfe5df",
            highlightthickness=0,
            borderwidth=0,
        )
        self.map_canvas.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.map_canvas.create_text(360, 260, text="Loading OpenFreeMap preview...", fill="#17211b", tags=("loading",))
        self.map_canvas.bind("<ButtonPress-1>", self.start_map_drag)
        self.map_canvas.bind("<B1-Motion>", self.drag_map)
        self.map_canvas.bind("<ButtonRelease-1>", self.end_map_drag)
        self.map_canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.map_canvas.bind("<Configure>", lambda _event: self.schedule_preview())
        return frame

    def resize_preview_status(self, event) -> None:
        pass

    def set_preview_status(self, text: str) -> None:
        self.vars["preview_status"].set(text)

    def build_actions(self, parent: ttk.Frame) -> ttk.Frame:
        frame = self.section_frame(parent, "Export")
        content = ttk.Frame(frame, style="Card.TFrame", padding=(10, 0, 10, 8))
        content.grid(row=1, column=0, sticky="ew")
        for column in range(4):
            content.columnconfigure(column, weight=1)
        ttk.Label(content, textvariable=self.vars["tile_count"], style="Hint.TLabel").grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 2))
        self.flash_bars_canvas = tk.Canvas(content, height=44, background=self.C_PANEL, highlightthickness=0)
        self.flash_bars_canvas.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 4))
        self.flash_bars_canvas.grid_remove()
        self.flash_bars_canvas.bind("<Configure>", lambda _e: self.draw_flash_bars(None))
        ttk.Label(content, textvariable=self.vars["status"], style="Hint.TLabel").grid(row=2, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        self.export_button = self.flat_button(content, "Export Tiles", self.export_tiles, primary=True)
        self.export_button.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(0, 5))
        self.flat_button(content, "Folder", self.open_output_folder).grid(row=2, column=2, sticky="ew", padx=5)
        self.flat_button(content, "About", self.show_about_licenses).grid(row=2, column=3, sticky="ew", padx=(5, 0))
        self.inkhud_button = self.flat_button(content, "⬡ Export for InkHUD", self.export_for_inkhud)
        self.inkhud_button.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        cov_frame = ttk.Frame(content, style="Card.TFrame")
        cov_frame.grid(row=3, column=3, sticky="ew", padx=(5, 0), pady=(6, 0))
        self.coverage_toggle = ToggleSwitch(cov_frame, variable=self.vars["show_inkhud_coverage"],
                                            command=self.draw_inkhud_coverage_overlay, bg=self.C_PANEL)
        self.coverage_toggle.grid(row=0, column=0, padx=(0, 4))
        ttk.Label(cov_frame, text="Coverage", style="Hint.TLabel").grid(row=0, column=1, sticky="w")
        self.progress_bar = ttk.Progressbar(content, variable=self.vars["progress_value"], maximum=1, mode="determinate")
        self.progress_bar.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        self.progress_bar.grid_remove()
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
        session_row = ttk.Frame(content, style="Card.TFrame")
        session_row.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        session_row.columnconfigure(0, weight=1)
        session_row.columnconfigure(1, weight=1)
        self.flat_button(session_row, "Save Session", self.save_session).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.flat_button(session_row, "Load Session", self.load_session).grid(row=0, column=1, sticky="ew", padx=(3, 0))
        return frame

    def selected_elements(self) -> list[str]:
        return [element for element in cli.MAP_ELEMENTS if bool(self.vars[f"element_{element}"].get())]

    def set_all_elements(self, enabled: bool) -> None:
        for element in cli.MAP_ELEMENTS:
            self.vars[f"element_{element}"].set(enabled)
        self.queue_live_update(preview=True, estimate=False)

    def update_elements_state(self) -> None:
        source = self.vars["source"].get()
        if source == "openfreemap-vector":
            self.elements_outer.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        else:
            self.elements_outer.grid_remove()

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
        # Check if click is near selected marker → start marker drag
        self._dragging_marker = False
        idx = self._editing_marker_index
        if idx is not None and 0 <= idx < len(self.markers):
            mx, my = self._canvas_marker_screen_pos(idx)
            if abs(event.x - mx) < 30 and abs(event.y - my) < 30:
                self._dragging_marker = True

    def drag_map(self, event) -> None:
        if not self.map_drag_start:
            return
        if self._dragging_marker and self._editing_marker_index is not None:
            # Move the selected marker to cursor position
            lon, lat = self._canvas_pixel_to_lon_lat(event.x, event.y)
            m = self.markers[self._editing_marker_index]
            m["lat"] = round(lat, 7)
            m["lon"] = round(lon, 7)
            self.draw_markers_overlay()
            self._update_marker_list_display()
            return
        start_x, start_y = self.map_drag_start
        center_lon, center_lat = self.map_drag_center
        center_px, center_py = self.lon_lat_to_world_pixel(center_lon, center_lat, self.map_zoom)
        new_lon, new_lat = self.world_pixel_to_lon_lat(center_px - (event.x - start_x), center_py - (event.y - start_y), self.map_zoom)
        self.map_center_lon = cli.normalize_lon(new_lon)
        self.map_center_lat = max(min(new_lat, cli.MAX_MERCATOR_LAT), -cli.MAX_MERCATOR_LAT)
        self.shift_current_preview(event.x - start_x, event.y - start_y)

    def end_map_drag(self, event) -> None:
        if self._dragging_marker:
            self._dragging_marker = False
            self.map_drag_start = None
            self.map_drag_center = None
            self.refresh_marker_list()
            self.draw_markers_overlay()
            return
        if self.map_drag_start is not None:
            dx = event.x - self.map_drag_start[0]
            dy = event.y - self.map_drag_start[1]
            moved = (dx * dx + dy * dy) ** 0.5
            self.map_drag_start = None
            self.map_drag_center = None
            if moved < 5 and self.marker_placing:
                self.add_marker_at_canvas(event.x, event.y)
                return
            if moved < 5 and self.vars["mode"].get() == "inkhud2":
                self.toggle_inkhud2_tile(event.x, event.y)
                return
        else:
            self.map_drag_start = None
            self.map_drag_center = None
        self.sync_view_area()
        self.schedule_preview(delay_ms=250)

    def _canvas_pixel_to_lon_lat(self, x: int, y: int):
        canvas_w = max(self.preview_rendered_width, 1)
        canvas_h = max(self.preview_rendered_height, 1)
        cx_view, cy_view = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, self.map_zoom)
        world_x = cx_view + x - canvas_w / 2
        world_y = cy_view + y - canvas_h / 2
        return self.world_pixel_to_lon_lat(world_x, world_y, self.map_zoom)

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
        source = self.vars["source"].get()
        url_template = SOURCES.get(source, {}).get("url_template") or self.vars["url"].get().strip() or None
        return {
            "bbox": {"west": bbox.west, "south": bbox.south, "east": bbox.east, "north": bbox.north},
            "zooms": zooms,
            "style": self.vars["style"].get().strip() or "osm-eink",
            "source": "xyz" if source != "openfreemap-vector" else source,
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
            estimated = total * 1500
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

        source = job.get("source", "openfreemap-vector")

        def render_tile(tile_job):
            tile_id, paste_x, paste_y = tile_job
            if source == "openfreemap-vector":
                image = self.render_preview_vector_tile(tile_id, job)
            else:
                image = self.render_preview_raster_tile(tile_id, job)
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
        tx = int(math.floor((cx_world - width / 2 + cx) / 256))
        ty = int(math.floor((cy_world - height / 2 + cy) / 256))
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

    def _add_grid_tiles(self) -> None:
        z = self.map_zoom
        try:
            n = int(self.vars["inkhud_grid"].get().split("x")[0])
        except (ValueError, AttributeError):
            n = 3
        # Compute fractional tile position and round to nearest boundary so the
        # NxN grid is centered on the map center regardless of zoom level.
        wx, wy = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, z)
        ftx = wx / 256.0
        fty = wy / 256.0
        start_tx = round(ftx) - n // 2
        start_ty = round(fty) - n // 2
        tiles = self.inkhud2_selected_tiles.setdefault(z, set())
        for ddx in range(n):
            for ddy in range(n):
                tiles.add((start_tx + ddx, start_ty + ddy))
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

        zoom_arr = ", ".join(str(int(t[0])) for t in tile_data)
        tx_arr   = ", ".join(str(int(t[1])) for t in tile_data)
        ty_arr   = ", ".join(str(int(t[2])) for t in tile_data)
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
    def _inkhud_grid_origin(lon: float, lat: float, z: int, g: int = 4, anchor_z: int | None = None) -> tuple[int, int]:
        """Return (gx0, gy0) — top-left tile of the gxg export grid at zoom z.

        Uses floor(ftx - g/2 + 0.5) so the tile containing the center point is
        always inside the grid and the grid is as symmetric as possible around it.
        anchor_z is accepted for API compatibility but ignored — per-zoom computation
        avoids cross-zoom integer truncation errors that cause coverage gaps.
        """
        n = 2 ** z
        cx = (lon + 180.0) / 360.0 * n
        cy = (1.0 - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
        gx0 = int(math.floor(cx - g / 2.0 + 0.5))
        gy0 = int(math.floor(cy - g / 2.0 + 0.5))
        return gx0, gy0

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

        # Anchor to max_zoom: snapping error is 0.5 tiles at max_zoom = tiny at coarser views.
        for i, z in enumerate(range(min_zoom, max_zoom + 1)):
            gx0, gy0 = self._inkhud_grid_origin(self.map_center_lon, self.map_center_lat, z, g, anchor_z=max_zoom)
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
                fill="", outline=color, width=2,
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

    def render_preview_raster_tile(self, tile: cli.Tile, job: dict[str, Any]):
        from PIL import Image
        from io import BytesIO

        source = job.get("source", "usgs-topo")
        url_template = job.get("urlTemplate") or SOURCES.get(source, {}).get("url_template", "")
        cache_key = (source, tile.z, tile.x, tile.y)
        cached = self.preview_tile_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        url = url_template.format(z=tile.z, x=tile.x, y=tile.y)
        try:
            data = cli.fetch_bytes(url, cli.DEFAULT_USER_AGENT, timeout=12, retries=2)
            image = Image.open(BytesIO(data)).convert("RGBA")
        except Exception:
            image = Image.new("RGBA", (256, 256), (255, 255, 255, 255))

        self.preview_tile_cache[cache_key] = image.copy()
        return image

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
        self.draw_markers_overlay()
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
        self.progress_bar.grid()
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
        source = self.vars["source"].get()
        max_zoom = max(job["zooms"])
        if source == "openfreemap-vector":
            if not cli.supports_vector_overzoom(job["style"]) and max_zoom > cli.OPENFREEMAP_MAX_DETAIL_ZOOM:
                raise ValueError(
                    "OpenFreeMap map detail currently stops at zoom 14. "
                    "Use osm-eink for crisp generalized map overzoom, "
                    "or osm-eink-topo for terrain-focused exports."
                )
            if cli.supports_vector_overzoom(job["style"]) and max_zoom > MAX_PREVIEW_ZOOM:
                raise ValueError(f"Overzoom exports are supported up to zoom {cli.OVERZOOM_MAX_DETAIL_ZOOM}.")
        else:
            source_max = SOURCES.get(source, {}).get("max_zoom", MAX_PREVIEW_ZOOM)
            if max_zoom > source_max:
                raise ValueError(f"{SOURCES[source]['label']} supports up to zoom {source_max}.")

    def run_export(self, job: dict[str, Any], output: Path, cancel_event: threading.Event) -> None:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            writer = QueueWriter(self.messages)
            with redirect_stdout(writer):
                exit_code = cli.download_tiles(
                    job, output, cancel_event=cancel_event,
                    rate_limit=DESKTOP_RATE_LIMIT_SECONDS, zip_output=True,
                    print_fn=lambda s: writer.write(s + "\n"),
                )
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
            self.after(0, self.progress_bar.grid_remove)

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
        zoom_specs = []
        eps = 1e-6
        for z in range(min_zoom, max_zoom + 1):
            tx, ty = self._inkhud_grid_origin(clng, clat, z, g, anchor_z=max_zoom)
            tx, ty = int(tx), int(ty)
            n = 2**z
            west  = tx / n * 360 - 180
            east  = (tx + g) / n * 360 - 180 - eps
            north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
            south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + g) / n)))) + eps
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
        self.progress_bar.grid()
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
        self.progress_bar.grid()
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
                writer = QueueWriter(self.messages)
                with redirect_stdout(writer):
                    exit_code = cli.download_tiles(
                        job, temp_out, cancel_event=cancel_event,
                        rate_limit=DESKTOP_RATE_LIMIT_SECONDS, print_fn=lambda s: writer.write(s + "\n"),
                    )
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
                    self._draw_markers_on_tile(rgb, z, tx, ty)
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
            self.after(0, self.progress_bar.grid_remove)

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
        half = g // 2
        cols, rows = g, g
        style = job["style"]
        min_zoom = zoom_specs[0]["zoom"]
        max_zoom = zoom_specs[-1]["zoom"]

        try:
            with tempfile.TemporaryDirectory(prefix="inkhud-export-") as temp_dir:
                temp_out = Path(temp_dir)
                writer = QueueWriter(self.messages)
                with redirect_stdout(writer):
                    exit_code = cli.download_tiles(
                        job, temp_out, cancel_event=cancel_event,
                        rate_limit=DESKTOP_RATE_LIMIT_SECONDS, print_fn=lambda s: writer.write(s + "\n"),
                    )
                if exit_code == 2:
                    self.after(0, self.finish_export_cancelled)
                    return
                if exit_code:
                    raise RuntimeError(f"Tile download failed (exit code {exit_code})")

                # Process each tile in the grid per zoom individually at full 256x256
                tile_data: list[tuple[int, int, int, list[int]]] = []  # (zoom, tx, ty, raw)
                for spec in zoom_specs:
                    z = spec["zoom"]
                    x0, y0 = spec["tx"], spec["ty"]
                    for dy in range(rows):
                        for dx in range(cols):
                            tx, ty = x0 + dx, y0 + dy
                            tile_path = temp_out / "tiles" / style / str(z) / str(tx) / f"{ty}.png"
                            rgb = Image.open(tile_path).convert("RGB") if tile_path.exists() else Image.new("RGB", (256, 256), (255, 255, 255))
                            self._draw_markers_on_tile(rgb, z, tx, ty)
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
            self.after(0, self.progress_bar.grid_remove)

    # ── Markers ──────────────────────────────────────────────────────────────

    MARKER_ICONS = ["parking", "sun", "star", "home", "fish", "bridge", "picnic", "bathroom", "binoculars", "hunting",
                    "tent", "rv", "tree", "group", "car", "campfire"]

    def build_markers_section(self, parent: ttk.Frame) -> ttk.Frame:
        from PIL import Image as _Image, ImageTk
        frame, content = self.collapsible_section(parent, "Markers", "collapse_markers")
        content.columnconfigure(0, weight=1)

        # Icon picker grid — click to select & enter placement mode
        picker = ttk.Frame(content, style="Card.TFrame")
        picker.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._icon_button_photos: dict[str, Any] = {}
        self._icon_buttons: dict[str, tk.Button] = {}
        icons_per_row = 5
        for i, icon_name in enumerate(self.MARKER_ICONS):
            icon_pil = self._get_icon_image(icon_name)
            photo = ImageTk.PhotoImage(icon_pil.resize((24, 24), _Image.NEAREST))
            self._icon_button_photos[icon_name] = photo
            btn = tk.Button(
                picker, image=photo, relief="flat", bd=2, cursor="hand2",
                command=lambda n=icon_name: self.select_icon_and_place(n),
            )
            btn.grid(row=i // icons_per_row, column=i % icons_per_row, padx=2, pady=2)
            self._icon_buttons[icon_name] = btn

        # Label text row
        label_row = ttk.Frame(content, style="Card.TFrame")
        label_row.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(label_row, text="Label text:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(label_row, textvariable=self.vars["marker_label_text"], width=14).grid(row=0, column=1, sticky="ew")
        ttk.Label(label_row, text="pt:").grid(row=0, column=2, padx=(6, 2))
        ttk.Spinbox(label_row, textvariable=self.vars["marker_label_font_size"], from_=6, to=72, width=4).grid(row=0, column=3)
        self.flat_button(label_row, "Place Label", self._place_label_marker).grid(row=0, column=4, padx=(6, 0))
        label_row.columnconfigure(1, weight=1)

        # Zoom range
        zoom_row = ttk.Frame(content, style="Card.TFrame")
        zoom_row.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(zoom_row, text="Show at zoom:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Spinbox(zoom_row, textvariable=self.vars["marker_min_zoom"], from_=0, to=20, width=4).grid(row=0, column=1)
        ttk.Label(zoom_row, text="–").grid(row=0, column=2, padx=4)
        ttk.Spinbox(zoom_row, textvariable=self.vars["marker_max_zoom"], from_=0, to=20, width=4).grid(row=0, column=3)

        self.marker_status_label = ttk.Label(content, text="Click an icon or Place Label, then click the map.", style="Hint.TLabel")
        self.marker_status_label.grid(row=3, column=0, sticky="w", pady=(0, 4))

        self.marker_list_frame = ttk.Frame(content, style="Card.TFrame")
        self.marker_list_frame.grid(row=4, column=0, sticky="ew")
        self.marker_list_frame.columnconfigure(0, weight=1)
        self.refresh_marker_list()
        return frame

    def _place_label_marker(self) -> None:
        text = self.vars["marker_label_text"].get().strip()
        if not text:
            return
        if self.marker_placing and self.vars["marker_icon"].get() == "__label__":
            self._exit_marker_placing()
            return
        self.vars["marker_icon"].set("__label__")
        self.marker_placing = True
        self.map_canvas.configure(cursor="crosshair")
        if hasattr(self, "_icon_buttons"):
            for btn in self._icon_buttons.values():
                btn.configure(relief="flat")
        if hasattr(self, "marker_status_label"):
            self.marker_status_label.configure(text=f"Click map to place label \"{text}\"  (click Place Label again to cancel)")

    def select_icon_and_place(self, icon_name: str) -> None:
        # If already placing this icon, cancel
        if self.marker_placing and self.vars["marker_icon"].get() == icon_name:
            self._exit_marker_placing()
            return
        self.vars["marker_icon"].set(icon_name)
        self.marker_placing = True
        self.map_canvas.configure(cursor="crosshair")
        for name, btn in self._icon_buttons.items():
            btn.configure(relief="sunken" if name == icon_name else "flat")
        if hasattr(self, "marker_status_label"):
            self.marker_status_label.configure(text=f"Click map to place {icon_name.title()}  (click icon again to cancel)")

    def _exit_marker_placing(self) -> None:
        self.marker_placing = False
        self._editing_marker_index = None
        self.map_canvas.configure(cursor="")
        if hasattr(self, "_icon_buttons"):
            for btn in self._icon_buttons.values():
                btn.configure(relief="flat")
        if hasattr(self, "marker_status_label"):
            self.marker_status_label.configure(text="Click an icon or Place Label, then click the map.")

    def toggle_marker_placing(self) -> None:
        if self.marker_placing:
            self._exit_marker_placing()
        else:
            self.marker_placing = True
            self.map_canvas.configure(cursor="crosshair")

    def add_marker_at_canvas(self, x: int, y: int) -> None:
        canvas_w = max(self.preview_rendered_width, 1)
        canvas_h = max(self.preview_rendered_height, 1)
        cx_view, cy_view = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, self.map_zoom)
        world_x = cx_view + x - canvas_w / 2
        world_y = cy_view + y - canvas_h / 2
        lon, lat = self.world_pixel_to_lon_lat(world_x, world_y, self.map_zoom)
        try:
            min_zoom = int(self.vars["marker_min_zoom"].get())
            max_zoom = int(self.vars["marker_max_zoom"].get())
        except ValueError:
            min_zoom = max_zoom = self.map_zoom
        icon = self.vars["marker_icon"].get()
        entry = {
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "icon": icon,
            "min_zoom": min_zoom,
            "max_zoom": max_zoom,
        }
        if icon == "__label__":
            entry["label_text"] = self.vars["marker_label_text"].get().strip()
            try:
                entry["font_size"] = max(6, int(self.vars["marker_label_font_size"].get()))
            except ValueError:
                entry["font_size"] = 12
        editing_idx = getattr(self, "_editing_marker_index", None)
        if editing_idx is not None and 0 <= editing_idx < len(self.markers):
            # Preserve icon/label_text/font_size from existing marker if not a label placement
            existing = self.markers[editing_idx]
            entry["icon"] = existing["icon"]
            if existing["icon"] == "__label__":
                entry["label_text"] = self.vars["marker_label_text"].get().strip() or existing.get("label_text", "")
                try:
                    entry["font_size"] = max(6, int(self.vars["marker_label_font_size"].get()))
                except ValueError:
                    entry["font_size"] = existing.get("font_size", 12)
            self.markers[editing_idx] = entry
            self._editing_marker_index = None
        else:
            self.markers.append(entry)
        self._exit_marker_placing()
        self.refresh_marker_list()
        self.draw_markers_overlay()

    def delete_marker(self, index: int) -> None:
        if 0 <= index < len(self.markers):
            self.markers.pop(index)
        self.refresh_marker_list()
        self.draw_markers_overlay()

    def _update_marker_list_display(self) -> None:
        """Update marker row labels in-place without rebuilding — preserves scroll position."""
        if not hasattr(self, "marker_list_frame"):
            return
        rows = self.marker_list_frame.winfo_children()
        editing_idx = getattr(self, "_editing_marker_index", None)
        for i, m in enumerate(self.markers):
            if i >= len(rows):
                break
            row = rows[i]
            children = row.winfo_children()
            if not children:
                continue
            lbl = children[0]
            if m["icon"] == "__label__":
                display = f"\"{m.get('label_text', '')}\"  {m.get('font_size', 12)}pt  z{m['min_zoom']}–{m['max_zoom']}  ({m['lat']:.5f}, {m['lon']:.5f})"
            else:
                display = f"{m['icon'].title()}  z{m['min_zoom']}–{m['max_zoom']}  ({m['lat']:.5f}, {m['lon']:.5f})"
            try:
                lbl.configure(text=display,
                              style="TLabel" if i == editing_idx else "Hint.TLabel")
            except Exception:
                pass

    def _preserve_scroll(self, fn):
        """Call fn(), then restore the sidebar scroll position after layout settles."""
        scroll_pos = self.controls_canvas.yview()[0] if hasattr(self, "controls_canvas") else 0
        fn()
        if hasattr(self, "controls_canvas"):
            self.after(50, lambda: self.controls_canvas.yview_moveto(scroll_pos))

    def refresh_marker_list(self) -> None:
        if not hasattr(self, "marker_list_frame"):
            return
        for w in self.marker_list_frame.winfo_children():
            w.destroy()
        if not self.markers:
            ttk.Label(self.marker_list_frame, text="No markers placed.", style="Hint.TLabel").grid(
                row=0, column=0, sticky="w", padx=4, pady=2)
            return
        editing_idx = getattr(self, "_editing_marker_index", None)
        for i, m in enumerate(self.markers):
            is_editing = (i == editing_idx)
            row = ttk.Frame(self.marker_list_frame,
                            style="Card.TFrame" if not is_editing else "TFrame")
            row.grid(row=i, column=0, sticky="ew", pady=1)
            row.columnconfigure(0, weight=1)
            if m["icon"] == "__label__":
                display = f"\"{m.get('label_text', '')}\"  {m.get('font_size', 12)}pt  z{m['min_zoom']}–{m['max_zoom']}  ({m['lat']:.5f}, {m['lon']:.5f})"
            else:
                display = f"{m['icon'].title()}  z{m['min_zoom']}–{m['max_zoom']}  ({m['lat']:.5f}, {m['lon']:.5f})"
            lbl = ttk.Label(row, text=display,
                            style="Hint.TLabel" if not is_editing else "TLabel",
                            cursor="hand2")
            lbl.grid(row=0, column=0, sticky="w", padx=4)
            lbl.bind("<Button-1>", lambda e, idx=i: self._select_edit_marker(idx))
            row.bind("<Button-1>", lambda e, idx=i: self._select_edit_marker(idx))
            self.flat_button(row, "×", lambda idx=i: self.delete_marker(idx), width=2).grid(row=0, column=1, padx=(0, 2))

    def _select_edit_marker(self, index: int) -> None:
        # Toggle off if already selected
        if self._editing_marker_index == index:
            self._editing_marker_index = None
            self._dragging_marker = False
            self.map_canvas.configure(cursor="")
            if hasattr(self, "marker_status_label"):
                self.marker_status_label.configure(text="Click an icon or Place Label, then click the map.")
            self._update_marker_list_display()
            self.draw_markers_overlay()
            return
        m = self.markers[index]
        self._editing_marker_index = index
        self._dragging_marker = False
        # Populate label controls from the marker
        if m["icon"] == "__label__":
            self.vars["marker_label_text"].set(m.get("label_text", ""))
            self.vars["marker_label_font_size"].set(str(m.get("font_size", 12)))
        self.vars["marker_min_zoom"].set(str(m["min_zoom"]))
        self.vars["marker_max_zoom"].set(str(m["max_zoom"]))
        self.vars["marker_icon"].set(m["icon"])
        self.map_canvas.configure(cursor="fleur")
        if hasattr(self, "marker_status_label"):
            name = f"\"{m.get('label_text', '')}\"" if m["icon"] == "__label__" else m["icon"].title()
            self.marker_status_label.configure(text=f"Drag {name} on the map to move it. Click row again to deselect.")
        self._update_marker_list_display()
        self.draw_markers_overlay()

    def _canvas_marker_screen_pos(self, index: int):
        """Return (px, py) canvas pixel of marker[index] at current zoom."""
        m = self.markers[index]
        z = self.map_zoom
        canvas_w = max(self.preview_rendered_width, 1)
        canvas_h = max(self.preview_rendered_height, 1)
        cx_view, cy_view = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, z)
        mx, my = self.lon_lat_to_world_pixel(m["lon"], m["lat"], z)
        return int(mx - cx_view + canvas_w / 2), int(my - cy_view + canvas_h / 2)

    def draw_markers_overlay(self) -> None:
        from PIL import Image as _Image, ImageTk
        self.map_canvas.delete("marker-overlay")
        self._marker_photo_refs.clear()
        if not self.markers:
            return
        z = self.map_zoom
        size = max(6, int(20 * 2 ** (z - 16)))
        half = size // 2
        canvas_w = max(self.preview_rendered_width, 1)
        canvas_h = max(self.preview_rendered_height, 1)
        cx_view, cy_view = self.lon_lat_to_world_pixel(self.map_center_lon, self.map_center_lat, z)
        editing_idx = self._editing_marker_index
        for i, marker in enumerate(self.markers):
            if not (marker["min_zoom"] <= z <= marker["max_zoom"]):
                continue
            mx, my = self.lon_lat_to_world_pixel(marker["lon"], marker["lat"], z)
            px = int(mx - cx_view + canvas_w / 2)
            py = int(my - cy_view + canvas_h / 2)
            if marker["icon"] == "__label__":
                base_fs = marker.get("font_size", 12)
                scaled_fs = max(6, int(base_fs * 2 ** (z - 16)))
                icon_pil = self._get_label_image(marker.get("label_text", "?"), scaled_fs)
            else:
                icon_pil = self._get_icon_image(marker["icon"])
                icon_pil = icon_pil.resize((size, size), _Image.NEAREST)
            photo = ImageTk.PhotoImage(icon_pil)
            self._marker_photo_refs.append(photo)
            w, h = icon_pil.size
            x0, y0 = px - w // 2, py - h // 2
            self.map_canvas.create_image(x0, y0, image=photo, anchor="nw", tags=("marker-overlay",))
            if i == editing_idx:
                pad = 3
                self.map_canvas.create_rectangle(
                    x0 - pad, y0 - pad, x0 + w + pad, y0 + h + pad,
                    outline="#00AAFF", width=2, tags=("marker-overlay",)
                )

    def _get_icon_image(self, name: str):
        from PIL import Image as _Image, ImageDraw, ImageFont
        if name in self._icon_cache:
            return self._icon_cache[name]
        # All icons: white symbol on black square (sign-board style)
        img = _Image.new("RGB", (16, 16), (0, 0, 0))
        d = ImageDraw.Draw(img)
        W = (255, 255, 255)
        B = (0, 0, 0)
        if name == "parking":
            # Bold white P on black
            d.rectangle([3, 2, 5, 13], fill=W)   # stem
            d.rectangle([5, 2, 10, 4], fill=W)   # top of bowl
            d.rectangle([5, 7, 10, 9], fill=W)   # bottom of bowl
            d.rectangle([10, 2, 12, 9], fill=W)  # right of bowl
        elif name == "sun":
            cx, cy = 7, 7
            d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=W)
            for deg in range(0, 360, 45):
                rad = math.radians(deg)
                x1 = int(cx + 4 * math.cos(rad))
                y1 = int(cy + 4 * math.sin(rad))
                x2 = int(cx + 6 * math.cos(rad))
                y2 = int(cy + 6 * math.sin(rad))
                d.line([x1, y1, x2, y2], fill=W, width=1)
        elif name == "star":
            cx, cy = 7, 7
            pts = []
            for i in range(10):
                a = math.radians(-90 + i * 36)
                r = 7 if i % 2 == 0 else 3
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            d.polygon(pts, fill=W)
        elif name == "home":
            d.polygon([(7, 2), (1, 7), (13, 7)], fill=W)   # roof
            d.rectangle([3, 7, 11, 13], fill=W)             # walls
            d.rectangle([5, 9, 9, 13], fill=B)              # door
        elif name == "fish":
            d.ellipse([4, 5, 14, 11], fill=W)
            d.polygon([(4, 8), (0, 5), (0, 11)], fill=W)   # tail
            d.ellipse([10, 6, 12, 8], fill=B)              # eye
        elif name == "bridge":
            # Deck
            d.rectangle([0, 8, 15, 10], fill=W)
            # Arch above deck
            d.arc([1, 3, 14, 11], start=180, end=0, fill=W, width=2)
            # Pillars below deck
            d.rectangle([2, 10, 4, 14], fill=W)
            d.rectangle([11, 10, 13, 14], fill=W)
        elif name == "picnic":
            # Table top
            d.rectangle([2, 5, 13, 7], fill=W)
            # Crossed legs
            d.line([(4, 7), (3, 12)], fill=W, width=1)
            d.line([(11, 7), (12, 12)], fill=W, width=1)
            # Benches
            d.rectangle([0, 9, 5, 11], fill=W)
            d.rectangle([10, 9, 15, 11], fill=W)
        elif name == "bathroom":
            # Two stick figures side by side
            d.ellipse([2, 2, 5, 5], fill=W)
            d.line([(3, 5), (3, 9)], fill=W, width=1)
            d.line([(1, 7), (5, 7)], fill=W, width=1)
            d.line([(3, 9), (1, 13)], fill=W, width=1)
            d.line([(3, 9), (5, 13)], fill=W, width=1)
            d.ellipse([10, 2, 13, 5], fill=W)
            d.line([(11, 5), (11, 9)], fill=W, width=1)
            d.line([(9, 7), (13, 7)], fill=W, width=1)
            d.line([(11, 9), (9, 13)], fill=W, width=1)
            d.line([(11, 9), (13, 13)], fill=W, width=1)
        elif name == "binoculars":
            d.ellipse([1, 4, 7, 12], fill=W)
            d.ellipse([2, 5, 6, 11], fill=B)
            d.ellipse([8, 4, 14, 12], fill=W)
            d.ellipse([9, 5, 13, 11], fill=B)
            d.rectangle([6, 7, 9, 9], fill=W)
        elif name == "hunting":
            cx, cy = 7, 7
            d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=W, width=1)
            d.line([cx, 0, cx, cy - 6], fill=W, width=1)
            d.line([cx, cy + 6, cx, 15], fill=W, width=1)
            d.line([0, cy, cx - 6, cy], fill=W, width=1)
            d.line([cx + 6, cy, 15, cy], fill=W, width=1)
        elif name == "tent":
            # Triangle tent with ground line
            d.polygon([(7, 2), (0, 13), (14, 13)], fill=W)
            d.rectangle([0, 13, 15, 14], fill=W)   # ground
            d.polygon([(7, 6), (4, 13), (10, 13)], fill=B)  # door opening
        elif name == "rv":
            # Boxy camper/RV profile
            d.rectangle([1, 5, 14, 11], fill=W)    # body
            d.rectangle([1, 3, 6, 5], fill=W)      # cab roof
            d.rectangle([1, 5, 4, 11], fill=W)     # cab front
            d.rectangle([2, 6, 3, 10], fill=B)     # cab window
            d.rectangle([7, 6, 13, 10], fill=B)    # RV window
            d.ellipse([2, 10, 6, 14], fill=W)      # rear wheel
            d.ellipse([3, 11, 5, 13], fill=B)
            d.ellipse([9, 10, 13, 14], fill=W)     # front wheel
            d.ellipse([10, 11, 12, 13], fill=B)
        elif name == "tree":
            # Pine tree — three stacked triangles
            d.polygon([(7, 1), (2, 6), (12, 6)], fill=W)
            d.polygon([(7, 4), (1, 10), (13, 10)], fill=W)
            d.polygon([(7, 7), (1, 14), (13, 14)], fill=W)
            d.rectangle([5, 13, 9, 15], fill=W)   # trunk
        elif name == "group":
            # Three figures — left, center (slightly taller), right
            for cx in [3, 8, 12]:
                d.ellipse([cx - 1, 2, cx + 1, 4], fill=W)
                d.line([cx, 4, cx, 9], fill=W, width=1)
                d.line([cx - 2, 6, cx + 2, 6], fill=W, width=1)
                d.line([cx, 9, cx - 2, 13], fill=W, width=1)
                d.line([cx, 9, cx + 2, 13], fill=W, width=1)
        elif name == "car":
            # Simple car side profile
            d.rectangle([1, 8, 14, 12], fill=W)    # body
            d.polygon([(3, 8), (4, 4), (11, 4), (13, 8)], fill=W)  # roof
            d.rectangle([5, 5, 8, 8], fill=B)      # front window
            d.rectangle([9, 5, 12, 8], fill=B)     # rear window
            d.ellipse([2, 11, 6, 14], fill=W)      # rear wheel
            d.ellipse([3, 12, 5, 14], fill=B)
            d.ellipse([9, 11, 13, 14], fill=W)     # front wheel
            d.ellipse([10, 12, 12, 14], fill=B)
        elif name == "campfire":
            # Logs at base, flame above
            d.rectangle([2, 11, 13, 13], fill=W)   # log 1
            d.line([4, 9, 11, 13], fill=W, width=1)  # log 2 diagonal
            d.line([11, 9, 4, 13], fill=W, width=1)  # log 3 diagonal
            # Flame: teardrop polygon
            d.polygon([(7, 2), (4, 7), (5, 10), (9, 10), (10, 7)], fill=W)
            d.polygon([(7, 5), (6, 8), (8, 8)], fill=B)  # inner dark core
        self._icon_cache[name] = img
        return img

    def _get_label_image(self, text: str, font_size: int):
        from PIL import Image as _Image, ImageDraw, ImageFont
        font_size = max(6, font_size)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        tmp = _Image.new("RGB", (1, 1))
        td = ImageDraw.Draw(tmp)
        bbox = td.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad = max(2, font_size // 6)
        img = _Image.new("RGB", (tw + pad * 2, th + pad * 2), (0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((pad - bbox[0], pad - bbox[1]), text, fill=(255, 255, 255), font=font)
        return img

    def _draw_markers_on_tile(self, rgb_image, z: int, tx: int, ty: int) -> None:
        n = 2 ** z
        size = max(6, int(20 * 2 ** (z - 16)))
        for marker in self.markers:
            if not (marker["min_zoom"] <= z <= marker["max_zoom"]):
                continue
            fx = (marker["lon"] + 180.0) / 360.0 * n
            lat_rad = math.radians(marker["lat"])
            fy = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
            px = int((fx - tx) * 256)
            py = int((fy - ty) * 256)
            if marker["icon"] == "__label__":
                base_fs = marker.get("font_size", 12)
                scaled_fs = max(6, int(base_fs * 2 ** (z - 16)))
                icon = self._get_label_image(marker.get("label_text", "?"), scaled_fs)
            else:
                icon = self._get_icon_image(marker["icon"]).resize((size, size))
            iw, ih = icon.size
            if px < -iw or px > 256 + iw or py < -ih or py > 256 + ih:
                continue
            paste_x, paste_y = px - iw // 2, py - ih // 2
            x0 = max(paste_x, 0)
            y0 = max(paste_y, 0)
            x1 = min(paste_x + iw, 256)
            y1 = min(paste_y + ih, 256)
            if x1 <= x0 or y1 <= y0:
                continue
            crop = icon.crop((x0 - paste_x, y0 - paste_y, x1 - paste_x, y1 - paste_y))
            rgb_image.paste(crop, (x0, y0))

    # ── Session save / load ───────────────────────────────────────────────────

    def save_session(self) -> None:
        import json
        path = filedialog.asksaveasfilename(
            title="Save session",
            defaultextension=".json",
            filetypes=[("Session files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        session = {
            "version": 1,
            "map_center_lat": self.map_center_lat,
            "map_center_lon": self.map_center_lon,
            "map_zoom": self.map_zoom,
            "settings": {
                k: self.vars[k].get()
                for k in [
                    "source", "min_zoom", "max_zoom", "mode", "style", "inkhud_grid",
                    "brightness", "contrast", "threshold",
                    "marker_icon", "marker_min_zoom", "marker_max_zoom", "marker_label_text", "marker_label_font_size",
                    "show_inkhud_coverage", "permission",
                ]
            },
            "elements": {e: bool(self.vars[f"element_{e}"].get()) for e in cli.MAP_ELEMENTS},
            "markers": self.markers,
            "inkhud2_selected_tiles": {
                str(z): [[tx, ty] for tx, ty in sorted(tiles)]
                for z, tiles in self.inkhud2_selected_tiles.items()
            },
        }
        Path(path).write_text(json.dumps(session, indent=2), encoding="utf-8")
        self.vars["status"].set(f"Session saved.")

    def load_session(self) -> None:
        import json
        path = filedialog.askopenfilename(
            title="Load session",
            filetypes=[("Session files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Load failed", str(exc))
            return
        self.map_center_lat = float(data.get("map_center_lat", self.map_center_lat))
        self.map_center_lon = float(data.get("map_center_lon", self.map_center_lon))
        self.map_zoom = int(data.get("map_zoom", self.map_zoom))
        settings = data.get("settings", {})
        for k in ["source", "min_zoom", "max_zoom", "mode", "style", "inkhud_grid",
                  "marker_icon", "marker_min_zoom", "marker_max_zoom", "marker_label_text", "marker_label_font_size"]:
            if k in settings and k in self.vars:
                self.vars[k].set(str(settings[k]))
        for k in ["brightness", "contrast", "threshold"]:
            if k in settings and k in self.vars:
                self.vars[k].set(float(settings[k]))
        for k in ["show_inkhud_coverage", "permission"]:
            if k in settings and k in self.vars:
                self.vars[k].set(bool(settings[k]))
        for e in cli.MAP_ELEMENTS:
            elems = data.get("elements", {})
            if e in elems:
                self.vars[f"element_{e}"].set(bool(elems[e]))
        self.markers = data.get("markers", [])
        raw = data.get("inkhud2_selected_tiles", {})
        self.inkhud2_selected_tiles = {int(z): {(tx, ty) for tx, ty in tiles} for z, tiles in raw.items()}
        if self.marker_placing:
            self._exit_marker_placing()
        self.refresh_marker_list()
        self.sync_view_area()
        self.schedule_preview(delay_ms=250)
        self.vars["status"].set("Session loaded.")

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

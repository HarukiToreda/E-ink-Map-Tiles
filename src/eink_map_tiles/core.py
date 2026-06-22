from __future__ import annotations

import json
import math
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_URL_TEMPLATE = None
OPENFREEMAP_VECTOR_TEMPLATE = "https://tiles.openfreemap.org/planet/latest/{z}/{x}/{y}.pbf"
OPENFREEMAP_MAX_DETAIL_ZOOM = 14
OVERZOOM_MAX_DETAIL_ZOOM = 16
TOPO_MAX_DETAIL_ZOOM = OVERZOOM_MAX_DETAIL_ZOOM
TERRAIN_TERRARIUM_TEMPLATE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DEFAULT_USER_AGENT = "eink-map-tiles/1.1.0 (+https://github.com/HarukiToreda/E-ink-Map-Tiles)"
MAX_MERCATOR_LAT = 85.05112878
VECTOR_EXTENT = 4096
MAP_ELEMENTS = ("land", "water", "roads", "highways", "paths", "buildings", "boundaries", "labels", "pois", "transit")
DEFAULT_STYLE = "osm-eink"
DEFAULT_BRIGHTNESS = 0.99
DEFAULT_CONTRAST = 1.15
DEFAULT_THRESHOLD = 120
DEFAULT_INCLUDE_ELEMENTS = [element for element in MAP_ELEMENTS if element not in {"buildings", "pois"}]
DEFAULT_TOPO_ELEMENTS = ["land", "water", "paths", "labels"]
DEFAULT_ATTRIBUTION = {
    "map_data": "© OpenStreetMap contributors",
    "map_data_license": "Open Database License (ODbL) 1.0",
    "openmaptiles": "© OpenMapTiles, if using OpenMapTiles schema/data",
    "terrain": "© Mapzen terrain tiles, if using topo style",
    "notes": "Verify and preserve attribution required by your tile source/provider.",
}


@dataclass(frozen=True)
class BBox:
    west: float
    south: float
    east: float
    north: float


@dataclass(frozen=True)
class Tile:
    z: int
    x: int
    y: int


def parse_zooms(value: str) -> list[int]:
    zooms: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise ValueError(f"Invalid zoom range: {part}")
            zooms.update(range(start, end + 1))
        else:
            zooms.add(int(part))
    if not zooms:
        raise ValueError("At least one zoom level is required")
    if min(zooms) < 0 or max(zooms) > 20:
        raise ValueError("Zoom levels must be between 0 and 20")
    return sorted(zooms)


def bbox_from_center(lat: float, lon: float, radius_km: float) -> BBox:
    if not -90 <= lat <= 90:
        raise ValueError("lat must be between -90 and 90")
    if not -180 <= lon <= 180:
        raise ValueError("lon must be between -180 and 180")
    if radius_km <= 0:
        raise ValueError("radius_km must be greater than zero")
    lat_delta = radius_km / 111.32
    lon_scale = max(math.cos(math.radians(lat)), 0.01)
    lon_delta = radius_km / (111.32 * lon_scale)
    return BBox(
        west=normalize_lon(lon - lon_delta),
        south=max(lat - lat_delta, -90),
        east=normalize_lon(lon + lon_delta),
        north=min(lat + lat_delta, 90),
    )


def normalize_lon(lon: float) -> float:
    while lon < -180:
        lon += 360
    while lon > 180:
        lon -= 360
    return lon


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    lat = max(min(lat, MAX_MERCATOR_LAT), -MAX_MERCATOR_LAT)
    n = 2**z
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    lat_rad = math.radians(lat)
    y = int(math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n))
    return clamp(x, 0, n - 1), clamp(y, 0, n - 1)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def tiles_for_bbox(bbox: BBox, zooms: list[int]) -> list[Tile]:
    tiles: list[Tile] = []
    for z in zooms:
        seen: set[tuple[int, int, int]] = set()
        for x_min, x_max, y_min, y_max in tile_ranges_for_bbox(bbox, z):
            for x in range(x_min, x_max + 1):
                for y in range(y_min, y_max + 1):
                    key = (z, x, y)
                    if key not in seen:
                        seen.add(key)
                        tiles.append(Tile(z=z, x=x, y=y))
    return tiles


def tile_ranges_for_bbox(bbox: BBox, z: int) -> list[tuple[int, int, int, int]]:
    lon_spans = [(bbox.west, bbox.east)]
    if bbox.west > bbox.east:
        lon_spans = [(bbox.west, 180.0), (-180.0, bbox.east)]
    ranges = []
    for west, east in lon_spans:
        x_min, y_min = lonlat_to_tile(west, bbox.north, z)
        x_max, y_max = lonlat_to_tile(east, bbox.south, z)
        ranges.append((min(x_min, x_max), max(x_min, x_max), min(y_min, y_max), max(y_min, y_max)))
    return ranges


def count_tiles_for_bbox(bbox: BBox, zooms: list[int]) -> int:
    total = 0
    for z in zooms:
        for x_min, x_max, y_min, y_max in tile_ranges_for_bbox(bbox, z):
            total += (x_max - x_min + 1) * (y_max - y_min + 1)
    return total


def first_tile_for_bbox(bbox: BBox, zooms: list[int]) -> Tile | None:
    if not zooms:
        return None
    ranges = tile_ranges_for_bbox(bbox, zooms[0])
    if not ranges:
        return None
    x_min, _x_max, y_min, _y_max = ranges[0]
    return Tile(z=zooms[0], x=x_min, y=y_min)


def tile_output_path(output_root: Path, style: str, layout: str, tile: Tile) -> Path:
    if layout == "single-map":
        base = output_root / "map"
    elif layout == "meshtastic-sd":
        base = output_root / "maps" / style
    elif layout == "style-root":
        base = output_root / style
    else:
        base = output_root / "tiles" / style
    return base / str(tile.z) / str(tile.x) / f"{tile.y}.png"


def tile_url(template: str, tile: Tile) -> str:
    return template.format(z=tile.z, x=tile.x, y=tile.y)


def fetch_tile(url: str, destination: Path, user_agent: str, timeout: float, retries: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".tile") as temp_file:
                    shutil.copyfileobj(response, temp_file)
                    temp_path = Path(temp_file.name)
            temp_path.replace(destination)
            return
        except (OSError, urllib.error.URLError, RuntimeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2**attempt, 10))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def fetch_bytes(url: str, user_agent: str, timeout: float, retries: int) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                return response.read()
        except (OSError, urllib.error.URLError, RuntimeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2**attempt, 10))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def render_openfreemap_tile(
    tile: Tile,
    destination: Path,
    user_agent: str,
    timeout: float,
    retries: int,
    elements: list[str] | tuple[str, ...] | None = None,
    style: str = "osm-eink",
) -> None:
    image = render_openfreemap_image(tile, user_agent, timeout, retries, elements, style)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)


def render_openfreemap_image(
    tile: Tile,
    user_agent: str,
    timeout: float,
    retries: int,
    elements: list[str] | tuple[str, ...] | None = None,
    style: str = "osm-eink",
):
    from mapbox_vector_tile import decode
    from PIL import Image, ImageDraw

    selected = set(elements if elements is not None else MAP_ELEMENTS)
    topo = is_topo_style(style)
    if supports_vector_overzoom(style) and tile.z > OPENFREEMAP_MAX_DETAIL_ZOOM:
        data = fetch_overzoomed_openfreemap_data(tile, user_agent, timeout, retries)
    else:
        raw = fetch_bytes(tile_url(OPENFREEMAP_VECTOR_TEMPLATE, tile), user_agent, timeout, retries)
        data = decode(raw, default_options={"y_coord_down": True}) if raw else {}
    image = Image.new("RGB", (256, 256), "#f7f8f4")
    draw = ImageDraw.Draw(image)

    if "land" in selected:
        draw_polygon_layer(draw, data, "landcover", "#c4cbc4", "#a7b1aa")
        draw_polygon_layer(draw, data, "landuse", "#e5e6e1", "#c5ccc4")
        draw_polygon_layer(draw, data, "park", "#b8c2b9", "#9ba89e")
    if topo:
        draw_topography(image, tile, user_agent, timeout, retries)
    if "water" in selected:
        draw_polygon_layer(draw, data, "water", "#aeb9b4", "#7f8d87")
        draw_line_layer(draw, data, "waterway", "#6f7d77", width=1)
    if "buildings" in selected and not topo:
        draw_polygon_layer(draw, data, "building", "#d0d5cf", None)
    if "boundaries" in selected:
        draw_line_layer(draw, data, "boundary", "#7d8781" if tile.z <= 6 else "#929c96", width=1)
    if {"roads", "highways", "paths", "transit"} & selected:
        draw_transportation(draw, data, tile.z, selected, topo=topo)
    if "labels" in selected:
        draw_labels(draw, data, tile.z, load_label_font(tile.z))
        if "paths" in selected:
            draw_transportation_names(image, draw, data, tile.z, load_label_font(tile.z, small=True))
    if "pois" in selected:
        draw_pois(draw, data, tile.z, load_label_font(tile.z, small=True))
    return image


def is_topo_style(style: str | None) -> bool:
    return "topo" in (style or "").lower()


def supports_vector_overzoom(style: str | None) -> bool:
    style_name = (style or DEFAULT_STYLE).lower()
    return style_name == DEFAULT_STYLE or is_topo_style(style_name)


def fetch_overzoomed_openfreemap_data(tile: Tile, user_agent: str, timeout: float, retries: int) -> dict:
    from mapbox_vector_tile import decode

    zoom_delta = tile.z - OPENFREEMAP_MAX_DETAIL_ZOOM
    scale = 2**zoom_delta
    parent_tile = Tile(z=OPENFREEMAP_MAX_DETAIL_ZOOM, x=tile.x // scale, y=tile.y // scale)
    raw = fetch_bytes(tile_url(OPENFREEMAP_VECTOR_TEMPLATE, parent_tile), user_agent, timeout, retries)
    if not raw:
        return {}
    data = decode(raw, default_options={"y_coord_down": True})
    return overzoom_vector_data(data, tile, scale)


def overzoom_vector_data(data: dict, tile: Tile, scale: int) -> dict:
    offset_x = (tile.x % scale) * VECTOR_EXTENT / scale
    offset_y = (tile.y % scale) * VECTOR_EXTENT / scale
    transformed: dict[str, dict] = {}
    for layer_name, layer in data.items():
        features = []
        for feature in layer.get("features", []):
            geometry = feature.get("geometry", {})
            features.append(
                {
                    **feature,
                    "geometry": {
                        **geometry,
                        "coordinates": overzoom_coordinates(geometry.get("coordinates", []), offset_x, offset_y, scale),
                    },
                }
            )
        transformed[layer_name] = {**layer, "features": features}
    return transformed


def overzoom_coordinates(value, offset_x: float, offset_y: float, scale: int):
    if (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        return [(value[0] - offset_x) * scale, (value[1] - offset_y) * scale]
    if isinstance(value, list):
        return [overzoom_coordinates(item, offset_x, offset_y, scale) for item in value]
    if isinstance(value, tuple):
        return tuple(overzoom_coordinates(item, offset_x, offset_y, scale) for item in value)
    return value


def draw_topography(image, tile: Tile, user_agent: str, timeout: float, retries: int) -> None:
    from PIL import ImageDraw

    if tile.z < 4:
        return
    try:
        terrain = fetch_terrain_image(tile, user_agent, timeout, retries)
    except RuntimeError:
        return
    elevations = decode_terrarium(terrain)
    apply_hillshade(image, elevations)
    draw_contours(ImageDraw.Draw(image), elevations, tile.z)


def fetch_terrain_image(tile: Tile, user_agent: str, timeout: float, retries: int):
    from PIL import Image

    terrain_z = min(tile.z, 15)
    scale = 2 ** max(tile.z - terrain_z, 0)
    terrain_tile = Tile(z=terrain_z, x=tile.x // scale, y=tile.y // scale)
    data = fetch_bytes(tile_url(TERRAIN_TERRARIUM_TEMPLATE, terrain_tile), user_agent, timeout, retries)
    with Image.open(BytesIO(data)) as image:
        terrain = image.convert("RGB")
    if scale > 1:
        crop_size = max(1, 256 // scale)
        offset_x = (tile.x % scale) * crop_size
        offset_y = (tile.y % scale) * crop_size
        terrain = terrain.crop((offset_x, offset_y, offset_x + crop_size, offset_y + crop_size)).resize((256, 256), Image.Resampling.BILINEAR)
    return terrain


def decode_terrarium(image) -> list[list[float]]:
    pixels = image.load()
    elevations: list[list[float]] = []
    for y in range(256):
        row = []
        for x in range(256):
            red, green, blue = pixels[x, y]
            row.append((red * 256 + green + blue / 256) - 32768)
        elevations.append(row)
    return elevations


def apply_hillshade(image, elevations: list[list[float]]) -> None:
    from PIL import Image

    shade = Image.new("L", (256, 256), 225)
    shade_pixels = shade.load()
    for y in range(1, 255):
        prev_row = elevations[y - 1]
        row = elevations[y]
        next_row = elevations[y + 1]
        for x in range(1, 255):
            east_west = row[x + 1] - row[x - 1]
            north_south = next_row[x] - prev_row[x]
            relief = max(-42, min(42, (east_west + north_south) * 0.42))
            slope = min(26, (abs(east_west) + abs(north_south)) * 0.09)
            shade_pixels[x, y] = int(max(168, min(244, 222 + relief - slope)))
    shaded = Image.blend(image.convert("RGB"), shade.convert("RGB"), 0.28)
    image.paste(shaded)


def draw_contours(draw, elevations: list[list[float]], z: int) -> None:
    step = 4 if z < 10 else 2
    if z < 7:
        interval = 500
    elif z < 10:
        interval = 250
    elif z < 13:
        interval = 100
    else:
        interval = 40
    index_interval = interval * 5
    for y in range(0, 255, step):
        for x in range(0, 255, step):
            e00 = elevations[y][x]
            e10 = elevations[y][min(x + step, 255)]
            e11 = elevations[min(y + step, 255)][min(x + step, 255)]
            e01 = elevations[min(y + step, 255)][x]
            minimum = min(e00, e10, e11, e01)
            maximum = max(e00, e10, e11, e01)
            if maximum - minimum < 1:
                continue
            start = math.floor(minimum / interval) + 1
            end = math.floor(maximum / interval)
            for level_index in range(start, end + 1):
                level = level_index * interval
                points = contour_intersections(x, y, step, e00, e10, e11, e01, level)
                if len(points) >= 2:
                    color = "#87918b" if level % index_interval == 0 else "#a9b2ac"
                    draw.line(points[:2], fill=color, width=1)
                if len(points) == 4:
                    color = "#87918b" if level % index_interval == 0 else "#a9b2ac"
                    draw.line(points[2:4], fill=color, width=1)


def contour_intersections(
    x: int, y: int, step: int,
    e00: float, e10: float, e11: float, e01: float,
    level: float,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    add_contour_point(points, e00, e10, level, (x, y), (x + step, y))
    add_contour_point(points, e10, e11, level, (x + step, y), (x + step, y + step))
    add_contour_point(points, e11, e01, level, (x + step, y + step), (x, y + step))
    add_contour_point(points, e01, e00, level, (x, y + step), (x, y))
    return points


def add_contour_point(
    points: list[tuple[float, float]],
    a: float, b: float, level: float,
    start: tuple[int, int], end: tuple[int, int],
) -> None:
    if (a < level <= b) or (b < level <= a):
        fraction = 0.5 if a == b else (level - a) / (b - a)
        points.append((start[0] + (end[0] - start[0]) * fraction, start[1] + (end[1] - start[1]) * fraction))


def draw_polygon_layer(draw, data: dict, layer_name: str, fill: str, outline: str | None) -> None:
    for feature in data.get(layer_name, {}).get("features", []):
        geometry = feature.get("geometry", {})
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates", [])
        if geometry_type == "Polygon":
            draw_polygon(draw, coordinates, fill, outline)
        elif geometry_type == "MultiPolygon":
            for polygon in coordinates:
                draw_polygon(draw, polygon, fill, outline)


def draw_polygon(draw, rings: list, fill: str, outline: str | None) -> None:
    if not rings:
        return
    outer = [scale_point(point) for point in rings[0]]
    if len(outer) >= 3:
        draw.polygon(outer, fill=fill, outline=outline)


def draw_line_layer(draw, data: dict, layer_name: str, color: str, width: int = 1) -> None:
    for feature in data.get(layer_name, {}).get("features", []):
        draw_geometry_lines(draw, feature.get("geometry", {}), color, width)


def draw_transportation(draw, data: dict, z: int, elements: set[str], topo: bool = False) -> None:
    if z <= 5 and not topo:
        return
    path_style = ("#424a45", None, 1, 0) if topo else ("#707a74", None, 1, 0)
    class_styles = {
        "motorway": ("#9ea7a1", None, 1, 0) if z < 12 else ("#5c655f", "#fbfbf8", 5, 3),
        "trunk": ("#a9b1ab", None, 1, 0) if z < 12 else ("#68716b", "#fbfbf8", 5, 3),
        "primary": ("#b6beb8", None, 1, 0) if z < 12 else ("#747e77", "#fbfbf8", 4, 2),
        "secondary": ("#9aa49e", "#ffffff", 2, 1) if topo else ("#8b948e", "#ffffff", 3, 1),
        "tertiary": ("#adb6b0", "#ffffff", 2, 1) if topo else ("#9aa29c", "#ffffff", 3, 1),
        "minor": ("#c8d0ca", None, 1, 0) if topo else ("#aeb6b0", "#ffffff", 2, 1),
        "service": ("#d3dad5", None, 1, 0) if topo else ("#bcc4be", "#ffffff", 2, 1),
        "track": path_style,
        "path": path_style,
        "footway": path_style,
        "cycleway": path_style,
        "bridleway": path_style,
        "steps": path_style,
        "rail": ("#4f5752", "#f6f6f3", 2, 1),
    }
    line_jobs = []
    path_classes = {"track", "path", "footway", "cycleway", "bridleway", "steps"}
    for feature in data.get("transportation", {}).get("features", []):
        properties = feature.get("properties", {})
        road_class = properties.get("class", "")
        if z < 12 and road_class not in {"motorway", "trunk", "primary"} and not (topo and road_class in path_classes):
            continue
        if road_class in {"motorway", "trunk", "primary"} and "highways" not in elements:
            continue
        if road_class in {"secondary", "tertiary", "minor", "service"} and "roads" not in elements:
            continue
        if road_class in path_classes and "paths" not in elements:
            continue
        if road_class == "rail" and "transit" not in elements:
            continue
        casing, fill, casing_width, fill_width = class_styles.get(road_class, ("#aeb6b0", "#ffffff", 2, 1))
        dashed = road_class in path_classes
        dash = 2 if topo and dashed else 1
        gap = 4 if topo and dashed else 5
        line_jobs.append((feature.get("geometry", {}), casing, fill, casing_width, fill_width, dashed, dash, gap))

    for geometry, casing, _fill, casing_width, _fill_width, dashed, dash, gap in line_jobs:
        draw_geometry_lines(draw, geometry, casing, casing_width, dashed=dashed, dash=dash, gap=gap)
    for geometry, _casing, fill, _casing_width, fill_width, dashed, dash, gap in line_jobs:
        if fill and fill_width > 0:
            draw_geometry_lines(draw, geometry, fill, fill_width, dashed=dashed, dash=dash, gap=gap)


def draw_geometry_lines(
    draw, geometry: dict, color: str, width: int,
    dashed: bool = False, dash: int = 1, gap: int = 5,
) -> None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if geometry_type == "LineString":
        draw_line(draw, coordinates, color, width, dashed=dashed, dash=dash, gap=gap)
    elif geometry_type == "MultiLineString":
        for line in coordinates:
            draw_line(draw, line, color, width, dashed=dashed, dash=dash, gap=gap)
    elif geometry_type == "Polygon":
        for ring in coordinates:
            draw_line(draw, ring, color, width, dashed=dashed, dash=dash, gap=gap)
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon:
                draw_line(draw, ring, color, width, dashed=dashed, dash=dash, gap=gap)


def draw_line(draw, points: list, color: str, width: int, dashed: bool = False, dash: int = 1, gap: int = 5) -> None:
    scaled = [scale_point(point) for point in points]
    if len(scaled) >= 2:
        if dashed:
            draw_dashed_line(draw, scaled, color, width, dash=dash, gap=gap)
        else:
            draw.line(scaled, fill=color, width=width, joint="curve")


def draw_dashed_line(draw, points: list[tuple[int, int]], color: str, width: int, dash: int = 1, gap: int = 5) -> None:
    for start, end in zip(points, points[1:]):
        x1, y1 = start
        x2, y2 = end
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length <= 0:
            continue
        distance = 0.0
        while distance < length:
            segment_end = min(distance + dash, length)
            sx = x1 + dx * (distance / length)
            sy = y1 + dy * (distance / length)
            ex = x1 + dx * (segment_end / length)
            ey = y1 + dy * (segment_end / length)
            draw.line([(sx, sy), (ex, ey)], fill=color, width=width)
            distance += dash + gap


def draw_labels(draw, data: dict, z: int, font) -> None:
    if z < 4:
        return
    max_labels = 18 if z < 6 else 14 if z < 10 else 24
    labels_drawn = 0
    candidates = []
    seen = set()
    for feature in data.get("place", {}).get("features", []):
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        point = representative_point(geometry)
        name = label_text(properties)
        label_class = properties.get("class", "")
        if not point or not name:
            continue
        key = (label_class, name)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((label_priority(properties, z), properties.get("rank", 99), name, point, label_class))

    for _priority, _rank, name, point, label_class in sorted(candidates):
        if labels_drawn >= max_labels:
            return
        x, y = scale_point(point)
        if x < -80 or x > 256 or y < -20 or y > 256:
            continue
        draw_readable_text(draw, (x, y), name, font, fill="#111111", stroke_width=2)
        labels_drawn += 1

    for feature in data.get("water_name", {}).get("features", []):
        if labels_drawn >= max_labels:
            return
        geometry = feature.get("geometry", {})
        point = representative_point(geometry)
        name = label_text(feature.get("properties", {}))
        if not point or not name:
            continue
        x, y = scale_point(point)
        if x < -80 or x > 256 or y < -20 or y > 256:
            continue
        draw_readable_text(draw, (x, y), name, font, fill="#111111", stroke_width=2)
        labels_drawn += 1


def label_priority(properties: dict, z: int) -> int:
    label_class = properties.get("class", "")
    if z <= 6:
        return {
            "country": 0, "state": 1, "aboriginal_lands": 2,
            "city": 3, "town": 4, "village": 5,
        }.get(label_class, 6)
    return {
        "city": 0, "town": 1, "state": 2, "village": 3, "country": 4,
    }.get(label_class, 5)


def draw_pois(draw, data: dict, z: int, font) -> None:
    if z < 13:
        return
    labels_drawn = 0
    for feature in data.get("poi", {}).get("features", []):
        if labels_drawn >= 18:
            return
        geometry = feature.get("geometry", {})
        point = representative_point(geometry)
        if not point:
            continue
        name = label_text(feature.get("properties", {}))
        if not name:
            continue
        x, y = scale_point(point)
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill="#111111", outline="#ffffff")
        draw_readable_text(draw, (x + 4, y - 5), name, font, fill="#111111", stroke_width=2)
        labels_drawn += 1


def _geometry_angle(geometry: dict, frac: float = 0.5) -> float:
    """Return the angle in degrees of a line geometry at the given fractional position. Range [-90, 90]."""
    geo_type = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if geo_type == "LineString" and len(coords) >= 2:
        pts = coords
    elif geo_type == "MultiLineString" and coords and len(coords[0]) >= 2:
        pts = coords[0]
    else:
        return 0.0
    mid = int(round(frac * (len(pts) - 1)))
    mid = max(0, min(mid, len(pts) - 1))
    p1 = pts[max(0, mid - 1)]
    p2 = pts[min(len(pts) - 1, mid + 1)]
    x1, y1 = scale_point(p1)
    x2, y2 = scale_point(p2)
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return 0.0
    angle = math.degrees(math.atan2(dy, dx))
    # Normalise to [-90, 90] so text is never rendered upside-down
    if angle > 90:
        angle -= 180
    elif angle < -90:
        angle += 180
    return angle


def draw_transportation_names(image, draw, data: dict, z: int, font) -> None:
    """Draw named trail/path labels rotated along the trail direction (z == 16 only)."""
    if z < 15:
        return
    from PIL import Image, ImageDraw

    path_classes = {"path", "track", "footway", "cycleway", "bridleway", "steps"}
    # All placed label centers — used to prevent visual overlap between different trails
    placed_all: list[tuple[int, int]] = []
    overlap_spacing = 50  # minimum px to avoid drawing two labels on top of each other
    # Minimum px between repeated labels of the same trail
    repeat_spacing = 130 if z >= 16 else 100

    # Sample many evenly-spaced positions so long trails get multiple repeats
    candidate_fracs = [i / 20 for i in range(1, 20)]  # 0.05, 0.10, … 0.95

    for feature in data.get("transportation_name", {}).get("features", []):
        properties = feature.get("properties", {})
        if properties.get("class", "") not in path_classes:
            continue
        name = label_text(properties)
        if not name:
            continue
        geometry = feature.get("geometry", {})

        try:
            bbox = font.getbbox(name)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        except AttributeError:
            text_w, text_h = len(name) * 6, 10

        pad = 4
        placed_this_trail: list[tuple[int, int]] = []

        for frac in candidate_fracs:
            pt = _line_point_at(geometry, frac)
            if pt is None:
                continue
            cx, cy = scale_point(pt)
            if not (0 <= cx <= 256 and 0 <= cy <= 256):
                continue
            # Skip sharp bends
            angle = _geometry_angle(geometry, frac)
            angle_before = _geometry_angle(geometry, max(0.0, frac - 0.15))
            angle_after = _geometry_angle(geometry, min(1.0, frac + 0.15))
            bend = abs(angle_after - angle_before)
            if bend > 180:
                bend = 360 - bend
            if bend > 30:
                continue
            # Don't repeat same trail too close
            if any(abs(cx - ex) + abs(cy - ey) < repeat_spacing for ex, ey in placed_this_trail):
                continue
            # Don't overlap any other trail's label
            if any(abs(cx - ex) + abs(cy - ey) < overlap_spacing for ex, ey in placed_all):
                continue
            scratch = Image.new("RGBA", (text_w + pad * 2, text_h + pad * 2), (0, 0, 0, 0))
            sd = ImageDraw.Draw(scratch)
            for ddx in (-1, 0, 1):
                for ddy in (-1, 0, 1):
                    if ddx or ddy:
                        sd.text((pad + ddx, pad + ddy), name, font=font, fill=(255, 255, 255, 220))
            sd.text((pad, pad), name, font=font, fill=(17, 17, 17, 255))
            rotated = scratch.rotate(-angle, expand=True, resample=Image.BICUBIC)
            rw, rh = rotated.size
            px_ = cx - rw // 2
            py_ = cy - rh // 2
            if px_ < 0 or py_ < 0 or px_ + rw > 256 or py_ + rh > 256:
                continue
            image.paste(rotated, (px_, py_), rotated)
            placed_this_trail.append((cx, cy))
            placed_all.append((cx, cy))


def load_label_font(z: int, small: bool = False):
    from PIL import ImageFont

    size = 10 if small else 11
    if z >= 12:
        size += 1
    if z >= 14:
        size += 1
    if small and z < 16:
        size -= 2
    for font_name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_readable_text(draw, xy: tuple[int, int], text: str, font, fill: str, stroke_width: int) -> None:
    try:
        draw.text(xy, text, fill=fill, font=font, stroke_width=stroke_width, stroke_fill="#ffffff")
    except TypeError:
        x, y = xy
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx or dy:
                    draw.text((x + dx, y + dy), text, fill="#ffffff", font=font)
        draw.text(xy, text, fill=fill, font=font)


def _line_point_at(geometry: dict, frac: float) -> list[float] | None:
    """Return the point at fractional position along a line geometry."""
    geo_type = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if geo_type == "LineString" and coords:
        pts = coords
    elif geo_type == "MultiLineString" and coords and coords[0]:
        pts = coords[0]
    else:
        return None
    idx = int(round(frac * (len(pts) - 1)))
    return pts[max(0, min(idx, len(pts) - 1))]


def representative_point(geometry: dict) -> list[float] | None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if geometry_type == "Point":
        return coordinates
    if geometry_type == "LineString" and coordinates:
        return coordinates[len(coordinates) // 2]
    if geometry_type == "MultiLineString" and coordinates and coordinates[0]:
        line = coordinates[0]
        return line[len(line) // 2]
    return None


def label_text(properties: dict) -> str:
    text = properties.get("name:en") or properties.get("name_int") or properties.get("name")
    return str(text)[:28] if text else ""


def scale_point(point: list[float] | tuple[float, float]) -> tuple[int, int]:
    x = int(round(float(point[0]) / VECTOR_EXTENT * 256))
    y = int(round(float(point[1]) / VECTOR_EXTENT * 256))
    return x, y


def optimize_tile(
    source: Path, destination: Path,
    mode: str, colors: int, brightness: float, contrast: float, threshold: int,
) -> None:
    if mode == "original" and brightness == 1.0 and contrast == 1.0:
        source.replace(destination)
        return
    from PIL import Image, ImageEnhance

    with Image.open(source) as image:
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image).convert("RGB")
        if brightness != 1.0:
            image = ImageEnhance.Brightness(image).enhance(brightness)
        if contrast != 1.0:
            image = ImageEnhance.Contrast(image).enhance(contrast)
        if mode == "palette":
            converted = image.quantize(colors=max(2, min(colors, 256)))
        elif mode == "grayscale":
            converted = image.convert("L")
        elif mode == "mono":
            converted = image.convert("L").point(lambda pixel: 255 if pixel >= threshold else 0, mode="1")
        else:
            converted = image
        destination.parent.mkdir(parents=True, exist_ok=True)
        converted.save(destination, format="PNG", optimize=True)
    source.unlink(missing_ok=True)


def make_zip(output_root: Path) -> Path:
    archive_base = output_root.with_suffix("")
    zip_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=output_root))
    return zip_path


def write_manifest(output_root: Path, job: dict, bbox: BBox, tiles: list[Tile]) -> None:
    style = job.get("style", DEFAULT_STYLE)
    layout = job.get("layout", "inkhud-dev")
    source = job.get("source", "openfreemap-vector")
    url_template = job.get("urlTemplate") or job.get("url_template")
    mode = job.get("mode", "grayscale")
    colors = int(job.get("colors", 256))
    brightness = float(job.get("brightness", DEFAULT_BRIGHTNESS))
    contrast = float(job.get("contrast", DEFAULT_CONTRAST))
    threshold = int(job.get("threshold", DEFAULT_THRESHOLD))
    elements_d = job.get("elements", {})
    include_elements = elements_d.get("include") if isinstance(elements_d, dict) else list(DEFAULT_INCLUDE_ELEMENTS)
    zooms = sorted({t.z for t in tiles})

    layout_path = {
        "inkhud-dev": f"/tiles/{style}",
        "style-root": f"/{style}",
        "single-map": "/map",
        "meshtastic-sd": f"/maps/{style}",
    }.get(layout, f"/tiles/{style}")

    attribution = dict(DEFAULT_ATTRIBUTION)
    if not is_topo_style(style):
        attribution.pop("terrain", None)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "layout": layout,
        "layout_path": layout_path,
        "style": style,
        "bbox": {"west": bbox.west, "south": bbox.south, "east": bbox.east, "north": bbox.north},
        "zooms": zooms,
        "tile_count": len(tiles),
        "source": source,
        "url_template": url_template,
        "mode": mode,
        "colors": colors if mode == "palette" else None,
        "brightness": brightness,
        "contrast": contrast,
        "threshold": threshold if mode == "mono" else None,
        "topography": is_topo_style(style),
        "elements": {
            "include": include_elements,
            "exclude": [e for e in MAP_ELEMENTS if e not in (include_elements or [])],
        },
        "attribution": attribution,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _write_attribution_file(output_root, source, url_template, is_topo_style(style))


def _write_attribution_file(output_root: Path, source: str, url_template: str | None, topo: bool) -> None:
    terrain_section = ""
    if topo:
        terrain_section = """
Terrain data:
  (c) Mapzen terrain tiles, if using topo style.
  Terrain Tiles were accessed from https://registry.opendata.aws/terrain-tiles/.
  See source data attribution: https://github.com/tilezen/joerd/blob/master/docs/attribution.md
"""
    text = f"""E-ink Map Tiles export attribution

Map data:
  (c) OpenStreetMap contributors
  OpenStreetMap data is available under the Open Database License (ODbL) 1.0.
  https://www.openstreetmap.org/copyright
  https://opendatacommons.org/licenses/odbl/1-0/

OpenMapTiles schema/data:
  (c) OpenMapTiles, if using OpenMapTiles-derived schema or data.
  https://openmaptiles.org/
{terrain_section}
Export source:
  source: {source}
  url_template: {url_template}

Keep this file and manifest.json with the exported tiles. Additional attribution may be required by
your tile source, local renderer, or downstream use case.
"""
    (output_root / "ATTRIBUTION.txt").write_text(text, encoding="utf-8")


def inkhud_quantize(rgb_image, contrast: float, brightness: float):
    """InkHUD 3-level quantize WITHOUT Bayer dither. Returns grayscale image with values {0, 128, 255}.
    Used for tile export so firmware can downsample in grayscale then dither on-device."""
    import numpy as np
    from PIL import Image as _Image, ImageEnhance, ImageFilter

    arr_rgb = np.array(rgb_image.convert("RGB"), dtype=np.int16)
    water_mask = (arr_rgb[:, :, 2] - arr_rgb[:, :, 0]) > 25
    gray = rgb_image.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(contrast)
    gray = ImageEnhance.Brightness(gray).enhance(brightness)
    sharp = gray.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=2))
    arr = np.array(sharp, dtype=np.float32)
    quantized = np.where(arr <= 175, 0, np.where(arr <= 215, 128, 255)).astype(np.uint8)
    quantized[water_mask] = 0
    return _Image.fromarray(quantized, mode="L")


def inkhud_process(rgb_image, contrast: float, brightness: float):
    """InkHUD 1-bit pipeline with Bayer dither. Used for preview only."""
    import numpy as np
    from PIL import Image as _Image, ImageEnhance, ImageFilter

    arr_rgb = np.array(rgb_image.convert("RGB"), dtype=np.int16)
    water_mask = (arr_rgb[:, :, 2] - arr_rgb[:, :, 0]) > 25
    gray = rgb_image.convert("L")
    gray = ImageEnhance.Contrast(gray).enhance(contrast)
    gray = ImageEnhance.Brightness(gray).enhance(brightness)
    sharp = gray.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=2))

    bayer = np.array([
        [ 0,  8,  2, 10],
        [12,  4, 14,  6],
        [ 3, 11,  1,  9],
        [15,  7, 13,  5],
    ], dtype=np.float32) * (255.0 / 16.0)
    arr = np.array(sharp, dtype=np.float32)
    quantized = np.where(arr <= 175, 0.0, np.where(arr <= 215, 170.0, 255.0))
    h, w = quantized.shape
    pattern = np.tile(bayer, (h // 4 + 1, w // 4 + 1))[:h, :w]
    dithered = np.where(quantized < pattern, 0, 255).astype(np.uint8)
    result = np.where(quantized >= 255, 255, np.where(quantized <= 0, 0, dithered)).astype(np.uint8)
    result[water_mask] = 0
    return _Image.fromarray(result, mode="L")


def download_tiles(
    job: dict,
    output_dir: Path,
    cancel_event=None,
    rate_limit: float = 1.0,
    overwrite: bool = False,
    zip_output: bool = False,
    print_fn=print,
) -> int:
    """Download and render tiles from a job dict to output_dir. Returns 0 on success, 2 on cancel."""
    bbox_d = job["bbox"]
    bbox = BBox(
        west=float(bbox_d["west"]), south=float(bbox_d["south"]),
        east=float(bbox_d["east"]), north=float(bbox_d["north"]),
    )
    zooms = [int(z) for z in job["zooms"]]
    style = job.get("style", DEFAULT_STYLE)
    source = job.get("source", "openfreemap-vector")
    layout = job.get("layout", "inkhud-dev")
    mode = job.get("mode", "grayscale")
    brightness = float(job.get("brightness", DEFAULT_BRIGHTNESS))
    contrast = float(job.get("contrast", DEFAULT_CONTRAST))
    threshold = int(job.get("threshold", DEFAULT_THRESHOLD))
    url_template = job.get("urlTemplate") or job.get("url_template") or DEFAULT_URL_TEMPLATE
    colors = int(job.get("colors", 256))
    elements_d = job.get("elements", {})
    include_elements = elements_d.get("include") if isinstance(elements_d, dict) else None
    if include_elements is None:
        include_elements = list(DEFAULT_TOPO_ELEMENTS if is_topo_style(style) else DEFAULT_INCLUDE_ELEMENTS)

    tiles = tiles_for_bbox(bbox, zooms)
    print_fn(f"Area: west={bbox.west:.6f}, south={bbox.south:.6f}, east={bbox.east:.6f}, north={bbox.north:.6f}")
    print_fn(f"Tiles: {len(tiles)} across zooms {','.join(map(str, zooms))}")

    completed = 0
    for tile in tiles:
        if cancel_event and cancel_event.is_set():
            print_fn("Export cancelled.")
            return 2
        destination = tile_output_path(output_dir, style, layout, tile)
        if destination.exists() and not overwrite:
            completed += 1
            continue
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
            temp_path = Path(temp_file.name)
        if source == "openfreemap-vector":
            render_openfreemap_tile(tile, temp_path, DEFAULT_USER_AGENT, 30.0, 3, include_elements, style=style)
        else:
            if not url_template:
                raise RuntimeError("url_template is required for XYZ source")
            fetch_tile(tile_url(url_template, tile), temp_path, DEFAULT_USER_AGENT, 30.0, 3)
        optimize_tile(temp_path, destination, mode, colors, brightness, contrast, threshold)
        completed += 1
        print_fn(f"[{completed}/{len(tiles)}] {destination}")
        if rate_limit and completed < len(tiles):
            time.sleep(rate_limit)

    write_manifest(output_dir, job, bbox, tiles)
    print_fn(f"Wrote manifest: {output_dir / 'manifest.json'}")
    if zip_output:
        zip_path = make_zip(output_dir)
        print_fn(f"Wrote ZIP: {zip_path}")
    return 0

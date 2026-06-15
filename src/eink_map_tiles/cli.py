from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_URL_TEMPLATE = None
DEFAULT_USER_AGENT = "eink-map-tiles/0.1 (+https://github.com/HarukiToreda/E-ink-Map-Tiles)"
MAX_MERCATOR_LAT = 85.05112878
MAP_ELEMENTS = ("land", "water", "roads", "highways", "paths", "buildings", "boundaries", "labels", "pois", "transit")
DEFAULT_ATTRIBUTION = {
    "map_data": "\u00a9 OpenStreetMap contributors",
    "map_data_license": "Open Database License (ODbL) 1.0",
    "openmaptiles": "\u00a9 OpenMapTiles, if using OpenMapTiles schema/data",
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
                raise argparse.ArgumentTypeError(f"Invalid zoom range: {part}")
            zooms.update(range(start, end + 1))
        else:
            zooms.add(int(part))

    if not zooms:
        raise argparse.ArgumentTypeError("At least one zoom level is required")
    if min(zooms) < 0 or max(zooms) > 20:
        raise argparse.ArgumentTypeError("Zoom levels must be between 0 and 20")
    return sorted(zooms)


def parse_bbox(value: str) -> BBox:
    try:
        west, south, east, north = [float(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use west,south,east,north") from exc

    if not -180 <= west <= 180 or not -180 <= east <= 180:
        raise argparse.ArgumentTypeError("Longitude values must be between -180 and 180")
    if not -90 <= south <= 90 or not -90 <= north <= 90:
        raise argparse.ArgumentTypeError("Latitude values must be between -90 and 90")
    if south >= north:
        raise argparse.ArgumentTypeError("south must be less than north")
    return BBox(west=west, south=south, east=east, north=north)


def parse_elements(value: str) -> list[str]:
    selected = []
    valid = set(MAP_ELEMENTS)
    for item in value.split(","):
        element = item.strip().lower()
        if not element:
            continue
        if element not in valid:
            raise argparse.ArgumentTypeError(f"Unknown map element: {element}")
        selected.append(element)
    return selected


def bbox_from_center(lat: float, lon: float, radius_km: float) -> BBox:
    if not -90 <= lat <= 90:
        raise argparse.ArgumentTypeError("--center-lat must be between -90 and 90")
    if not -180 <= lon <= 180:
        raise argparse.ArgumentTypeError("--center-lon must be between -180 and 180")
    if radius_km <= 0:
        raise argparse.ArgumentTypeError("--radius-km must be greater than zero")

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
    lon_spans = [(bbox.west, bbox.east)]
    if bbox.west > bbox.east:
        lon_spans = [(bbox.west, 180.0), (-180.0, bbox.east)]

    for z in zooms:
        seen: set[tuple[int, int, int]] = set()
        for west, east in lon_spans:
            x_min, y_min = lonlat_to_tile(west, bbox.north, z)
            x_max, y_max = lonlat_to_tile(east, bbox.south, z)
            for x in range(min(x_min, x_max), max(x_min, x_max) + 1):
                for y in range(min(y_min, y_max), max(y_min, y_max) + 1):
                    key = (z, x, y)
                    if key not in seen:
                        seen.add(key)
                        tiles.append(Tile(z=z, x=x, y=y))
    return tiles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and optimize XYZ map tiles for e-ink firmware experiments.",
    )
    parser.add_argument("--job", type=Path, help="Read settings from a JSON job exported by the picker")
    area = parser.add_mutually_exclusive_group()
    area.add_argument("--bbox", type=parse_bbox, help="Area as west,south,east,north")
    area.add_argument("--center-lat", type=float, help="Center latitude for a radius download")
    parser.add_argument("--center-lon", type=float, help="Center longitude for a radius download")
    parser.add_argument("--radius-km", type=float, help="Radius in kilometers when using --center-lat")
    parser.add_argument("--zooms", type=parse_zooms, help="Zooms like 6-10 or 6,8,12")
    parser.add_argument("--style", default="osm", help="Style folder name")
    parser.add_argument(
        "--url-template",
        default=DEFAULT_URL_TEMPLATE,
        help="XYZ URL with {z}, {x}, {y}. Prefer a local/self-hosted renderer for bulk downloads.",
    )
    parser.add_argument("--output", type=Path, default=Path("build/inkhud-tiles"), help="Output root folder")
    parser.add_argument(
        "--layout",
        choices=["inkhud-dev", "style-root", "single-map", "meshtastic-sd"],
        default="inkhud-dev",
        help="Output layout. Default writes /tiles/{style}/z/x/y.png.",
    )
    parser.add_argument("--single-style", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--zip", action="store_true", help="Create a ZIP next to the output folder")
    parser.add_argument("--dry-run", action="store_true", help="Only print tile count and sample paths")
    parser.add_argument("--overwrite", action="store_true", help="Re-download existing tiles")
    parser.add_argument("--rate-limit", type=float, default=1.0, help="Seconds between tile requests")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Retry count for failed requests")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="HTTP User-Agent")
    parser.add_argument(
        "--mode",
        choices=["palette", "grayscale", "mono", "original"],
        default="grayscale",
        help="Image conversion mode. grayscale is the default for e-ink experiments.",
    )
    parser.add_argument("--colors", type=int, default=256, help="Palette colors for --mode palette")
    parser.add_argument("--brightness", type=float, default=1.0, help="Brightness multiplier")
    parser.add_argument("--contrast", type=float, default=1.0, help="Contrast multiplier")
    parser.add_argument("--threshold", type=int, default=201, help="Black/white cutoff for --mode mono")
    parser.add_argument(
        "--include-elements",
        type=parse_elements,
        default=list(MAP_ELEMENTS),
        help="Comma-separated vector-style element categories to include in the manifest.",
    )
    return parser


def apply_job_file(args: argparse.Namespace) -> None:
    if not args.job:
        if not args.bbox and args.center_lat is None:
            raise SystemExit("Provide --bbox, --center-lat with --center-lon and --radius-km, or --job")
        if not args.zooms:
            raise SystemExit("Provide --zooms or --job")
        return

    job = json.loads(args.job.read_text(encoding="utf-8"))
    bbox = job.get("bbox")
    if not isinstance(bbox, dict):
        raise SystemExit("Job file must include a bbox object")

    args.bbox = BBox(
        west=float(bbox["west"]),
        south=float(bbox["south"]),
        east=float(bbox["east"]),
        north=float(bbox["north"]),
    )
    args.center_lat = None
    args.center_lon = None
    args.radius_km = None
    args.zooms = [int(z) for z in job.get("zooms", [])]
    if not args.zooms:
        raise SystemExit("Job file must include zooms")

    args.style = job.get("style") or args.style
    args.mode = job.get("mode") or args.mode
    args.brightness = float(job.get("brightness", args.brightness))
    args.contrast = float(job.get("contrast", args.contrast))
    args.threshold = int(job.get("threshold", args.threshold))
    job_elements = job.get("elements")
    if isinstance(job_elements, dict):
        args.include_elements = [element for element in job_elements.get("include", []) if element in MAP_ELEMENTS]
    args.layout = job.get("layout") or args.layout
    args.url_template = job.get("urlTemplate") or job.get("url_template") or args.url_template


def args_to_bbox(args: argparse.Namespace) -> BBox:
    if args.bbox:
        return args.bbox
    if args.center_lon is None or args.radius_km is None:
        raise SystemExit("--center-lon and --radius-km are required with --center-lat")
    return bbox_from_center(args.center_lat, args.center_lon, args.radius_km)


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


def optimize_tile(
    source: Path,
    destination: Path,
    mode: str,
    colors: int,
    brightness: float,
    contrast: float,
    threshold: int,
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


def write_manifest(output_root: Path, args: argparse.Namespace, bbox: BBox, tiles: list[Tile]) -> None:
    layout_path = {
        "inkhud-dev": f"/tiles/{args.style}",
        "style-root": f"/{args.style}",
        "single-map": "/map",
        "meshtastic-sd": f"/maps/{args.style}",
    }[args.layout]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "layout": args.layout,
        "layout_path": layout_path,
        "style": args.style,
        "bbox": {
            "west": bbox.west,
            "south": bbox.south,
            "east": bbox.east,
            "north": bbox.north,
        },
        "zooms": args.zooms,
        "tile_count": len(tiles),
        "url_template": args.url_template,
        "mode": args.mode,
        "colors": args.colors if args.mode == "palette" else None,
        "brightness": args.brightness,
        "contrast": args.contrast,
        "threshold": args.threshold if args.mode == "mono" else None,
        "elements": {
            "include": args.include_elements,
            "exclude": [element for element in MAP_ELEMENTS if element not in args.include_elements],
        },
        "attribution": DEFAULT_ATTRIBUTION,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def make_zip(output_root: Path) -> Path:
    archive_base = output_root.with_suffix("")
    zip_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=output_root))
    return zip_path


def run(args: argparse.Namespace) -> int:
    bbox = args_to_bbox(args)
    tiles = tiles_for_bbox(bbox, args.zooms)
    print(f"Area: west={bbox.west:.6f}, south={bbox.south:.6f}, east={bbox.east:.6f}, north={bbox.north:.6f}")
    print(f"Tiles: {len(tiles)} across zooms {','.join(map(str, args.zooms))}")
    if tiles:
        sample = tile_output_path(args.output, args.style, args.layout, tiles[0])
        print(f"First output path: {sample}")

    if args.dry_run:
        return 0

    if not args.url_template:
        raise SystemExit("--url-template is required for downloads. Use a local/self-hosted tile renderer when creating bundles.")
    if args.colors < 2 or args.colors > 256:
        raise SystemExit("--colors must be between 2 and 256")
    if args.threshold < 0 or args.threshold > 255:
        raise SystemExit("--threshold must be between 0 and 255")
    if args.rate_limit < 0:
        raise SystemExit("--rate-limit cannot be negative")

    completed = 0
    for tile in tiles:
        destination = tile_output_path(args.output, args.style, args.layout, tile)
        if destination.exists() and not args.overwrite:
            completed += 1
            continue

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
            temp_path = Path(temp_file.name)
        fetch_tile(tile_url(args.url_template, tile), temp_path, args.user_agent, args.timeout, args.retries)
        optimize_tile(temp_path, destination, args.mode, args.colors, args.brightness, args.contrast, args.threshold)
        completed += 1
        print(f"[{completed}/{len(tiles)}] {destination}")
        if args.rate_limit and completed < len(tiles):
            time.sleep(args.rate_limit)

    write_manifest(args.output, args, bbox, tiles)
    print(f"Wrote manifest: {args.output / 'manifest.json'}")
    if args.zip:
        zip_path = make_zip(args.output)
        print(f"Wrote ZIP: {zip_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.single_style:
        args.layout = "single-map"
    apply_job_file(args)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

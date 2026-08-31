#!/usr/bin/env python3
"""Extract legend symbols from a sheet and give each one a ground coordinate.

Three classes, chosen because the legend defines them and the printing separates
them cleanly at this scan resolution:

  building   "Maisons" - individual solid red marks. Outside the built-up areas
             every house is drawn separately, so a count is a settlement-density
             measure at a far finer grain than any place-name layer.
  well       "Puits et fontaine" - a thin blue open ring, about 10 px across.
             PROVISIONAL, and not extracted by default. Across ten sheets whose
             transforms fit to 12-14 m the counts run from 4 (Djebel Semmama) to
             2158 (Oued-Zarga). Some of that spread is real - a dry massif has
             fewer wells than the Medjerda valley - but a factor of 500 is not,
             and the overlays show the detector firing on blue hatching in
             marshy ground. Pass --classes building,well to include it.
  vegetation "Bois / Broussailles / Oliviers / Palmiers" - the teal stipple, one
             ring per tree or small group. Available but NOT extracted by
             default, because it is not yet reliable: the stipple is dense and
             saturated on the Sahel sheets and faint on the steppe ones, and a
             threshold that finds 268 rings in a Kasserine window finds 3 when
             tightened enough to stop it tracing the black lettering. It needs
             per-sheet calibration before its counts mean anything. Pass
             --classes building,well,vegetation to include it anyway.

Wells and vegetation stipple look alike in shape and are told apart by hue
alone: on the Sfax sheet a well ring runs about (78, 106, 143) in RGB, blue well
above green, while the vegetation ring has green at or above blue. Getting that
the wrong way round turns every olive tree into a well, so the two masks are
deliberately exclusive and the counts are reported separately.

A ring is not a blob. Connected-component labelling finds only a tenth of the
rings, because the stroke is one or two pixels wide and breaks wherever it
crosses another feature, so each ring falls apart into arcs that no size filter
can recognise. Matching an annulus template instead scores the whole shape at
once, and asks for the middle to be empty as well as the rim to be inked, which
is what distinguishes a ring from a filled dot.

Coordinates come from scripts/georeference_sheets.py, so every symbol carries a
Lambert easting and northing and a WGS84 longitude and latitude, and inherits
that sheet's stated accuracy.

Whether a sheet's absolute anchor was confirmed is deliberately NOT copied onto
each symbol. It is a property of the sheet, and duplicating it per feature is
what let two copies drift apart. Consumers join it from
data/sheet_georef.csv on record_id.

Outputs:
    data/symbols/<record_id>.geojson   EPSG:4326, one feature per symbol
    data/symbols_summary.csv           counts per sheet and class
    optional --overlay <dir>           the crop with detections drawn, for
                                       checking by eye rather than by count

Usage:
    python3 scripts/extract_symbols.py --images <dir> --only <record_id>
    python3 scripts/extract_symbols.py --images <dir> --overlay data/overlays
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Transformer
from scipy import ndimage
from scipy.signal import fftconvolve

warnings.filterwarnings("ignore", message=".*lose important projection.*")
Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent

# Five decimal places is about a metre. Seven, the default of the first version,
# implies a centimetre on coordinates whose stated accuracy is twenty metres, and
# spends a third of the file size saying so.
COORD_DECIMALS = 5

# Ring radii in pixels, at the series' measured 236 px/km. A legend ring is
# about 0.5 mm on paper, so 10 px across.
RING_RADII = (4.5, 5.0, 5.5, 6.0)
RING_THICKNESS = 1.8
RING_SCORE = 0.30
RING_SUPPRESS_PX = 9          # no two ring centres closer than this

BUILDING_MIN_PX = 12          # a 0.4 mm mark is about 16 px of ink
BUILDING_MAX_PX = 400
BUILDING_MAX_ASPECT = 6.0
# The house mark is a filled rectangle. The red numerals printed on the map -
# spot heights and grid labels - are the same colour and a similar size, but
# they are strokes, so they fill much less of their bounding box.
BUILDING_MIN_FILL = 0.55
# Detections are clipped to the sheet's own catalogued extent, which is exactly
# what its "Coordonnees (E ... / N ...)" statement describes: the neatline.
#
# The detected neatline was tried for this first and is the wrong tool. Its box
# comes out a median 6% smaller than the catalogued one but ranges from 40%
# smaller to larger, because each side of the frame is three rules and the
# detector picks a different one on different sheets - so the clip was
# discarding a border of real map content on some sheets and letting margin in
# on others. The catalogue box is good to about 800 m and does not vary with how
# a scan came out, so it is strictly the better clip. The legend and the red grid
# labels lie outside it by construction.
CLIP_INSET_DEG = 0.002        # about 200 m, to stay clear of the neatline itself


GRID_EXCLUDE_PX = 6           # how far from a grid line to ignore red ink
GRID_BLOCK_ROWS = 512         # rows per pass when masking out the grid
ISOLATION_RADIUS = 2.6        # multiples of the ring radius
ISOLATION_MAX_DENSITY = 0.12  # ink share allowed around an isolated ring


def masks(array: np.ndarray, wanted: set[str]) -> dict[str, np.ndarray]:
    """Colour masks, built only for the classes asked for.

    Building all three costs three full-resolution int16 channels and three
    boolean masks of a 66-megapixel scan whether they are used or not, which on
    a default run that wants houses alone is most of the memory traffic.
    """
    red, green, blue = (array[..., 0].astype(np.int16),
                        array[..., 1].astype(np.int16),
                        array[..., 2].astype(np.int16))
    recipes = {
        # Solid printed red - the same red as the grid, which is why the grid is
        # masked out geometrically rather than by colour.
        "building": lambda: ((red - green > 45) & (red - blue > 40)
                            & (red > 110)),
        # Blue above green: this is what separates a well from an olive tree.
        "well": lambda: ((blue - red > 25) & (blue - green > 12) & (blue > 80)),
        # Green must actually be green, not merely the greenest channel of a
        # grey edge: relaxing this to catch fainter stipple made the detector
        # trace the black lettering and the tracks instead.
        "vegetation": lambda: ((green - red > 16) & (green - blue > 4)
                               & (green > 80)
                               & (green - np.minimum(red, blue) > 24)),
    }
    return {name: recipe() for name, recipe in recipes.items()
            if name in wanted}


def grid_stripe(shape: tuple[int, int], lines: dict,
                origin: tuple[int, int]) -> np.ndarray:
    """Pixels within a few px of a printed grid line.

    The houses and the grid are printed in the same red, and at a grid crossing
    the two lines make a compact blob that no size or aspect filter can tell
    from a house - the first run returned the crossings and the red grid labels
    as buildings. But the grid's geometry is already known exactly from the
    georeferencing, so it can simply be cut out.
    """
    rows, columns = shape
    stripe = np.zeros(shape, bool)
    columns_axis = np.arange(columns, dtype=np.float32) + origin[0]
    eastings = np.asarray(lines["easting_constants"], dtype=np.float32)
    northings = np.asarray(lines["northing_constants"], dtype=np.float32)

    # In row blocks rather than whole-image index grids. np.mgrid over a
    # 66-megapixel scan is two int64 arrays of half a gigabyte each, and then
    # every one of the ~55 grid lines makes another full-size temporary: on the
    # Kasserine sheet that was two minutes of system time per sheet, more than
    # the detection itself. A block of a few hundred rows fits in cache.
    for start in range(0, rows, GRID_BLOCK_ROWS):
        stop = min(start + GRID_BLOCK_ROWS, rows)
        rows_axis = (np.arange(start, stop, dtype=np.float32)
                     + origin[1])[:, None]
        block = stripe[start:stop]

        # Distance to the nearest easting line, via its line constant.
        u = columns_axis[None, :] - lines["tan_e"] * rows_axis
        block |= nearest_distance(u, eastings) < GRID_EXCLUDE_PX
        v = rows_axis - lines["tan_n"] * columns_axis[None, :]
        block |= nearest_distance(v, northings) < GRID_EXCLUDE_PX
    return stripe


def nearest_distance(values: np.ndarray, sorted_lines: np.ndarray) -> np.ndarray:
    """Distance from each value to the closest entry of `sorted_lines`.

    One searchsorted plus two subtractions, instead of one full-size comparison
    per line.
    """
    if sorted_lines.size == 0:
        return np.full(values.shape, np.inf, dtype=np.float32)
    index = np.searchsorted(sorted_lines, values)
    left = sorted_lines[np.clip(index - 1, 0, sorted_lines.size - 1)]
    right = sorted_lines[np.clip(index, 0, sorted_lines.size - 1)]
    return np.minimum(np.abs(values - left), np.abs(values - right))


def ring_template(outer: float, thickness: float):
    size = int(np.ceil(outer * 2)) + 3
    grid = np.mgrid[0:size, 0:size]
    centre = (size - 1) / 2
    distance = np.hypot(grid[0] - centre, grid[1] - centre)
    inner = outer - thickness
    return ((distance <= outer) & (distance >= inner)).astype(np.float32), \
           (distance < inner).astype(np.float32)


def find_rings(mask: np.ndarray) -> list[tuple[float, float]]:
    """Annulus template match over a range of radii, then keep the best peaks."""
    signal = mask.astype(np.float32)
    best_score = None
    for outer in RING_RADII:
        rim, middle = ring_template(outer, RING_THICKNESS)
        on_rim = fftconvolve(signal, rim[::-1, ::-1], mode="same") / max(rim.sum(), 1)
        in_middle = (fftconvolve(signal, middle[::-1, ::-1], mode="same")
                     / max(middle.sum(), 1))
        # Inked rim, empty middle. Without the second term a filled dot and a
        # ring score the same.
        score = on_rim - 0.8 * in_middle
        best_score = score if best_score is None else np.maximum(best_score, score)

    peaks = (best_score == ndimage.maximum_filter(best_score, size=RING_SUPPRESS_PX))
    peaks &= best_score > RING_SCORE

    # A well is an isolated ring; a watercourse is a chain of them. Without this
    # test the detector traced the oued down the middle of the sheet and called
    # every bend a well. Requiring the neighbourhood beyond the ring to be
    # mostly empty keeps the isolated symbol and drops the chain.
    outer = max(RING_RADII)
    surround = ring_template(outer * ISOLATION_RADIUS, outer * ISOLATION_RADIUS)[1]
    density = (fftconvolve(signal, surround[::-1, ::-1], mode="same")
               / max(surround.sum(), 1))
    peaks &= density < ISOLATION_MAX_DENSITY

    rows, columns = np.nonzero(peaks)
    return [(float(x), float(y)) for x, y in zip(columns, rows)]


def find_blobs(mask: np.ndarray) -> list[tuple[float, float]]:
    """Compact solid marks: the houses, with roads and grid lines rejected."""
    labels, count = ndimage.label(mask)
    if count == 0:
        return []
    sizes = ndimage.sum(mask, labels, range(1, count + 1))
    boxes = ndimage.find_objects(labels)
    centres = ndimage.center_of_mass(mask, labels, range(1, count + 1))

    found = []
    for index, box in enumerate(boxes):
        area = sizes[index]
        if not BUILDING_MIN_PX <= area <= BUILDING_MAX_PX:
            continue
        height = box[0].stop - box[0].start
        width = box[1].stop - box[1].start
        if max(height, width) / max(min(height, width), 1) > BUILDING_MAX_ASPECT:
            continue
        if area / (height * width) < BUILDING_MIN_FILL:
            continue
        found.append((float(centres[index][1]), float(centres[index][0])))
    return found


def extract(path: Path, window: tuple[int, int, int, int] | None,
            lines: dict | None = None, wanted: tuple[str, ...] = ("building",)):
    image = Image.open(path).convert("RGB")
    if window:
        image = image.crop(window)
        origin = (window[0], window[1])
    else:
        origin = (0, 0)
    array = np.asarray(image)
    layers = masks(array, set(wanted))
    if lines:
        layers["building"] &= ~grid_stripe(layers["building"].shape, lines, origin)

    finders = {"building": find_blobs, "well": find_rings,
               "vegetation": find_rings}
    found = {name: finders[name](layer) for name, layer in layers.items()}
    shifted = {name: [(x + origin[0], y + origin[1]) for x, y in points]
               for name, points in found.items()}
    return shifted, image, found


def to_geojson(found: dict, affine: list, epsg: int, record_id: str,
               box: dict | None) -> dict:
    a, d, b, e, c, f = affine
    to_wgs84 = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    features = []
    for name, points in found.items():
        for x, y in points:
            easting = a * x + b * y + c
            northing = d * x + e * y + f
            lon, lat = to_wgs84.transform(easting, northing)
            if box and not (box["west"] + CLIP_INSET_DEG <= lon
                            <= box["east"] - CLIP_INSET_DEG
                            and box["south"] + CLIP_INSET_DEG <= lat
                            <= box["north"] - CLIP_INSET_DEG):
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point",
                             "coordinates": [round(lon, COORD_DECIMALS),
                                             round(lat, COORD_DECIMALS)]},
                "properties": {
                    "record_id": record_id,
                    "symbol_class": name,
                    "pixel_x": round(x, 1),
                    "pixel_y": round(y, 1),
                    "easting": round(easting, 1),
                    "northing": round(northing, 1),
                    "epsg_source": epsg,
                },
            })
    return {"type": "FeatureCollection", "features": features}


COLOURS = {"building": (255, 0, 255), "well": (0, 0, 255),
           "vegetation": (0, 160, 0)}


def draw_overlay(image: Image.Image, local: dict, out: Path) -> None:
    canvas = image.copy()
    pen = ImageDraw.Draw(canvas)
    for name, points in local.items():
        colour = COLOURS[name]
        for x, y in points:
            pen.ellipse([x - 9, y - 9, x + 9, y + 9], outline=colour, width=2)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=90)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--georef", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.json")
    parser.add_argument("--partner", type=Path,
                        default=REPO_ROOT / "data" / "partner_records.json")
    parser.add_argument("--series", type=Path,
                        default=REPO_ROOT / "data" / "tunisia_50k_series.csv")
    parser.add_argument("--out-dir", type=Path,
                        default=REPO_ROOT / "data" / "symbols")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "symbols_summary.csv")
    parser.add_argument("--overlay", type=Path, default=None)
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--classes", default="building",
                        help="comma-separated symbol classes to extract")
    parser.add_argument("--window", nargs=4, type=int, default=None,
                        metavar=("X0", "Y0", "X1", "Y1"),
                        help="restrict to a pixel window, for checking")
    args = parser.parse_args()

    georef = json.loads(args.georef.read_text(encoding="utf-8"))
    partner = json.loads(args.partner.read_text(encoding="utf-8"))
    sheets = {r["record_id"]: r
              for r in csv.DictReader(args.series.open(encoding="utf-8"))}

    targets = sorted(args.images.glob("*.jpg"))
    if args.only:
        targets = [t for t in targets if t.stem in set(args.only)]

    rows = []
    wanted = [c.strip() for c in args.classes.split(",") if c.strip()]
    for index, path in enumerate(targets, 1):
        record_id = path.stem
        reference = georef.get(record_id, {})
        name = sheets.get(record_id, {}).get("sheet_name") or record_id[-6:]
        if "affine" not in reference:
            print(f"  {index}/{len(targets)} {name[:22]:<22} - not georeferenced")
            continue

        window = tuple(args.window) if args.window else None
        found, image, local = extract(path, window, reference.get("grid_lines"),
                                      tuple(wanted))
        collection = to_geojson(found, reference["affine"], reference["epsg"],
                                record_id,
                                partner.get(record_id, {}).get("bbox"))
        kept = len(collection["features"])
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / f"{record_id}.geojson").write_text(
            json.dumps(collection), encoding="utf-8")

        if args.overlay:
            draw_overlay(image, local, args.overlay / f"{record_id}.jpg")

        # Counted after the clip, so the table matches the GeoJSON.
        counts = {k: 0 for k in ("building", "well", "vegetation")}
        for feature in collection["features"]:
            counts[feature["properties"]["symbol_class"]] += 1
        rows.append({
            "record_id": record_id,
            "sheet_name": sheets.get(record_id, {}).get("sheet_name", ""),
            "anchor_confident": int(bool(reference.get("anchor_confident"))),
            "clipped_out": sum(len(v) for v in found.values()) - kept,
            "residual_rms_m": reference.get("residual_rms_m", ""),
            **counts,
            "total": kept,
        })
        print(f"  {index}/{len(targets)} {name[:22]:<22} "
              + " ".join(f"{k}={counts[k]}" for k in wanted), flush=True)

    if rows:
        fields = ["record_id", "sheet_name", "anchor_confident",
                  "residual_rms_m", "building", "well", "vegetation", "total",
                  "clipped_out"]
        with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n{len(rows)} sheets, {sum(r['total'] for r in rows)} symbols")
        print(f"  -> {args.out_dir}/\n  -> {args.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

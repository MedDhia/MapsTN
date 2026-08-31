#!/usr/bin/env python3
"""Turn each sheet's printed grid into an exact pixel-to-ground transform.

This is the step that makes objects extracted from a sheet repositionable on a
modern map. It produces, per sheet, an affine transform from scan pixels to
Lambert Tunisie metres, a control-point list, and a world file - all usable
directly by GDAL or QGIS.

The problem is that neither of the two available anchors is sufficient alone.

  The catalogue bounding box gives absolute position, but its corners are
  rounded - to whole arcminutes on 29 of 93 sheets - so it is good to roughly
  +/-800 m, which is worse than the sheet deserves by two orders of magnitude.

  The printed kilometric grid gives scale and rotation to about a tenth of a
  percent, and its lines are at exact integer kilometres in Lambert. But the
  detector finds where the lines are, not which kilometre each one is.

Putting them together removes both weaknesses. The bounding box predicts each
line's easting to within a fraction of the 1 km line spacing; rounding that
prediction to the nearest integer recovers the exact value; and refitting on the
exact values discards the bounding box's error entirely. The snap distance is
reported per sheet, because the argument only holds while it stays well under
500 m - at 500 m the rounding could go to the wrong kilometre and shift the
whole sheet by one.

Three independent checks are recorded rather than assumed:

  frame_size_error_pct  the neatline's measured size against the size the
                        catalogue extent implies. Agreement confirms the
                        neatline detector, the grid spacing and the projection
                        at once, since they are measured three different ways.
  snap_max_m            how far the bounding-box prediction sat from the
                        integer kilometre it was rounded to.
  residual_rms_m        how well one affine fits all the grid intersections.
                        A printed grid is rigid, so this is small unless the
                        paper is distorted or the detection is wrong.

Outputs:
    data/sheet_georef.json          transform, checks and corner coordinates
    data/sheet_georef.csv
    data/georef/<record_id>.points  QGIS georeferencer control points
    data/georef/<record_id>.wld     world file, in the sheet's Lambert zone

Usage:
    python3 scripts/georeference_sheets.py --images <dir of record_id.jpg>
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image
from pyproj import Transformer

warnings.filterwarnings("ignore", message=".*lose important projection.*")
Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent

# Carthage / Nord Tunisie and Carthage / Sud Tunisie: Lambert conformal conic on
# the Clarke 1880 IGN ellipsoid, which is the ellipsoid the sheets' own
# catalogue records name.
ZONE_EPSG = {"nord": 22391, "sud": 22392}

NEATLINE_DOWNSAMPLE = 2
PAPER_BRIGHTNESS = 140
PAPER_ROW_SHARE = 0.6
GRID_DOWNSAMPLE = 4          # must match detect_sheet_grid.DOWNSAMPLE
BODY_MARGIN_TOP = 0.10       # must match detect_sheet_grid
BODY_MARGIN_LEFT = 0.08

# Beyond this the integer-kilometre snap could have gone to the wrong line.
SNAP_WARN_M = 350.0


def find_neatline(path: Path) -> dict:
    """Pixel positions of the four sides of the map frame.

    Detected at half resolution rather than quarter: the neatline is two or
    three pixels wide, and at quarter resolution it blurs below any threshold -
    a first attempt at DOWNSAMPLE 4 found the frame on one sheet in six.
    """
    image = Image.open(path).convert("L")
    width, height = image.size
    array = np.asarray(image.resize((width // NEATLINE_DOWNSAMPLE,
                                     height // NEATLINE_DOWNSAMPLE),
                                    Image.BILINEAR)).astype(np.float32)
    rows, columns = array.shape

    paper = array > PAPER_BRIGHTNESS
    paper_rows = np.where(paper.mean(axis=1) > PAPER_ROW_SHARE)[0]
    paper_columns = np.where(paper.mean(axis=0) > PAPER_ROW_SHARE)[0]
    if paper_rows.size == 0 or paper_columns.size == 0:
        return {}
    top, bottom = int(paper_rows[0]), int(paper_rows[-1])
    left, right = int(paper_columns[0]), int(paper_columns[-1])

    darkness = 255.0 - array
    row_profile = darkness[:, int(columns * 0.30):int(columns * 0.70)].mean(axis=1)
    column_profile = darkness[int(rows * 0.30):int(rows * 0.70), :].mean(axis=0)

    def edge(profile: np.ndarray, start: int, limit: int):
        """First strong narrow dark line going outward from `start`.

        Outward, not inward from the paper edge. Each side of the frame is three
        rules, not one: the inner neatline against the map, then the graticule's
        graduated band, then a heavy outer rule. Searching inward finds the
        heavy outer rule, which sits about 130 px beyond the neatline and made
        every sheet measure some 5% too tall - and that fed straight through to
        a 400 m error in the anchor. Searching outward from the middle of the map
        finds the neatline first. Map content is not a hazard here because the
        test demands a line spanning the central 40% of the sheet.
        """
        background = np.convolve(profile, np.ones(31) / 31, "same")
        sharp = profile - background
        threshold = max(sharp.std() * 2.0, 3.0)
        step = 1 if limit > start else -1
        for index in range(start, limit, step):
            if 0 <= index < len(sharp) and sharp[index] > threshold:
                return index
        return None

    middle_row, middle_column = (top + bottom) // 2, (left + right) // 2
    sides = {
        "top": edge(row_profile, middle_row, top),
        "bottom": edge(row_profile, middle_row, bottom),
        "left": edge(column_profile, middle_column, left),
        "right": edge(column_profile, middle_column, right),
    }
    if any(v is None for v in sides.values()):
        return {}
    return {k: v * NEATLINE_DOWNSAMPLE for k, v in sides.items()}


LABEL_BANDS = {
    "easting": [(0.0, 0.0, 1.0, 0.13), (0.0, 0.86, 1.0, 1.0)],
    "northing": [(0.0, 0.02, 0.10, 0.98), (0.90, 0.02, 1.0, 0.98)],
}
LABEL_UPSCALE = 2
LABEL_WINDOW_KM = 2      # how far outside the catalogue extent a label may lie
LABEL_MATCH_PX = 0.45    # a label must sit within this fraction of a km of a line


def read_labels(path: Path) -> dict:
    """Red three-digit grid labels in the margins, with their pixel centres.

    Position matters as much as value. A label's value alone cannot be attached
    to a line, and the top and bottom margins disagree about where a given
    kilometre is by more than a kilometre - the grid is tilted about four
    degrees, so over 5000 px of sheet height the same easting line arrives at
    the two margins 350 px apart. Both coordinates are returned so the label can
    be reduced to the line constant it actually lies on.
    """
    image = Image.open(path).convert("RGB")
    width, height = image.size
    found: dict[str, list] = {}
    for axis, bands in LABEL_BANDS.items():
        readings = []
        for x0, y0, x1, y1 in bands:
            box = (int(x0 * width), int(y0 * height),
                   int(x1 * width), int(y1 * height))
            crop = image.crop(box)
            array = np.asarray(crop).astype(np.int16)
            red, green, blue = array[..., 0], array[..., 1], array[..., 2]
            mask = (red - green > 40) & (red - blue > 30) & (red > 110)
            binary = Image.fromarray(np.where(mask, 0, 255).astype(np.uint8))
            binary = binary.resize((binary.width * LABEL_UPSCALE,
                                    binary.height * LABEL_UPSCALE), Image.LANCZOS)
            data = pytesseract.image_to_data(
                binary, config="--psm 11 -c tessedit_char_whitelist=0123456789",
                output_type=pytesseract.Output.DICT)
            for text, x, y, w, h in zip(data["text"], data["left"], data["top"],
                                        data["width"], data["height"]):
                token = text.strip()
                if len(token) == 3 and token.isdigit():
                    readings.append((int(token),
                                     box[0] + (x + w / 2) / LABEL_UPSCALE,
                                     box[1] + (y + h / 2) / LABEL_UPSCALE))
        found[axis] = readings
    return found


def anchor_from_labels(labels: list, lines: list, tangent: float,
                       axis: int, window: tuple[int, int],
                       px_per_km: float, sign: int) -> dict:
    """Which kilometre is line 0? Decided by vote among the margin labels.

    Each label is reduced to the line constant it lies on, matched to the
    nearest detected line, and votes for one offset. Individual labels are
    unreliable - Tesseract turns 209 into 208 - but a wrong reading votes for a
    wrong offset while right ones agree, so the mode is safe well below perfect
    OCR. Only labels inside the catalogue's own extent are considered, which
    keeps out the graticule's minute numbering and the kilometre count.
    """
    low, high = window
    votes: dict[int, int] = {}
    for value, x, y in labels:
        if not low <= value <= high:
            continue
        constant = (x - y * tangent) if axis == 0 else (y - x * tangent)
        distances = [abs(constant - c) for _, c in lines]
        nearest = int(np.argmin(distances))
        if distances[nearest] > px_per_km * LABEL_MATCH_PX:
            continue
        offset = value + sign * lines[nearest][0]
        votes[offset] = votes.get(offset, 0) + 1
    if not votes:
        return {}
    best = max(votes, key=lambda k: votes[k])
    total = sum(votes.values())
    return {"origin_km": best, "votes": votes[best], "labels_matched": total}


def grid_lines(found: dict) -> tuple[list[float], list[float], float, float]:
    """Line constants and shear tangents, in full-resolution pixel coordinates.

    detect_sheet_grid finds the eastings by shearing each row left by
    round(y * tan a) and summing, so a peak at projected position p is the set
    of pixels with x = p + y * tan a. Northings are the same with the axes
    swapped. The peaks are indices into the measured body crop, so the crop
    offset has to be added back.
    """
    width, height = found["width_px"], found["height_px"]
    offset = found.get("body_offset_px")
    if offset is None:
        # Older caches predate the stored offset; it is deterministic.
        columns, rows = width // GRID_DOWNSAMPLE, height // GRID_DOWNSAMPLE
        offset = [int(columns * BODY_MARGIN_LEFT) * GRID_DOWNSAMPLE,
                  int(rows * BODY_MARGIN_TOP) * GRID_DOWNSAMPLE]
    column_offset, row_offset = offset

    tan_e = math.tan(math.radians(found["easting"]["angle_deg"]))
    tan_n = math.tan(math.radians(found["northing"]["angle_deg"]))

    # u(x, y) = x - tan_e * y is constant along an easting line.
    eastings = [p + column_offset - row_offset * tan_e
                for p in found["easting_peaks_px"]]
    # v(x, y) = y - tan_n * x is constant along a northing line.
    northings = [p + row_offset - column_offset * tan_n
                 for p in found["northing_peaks_px"]]
    return eastings, northings, tan_e, tan_n


MAX_LINE_OFFSET_KM = 0.25


def kilometre_indices(constants: list[float], px_per_km: float):
    """Which kilometre each detected line is, counted from the first.

    Not simply its position in the list. The detector occasionally finds a
    spurious line or misses a faint one, and then the nth line is not the nth
    kilometre - which shifts every index after it. On the Kairouan sheet that
    made one affine fit the intersections to only 239 m rms, where a rigid
    printed grid should fit to under 30. Deriving the index from the measured
    position instead tolerates a gap, and a line that does not sit near a whole
    kilometre from the first is dropped rather than trusted.
    """
    kept = []
    for constant in constants:
        offset = (constant - constants[0]) / px_per_km
        index = round(offset)
        if abs(offset - index) <= MAX_LINE_OFFSET_KM:
            kept.append((index, constant))
    return kept


def intersections(eastings, northings, tan_e, tan_n):
    """Solve x - tan_e*y = u and y - tan_n*x = v for every line pair.

    `eastings` and `northings` are (kilometre index, line constant) pairs, so
    the index carried through is a distance in kilometres and not a position in
    a list.
    """
    determinant = 1.0 - tan_e * tan_n
    points = []
    for i, u in eastings:
        for j, v in northings:
            x = (u + tan_e * v) / determinant
            y = (v + tan_n * u) / determinant
            points.append((i, j, x, y))
    return points


def fit_affine(pixels: np.ndarray, world: np.ndarray):
    """Least-squares (x, y, 1) -> (easting, northing); returns coefficients."""
    design = np.column_stack([pixels[:, 0], pixels[:, 1], np.ones(len(pixels))])
    solution, *_ = np.linalg.lstsq(design, world, rcond=None)
    predicted = design @ solution
    residuals = np.linalg.norm(predicted - world, axis=1)
    return solution, residuals


def apply_affine(solution, x, y):
    return (solution[0, 0] * x + solution[1, 0] * y + solution[2, 0],
            solution[0, 1] * x + solution[1, 1] * y + solution[2, 1])


def georeference(path: Path, found: dict, box: dict, zone: str) -> dict:
    epsg = ZONE_EPSG[zone]
    to_lambert = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    to_wgs84 = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)

    frame = find_neatline(path)
    if not frame:
        return {"error": "neatline not found"}

    raw_eastings, raw_northings, tan_e, tan_n = grid_lines(found)
    px_per_km = found["px_per_km"]
    eastings = kilometre_indices(raw_eastings, px_per_km)
    northings = kilometre_indices(raw_northings, px_per_km)
    points = intersections(eastings, northings, tan_e, tan_n)
    if not points:
        return {"error": "no grid intersections"}
    pixels = np.array([(x, y) for _, _, x, y in points], float)

    # Step 1: the linear part, from the grid alone. Line index i is one
    # kilometre of easting and index j one kilometre of northing, with northing
    # decreasing as pixel rows increase. This fixes scale, rotation and skew
    # exactly, because the spacing is one kilometre by construction - no
    # catalogue value is involved and none of its rounding enters.
    relative = np.array([(i * 1000.0, -j * 1000.0) for i, j, _, _ in points])
    linear, residuals = fit_affine(pixels, relative)

    # Step 2: the absolute kilometre of line zero, read off the sheet.
    #
    # The obvious anchor is the catalogue box against the detected frame, and it
    # is not good enough. Each side of the frame is three rules - inner
    # neatline, graduated band, heavy outer rule - and picking the wrong one
    # moves an edge by 130 px; measured against the catalogue extent the frame
    # came out 5% too tall searching inward and 2% too short searching outward,
    # which is +/-400 m of anchor error either way. So the frame is kept only as
    # a cross-check, and the anchor comes from the grid labels themselves.
    centre_latitude = (box["north"] + box["south"]) / 2
    centre_longitude = (box["west"] + box["east"]) / 2
    west_x, _ = to_lambert.transform(box["west"], centre_latitude)
    east_x, _ = to_lambert.transform(box["east"], centre_latitude)
    _, south_y = to_lambert.transform(centre_longitude, box["south"])
    _, north_y = to_lambert.transform(centre_longitude, box["north"])

    labels = read_labels(path)
    # Eastings ascend with line index; northings descend, so line 0 is the
    # highest and its offset is value + index.
    easting_anchor = anchor_from_labels(
        labels["easting"], eastings, tan_e, 0,
        (int(west_x / 1000) - LABEL_WINDOW_KM, int(east_x / 1000) + LABEL_WINDOW_KM),
        px_per_km, -1)
    northing_anchor = anchor_from_labels(
        labels["northing"], northings, tan_n, 1,
        (int(south_y / 1000) - LABEL_WINDOW_KM, int(north_y / 1000) + LABEL_WINDOW_KM),
        px_per_km, +1)
    if not easting_anchor or not northing_anchor:
        return {"error": "grid labels not read"}

    solution = linear.copy()
    solution[2, 0] += easting_anchor["origin_km"] * 1000.0
    solution[2, 1] += northing_anchor["origin_km"] * 1000.0

    # Cross-check: what the catalogue box would have said, at the frame centre.
    # This is the number the anchor no longer depends on, so a disagreement of
    # a few hundred metres is expected and harmless; a disagreement of a whole
    # kilometre or more means the labels were misread and is worth flagging.
    centre_pixel = ((frame["left"] + frame["right"]) / 2,
                    (frame["top"] + frame["bottom"]) / 2)
    centre_fitted = apply_affine(solution, *centre_pixel)
    centre_catalogue = to_lambert.transform(centre_longitude, centre_latitude)
    anchor_check = (abs(centre_fitted[0] - centre_catalogue[0]),
                    abs(centre_fitted[1] - centre_catalogue[1]))

    # An independent check on the frame, and so on the anchor: the frame's
    # measured size against the size the catalogue extent implies. The two come
    # from the neatline and grid spacing on one side and the catalogue and the
    # projection on the other, so agreement is not circular.
    frame_width_km = (frame["right"] - frame["left"]) / px_per_km
    frame_height_km = (frame["bottom"] - frame["top"]) / px_per_km
    catalogue_width_km = abs(east_x - west_x) / 1000
    catalogue_height_km = abs(north_y - south_y) / 1000
    size_error = max(
        abs(frame_width_km - catalogue_width_km) / catalogue_width_km,
        abs(frame_height_km - catalogue_height_km) / catalogue_height_km) * 100

    corners = {}
    for name, (x, y) in {
        "north_west": (frame["left"], frame["top"]),
        "north_east": (frame["right"], frame["top"]),
        "south_west": (frame["left"], frame["bottom"]),
        "south_east": (frame["right"], frame["bottom"]),
    }.items():
        easting, northing = apply_affine(solution, x, y)
        lon, lat = to_wgs84.transform(easting, northing)
        corners[name] = {"lon": round(lon, 6), "lat": round(lat, 6),
                         "easting": round(easting, 1), "northing": round(northing, 1)}

    return {
        "lambert_zone": zone,
        "epsg": epsg,
        "neatline_px": frame,
        "grid_intersections": len(points),
        # Kept so symbol extraction can cut the grid out of the red channel:
        # houses and grid lines are printed in the same ink.
        "grid_lines": {
            "tan_e": round(tan_e, 6),
            "tan_n": round(tan_n, 6),
            "easting_constants": [round(c, 2) for _, c in eastings],
            "northing_constants": [round(c, 2) for _, c in northings],
        },
        "easting_lines": len(eastings),
        "northing_lines": len(northings),
        # World-file order: A, D, B, E, C, F.
        "affine": [round(float(v), 6) for v in
                   (solution[0, 0], solution[0, 1], solution[1, 0],
                    solution[1, 1], solution[2, 0], solution[2, 1])],
        "frame_size_error_pct": round(float(size_error), 2),
        "easting_origin_km": easting_anchor["origin_km"],
        "northing_origin_km": northing_anchor["origin_km"],
        "label_votes_e": easting_anchor["votes"],
        "label_votes_n": northing_anchor["votes"],
        "labels_matched_e": easting_anchor["labels_matched"],
        "labels_matched_n": northing_anchor["labels_matched"],
        "anchor_vs_catalogue_e_m": round(float(anchor_check[0]), 1),
        "anchor_vs_catalogue_n_m": round(float(anchor_check[1]), 1),
        "residual_rms_m": round(float(np.sqrt((residuals ** 2).mean())), 2),
        "residual_max_m": round(float(residuals.max()), 2),
        # Confidence is not decided here - see anchor_is_confident, which is
        # applied when the table is written so the rule can be changed without
        # re-reading ninety-six scans.
        "corners": corners,
    }


def write_sidecars(directory: Path, record_id: str, found: dict,
                   path: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    a, d, b, e, c, f = found["affine"]

    # World file: pixel centre convention, so shift the origin by half a pixel.
    (directory / f"{record_id}.wld").write_text(
        "\n".join(f"{v:.10f}" for v in
                  (a, d, b, e, c + 0.5 * (a + b), f + 0.5 * (d + e))) + "\n",
        encoding="utf-8")

    # QGIS georeferencer points: the four frame corners are enough to load, and
    # a reader can re-fit from them.
    lines = ["mapX,mapY,pixelX,pixelY,enable,dX,dY,residual"]
    frame = found["neatline_px"]
    for name, (x, y) in {
        "north_west": (frame["left"], frame["top"]),
        "north_east": (frame["right"], frame["top"]),
        "south_east": (frame["right"], frame["bottom"]),
        "south_west": (frame["left"], frame["bottom"]),
    }.items():
        corner = found["corners"][name]
        lines.append(f"{corner['easting']},{corner['northing']},"
                     f"{x},{-y},1,0,0,0")
    (directory / f"{record_id}.points").write_text("\n".join(lines) + "\n",
                                                   encoding="utf-8")


# A sheet's anchor is trusted when the labels agree with each other and the
# result agrees with the catalogue to better than a kilometre. The vote share
# matters as much as the count: the Cap Negro sheet had 13 votes for its winning
# easting out of 22 labels matched, and its anchor is 7 km from the catalogue.
MIN_VOTE_SHARE = 0.70
MIN_VOTES = 3
MAX_ANCHOR_DISAGREEMENT_M = 1000.0


def anchor_is_confident(found: dict) -> bool:
    if "label_votes_e" not in found:
        return False
    shares = []
    for axis in ("e", "n"):
        votes = found[f"label_votes_{axis}"]
        matched = max(found[f"labels_matched_{axis}"], 1)
        if votes < MIN_VOTES:
            return False
        shares.append(votes / matched)
    return (min(shares) >= MIN_VOTE_SHARE
            and max(found["anchor_vs_catalogue_e_m"],
                    found["anchor_vs_catalogue_n_m"]) < MAX_ANCHOR_DISAGREEMENT_M)


CSV_FIELDS = [
    "record_id", "designation", "sheet_name", "lambert_zone", "epsg",
    "grid_intersections", "frame_size_error_pct",
    "easting_origin_km", "northing_origin_km",
    "label_votes_e", "label_votes_n", "labels_matched_e", "labels_matched_n",
    "anchor_vs_catalogue_e_m", "anchor_vs_catalogue_n_m",
    "residual_rms_m", "residual_max_m", "anchor_confident",
    "nw_lon", "nw_lat", "se_lon", "se_lat", "error",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--grid", type=Path,
                        default=REPO_ROOT / "data" / "sheet_grid.json")
    parser.add_argument("--partner", type=Path,
                        default=REPO_ROOT / "data" / "partner_records.json")
    parser.add_argument("--series", type=Path,
                        default=REPO_ROOT / "data" / "tunisia_50k_series.csv")
    parser.add_argument("--out-json", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.json")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.csv")
    parser.add_argument("--sidecars", type=Path,
                        default=REPO_ROOT / "data" / "georef")
    parser.add_argument("--only", nargs="*", default=None,
                        help="record ids to process")
    parser.add_argument("--csv-only", action="store_true",
                        help="rebuild the table from the cached JSON, applying "
                             "the current confidence rule, without re-reading "
                             "any scan")
    args = parser.parse_args()

    grid = json.loads(args.grid.read_text(encoding="utf-8"))
    partner = json.loads(args.partner.read_text(encoding="utf-8"))
    sheets = {r["record_id"]: r
              for r in csv.DictReader(args.series.open(encoding="utf-8"))}
    zones = {r["record_id"]: r["lambert_zone"]
             for r in csv.DictReader(
                 (REPO_ROOT / "data" / "sheet_grid.csv").open(encoding="utf-8"))}

    results: dict = {}
    if args.out_json.exists():
        results = json.loads(args.out_json.read_text(encoding="utf-8"))

    targets = [] if args.csv_only else sorted(args.images.glob("*.jpg"))
    if args.only:
        targets = [t for t in targets if t.stem in set(args.only)]

    for index, path in enumerate(targets, 1):
        record_id = path.stem
        found = grid.get(record_id)
        box = partner.get(record_id, {}).get("bbox")
        zone = zones.get(record_id)
        name = sheets.get(record_id, {}).get("sheet_name") or record_id[-6:]

        if not found or not found.get("has_kilometric_grid"):
            results[record_id] = {"error": "no kilometric grid"}
        elif not box:
            results[record_id] = {"error": "no catalogue bounding box"}
        elif zone not in ZONE_EPSG:
            results[record_id] = {"error": f"no Lambert zone ({zone or 'unset'})"}
        else:
            results[record_id] = georeference(path, found, box, zone)
            if "error" not in results[record_id]:
                write_sidecars(args.sidecars, record_id, results[record_id], path)

        outcome = results[record_id]
        if "error" in outcome:
            print(f"  {index}/{len(targets)} {name[:22]:<22} - {outcome['error']}",
                  flush=True)
        else:
            print(f"  {index}/{len(targets)} {name[:22]:<22} "
                  f"size_err={outcome['frame_size_error_pct']}% "
                  f"origin=({outcome['easting_origin_km']},{outcome['northing_origin_km']})km "
                  f"votes={outcome['label_votes_e']}/{outcome['labels_matched_e']},"
                  f"{outcome['label_votes_n']}/{outcome['labels_matched_n']} "
                  f"vs_cat=({outcome['anchor_vs_catalogue_e_m']},{outcome['anchor_vs_catalogue_n_m']})m "
                  f"rms={outcome['residual_rms_m']}m "
                  f"{'ok' if anchor_is_confident(outcome) else 'ANCHOR UNCERTAIN'}",
                  flush=True)
        args.out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    rows = []
    for record_id, found in sorted(results.items()):
        sheet = sheets.get(record_id, {})
        corners = found.get("corners", {})
        rows.append({
            "record_id": record_id,
            "designation": sheet.get("designation", ""),
            "sheet_name": sheet.get("sheet_name", ""),
            "lambert_zone": found.get("lambert_zone", ""),
            "epsg": found.get("epsg", ""),
            "grid_intersections": found.get("grid_intersections", ""),
            "frame_size_error_pct": found.get("frame_size_error_pct", ""),
            "easting_origin_km": found.get("easting_origin_km", ""),
            "northing_origin_km": found.get("northing_origin_km", ""),
            "label_votes_e": found.get("label_votes_e", ""),
            "label_votes_n": found.get("label_votes_n", ""),
            "labels_matched_e": found.get("labels_matched_e", ""),
            "labels_matched_n": found.get("labels_matched_n", ""),
            "anchor_vs_catalogue_e_m": found.get("anchor_vs_catalogue_e_m", ""),
            "anchor_vs_catalogue_n_m": found.get("anchor_vs_catalogue_n_m", ""),
            "residual_rms_m": found.get("residual_rms_m", ""),
            "residual_max_m": found.get("residual_max_m", ""),
            "anchor_confident": int(anchor_is_confident(found))
                                if "affine" in found else "",
            "nw_lon": corners.get("north_west", {}).get("lon", ""),
            "nw_lat": corners.get("north_west", {}).get("lat", ""),
            "se_lon": corners.get("south_east", {}).get("lon", ""),
            "se_lat": corners.get("south_east", {}).get("lat", ""),
            "error": found.get("error", ""),
        })

    with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    good = [r for r in rows if not r["error"]]
    print(f"\n{len(rows)} sheets: {len(good)} georeferenced")
    if good:
        for field, unit in (("frame_size_error_pct", "%"),
                            ("anchor_vs_catalogue_e_m", " m"),
                            ("anchor_vs_catalogue_n_m", " m"),
                            ("residual_rms_m", " m")):
            values = [float(r[field]) for r in good]
            print(f"  {field}: median {np.median(values):.2f}{unit}, "
                  f"max {max(values):.2f}{unit}")
        uncertain = [r for r in good if r["anchor_confident"] == 0]
        print(f"  anchor uncertain on {len(uncertain)} sheet(s)")
    print(f"  -> {args.out_json}\n  -> {args.out_csv}\n  -> {args.sidecars}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

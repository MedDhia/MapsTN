#!/usr/bin/env python3
"""Detect the printed Lambert kilometric grid on each sheet, and read its labels.

docs/OBJECT-EXTRACTION.md said grid detection had been attempted by colour
thresholding and abandoned, because the red of the grid is the red of the roads
and the built-up hatching. That was the right diagnosis of the wrong method.
A colour threshold asks "is this pixel grid-red", which is unanswerable. This
asks a different question: "is there a direction in which the red pixels pile up
into a regular comb". Roads are crooked and unrepeating and contribute a smooth
background to such a projection; the grid contributes sharp peaks at a fixed
period. So the grid is recoverable from the same noisy mask that defeats a
per-pixel classifier.

Three steps.

1. Shear-and-project (a poor man's Radon transform). The grid is not square to
   the scan - the sheets are cut on the graticule, the grid is Lambert, and the
   scans are slightly skewed on top of that, which together come to about four
   degrees. Project the red mask along a range of shear angles and keep the
   angle where the projection is most peaked.

2. Peak spacing. Local maxima of that projection are the grid lines; the median
   gap between them is one kilometre. This measures the scan resolution far more
   reliably than the catalogued paper size, which is rounded to the centimetre
   and describes the sheet rather than the printed image.

3. OCR of the margin. The grid lines are labelled with absolute Lambert
   coordinates in red - "389 390 391 ..." - and the header states the zone:
   "CARROYAGE KILOMETRIQUE LAMBERT (NORD TUNISIE)". Masking to red and running
   Tesseract over the top strip recovers both. Absolute labels plus detected
   pixel positions is a georeference with no human in the loop.

Numbers OCR badly (392 comes back as "39?", 396 as "3%"), so no label is trusted
on its own. Only the longest near-consecutive run of three-digit readings is
kept, and only its endpoints - a mangled label in the middle of a run costs
nothing, because its neighbours fix where it must have been.

Outputs:
    data/sheet_grid.json
    data/sheet_grid.csv

Usage:
    python3 scripts/detect_sheet_grid.py --images <dir of record_id.jpg>
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

try:
    import pytesseract
except ImportError:  # OCR is optional; geometry still works without it
    pytesseract = None

Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent

DOWNSAMPLE = 4
SCALE_DENOMINATOR = 50_000
# One kilometre at 1:50 000 is 20 mm of paper, i.e. 0.7874 inch.
INCHES_PER_KM = (1000.0 / SCALE_DENOMINATOR) * 1000 / 25.4

# A grid line is red; so is a main road. The mask lets both through on purpose.
RED_MINUS_GREEN = 28
RED_MINUS_BLUE = 18
RED_FLOOR = 110

ANGLES = np.arange(-6.0, 6.01, 0.25)
MIN_SEPARATION = 40          # px at DOWNSAMPLE; one km is about 59
MIN_LINES = 8                # fewer than this is not a grid
MAX_GAP_IQR = 3.0            # px at DOWNSAMPLE; a real grid is very regular

ZONE_RE = re.compile(r"(CARROYAGE|QUADRILLAGE)\s+KILOM[EÉ]TRIQUE\s+LAMBERT\s*\(?\s*"
                     r"(NORD|SUD)\s+TUNISIE", re.IGNORECASE)
THREE_DIGIT_RE = re.compile(r"\b(\d{3})\b")


# The grid is measured on the map body only, so peak positions are relative to
# that crop. Anything converting them back to full-image pixels needs the same
# offsets, so they are defined once here and stored per sheet.
BODY_MARGIN_TOP = 0.10
BODY_MARGIN_LEFT = 0.08


def body_offsets(width: int, height: int) -> tuple[int, int]:
    """(column, row) offset of the measured body within the downsampled mask."""
    columns, rows = width // DOWNSAMPLE, height // DOWNSAMPLE
    return int(columns * BODY_MARGIN_LEFT), int(rows * BODY_MARGIN_TOP)


def red_mask(path: Path, downsample: int = DOWNSAMPLE):
    image = Image.open(path).convert("RGB")
    width, height = image.size
    small = image.resize((width // downsample, height // downsample), Image.BILINEAR)
    array = np.asarray(small).astype(np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    mask = ((red - green > RED_MINUS_GREEN)
            & (red - blue > RED_MINUS_BLUE)
            & (red > RED_FLOOR))
    return mask, (width, height)


def project(mask: np.ndarray, axis: int, angle: float) -> np.ndarray:
    """Sum the mask along one axis after shearing, so tilted lines stack up."""
    height, width = mask.shape
    tangent = math.tan(math.radians(angle))
    if axis == 0:                                    # vertical lines (eastings)
        shifts = (np.arange(height) * tangent).round().astype(int)
        accumulator = np.zeros(width)
        for row in range(height):
            accumulator += np.roll(mask[row], -shifts[row])
    else:                                            # horizontal lines (northings)
        shifts = (np.arange(width) * tangent).round().astype(int)
        accumulator = np.zeros(height)
        for column in range(width):
            accumulator += np.roll(mask[:, column], -shifts[column])
    return accumulator


def find_peaks(accumulator: np.ndarray, min_separation: int) -> list[int]:
    """Local maxima of the projection, after removing its slow background."""
    window = int(min_separation * 2)
    background = np.convolve(accumulator, np.ones(window) / window, "same")
    detrended = accumulator - background
    threshold = detrended.std() * 1.2

    peaks: list[int] = []
    index = 0
    length = len(detrended)
    while index < length:
        if detrended[index] > threshold:
            end = index
            while end + 1 < length and detrended[end + 1] > threshold:
                end += 1
            peaks.append(index + int(np.argmax(accumulator[index:end + 1])))
            index = end + 1
        else:
            index += 1
    # Two maxima closer than most of a kilometre are one line found twice.
    return [p for i, p in enumerate(peaks)
            if i == 0 or p - peaks[i - 1] >= min_separation * 0.6]


def measure_axis(mask: np.ndarray, axis: int) -> dict:
    best = None
    for angle in ANGLES:
        accumulator = project(mask, axis, float(angle))
        contrast = accumulator.std() / max(accumulator.mean(), 1e-6)
        if best is None or contrast > best[0]:
            best = (contrast, float(angle), accumulator)
    contrast, angle, accumulator = best

    peaks = find_peaks(accumulator, MIN_SEPARATION)
    gaps = np.diff(peaks) if len(peaks) > 2 else np.array([])
    if gaps.size:
        median_gap = float(np.median(gaps))
        iqr = float(np.percentile(gaps, 75) - np.percentile(gaps, 25))
    else:
        median_gap, iqr = float("nan"), float("nan")

    return {
        "angle_deg": round(angle, 2),
        "contrast": round(contrast, 2),
        "lines": len(peaks),
        "median_gap_px": round(median_gap, 1),
        "gap_iqr_px": round(iqr, 1),
        "px_per_km": round(median_gap * DOWNSAMPLE, 1),
        "peaks_px": [p * DOWNSAMPLE for p in peaks],
    }


def read_margin(path: Path) -> dict:
    """OCR the red text in the top strip: the zone statement and grid labels."""
    if pytesseract is None:
        return {}
    image = Image.open(path).convert("RGB")
    width, height = image.size
    strip = image.crop((0, 0, width, int(height * 0.12)))
    array = np.asarray(strip).astype(np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    # A tighter red than the grid mask: margin type is solid, roads are not here.
    mask = (red - green > 40) & (red - blue > 30) & (red > RED_FLOOR)
    binary = Image.fromarray(np.where(mask, 0, 255).astype(np.uint8))
    binary = binary.resize((binary.width * 2, binary.height * 2), Image.LANCZOS)
    text = " ".join(pytesseract.image_to_string(
        binary, lang="fra", config="--psm 6").split())

    found: dict = {"header_text": text[:300]}
    zone = ZONE_RE.search(text)
    if zone:
        found["grid_wording"] = zone.group(1).lower()
        found["lambert_zone"] = zone.group(2).lower()

    # Labels are consecutive kilometres. OCR mangles individual digits, so keep
    # the longest near-consecutive run rather than any single reading.
    numbers = sorted({int(n) for n in THREE_DIGIT_RE.findall(text)})
    run: list[int] = []
    best_run: list[int] = []
    for value in numbers:
        if run and value - run[-1] <= 3:
            run.append(value)
        else:
            run = [value]
        if len(run) > len(best_run):
            best_run = list(run)
    if len(best_run) >= 5:
        found["easting_label_min_km"] = best_run[0]
        found["easting_label_max_km"] = best_run[-1]
        found["easting_labels_read"] = len(best_run)
    return found


def decide(easting: dict, northing: dict) -> dict:
    """Is this a grid, and at what spacing? Kept separate from the measuring so
    that changing the rule does not mean re-reading ninety-six 60-megapixel
    scans - see --recompute."""

    def usable(axis: dict) -> bool:
        return (axis["lines"] >= MIN_LINES
                and axis["gap_iqr_px"] == axis["gap_iqr_px"]  # not NaN
                and axis["gap_iqr_px"] <= MAX_GAP_IQR)

    clean = [a for a in (easting, northing) if usable(a)]
    if len(clean) == 2:
        has_grid, basis = True, "both_axes"
        px_per_km = (easting["px_per_km"] + northing["px_per_km"]) / 2
    elif len(clean) == 1:
        # A kilometric grid is square, so the two axes must give the same
        # spacing. When one axis is clean and the other's median agrees with it,
        # the second axis is a detection failure and not a missing grid: on the
        # Djebeniana sheet the eastings came back perfect (28 lines, zero spread)
        # while the northings picked up spurious peaks, and requiring both axes
        # threw away a sheet whose grid is plainly there.
        other = northing if clean[0] is easting else easting
        reference = clean[0]["px_per_km"]
        agrees = (other["px_per_km"] == other["px_per_km"]
                  and abs(other["px_per_km"] - reference) / reference <= 0.05)
        has_grid = agrees
        basis = "one_axis_confirmed_by_spacing" if agrees else "not_detected"
        px_per_km = reference if agrees else float("nan")
    else:
        has_grid, basis, px_per_km = False, "not_detected", float("nan")

    return {
        "has_kilometric_grid": has_grid,
        "grid_basis": basis,
        "px_per_km": round(px_per_km, 1) if has_grid else None,
        "scan_dpi": round(px_per_km / INCHES_PER_KM) if has_grid else None,
        "metres_per_px": round(1000 / px_per_km, 2) if has_grid else None,
        # The grid is rotated relative to the scan raster; the two axes report
        # that rotation with opposite sign by construction.
        "grid_rotation_deg": round((easting["angle_deg"] - northing["angle_deg"]) / 2, 2),
    }


def analyse(path: Path) -> dict:
    mask, (width, height) = red_mask(path)
    rows, columns = mask.shape
    # Margins carry type and the sheet edge; measure the map body only.
    body = mask[int(rows * BODY_MARGIN_TOP):int(rows * (1 - BODY_MARGIN_TOP)),
                int(columns * BODY_MARGIN_LEFT):int(columns * (1 - BODY_MARGIN_LEFT))]

    easting = measure_axis(body, 0)
    northing = measure_axis(body, 1)

    column_offset, row_offset = body_offsets(width, height)
    record = {
        "width_px": width,
        "height_px": height,
        "body_offset_px": [column_offset * DOWNSAMPLE, row_offset * DOWNSAMPLE],
        "red_density": round(float(mask.mean()), 4),
        **decide(easting, northing),
        "easting": {k: v for k, v in easting.items() if k != "peaks_px"},
        "northing": {k: v for k, v in northing.items() if k != "peaks_px"},
        "easting_peaks_px": easting["peaks_px"],
        "northing_peaks_px": northing["peaks_px"],
    }
    record.update(read_margin(path))
    return record


# Lambert Nord Tunisie and Lambert Sud Tunisie are separate zones. The header
# states which, but the statement OCRs on only some sheets, so latitude fills
# the gap - and only where latitude is unambiguous. The conventional limit
# between the two is 34 deg 39', which falls in the observed gap between the
# southernmost sheet whose header reads NORD (34.97) and the northernmost that
# reads SUD (33.77). A sheet sitting on the limit is left unassigned rather than
# guessed: "Environs de Sfax" begins at exactly 34.65.
ZONE_SOUTH_MAX_LATITUDE = 34.4
ZONE_NORTH_MIN_LATITUDE = 34.9

CSV_FIELDS = [
    "record_id", "designation", "sheet_name", "revision_year",
    "has_kilometric_grid", "grid_basis",
    "lambert_zone", "lambert_zone_basis", "grid_wording",
    "px_per_km", "scan_dpi", "metres_per_px", "grid_rotation_deg",
    "easting_lines", "northing_lines", "gap_iqr_px",
    "easting_label_min_km", "easting_label_max_km",
    "width_px", "height_px",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True,
                        help="directory of scans named <record_id>.jpg")
    parser.add_argument("--series", type=Path,
                        default=REPO_ROOT / "data" / "tunisia_50k_series.csv")
    parser.add_argument("--out-json", type=Path,
                        default=REPO_ROOT / "data" / "sheet_grid.json")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "sheet_grid.csv")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--recompute", action="store_true",
                        help="re-apply the grid decision to cached measurements "
                             "without re-reading the scans")
    args = parser.parse_args()

    sheets = {r["record_id"]: r
              for r in csv.DictReader(args.series.open(encoding="utf-8"))}

    results: dict = {}
    if args.out_json.exists():
        results = json.loads(args.out_json.read_text(encoding="utf-8"))

    if args.recompute:
        changed = 0
        for found in results.values():
            if "easting" not in found:
                continue
            before = found.get("has_kilometric_grid")
            found.update(decide(found["easting"], found["northing"]))
            changed += found["has_kilometric_grid"] != before
        print(f"recomputed {len(results)} cached measurements, "
              f"{changed} changed verdict")
        # Write it back here. The only other write is inside the loop over
        # pending scans, and --recompute leaves that loop empty, so a recomputed
        # verdict reached the table and never the cache. The two then disagreed
        # about whether the Djebeniana sheet has a grid, and georeferencing
        # reads the cache - so the sheet stayed unusable while the table said
        # otherwise.
        args.out_json.write_text(json.dumps(results, ensure_ascii=False,
                                            indent=2), encoding="utf-8")

    files = sorted(args.images.glob("*.jpg"))
    pending = [] if args.recompute else [f for f in files if f.stem not in results]
    cached = len(files) - len(pending)
    if args.limit:
        pending = pending[:args.limit]
    print(f"{len(files)} scans, {cached} cached, {len(pending)} to analyse")

    for index, path in enumerate(pending, 1):
        try:
            results[path.stem] = analyse(path)
        except Exception as error:                      # a bad scan is data too
            results[path.stem] = {"error": str(error)}
        found = results[path.stem]
        print(f"  {index}/{len(pending)} {sheets.get(path.stem, {}).get('sheet_name', path.stem)[:22]:<22}"
              f" grid={found.get('has_kilometric_grid')} "
              f"{found.get('px_per_km') or '-'} px/km "
              f"zone={found.get('lambert_zone') or '-'}", flush=True)
        args.out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    rows = []
    for record_id, found in sorted(results.items()):
        sheet = sheets.get(record_id, {})
        zone = found.get("lambert_zone", "")
        zone_basis = "header_text" if zone else ""
        if not zone and sheet.get("bbox_south"):
            latitude = float(sheet["bbox_south"])
            if latitude < ZONE_SOUTH_MAX_LATITUDE:
                zone, zone_basis = "sud", "inferred_from_latitude"
            elif latitude > ZONE_NORTH_MIN_LATITUDE:
                zone, zone_basis = "nord", "inferred_from_latitude"
        rows.append({
            "record_id": record_id,
            "designation": sheet.get("designation", ""),
            "sheet_name": sheet.get("sheet_name", ""),
            "revision_year": sheet.get("revision_year") or sheet.get("published_year", ""),
            "has_kilometric_grid": int(bool(found.get("has_kilometric_grid"))),
            "grid_basis": found.get("grid_basis", ""),
            "lambert_zone": zone,
            "lambert_zone_basis": zone_basis,
            "grid_wording": found.get("grid_wording", ""),
            "px_per_km": found.get("px_per_km") or "",
            "scan_dpi": found.get("scan_dpi") or "",
            "metres_per_px": found.get("metres_per_px") or "",
            "grid_rotation_deg": found.get("grid_rotation_deg", ""),
            "easting_lines": found.get("easting", {}).get("lines", ""),
            "northing_lines": found.get("northing", {}).get("lines", ""),
            "gap_iqr_px": found.get("easting", {}).get("gap_iqr_px", ""),
            "easting_label_min_km": found.get("easting_label_min_km", ""),
            "easting_label_max_km": found.get("easting_label_max_km", ""),
            "width_px": found.get("width_px", ""),
            "height_px": found.get("height_px", ""),
        })

    with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    gridded = [r for r in rows if r["has_kilometric_grid"]]
    print(f"\n{len(rows)} sheets: {len(gridded)} carry a kilometric grid")
    if gridded:
        dpis = [float(r["scan_dpi"]) for r in gridded if r["scan_dpi"]]
        print(f"  scan resolution: median {np.median(dpis):.0f} dpi "
              f"(range {min(dpis):.0f}-{max(dpis):.0f})")
        zones = {}
        for r in gridded:
            zones[r["lambert_zone"] or "unread"] = zones.get(r["lambert_zone"] or "unread", 0) + 1
        print(f"  Lambert zone: {zones}")
    print(f"  -> {args.out_json}\n  -> {args.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Place a sheet from its four printed corner coordinates alone, no grid.

The main path (scripts/georeference_sheets.py) takes scale, rotation and skew
from the printed kilometric grid and only the translation from the printed
corners. That fails on a specific, diagnosable class of sheet: one where the
grid detector finds plenty of lines on one axis and **one** on the other.
A single line gives no spacing, so that axis has no scale, and the affine's
whole row for it comes out zero:

    La Goulette  easting_lines 32, northing_lines 1
                 affine [3.95963, 0.0, -4.792149, 0.0, -0.00549, 0.0]
                                    ^^^          ^^^

Both the northing coefficients are 0.0. The stored residual of 7.08 m rms is
real and meaningless - it is the fit of the easting axis to itself. Four sheets
of the series are in this state (Kalaat es Senam, Ksar Tlili, La Goulette,
Nasr Allah), all with northing_lines = 1.

But the sheet prints its four corners in the margin to the metre, and the corner
reader already reads them. Four corners are twelve numbers where a
six-parameter affine needs six, so **the corners alone over-determine the
transform** - no grid required. That is what this script does.

Why this is not just the main path with fewer control points: the grid gives 20
to 32 lines per axis and its scale is a kilometre measured over dozens of
repeats, which is why it beats four corners when it is available. When it is
not, four corners spanning the whole sheet are the next best thing, and they are
better than they sound because they are the sheet's own statement of where it
is rather than a measurement of it.

**What it is checked against, none of it used in the fit.**

    scale        must fall in the series' own 4.20-4.27 m/px, widened a little
    rotation     must agree with the grid detector's angle, which comes from
                 the line directions and survives a missing spacing
    frame        must come out near 32 x 20 km
    neighbours   the shared-corner test: adjacent sheets print identical values
                 at the corners they share, so a placed sheet's corners must
                 land on its neighbours'. The series median is 72 m and an
                 anchor error is a whole kilometre by construction, so this is
                 what rules one out.

**What it achieves on the two sheets it can fit.**

    Ksar Tlili   corner readings close to 0 m; scale 4.237/4.218 against the
                 detector's 4.24; rotation +4.35 against +4.38; frame
                 31.98 x 20.00 km; 10 shared corners, median 56 m - better
                 than the series median.
    La Goulette  corner readings close to 50 m; scale 4.317/4.218 against
                 4.27; rotation +4.32 against +4.25; frame 32.08 x 19.99 km;
                 9 shared corners, median 118 m.

Ksar Tlili is series-quality. La Goulette is a notch coarser: its four printed
eastings do not close as a parallelogram, leaving a 200 m saddle that the fit
spreads as +/-50 m. On Kasserine the same eight numbers close to 1 m, so this is
either one misread digit or a neatline edge detected 47 px out - and since the
sheet also has frame_size_error_pct 8.7, the neatline is the suspect. Either way
the *anchor* is certain: 118 m rules out the whole kilometre that an anchor error
would have to be.

So each sheet gets `precision_class` from its own measured neighbour agreement -
`corner_fit` under CLASS_TIGHT_M, `corner_fit_coarse` above - and neither is
merged into the main table by this script. That is the same rule the graticule
sheets are held to: a position is only allowed into a dataset whose accuracy is
claimed at 20 m if it has been shown to belong there.

Outputs:
    data/sheet_corner_fit.{json,csv}
    data/georef_corner_fit/<record_id>.{wld,points}

Usage:
    python3 scripts/georeference_from_corners.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from georeference_sheets import (  # noqa: E402
    apply_affine, write_sidecars,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

CORNER_ORDER = ("north_west", "north_east", "south_east", "south_west")
CORNER_PIXEL = {
    "north_west": ("left", "top"),
    "north_east": ("right", "top"),
    "south_west": ("left", "bottom"),
    "south_east": ("right", "bottom"),
}

# An axis with fewer than two detected lines has no spacing and so no scale.
# This is the condition that makes a sheet a candidate, not a guess about it.
MIN_GRID_LINES = 2

# Six parameters need three points; the fourth corner is what turns the fit into
# a check, so three is the floor and four is what the good cases give.
MIN_CORNERS = 3

# From the 76 confirmed sheets: metres_per_px 4.200-4.270, frame height
# 19.46-22.54 km, width 20.88-35.96 km, grid rotation 4.00-4.50 deg. Bounds are
# those ranges with a little slack, so a fit that lands outside is outside the
# series rather than merely at its edge.
SCALE_RANGE_M = (4.10, 4.40)
FRAME_WIDTH_KM = (20.0, 37.0)
FRAME_HEIGHT_KM = (19.0, 23.0)
# The grid detector's angle comes from the line directions, which survive a
# missing spacing - so it is available even on these sheets and is independent
# of the corner readings.
ROTATION_AGREEMENT_DEG = 0.6

# A shared corner that agrees this well cannot be a whole kilometre wrong, which
# is the only kind of anchor error there is.
NEIGHBOUR_MATCH_M = 400.0
MIN_NEIGHBOUR_MATCHES = 2
# Above this the placement is kept but labelled coarse and kept out of anything
# claiming series precision. The series' own shared-corner median is 72 m.
CLASS_TIGHT_M = 100.0


def corner_pixels(frame: dict) -> dict:
    return {name: (frame[x], frame[y]) for name, (x, y) in CORNER_PIXEL.items()}


def best_reading(values: list) -> float | None:
    """The metre value the most OCR passes produced, or None."""
    return max(set(values), key=values.count) if values else None


def readings_for(record: dict) -> tuple[dict, dict]:
    """Printed easting and northing per corner, one value each."""
    eastings, northings = {}, {}
    for name, axes in (record.get("corner_readings") or {}).items():
        if name not in CORNER_PIXEL:
            continue
        east = best_reading(axes["easting"]["metres"])
        north = best_reading(axes["northing"]["metres"])
        if east is not None:
            eastings[name] = east
        if north is not None:
            northings[name] = north
    return eastings, northings


def fit_axis(pixels: dict, values: dict):
    """One axis: (x, y, 1) -> metres, by least squares."""
    names = list(values)
    design = np.array([[pixels[n][0], pixels[n][1], 1.0] for n in names])
    target = np.array([values[n] for n in names], float)
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    residuals = design @ coefficients - target
    return coefficients, {n: float(r) for n, r in zip(names, residuals)}


def degenerate_axes(found: dict) -> list[str]:
    """Which axes the grid left without a scale."""
    axes = []
    if (found.get("easting_lines") or 0) < MIN_GRID_LINES:
        axes.append("easting")
    if (found.get("northing_lines") or 0) < MIN_GRID_LINES:
        axes.append("northing")
    return axes


def confirmed_corners(georef: dict, epsg: int, skip: str) -> np.ndarray:
    """Every corner of every sheet standing on its own confirmed printing."""
    points, labels = [], []
    for record_id, found in georef.items():
        if record_id == skip or "corners" not in found:
            continue
        if found.get("anchor_provisional") or not found.get("anchor_confident"):
            continue
        if found.get("epsg") != epsg:
            continue
        for name, corner in found["corners"].items():
            points.append((corner["easting"], corner["northing"]))
            labels.append((record_id, name))
    return np.array(points).reshape(-1, 2), labels


def neighbour_agreement(corners: dict, georef: dict, epsg: int,
                        record_id: str) -> list[tuple]:
    """How far each fitted corner sits from the nearest confirmed one."""
    points, labels = confirmed_corners(georef, epsg, record_id)
    if len(points) == 0:
        return []
    matches = []
    for name in CORNER_ORDER:
        here = np.array([corners[name]["easting"], corners[name]["northing"]])
        distance = np.hypot(points[:, 0] - here[0], points[:, 1] - here[1])
        for index in np.where(distance < NEIGHBOUR_MATCH_M)[0]:
            matches.append((float(distance[index]), name,
                            labels[index][0], labels[index][1]))
    return sorted(matches)


def georeference(record_id: str, found: dict, reading: dict,
                 grid: dict, georef: dict) -> dict:
    frame = found["neatline_px"]
    pixels = corner_pixels(frame)
    eastings, northings = readings_for(reading)

    outcome: dict = {
        "neatline_px": frame,
        "epsg": found["epsg"],
        "lambert_zone": found.get("lambert_zone"),
        "grid_easting_lines": found.get("easting_lines"),
        "grid_northing_lines": found.get("northing_lines"),
        "degenerate_axes": " ".join(degenerate_axes(found)),
        "corners_read_e": len(eastings),
        "corners_read_n": len(northings),
    }
    if len(eastings) < MIN_CORNERS or len(northings) < MIN_CORNERS:
        outcome["refused"] = (f"{len(eastings)} easting and "
                              f"{len(northings)} northing corner readings, "
                              f"needs {MIN_CORNERS} of each")
        return outcome

    east_coefficients, east_residuals = fit_axis(pixels, eastings)
    north_coefficients, north_residuals = fit_axis(pixels, northings)
    solution = np.column_stack([east_coefficients, north_coefficients])

    # Same corner schema as the main path, lon/lat included: consumers such as
    # extract_symbols read the geographic pair, so a record missing it is not a
    # drop-in for data/sheet_georef.json.
    to_wgs84 = Transformer.from_crs(f"EPSG:{found['epsg']}", "EPSG:4326",
                                    always_xy=True)
    corners = {}
    for name in CORNER_ORDER:
        easting, northing = apply_affine(solution, *pixels[name])
        longitude, latitude = to_wgs84.transform(easting, northing)
        corners[name] = {"lon": round(longitude, 6), "lat": round(latitude, 6),
                         "easting": round(easting, 1),
                         "northing": round(northing, 1)}

    def span(a: str, b: str) -> float:
        return float(np.hypot(corners[a]["easting"] - corners[b]["easting"],
                              corners[a]["northing"] - corners[b]["northing"]))

    width = span("north_west", "north_east") / 1000.0
    height = span("north_west", "south_west") / 1000.0
    scale_x = float(np.hypot(east_coefficients[0], north_coefficients[0]))
    scale_y = float(np.hypot(east_coefficients[1], north_coefficients[1]))
    rotation = float(np.degrees(np.arctan2(-north_coefficients[0],
                                           east_coefficients[0])))
    detector_rotation = (grid or {}).get("grid_rotation_deg")

    outcome.update({
        "affine": [round(float(v), 6) for v in
                   (east_coefficients[0], north_coefficients[0],
                    east_coefficients[1], north_coefficients[1],
                    east_coefficients[2], north_coefficients[2])],
        "corners": corners,
        "reading_residual_max_m_e": round(max(abs(v) for v in
                                              east_residuals.values()), 1),
        "reading_residual_max_m_n": round(max(abs(v) for v in
                                              north_residuals.values()), 1),
        "metres_per_px_x": round(scale_x, 3),
        "metres_per_px_y": round(scale_y, 3),
        "rotation_deg": round(rotation, 2),
        "detector_rotation_deg": detector_rotation,
        "frame_width_km": round(width, 2),
        "frame_height_km": round(height, 2),
    })

    failures = []
    for name, value in (("scale x", scale_x), ("scale y", scale_y)):
        if not SCALE_RANGE_M[0] <= value <= SCALE_RANGE_M[1]:
            failures.append(f"{name} {value:.3f} outside "
                            f"{SCALE_RANGE_M[0]}-{SCALE_RANGE_M[1]} m/px")
    if not FRAME_WIDTH_KM[0] <= width <= FRAME_WIDTH_KM[1]:
        failures.append(f"frame width {width:.2f} km outside the series")
    if not FRAME_HEIGHT_KM[0] <= height <= FRAME_HEIGHT_KM[1]:
        failures.append(f"frame height {height:.2f} km outside the series")
    if detector_rotation is not None:
        gap = abs(rotation - detector_rotation)
        outcome["rotation_gap_deg"] = round(gap, 2)
        if gap > ROTATION_AGREEMENT_DEG:
            failures.append(f"rotation {rotation:.2f} disagrees with the "
                            f"detector's {detector_rotation:.2f}")

    matches = neighbour_agreement(corners, georef, found["epsg"], record_id)
    outcome["neighbour_matches"] = len(matches)
    if matches:
        distances = [m[0] for m in matches]
        outcome["neighbour_median_m"] = round(float(np.median(distances)), 1)
        outcome["neighbour_best_m"] = round(distances[0], 1)
        outcome["neighbour_detail"] = [
            f"{m[1]} ~ {m[2].split(':')[-1]}.{m[3]} {m[0]:.0f}m"
            for m in matches[:6]]
    if len(matches) < MIN_NEIGHBOUR_MATCHES:
        failures.append(f"only {len(matches)} neighbour corners within "
                        f"{NEIGHBOUR_MATCH_M:.0f} m - nothing to confirm the "
                        f"anchor")

    if failures:
        outcome["refused"] = "; ".join(failures)
        return outcome

    median = outcome["neighbour_median_m"]
    outcome["precision_class"] = ("corner_fit" if median <= CLASS_TIGHT_M
                                  else "corner_fit_coarse")
    outcome["anchor_basis"] = "printed_corners_only"
    return outcome


FIELDS = ["record_id", "designation", "sheet_name", "lambert_zone", "epsg",
          "grid_easting_lines", "grid_northing_lines", "degenerate_axes",
          "corners_read_e", "corners_read_n",
          "reading_residual_max_m_e", "reading_residual_max_m_n",
          "metres_per_px_x", "metres_per_px_y",
          "rotation_deg", "detector_rotation_deg", "rotation_gap_deg",
          "frame_width_km", "frame_height_km",
          "neighbour_matches", "neighbour_median_m", "neighbour_best_m",
          "precision_class", "anchor_basis", "refused"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--georef", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.json")
    parser.add_argument("--corners", type=Path,
                        default=REPO_ROOT / "data" / "sheet_corners.json")
    parser.add_argument("--grid", type=Path,
                        default=REPO_ROOT / "data" / "sheet_grid.json")
    parser.add_argument("--table", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.csv")
    parser.add_argument("--images", type=Path, default=None,
                        help="scans, only needed to write sidecars")
    parser.add_argument("--out-json", type=Path,
                        default=REPO_ROOT / "data" / "sheet_corner_fit.json")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "sheet_corner_fit.csv")
    parser.add_argument("--sidecars", type=Path,
                        default=REPO_ROOT / "data" / "georef_corner_fit")
    args = parser.parse_args()

    georef = json.loads(args.georef.read_text(encoding="utf-8"))
    corners = json.loads(args.corners.read_text(encoding="utf-8"))
    grid = json.loads(args.grid.read_text(encoding="utf-8"))
    table = {r["record_id"]: r for r in
             csv.DictReader(args.table.open(encoding="utf-8"))}

    results, rows = {}, []
    for record_id, found in sorted(georef.items()):
        if "neatline_px" not in found or "epsg" not in found:
            continue
        # Only sheets the grid path could not finish. A sheet with a good grid
        # fit on both axes keeps it: 20-32 lines beat four corners.
        if not degenerate_axes(found) and not found.get("anchor_provisional"):
            continue
        reading = corners.get(record_id)
        if not reading:
            continue
        outcome = georeference(record_id, found, reading,
                               grid.get(record_id, {}), georef)
        results[record_id] = outcome
        meta = table.get(record_id, {})
        rows.append({"record_id": record_id,
                     "designation": meta.get("designation", ""),
                     "sheet_name": meta.get("sheet_name", ""),
                     **{k: outcome.get(k, "") for k in FIELDS[3:]}})
        if "affine" in outcome and "refused" not in outcome and args.images:
            scan = args.images / f"{record_id}.jpg"
            if scan.exists():
                write_sidecars(args.sidecars, record_id, outcome, scan)

    args.out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    placed = [r for r in rows if r["precision_class"]]
    print(f"{len(rows)} sheets the grid path left unfinished; "
          f"{len(placed)} placed from their printed corners alone\n")
    for row in rows:
        name = row["sheet_name"] or row["record_id"].split(":")[-1]
        if row["precision_class"]:
            print(f"  {name[:20]:20s} {row['precision_class']:18s} "
                  f"corners {row['corners_read_e']}E/{row['corners_read_n']}N  "
                  f"reading resid {row['reading_residual_max_m_e']:>4}/"
                  f"{row['reading_residual_max_m_n']:>4} m  "
                  f"rotation {row['rotation_deg']:+.2f} vs detector "
                  f"{row['detector_rotation_deg']}  "
                  f"{row['neighbour_matches']} shared corners, median "
                  f"{row['neighbour_median_m']} m")
        else:
            print(f"  {name[:20]:20s} {'refused':18s} {row['refused']}")

    if placed:
        medians = [float(r["neighbour_median_m"]) for r in placed]
        print(f"\nShared-corner agreement across the placed sheets: "
              f"{min(medians):.0f}-{max(medians):.0f} m, against the series' "
              f"own 72 m median. An anchor error is a whole kilometre, so every "
              f"one of these anchors is confirmed.")
        print("These are NOT merged into data/sheet_georef.json; they carry "
              "their own precision_class and are consumed only where that "
              "class is acceptable.")
    print(f"\n  -> {args.out_json}\n  -> {args.out_csv}")
    if args.images:
        print(f"  -> {args.sidecars}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

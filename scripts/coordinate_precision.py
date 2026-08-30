#!/usr/bin/env python3
"""Report, per sheet, how precisely an object on it can be located.

The question this answers is "if I pick a well off this sheet, how well do I
know where it is". That depends much less on the map than on which control you
georeference from, and the difference is two orders of magnitude:

  from the catalogue bounding box  - the corners of 29 of 93 sheets are stated
      only to whole arcminutes. If those are rounded rather than exact sheet
      edges, the corner is uncertain by up to 30 arcseconds, which is about
      740 m of longitude and 930 m of latitude at this latitude.

  from the printed kilometric grid - the sheets carry a labelled Lambert grid
      with its corner value printed to the metre ("531.624 m" on La Marsa).
      Grid intersections are control points every kilometre, and localising one
      costs about two pixels.

So the bounding box is for indexing and the printed grid is for georeferencing.
This script quantifies both for every sheet, and flags extents that cannot be
right.

Scan resolution is no longer assumed. It used to be a single constant of 311 dpi
inferred from La Marsa's catalogued paper size; scripts/detect_sheet_grid.py now
measures it on every sheet from the spacing of the printed kilometre grid, and
the two disagree by about 4%. The measurement wins: paper size is catalogued to
the nearest centimetre and describes the sheet rather than the printed image,
whereas the grid is a known one kilometre and is measured over thirty repeats.
Sheets without a measurement fall back to the series median, and the source is
recorded per sheet in `resolution_basis`.

Outputs:
    data/tunisia_50k_precision.csv
    docs/OBJECT-EXTRACTION.md is written by hand and cites these numbers.

Usage:
    python3 scripts/coordinate_precision.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent

SCALE_DENOMINATOR = 50_000
# Used only when a sheet has no measured grid; overwritten at run time by the
# median of the sheets that do.
FALLBACK_METRES_PER_PIXEL = 4.24

# A 1:50 000 sheet of this series should be about 21 x 11 arcminutes; anything
# far outside that is a bad record, not an unusual sheet.
PLAUSIBLE_WIDTH_MIN = 12.0
PLAUSIBLE_WIDTH_MAX = 32.0
PLAUSIBLE_HEIGHT_MIN = 7.0
PLAUSIBLE_HEIGHT_MAX = 16.0


def stated_unit(degrees: float) -> str:
    """Coarsest unit the value is an exact multiple of, i.e. how it was written."""
    for size, name in ((1.0, "degree"), (1 / 60, "minute"), (1 / 3600, "second")):
        if abs(degrees / size - round(degrees / size)) < 1e-6:
            return name
    return "finer"


def metres_per_degree(latitude: float) -> tuple[float, float]:
    return (111_320.0 * math.cos(math.radians(latitude)), 111_132.0)


def assess(box: dict, metres_per_pixel: float, resolution_basis: str) -> dict:
    units = {corner: stated_unit(box[corner])
             for corner in ("west", "east", "north", "south")}
    rank = {"degree": 0, "minute": 1, "second": 2, "finer": 3}
    # Use the FINEST unit any corner needs, not the coarsest. A corner that
    # lands on exactly 37 degrees is not "rounded to the nearest degree" - if a
    # neighbouring corner is written 10d47'36", the record is working in
    # seconds and 37 means 37d00'00". Reading it the other way put the worst
    # case at 45 km, which is nonsense for a sheet 31 km wide.
    working = max(units.values(), key=lambda u: rank[u])

    centre_latitude = (box["north"] + box["south"]) / 2
    lon_m, lat_m = metres_per_degree(centre_latitude)

    # Half the last stated unit is the worst-case rounding error.
    half_unit = {"degree": 0.5, "minute": 0.5 / 60,
                 "second": 0.5 / 3600, "finer": 0.5 / 3600}[working]

    width = (box["east"] - box["west"]) * 60
    height = (box["north"] - box["south"]) * 60
    plausible = (PLAUSIBLE_WIDTH_MIN <= width <= PLAUSIBLE_WIDTH_MAX
                 and PLAUSIBLE_HEIGHT_MIN <= height <= PLAUSIBLE_HEIGHT_MAX)

    return {
        "corner_unit": working,
        "bbox_uncertainty_lon_m": round(half_unit * lon_m),
        "bbox_uncertainty_lat_m": round(half_unit * lat_m),
        "width_arcmin": round(width, 2),
        "height_arcmin": round(height, 2),
        "extent_plausible": "1" if plausible else "0",
        # Grid-based control does not depend on the catalogue corners at all.
        "metres_per_pixel": round(metres_per_pixel, 2),
        "resolution_basis": resolution_basis,
        "grid_uncertainty_m": round(2 * metres_per_pixel),
        "symbol_centre_uncertainty_m": round(4 * metres_per_pixel),
        "recommended_control": "kilometric_grid" if working in ("degree", "minute")
                               else "kilometric_grid (bbox usable as fallback)",
    }


FIELDS = [
    "record_id", "designation", "sheet_name", "revision_year",
    "corner_unit", "bbox_uncertainty_lon_m", "bbox_uncertainty_lat_m",
    "metres_per_pixel", "resolution_basis",
    "grid_uncertainty_m", "symbol_centre_uncertainty_m",
    "width_arcmin", "height_arcmin", "extent_plausible",
    "recommended_control", "url",
]


def load_measured_resolution(path: Path) -> dict[str, float]:
    """record_id -> ground metres per pixel, from the detected kilometre grid."""
    if not path.exists():
        return {}
    measured = {}
    for row in csv.DictReader(path.open(encoding="utf-8")):
        if row.get("has_kilometric_grid") == "1" and row.get("px_per_km"):
            measured[row["record_id"]] = 1000.0 / float(row["px_per_km"])
    return measured


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", type=Path,
                        default=REPO_ROOT / "data" / "tunisia_50k_series.csv")
    parser.add_argument("--partner", type=Path,
                        default=REPO_ROOT / "data" / "partner_records.json")
    parser.add_argument("--grid", type=Path,
                        default=REPO_ROOT / "data" / "sheet_grid.csv")
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "data" / "tunisia_50k_precision.csv")
    args = parser.parse_args()

    measured = load_measured_resolution(args.grid)
    fallback = (float(np.median(list(measured.values()))) if measured
                else FALLBACK_METRES_PER_PIXEL)

    partner = json.loads(args.partner.read_text(encoding="utf-8"))
    rows = []
    for sheet in csv.DictReader(args.series.open(encoding="utf-8")):
        box = partner.get(sheet["record_id"], {}).get("bbox")
        if not box:
            continue
        row = {
            "record_id": sheet["record_id"],
            "designation": sheet["designation"],
            "sheet_name": sheet["sheet_name"],
            "revision_year": sheet["revision_year"] or sheet["published_year"],
            "url": sheet["url"],
        }
        resolution = measured.get(sheet["record_id"])
        row.update(assess(box,
                          resolution if resolution else fallback,
                          "measured_grid" if resolution else "series_median"))
        rows.append(row)

    rows.sort(key=lambda r: (-int(r["bbox_uncertainty_lon_m"]), r["designation"]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    units = Counter(r["corner_unit"] for r in rows)
    basis = Counter(r["resolution_basis"] for r in rows)
    bad = [r for r in rows if r["extent_plausible"] == "0"]
    print(f"{len(rows)} sheets -> {args.out}")
    print(f"  resolution: {fallback:.2f} m/px median "
          f"({(25.4 / fallback) * SCALE_DENOMINATOR / 1000:.0f} dpi); basis {dict(basis)}")
    print(f"  corner precision: {dict(units)}")
    print(f"  grid-based uncertainty: ~{round(2 * fallback)} m "
          f"| symbol centre: ~{round(4 * fallback)} m")
    worst = max(int(r["bbox_uncertainty_lon_m"]) for r in rows)
    print(f"  worst bbox-only uncertainty: {worst} m in longitude")
    if bad:
        print(f"  ! {len(bad)} sheet(s) with an impossible extent:")
        for r in bad:
            print(f"      {r['designation']} {r['sheet_name']}: "
                  f"{r['width_arcmin']}' x {r['height_arcmin']}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())

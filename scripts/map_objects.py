#!/usr/bin/env python3
"""Put the extracted objects onto contemporary Tunisia, and count them by unit.

Joins every symbol extracted from the 1:50 000 sheets to the modern gouvernorat
and délégation it falls in, then draws the result over the contemporary
boundaries.

The one thing this must not do is present extraction coverage as geography.
Symbols have been extracted from ten sheets, so a raw count per gouvernorat says
mostly which sheets happen to be done - a gouvernorat with no extracted sheet
would render as a confident zero and read as "no houses here". Two guards:

  Density, not count. The denominator is the *extracted* area inside each unit -
  the convex hull of that unit's extracted symbols, clipped to the unit - not the
  unit's own area. So the number means "houses per square kilometre of the ground
  actually read", which is comparable across units.

  No data is drawn as no data. Units with no extracted sheet get a hatch, never
  the lightest step of the ramp. The lightest step means "near zero", and near
  zero is a claim.

Outputs:
    data/symbols_by_unit.csv        per gouvernorat and délégation
    data/symbols_joined.geojson     every symbol with its modern unit attached
    docs/img/objects_on_modern_tunisia.png

Usage:
    python3 scripts/map_objects.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import shapefile
from shapely.geometry import MultiPoint, Point, shape
from shapely.strtree import STRtree

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent.parent

# From the data-viz reference palette. Sequential encoding uses one hue,
# light to dark; no-data is a hatch rather than the lightest step.
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES_1 = "#2a78d6"
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5",
              "#256abf", "#184f95", "#0d366b"]
NO_DATA_FACE = "#f0efec"

LEVELS = {2: ("gouvernorat", "adm2_name"), 3: ("délégation", "adm3_name")}


def read_units(path: Path, name_field: str) -> list[dict]:
    reader = shapefile.Reader(str(path))
    fields = [f[0] for f in reader.fields[1:]]
    units = []
    for record in reader.iterShapeRecords():
        attributes = dict(zip(fields, record.record))
        geometry = shape(record.shape.__geo_interface__)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        units.append({"name": attributes.get(name_field) or "?",
                      "parent": attributes.get("adm2_name") or "",
                      "geometry": geometry})
    return units


def load_symbols(directory: Path) -> list[dict]:
    symbols = []
    for path in sorted(directory.glob("*.geojson")):
        collection = json.loads(path.read_text(encoding="utf-8"))
        for feature in collection["features"]:
            lon, lat = feature["geometry"]["coordinates"]
            symbols.append({
                "lon": lon, "lat": lat,
                "symbol_class": feature["properties"]["symbol_class"],
                "record_id": feature["properties"]["record_id"],
            })
    return symbols


def join(symbols: list[dict], units: list[dict]) -> None:
    """Attach each symbol's unit name, in place."""
    geometries = [u["geometry"] for u in units]
    tree = STRtree(geometries)
    for symbol in symbols:
        point = Point(symbol["lon"], symbol["lat"])
        symbol["unit"] = None
        for index in tree.query(point):
            if geometries[index].contains(point):
                symbol["unit"] = units[index]["name"]
                break


def extracted_area_km2(unit: dict, points: list[tuple[float, float]]) -> float:
    """Area of ground actually read inside this unit.

    The hull of a unit's own symbols, clipped to the unit. A unit crossed by an
    extracted sheet but holding only a corner of it should get credit for the
    corner, not the sheet.
    """
    if len(points) < 3:
        return 0.0
    hull = MultiPoint(points).convex_hull
    overlap = hull.intersection(unit["geometry"])
    if overlap.is_empty:
        return 0.0
    # Degrees to km at this latitude; adequate for a density denominator.
    latitude = unit["geometry"].centroid.y
    km_per_degree_lat = 110.574
    km_per_degree_lon = 111.320 * math.cos(math.radians(latitude))
    return overlap.area * km_per_degree_lat * km_per_degree_lon


def summarise(symbols: list[dict], units: list[dict], level_name: str) -> list[dict]:
    by_unit = defaultdict(lambda: defaultdict(int))
    points = defaultdict(list)
    sheets = defaultdict(set)
    for symbol in symbols:
        if symbol["unit"] is None:
            continue
        by_unit[symbol["unit"]][symbol["symbol_class"]] += 1
        points[symbol["unit"]].append((symbol["lon"], symbol["lat"]))
        sheets[symbol["unit"]].add(symbol["record_id"])

    rows = []
    for unit in units:
        name = unit["name"]
        counts = by_unit.get(name, {})
        area = extracted_area_km2(unit, points.get(name, []))
        buildings = counts.get("building", 0)
        rows.append({
            "level": level_name,
            "unit": name,
            "parent_gouvernorat": unit["parent"] if level_name == "délégation" else "",
            "sheets_extracted": len(sheets.get(name, ())),
            "building": buildings,
            "well_provisional": counts.get("well", 0),
            "extracted_km2": round(area, 1),
            "buildings_per_km2": round(buildings / area, 3) if area > 0 else "",
        })
    rows.sort(key=lambda r: (-r["building"], r["unit"]))
    return rows


def ramp_colour(value: float, breaks: list[float]) -> str:
    for index, upper in enumerate(breaks):
        if value <= upper:
            return SEQUENTIAL[index]
    return SEQUENTIAL[-1]


def draw(units2: list[dict], rows2: list[dict], symbols: list[dict],
         footprints: list[list[tuple[float, float]]], out: Path) -> None:
    # Tunisia is about 4.1 degrees wide and 7.3 tall, and the latitude aspect
    # correction stretches the height further, so each panel is roughly twice as
    # tall as it is wide. A landscape figure leaves most of the canvas empty and
    # shrinks both maps; two such panels want a nearly square figure.
    figure, axes = plt.subplots(1, 2, figsize=(9.6, 10.4), facecolor=SURFACE)

    density = {r["unit"]: r["buildings_per_km2"] for r in rows2}
    values = sorted(v for v in density.values() if v != "")
    # Quantile breaks: the distribution is skewed, so equal intervals would put
    # almost every unit in one class.
    breaks = ([float(np.quantile(values, q))
               for q in (1 / 7, 2 / 7, 3 / 7, 4 / 7, 5 / 7, 6 / 7)]
              if len(values) >= 7 else [max(values or [1])] * 6)

    # ---- Panel A: where the objects are
    ax = axes[0]
    ax.set_facecolor(SURFACE)
    for unit in units2:
        for polygon in getattr(unit["geometry"], "geoms", [unit["geometry"]]):
            x, y = polygon.exterior.xy
            ax.fill(x, y, facecolor="#ffffff", edgecolor=GRIDLINE, linewidth=0.6)
    for corners in footprints:
        xs = [c[0] for c in corners] + [corners[0][0]]
        ys = [c[1] for c in corners] + [corners[0][1]]
        ax.plot(xs, ys, color=BASELINE, linewidth=0.7, zorder=2)
    buildings = [(s["lon"], s["lat"]) for s in symbols
                 if s["symbol_class"] == "building"]
    if buildings:
        ax.scatter([p[0] for p in buildings], [p[1] for p in buildings],
                   s=1.6, c=SERIES_1, linewidths=0, alpha=0.8, zorder=3)
    # Counted, not typed in: a number written into a title goes stale silently
    # the first time the extraction is re-run.
    sheets_done = len({s["record_id"] for s in symbols})
    ax.set_title(f"{len(buildings):,} houses extracted from {sheets_done} sheets,\n"
                 f"on the {len(units2)} contemporary gouvernorats"
                 .replace(",", "\u2009"),
                 fontsize=12, color=INK_PRIMARY, loc="left", pad=10)

    # ---- Panel B: how dense, where read
    ax = axes[1]
    ax.set_facecolor(SURFACE)
    for unit in units2:
        value = density.get(unit["name"], "")
        for polygon in getattr(unit["geometry"], "geoms", [unit["geometry"]]):
            x, y = polygon.exterior.xy
            if value == "":
                ax.fill(x, y, facecolor=NO_DATA_FACE, edgecolor=GRIDLINE,
                        linewidth=0.6, hatch="///")
            else:
                ax.fill(x, y, facecolor=ramp_colour(value, breaks),
                        edgecolor=GRIDLINE, linewidth=0.6)
    ax.set_title("Houses per km² of ground read,\nby gouvernorat",
                 fontsize=12, color=INK_PRIMARY, loc="left", pad=10)

    handles = [mpatches.Patch(facecolor=SEQUENTIAL[i], edgecolor=GRIDLINE,
                              label=("≤ %.1f" % breaks[i]) if i < len(breaks)
                              else "> %.1f" % breaks[-1])
               for i in range(len(SEQUENTIAL))]
    handles.append(mpatches.Patch(facecolor=NO_DATA_FACE, edgecolor=GRIDLINE,
                                  hatch="///", label="no sheet extracted"))
    ax.legend(handles=handles, loc="lower left", frameon=False, fontsize=8,
              labelcolor=INK_SECONDARY, title="houses / km²",
              title_fontsize=8.5, ncols=2, handlelength=1.4,
              columnspacing=1.0, borderaxespad=0.0)

    for ax in axes:
        ax.set_aspect(1 / math.cos(math.radians(34.0)))
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    figure.text(0.03, 0.115,
                "Hairline rectangles: the 73 georeferenced sheets.\n"
                "Dots: individual houses, from the legend's “Maisons” mark.",
                fontsize=8.5, color=INK_SECONDARY, va="top")
    figure.text(0.53, 0.115,
                "Denominator is extracted area, not gouvernorat area.\n"
                "Hatched units are not zero — no sheet extracted there yet.",
                fontsize=8.5, color=INK_SECONDARY, va="top")
    figure.suptitle("Objects from the Tunisia 1:50 000 series, on contemporary boundaries",
                    fontsize=13.5, color=INK_PRIMARY, x=0.03, ha="left", y=0.978)
    figure.text(0.03, 0.018,
                "Symbols: Service géographique de l'Armée / IGN sheets, fieldwork 1880s–1930s, "
                "georeferenced from their printed Lambert grid (16 m rms).\n"
                "Boundaries: OCHA Common Operational Dataset for Tunisia, CC BY-IGO.",
                fontsize=8, color=INK_MUTED, va="bottom")
    figure.subplots_adjust(left=0.02, right=0.98, top=0.905, bottom=0.155,
                           wspace=0.02)
    out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out, dpi=170, facecolor=SURFACE)
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=Path,
                        default=REPO_ROOT / "data" / "symbols")
    parser.add_argument("--boundaries", type=Path,
                        default=REPO_ROOT / "data" / "boundaries")
    parser.add_argument("--georef", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.json")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "symbols_by_unit.csv")
    parser.add_argument("--out-geojson", type=Path,
                        default=REPO_ROOT / "data" / "symbols_joined.geojson")
    parser.add_argument("--out-png", type=Path,
                        default=REPO_ROOT / "docs" / "img"
                                / "objects_on_modern_tunisia.png")
    args = parser.parse_args()

    symbols = load_symbols(args.symbols)
    print(f"{len(symbols)} symbols from {len(set(s['record_id'] for s in symbols))} sheets")

    all_rows = []
    for level, (level_name, name_field) in LEVELS.items():
        units = read_units(args.boundaries / f"tun_admin{level}", name_field)
        join(symbols, units)
        for symbol in symbols:
            symbol[level_name] = symbol.pop("unit")
        rows = summarise(
            [{**s, "unit": s[level_name]} for s in symbols], units, level_name)
        all_rows.extend(rows)
        with_any = [r for r in rows if r["building"] > 0]
        print(f"  admin{level} ({level_name}): {len(units)} units, "
              f"{len(with_any)} with extracted houses")
        if level == 2:
            units2, rows2 = units, rows

    fields = ["level", "unit", "parent_gouvernorat", "sheets_extracted",
              "building", "well_provisional", "extracted_km2",
              "buildings_per_km2"]
    with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)

    args.out_geojson.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {k: s[k] for k in
                           ("symbol_class", "record_id", "gouvernorat",
                            "délégation")},
        } for s in symbols],
    }, ensure_ascii=False), encoding="utf-8")

    georef = json.loads(args.georef.read_text(encoding="utf-8"))
    footprints = []
    for found in georef.values():
        corners = found.get("corners")
        if not corners:
            continue
        footprints.append([(corners[k]["lon"], corners[k]["lat"]) for k in
                           ("north_west", "north_east", "south_east",
                            "south_west")])

    draw(units2, rows2, symbols, footprints, args.out_png)

    top = [r for r in all_rows if r["level"] == "gouvernorat"][:6]
    print("\n  busiest gouvernorats by extracted houses:")
    for row in top:
        print(f"    {row['unit'][:20]:<20} {row['building']:>5} houses  "
              f"{row['extracted_km2']:>7} km²  "
              f"{row['buildings_per_km2'] or '—':>7} /km²")
    print(f"\n  -> {args.out_csv}\n  -> {args.out_geojson}\n  -> {args.out_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

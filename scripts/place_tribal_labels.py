#!/usr/bin/env python3
"""Put the tribal names printed on a map onto the ground, and say how well.

A tribe on these maps is not a polygon. It is a name in letterspaced capitals
laid across the country it holds, with no boundary drawn anywhere - not on the
1853 Pellissier, not on the 1881 war-theatre sheet, not on the 1:800 000
itinerary series. Whoever drew them knew where a tribe was and did not claim to
know where it ended. Anything this module produces has to keep that distinction,
so it emits **points, and calls them label anchors**, never territories with
edges.

What a point means, precisely: *the engraver centred this tribe's name here*.
Six labels measured on the tiles run 175 to 400 px - 14 to 32 km of ground - so
the point locates the tribe to within a tribe's width. Reading the same label
twice from two overlapping tiles agreed to 3-5 px, and the two towns read twice
agreed to 3 px, so transcription is not what limits this. The annotation is.

**Georeferencing.** From towns, not from the printed graticule, for a reason
worth stating: the graticule is legible but the frame is not square on the scan
- the 8 degree tick on the top border and the one on the bottom border are 141 px
apart in x - so a transform fitted to the border ticks inherits the frame's own
skew. Seven towns with known modern coordinates give an affine instead, and the
residual is then a measurement rather than a leftover: it is how far the 1881
compilation sits from the ground, plus how well I read a printed dot.

The residual is reported two ways. In-sample RMS is what the fit achieves on the
points it was given. Leave-one-out RMS refits without each town and predicts it,
which is the number that means anything for a label the fit has never seen - and
on seven points it is the larger of the two. Both are printed.

An affine is the right model and not a neutral one: it absorbs rotation, scale
and shear but cannot bend, so on a sheet drawn on a conic projection the
curvature it cannot follow ends up inside the residual. At this scale, over this
extent, that is small compared with the thing being measured.

Outputs:
    data/tribal_territories.csv        one row per label, with lon/lat
    data/tribal_territories.geojson    EPSG:4326 points
    data/tribal_fit.json               per-map transform and residuals
    docs/img/tribal_territories.png    the labels on contemporary boundaries

Usage:
    python3 scripts/place_tribal_labels.py
    python3 scripts/place_tribal_labels.py --no-figure
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import unicodedata
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shapefile
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent.parent

# Five decimals is about a metre, which already overstates a coordinate whose
# stated accuracy is kilometres. Three decimals - about 100 m - is as fine as
# anything here deserves, and says so by being visibly coarse.
COORD_DECIMALS = 3

# One hue for the tribal points, a neutral ground for the boundaries. The
# frontier tribes are drawn in the same hue at lower alpha rather than a second
# colour: they are the same kind of object, read off the same sheet, and only
# happen to fall outside the modern border.
INK = "#2f5f8f"
INK_OUTSIDE = "#9aaec4"
LAND = "#f2efe9"
LINE = "#c9c2b6"


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(text))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def normalise(text: str) -> str:
    """Lowercase, accent-free, punctuation-free, single-spaced."""
    return re.sub(r"[^a-z0-9]+", " ", strip_accents(text).lower()).strip()


def load_gazetteer(path: Path) -> dict:
    entries = json.loads(path.read_text(encoding="utf-8"))["tribes"]
    lookup = {}
    for entry in entries:
        keys = {normalise(entry["name"])}
        keys |= {normalise(v) for v in entry.get("variants", [])}
        for key in keys:
            lookup.setdefault(key, entry)
    return lookup


def canonical(text: str, lookup: dict) -> tuple[str, bool]:
    """Map a printed label to a gazetteer name. Returns (name, matched)."""
    key = normalise(text)
    if key in lookup:
        return lookup[key]["name"], True
    # 'O. Riah' and 'Ouled Riah' are the same tribe with the prefix abbreviated,
    # and the sheets use both on one face. Expand the abbreviation and retry
    # before giving up, but never guess past that.
    expanded = re.sub(r"^(o|od|oulad|ouled)\b", "ouled", key)
    if expanded in lookup:
        return lookup[expanded]["name"], True
    stripped = re.sub(r"^ouled\s+", "", key)
    if stripped in lookup:
        return lookup[stripped]["name"], True
    return text, False


def fit_affine(points: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Least squares (lon, lat, 1) -> x and -> y."""
    design = np.array([[p["lon"], p["lat"], 1.0] for p in points])
    xs = np.array([p["x"] for p in points], dtype=float)
    ys = np.array([p["y"] for p in points], dtype=float)
    cx, *_ = np.linalg.lstsq(design, xs, rcond=None)
    cy, *_ = np.linalg.lstsq(design, ys, rcond=None)
    return cx, cy


def px_per_degree(cx: np.ndarray, cy: np.ndarray) -> tuple[float, float]:
    return math.hypot(cx[0], cy[0]), math.hypot(cx[1], cy[1])


def residuals(points: list[dict], cx: np.ndarray, cy: np.ndarray) -> np.ndarray:
    design = np.array([[p["lon"], p["lat"], 1.0] for p in points])
    dx = design @ cx - np.array([p["x"] for p in points], dtype=float)
    dy = design @ cy - np.array([p["y"] for p in points], dtype=float)
    return np.hypot(dx, dy)


def leave_one_out(points: list[dict]) -> np.ndarray:
    """Refit without each point and predict it. Four points is the minimum that
    still leaves an over-determined fit behind, so this stops at that."""
    out = []
    for i in range(len(points)):
        rest = points[:i] + points[i + 1:]
        if len(rest) < 4:
            continue
        cx, cy = fit_affine(rest)
        out.append(residuals([points[i]], cx, cy)[0])
    return np.array(out)


def invert(cx: np.ndarray, cy: np.ndarray, x: float, y: float) -> tuple[float, float]:
    """Pixel back to lon/lat. The forward map is affine, so this is a 2x2 solve."""
    matrix = np.array([[cx[0], cx[1]], [cy[0], cy[1]]])
    rhs = np.array([x - cx[2], y - cy[2]])
    lon, lat = np.linalg.solve(matrix, rhs)
    return float(lon), float(lat)


def load_units(path: Path, name_field: str) -> tuple[STRtree, list[dict]]:
    reader = shapefile.Reader(str(path))
    units = []
    for shape_rec in reader.shapeRecords():
        attributes = shape_rec.record.as_dict()
        geometry = shape(shape_rec.shape.__geo_interface__)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        units.append({"name": attributes.get(name_field) or "", "geom": geometry})
    return STRtree([u["geom"] for u in units]), units


def join_unit(tree: STRtree, units: list[dict], lon: float, lat: float) -> str:
    point = Point(lon, lat)
    for idx in tree.query(point):
        if units[int(idx)]["geom"].contains(point):
            return units[int(idx)]["name"]
    return ""


def place(config: dict, gazetteer: dict) -> tuple[list[dict], dict]:
    tree2, units2 = load_units(REPO_ROOT / "data" / "boundaries" / "tun_admin2.shp",
                              "adm2_name")
    rows, fits = [], {}
    for record_id, sheet in config["maps"].items():
        control = sheet["control_points"]
        cx, cy = fit_affine(control)
        res = residuals(control, cx, cy)
        loo = leave_one_out(control)
        _, py_lat = px_per_degree(cx, cy)
        km_per_px = 111.0 / py_lat
        fits[record_id] = {
            "title": sheet["title"],
            "year": sheet["year"],
            "scale": sheet.get("scale", ""),
            "control_points": len(control),
            "px_per_degree_lon": round(px_per_degree(cx, cy)[0], 1),
            "px_per_degree_lat": round(py_lat, 1),
            "km_per_px": round(km_per_px, 4),
            "rms_px": round(float(np.sqrt((res ** 2).mean())), 1),
            "rms_km": round(float(np.sqrt((res ** 2).mean()) * km_per_px), 2),
            "max_px": round(float(res.max()), 1),
            "loo_rms_px": round(float(np.sqrt((loo ** 2).mean())), 1) if len(loo) else None,
            "loo_rms_km": round(float(np.sqrt((loo ** 2).mean()) * km_per_px), 2) if len(loo) else None,
            "per_town": {p["place"]: round(float(r), 1) for p, r in zip(control, res)},
            "labels": len(sheet["labels"]),
        }
        for label in sheet["labels"]:
            lon, lat = invert(cx, cy, label["x"], label["y"])
            name, matched = canonical(label["text"], gazetteer)
            unit = join_unit(tree2, units2, lon, lat)
            rows.append({
                "record_id": record_id,
                "year": sheet["year"],
                "label_as_printed": label["text"],
                "tribe": name,
                "in_gazetteer": int(matched),
                "marker": label["marker"] or "",
                "marked_tribe": int(bool(label["marker"])),
                "x_px": label["x"],
                "y_px": label["y"],
                "lon": round(lon, COORD_DECIMALS),
                "lat": round(lat, COORD_DECIMALS),
                "gouvernorat": unit,
                "inside_tunisia": int(bool(unit)),
                "read_confidence": label["read_confidence"],
            })
    return rows, fits


def write_csv(rows: list[dict], path: Path) -> None:
    fields = ["record_id", "year", "label_as_printed", "tribe", "in_gazetteer",
              "marker", "marked_tribe", "x_px", "y_px", "lon", "lat",
              "gouvernorat", "inside_tunisia", "read_confidence"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_geojson(rows: list[dict], fits: dict, path: Path) -> None:
    features = []
    for row in rows:
        properties = {k: v for k, v in row.items() if k not in ("lon", "lat")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
            "properties": properties,
        })
    collection = {
        "type": "FeatureCollection",
        "name": "tribal_label_anchors",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "note": ("Points are where a tribe's name is centred on the sheet, not "
                 "territory centroids; no sheet in this collection draws a tribal "
                 "boundary. Positional accuracy is in data/tribal_fit.json."),
        "fit": fits,
        "features": features,
    }
    path.write_text(json.dumps(collection, ensure_ascii=False, indent=1), encoding="utf-8")


def draw(rows: list[dict], fits: dict, path: Path) -> None:
    reader0 = shapefile.Reader(str(REPO_ROOT / "data" / "boundaries" / "tun_admin0.shp"))
    country = shape(reader0.shapeRecords()[0].shape.__geo_interface__)
    _, units2 = load_units(REPO_ROOT / "data" / "boundaries" / "tun_admin2.shp",
                           "adm2_name")

    figure, ax = plt.subplots(figsize=(7.2, 9.6), dpi=170)
    for unit in units2:
        for geom in (unit["geom"].geoms if unit["geom"].geom_type == "MultiPolygon"
                     else [unit["geom"]]):
            xs, ys = geom.exterior.xy
            ax.fill(xs, ys, facecolor=LAND, edgecolor=LINE, linewidth=0.4, zorder=1)
    for geom in (country.geoms if country.geom_type == "MultiPolygon" else [country]):
        xs, ys = geom.exterior.xy
        ax.plot(xs, ys, color="#8d8579", linewidth=0.9, zorder=2)

    inside = [r for r in rows if r["inside_tunisia"]]
    outside = [r for r in rows if not r["inside_tunisia"]]
    ax.scatter([r["lon"] for r in outside], [r["lat"] for r in outside], s=16,
               facecolor=INK_OUTSIDE, edgecolor="none", zorder=3)
    ax.scatter([r["lon"] for r in inside], [r["lat"] for r in inside], s=26,
               facecolor=INK, edgecolor="white", linewidth=0.4, zorder=4)
    # The north-west is where the annotation is densest, which is the finding and
    # also what makes the names collide. Offsets alternate side and height for
    # points that sit within half a degree of one already labelled.
    placed: list[tuple[float, float]] = []
    for row in sorted(inside, key=lambda r: (-r["lat"], r["lon"])):
        crowded = sum(1 for lon, lat in placed
                      if abs(lon - row["lon"]) < 0.45 and abs(lat - row["lat"]) < 0.25)
        dx, dy = (6, 2) if crowded % 2 == 0 else (-6, -8)
        ax.annotate(row["tribe"], (row["lon"], row["lat"]),
                    textcoords="offset points", xytext=(dx, dy), fontsize=4.6,
                    ha="left" if dx > 0 else "right", color="#1d3d52", zorder=5)
        placed.append((row["lon"], row["lat"]))

    fit = next(iter(fits.values()))
    ax.set_xlim(7.3, 11.9)
    ax.set_ylim(32.9, 37.7)
    ax.set_aspect(1 / math.cos(math.radians(35.3)))
    ax.set_axis_off()
    years = sorted({str(f["year"]) for f in fits.values()})
    ax.set_title(f"Where the {', '.join(years)} sheet puts each tribe's name"
                 if len(years) == 1 else
                 f"Where the {', '.join(years)} sheets put each tribe's name",
                 fontsize=10, color="#26231e", loc="left", pad=10)
    ax.text(0.0, -0.02,
            f"{len(inside)} labels inside modern Tunisia, {len(outside)} west of the "
            f"frontier (pale).\nPoints are label centres, not territory centroids: no "
            f"tribal boundary is drawn on the sheet.\nFit to {fit['control_points']} towns, "
            f"leave-one-out RMS {fit['loo_rms_km']} km.",
            transform=ax.transAxes, fontsize=6.2, color="#57534a", va="top")
    figure.tight_layout()
    figure.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=REPO_ROOT / "config" / "tribal_labels_read.json")
    parser.add_argument("--gazetteer", type=Path,
                        default=REPO_ROOT / "config" / "tribal_gazetteer.json")
    parser.add_argument("--no-figure", action="store_true")
    args = parser.parse_args(argv)

    config = json.loads(args.config.read_text(encoding="utf-8"))
    gazetteer = load_gazetteer(args.gazetteer)
    rows, fits = place(config, gazetteer)

    write_csv(rows, REPO_ROOT / "data" / "tribal_territories.csv")
    write_geojson(rows, fits, REPO_ROOT / "data" / "tribal_territories.geojson")
    (REPO_ROOT / "data" / "tribal_fit.json").write_text(
        json.dumps(fits, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.no_figure:
        draw(rows, fits, REPO_ROOT / "docs" / "img" / "tribal_territories.png")

    for record_id, fit in fits.items():
        print(f"{record_id} {fit['year']} {fit['labels']} labels, "
              f"RMS {fit['rms_px']} px ({fit['rms_km']} km), "
              f"leave-one-out {fit['loo_rms_px']} px ({fit['loo_rms_km']} km)")
    unmatched = [r["label_as_printed"] for r in rows if not r["in_gazetteer"]]
    print(f"{len(rows)} labels placed, {sum(r['inside_tunisia'] for r in rows)} inside "
          f"modern Tunisia, {len(unmatched)} not in the gazetteer")
    if unmatched:
        print("  not matched: " + ", ".join(unmatched))
    return 0


if __name__ == "__main__":
    sys.exit(main())

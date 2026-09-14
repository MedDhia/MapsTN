#!/usr/bin/env python3
"""The spread of each tribe, drawn as a field rather than an area.

A tribe on these sheets is a name laid across country, with no line around it.
Three ways of drawing that have been tried here and the first two are recorded
in the repository because they failed in instructive, opposite directions.

  A dot at each label is exact and says almost nothing: it marks where an
  engraver centred a word and leaves every question about extent unanswered.

  Filling administrative units - the imada, the finest published Tunisian unit -
  answers the extent question by inventing it. However the caption is worded, a
  filled polygon reads as territory, and worse, it confines a nineteenth-century
  tribe inside a 2022 administrative mesh that has nothing to do with it. A
  sprinkle of dots inside those same polygons is the same error with softer
  edges: still clipped to units, still stopping at the modern frontier.

What is drawn here instead is a field. Each tribe's labels are convolved with a
Gaussian of 18 km and painted as a continuous alpha ramp, one hue per
cartographer, so each sheet's reach appears as a soft surface that fades out
rather than ending. There is no contour line anywhere in it, because a line here
would be read as an edge. Nothing is clipped: not to the imada, not to the gouvernorat, not to the modern border,
which the 31 labels printed on what is now Algerian ground quietly insist on.
Mounds overlap where sources disagree or where tribes genuinely interleaved, and
the overlap is left visible rather than resolved.

The bandwidth is not a free parameter. Six labels measured on the tiles run 14
to 32 km end to end, a median of about 22, and a Gaussian of sigma 18 km has its
half-peak at a radius of 21 km, so the surface falls to half about one printed
name away from the engraving. The blur is the annotation's own grain.

Four panels: one per cartographer on his own names, and one pooled.

    1853  Pellissier, read off the Gallica scan, Tell to about 34 N
    1881  Lasailly, read off the Gallica scan, whole face
    1881  Martel 1965, a historian's sketch map, whole country, secondary

Outputs:
    docs/img/tribal_spread.png
    data/tribal_spread.csv              one row per tribe: how many labels, how
                                        far apart, how much ground the field
                                        covers
    data/tribal_imada_assignment.csv    the modern-unit index, unchanged in
                                        kind: which tribe's name is nearest each
                                        of the 2,084 imadas
    data/tribal_spread_summary.json

Usage:
    python3 scripts/map_tribal_spread.py
    python3 scripts/map_tribal_spread.py --sigma-km 25
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import textwrap
import warnings
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import shapefile
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from shapely.geometry import Point, shape

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent.parent
BOUNDARIES = REPO_ROOT / "data" / "boundaries"

SOURCES = ["1853 Pellissier", "1881 Lasailly", "1881 Martel (1965)"]
SOURCE_INK = {"1853 Pellissier": "#a5642a",
              "1881 Lasailly": "#2f5f8f",
              "1881 Martel (1965)": "#4a7c59"}

LAND = "#f7f5f1"
ABROAD = "#efece6"
MESH = "#e4dfd5"
LINE = "#c3bbae"
COAST = "#6b645a"
FRONTIER = "#8d8579"

DEFAULT_SIGMA_KM = 18.0
# Four nested rings at these fractions of each tribe's own peak. Stacked at low
# alpha they read as a gradient, so no single line looks like a boundary.
# Each tribe is painted as a continuous alpha ramp rather than as contour
# rings. Rings, however many and however faint, still draw lines, and a line on
# this figure would be read as an edge. GAMMA above 1 pulls the faint tail in so
# a mound has a core rather than a uniform haze; PEAK_ALPHA is what one tribe
# alone reaches at its crest, low enough that two overlapping tribes are
# visibly two.
GAMMA = 1.5
PEAK_ALPHA = 0.72
# The level at which a field is called part of a tribe, for the areas reported
# in data/tribal_spread.csv. Half the peak, which for this sigma is a radius of
# about one printed name.
HALF = 0.5

# The window is the sheets' own, not the country's: it has to hold the labels
# printed west of the frontier.
WEST, EAST, SOUTH, NORTH = 6.9, 11.95, 30.1, 37.9
STEP = 0.02

KM_PER_DEG_LAT = 110.574
LAT0 = 34.5
KM_PER_DEG_LON = 111.320 * math.cos(math.radians(LAT0))

DEFAULT_CUTOFF_KM = 60.0


def to_km(lon, lat):
    return np.asarray(lon) * KM_PER_DEG_LON, np.asarray(lat) * KM_PER_DEG_LAT


def read_points() -> list[dict]:
    points = []
    path = REPO_ROOT / "data" / "tribal_territories.csv"
    for row in csv.DictReader(path.open(encoding="utf-8")):
        points.append({
            "tribe": row["tribe"] or row["label_as_printed"],
            "label": row["label_as_printed"],
            "source": ("1853 Pellissier" if row["year"] == "1853"
                       else "1881 Lasailly"),
            "lon": float(row["lon"]), "lat": float(row["lat"]),
            "inside": row["inside_tunisia"] == "1",
        })
    martel = REPO_ROOT / "data" / "martel_1965_tribes.csv"
    if martel.exists():
        reader = shapefile.Reader(str(BOUNDARIES / "tun_admin0.shp"))
        tunisia = shape(reader.shapeRecords()[0].shape.__geo_interface__)
        for row in csv.DictReader(martel.open(encoding="utf-8")):
            lon, lat = float(row["lon"]), float(row["lat"])
            points.append({
                "tribe": row["tribe"], "label": row["label_as_printed"],
                "source": "1881 Martel (1965)",
                "lon": lon, "lat": lat,
                # The Martel CSV carries no inside flag, so it is computed here
                # rather than assumed: four of his names are west of the
                # frontier and assuming otherwise undercounted the crossings.
                "inside": tunisia.contains(Point(lon, lat)),
            })
    return points


def load_imadas(path: Path) -> list[dict]:
    reader = shapefile.Reader(str(path))
    out = []
    for shape_rec in reader.shapeRecords():
        attributes = shape_rec.record.as_dict()
        geometry = shape(shape_rec.shape.__geo_interface__)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        inside = geometry.representative_point()
        out.append({
            "pcode": attributes["adm4_pcode"], "imada": attributes["adm4_name"],
            "delegation": attributes["adm3_name"],
            "gouvernorat": attributes["adm2_name"],
            "area_sqkm": float(attributes["area_sqkm"] or 0),
            "geom": geometry, "lon": inside.x, "lat": inside.y,
        })
    return out


def exteriors(geometry) -> list[np.ndarray]:
    geoms = geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]
    return [np.asarray(g.exterior.coords) for g in geoms]


def grid():
    lons = np.arange(WEST, EAST + STEP, STEP)
    lats = np.arange(SOUTH, NORTH + STEP, STEP)
    mesh_lon, mesh_lat = np.meshgrid(lons, lats)
    return lons, lats, mesh_lon * KM_PER_DEG_LON, mesh_lat * KM_PER_DEG_LAT


def field(points: list[dict], gx: np.ndarray, gy: np.ndarray,
          sigma_km: float) -> np.ndarray:
    """Sum of Gaussians at a tribe's labels, normalised to its own peak."""
    total = np.zeros_like(gx)
    for point in points:
        px, py = to_km(point["lon"], point["lat"])
        total += np.exp(-((gx - px) ** 2 + (gy - py) ** 2) / (2 * sigma_km ** 2))
    peak = total.max()
    return total / peak if peak else total


def surface(points: list[dict], gx: np.ndarray, gy: np.ndarray,
            sigma_km: float) -> np.ndarray:
    """How close the nearest printed name of this sheet is, everywhere.

    exp(-d^2 / 2 sigma^2) for d the distance to the nearest label, so the value
    is 1 where a name is printed, 0.5 at 1.177 sigma - about one printed name
    away - and fades to nothing beyond. Taking the nearest rather than summing
    is deliberate: a sum would make a crowded corner of the country look like
    strong evidence about one tribe when it is really several names side by
    side, and the crowding is already visible in the label dots.
    """
    if not points:
        return np.zeros_like(gx)
    nearest_sq = np.full(gx.shape, np.inf)
    for point in points:
        px, py = to_km(point["lon"], point["lat"])
        np.minimum(nearest_sq, (gx - px) ** 2 + (gy - py) ** 2, out=nearest_sq)
    return np.exp(-nearest_sq / (2 * sigma_km ** 2))


def paint(layers: list[tuple[np.ndarray, str]]) -> np.ndarray:
    """Alpha-composite one or more single-hue surfaces into an RGBA image.

    No contour anywhere in it. A line on this figure would be read as a
    boundary, and there are no boundaries to draw.
    """
    from matplotlib.colors import to_rgb

    shape_ = layers[0][0].shape
    out_rgb = np.zeros(shape_ + (3,))
    out_a = np.zeros(shape_)
    for grid_field, colour in layers:
        alpha = np.clip(grid_field, 0, 1) ** GAMMA * PEAK_ALPHA
        rgb = np.array(to_rgb(colour))
        out_rgb = rgb * alpha[..., None] + out_rgb * (1 - alpha)[..., None]
        out_a = alpha + out_a * (1 - alpha)
    return np.dstack([out_rgb, out_a])


def spread_table(points: list[dict], fields: dict[str, np.ndarray],
                 sigma_km: float, path: Path) -> list[dict]:
    """How far a tribe's own labels stand apart, and how much ground its field
    covers. The first is evidence, the second is the first plus the bandwidth."""
    cell_km2 = (STEP * KM_PER_DEG_LON) * (STEP * KM_PER_DEG_LAT)
    by_tribe: dict[str, list[dict]] = defaultdict(list)
    for point in points:
        by_tribe[point["tribe"]].append(point)

    rows = []
    for tribe, members in by_tribe.items():
        xs, ys = to_km([m["lon"] for m in members], [m["lat"] for m in members])
        widest = 0.0
        for i, j in combinations(range(len(members)), 2):
            widest = max(widest, math.hypot(xs[i] - xs[j], ys[i] - ys[j]))
        rows.append({
            "tribe": tribe,
            "labels": len(members),
            "sources": len({m["source"] for m in members}),
            "sources_named": " | ".join(sorted({m["source"] for m in members})),
            "printed_as": " | ".join(sorted({m["label"] for m in members})),
            "lon": round(sum(m["lon"] for m in members) / len(members), 3),
            "lat": round(sum(m["lat"] for m in members) / len(members), 3),
            "widest_label_gap_km": round(widest, 1),
            "field_sqkm_half_peak": round(
                float((fields[tribe] >= HALF).sum()) * cell_km2),
            "labels_outside_modern_tunisia": sum(1 for m in members
                                                 if not m["inside"]),
        })
    rows.sort(key=lambda r: -r["field_sqkm_half_peak"])
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def nearest(imadas: list[dict], points: list[dict], cutoff_km: float) -> dict:
    if not points:
        return {}
    px = np.column_stack(to_km([p["lon"] for p in points],
                               [p["lat"] for p in points]))
    out = {}
    for unit in imadas:
        ux, uy = to_km(unit["lon"], unit["lat"])
        distances = np.hypot(px[:, 0] - ux, px[:, 1] - uy)
        index = int(distances.argmin())
        distance = float(distances[index])
        if distance > cutoff_km:
            out[unit["pcode"]] = ("", "", round(distance, 1), "", "")
            continue
        winner = points[index]["tribe"]
        runner, runner_km = "", ""
        for candidate in np.argsort(distances)[1:]:
            if points[int(candidate)]["tribe"] != winner:
                runner = points[int(candidate)]["tribe"]
                runner_km = round(float(distances[int(candidate)]), 1)
                break
        out[unit["pcode"]] = (winner, points[index]["source"],
                              round(distance, 1), runner, runner_km)
    return out


def write_assignment(imadas, per_source, pooled, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "adm4_pcode", "imada", "delegation", "gouvernorat", "area_sqkm",
            "tribe_1853_pellissier", "km_1853", "tribe_1881_lasailly", "km_1881",
            "tribe_1881_martel", "km_martel", "tribe_pooled", "source_pooled",
            "km_pooled", "runner_up", "runner_up_km", "sources_naming",
            "sources_agreeing"])
        for unit in sorted(imadas, key=lambda u: (u["gouvernorat"],
                                                  u["delegation"], u["imada"])):
            row = [unit["pcode"], unit["imada"], unit["delegation"],
                   unit["gouvernorat"], round(unit["area_sqkm"], 2)]
            named = []
            for name in SOURCES:
                tribe, _, distance, *_ = per_source[name].get(
                    unit["pcode"], ("", "", "", "", ""))
                row += [tribe, distance if tribe else ""]
                if tribe:
                    named.append(tribe)
            tribe, source, distance, runner, runner_km = pooled.get(
                unit["pcode"], ("", "", "", "", ""))
            agreeing = sum(1 for t in named if t == tribe) if tribe else 0
            row += [tribe, source, distance if tribe else "", runner, runner_km,
                    len(named), agreeing]
            writer.writerow(row)


def basemap(ax, tunisia, gouvernorats, imada_lines, neighbours):
    for feature in neighbours:
        for ring in exteriors(feature["geom"]):
            ax.fill(ring[:, 0], ring[:, 1], facecolor=ABROAD, edgecolor="none",
                    zorder=0)
            ax.plot(ring[:, 0], ring[:, 1], color=LINE, linewidth=0.4, zorder=1)
    for ring in exteriors(tunisia):
        ax.fill(ring[:, 0], ring[:, 1], facecolor=LAND, edgecolor="none",
                zorder=1)
    ax.add_collection(LineCollection(imada_lines, colors=MESH, linewidths=0.1,
                                     zorder=2))
    ax.add_collection(LineCollection(gouvernorats, colors=LINE, linewidths=0.3,
                                     zorder=3))
    for ring in exteriors(tunisia):
        ax.plot(ring[:, 0], ring[:, 1], color=COAST, linewidth=0.7, zorder=4)


def draw(panels, points, sigma_km, lons, lats, path, stats):
    reader0 = shapefile.Reader(str(BOUNDARIES / "tun_admin0.shp"))
    tunisia = shape(reader0.shapeRecords()[0].shape.__geo_interface__)
    reader2 = shapefile.Reader(str(BOUNDARIES / "tun_admin2.shp"))
    gouvernorats = [ring for s in reader2.shapeRecords()
                    for ring in exteriors(shape(s.shape.__geo_interface__))]
    imada_lines = []
    imada_path = BOUNDARIES / "tun_admin4.shp"
    if imada_path.exists():
        reader4 = shapefile.Reader(str(imada_path))
        imada_lines = [ring for s in reader4.shapeRecords()
                       for ring in exteriors(shape(s.shape.__geo_interface__))]
    neighbours = []
    neighbour_path = BOUNDARIES / "neighbours_ne50m.geojson"
    if neighbour_path.exists():
        for feature in json.loads(neighbour_path.read_text())["features"]:
            neighbours.append({"name": feature["properties"]["name"],
                               "geom": shape(feature["geometry"])})

    figure, axes = plt.subplots(1, 4, figsize=(12.8, 7.6), dpi=200)

    for ax, (title, layers, fields, panel) in zip(axes, panels):
        basemap(ax, tunisia, gouvernorats, imada_lines, neighbours)
        ax.imshow(paint(layers), origin="lower", interpolation="bilinear",
                  zorder=5, extent=(lons[0], lons[-1], lats[0], lats[-1]),
                  aspect="auto")
        for point in points:
            if title != "All three, pooled" and point["source"] != title:
                continue
            ax.plot([point["lon"]], [point["lat"]], marker="o", markersize=2.2,
                    markerfacecolor=SOURCE_INK[point["source"]],
                    markeredgecolor="white", markeredgewidth=0.4, zorder=7)

        # A name at the crest of the biggest mounds, so the field can be read.
        crests = sorted(fields.items(),
                        key=lambda kv: -(kv[1] >= HALF).sum())[:20]
        for tribe, grid_field in crests:
            j, i = np.unravel_index(int(grid_field.argmax()), grid_field.shape)
            ax.annotate(tribe, (lons[i], lats[j]), fontsize=4.3, ha="center",
                        va="center", color="#33302a", zorder=8)

        ax.set_xlim(WEST + 0.1, EAST - 0.05)
        ax.set_ylim(SOUTH + 0.05, NORTH - 0.15)
        ax.set_aspect(1 / math.cos(math.radians(LAT0)))
        ax.set_axis_off()
        ax.set_title(title, fontsize=8.5, color="#26231e", loc="left", pad=6)
        ax.text(0.0, 0.235,
                f"{panel['points']} names, {panel['tribes']} tribes\n"
                f"{panel['outside']} of them printed on ground\nthat is now "
                f"Algeria\nwidest tribe {panel['widest']:,} km²",
                transform=ax.transAxes, fontsize=5.8, color="#57534a", va="top")

    axes[3].legend(handles=[Line2D([], [], marker="o", linestyle="none",
                                   color=SOURCE_INK[s], markersize=4, label=s)
                            for s in SOURCES],
                   loc="lower left", bbox_to_anchor=(0.0, 0.02), frameon=False,
                   fontsize=6.2)

    figure.suptitle("The spread of each tribe, as four cartographers had it",
                    fontsize=12.5, color="#26231e", x=0.02, ha="left", y=0.985)
    figure.text(0.02, 0.947,
                f"Each tribe's printed names blurred by {sigma_km:.0f} km and "
                "painted as a continuous surface, one hue per cartographer. "
                "No contour line anywhere in it, and nothing clipped to a "
                "boundary.",
                fontsize=7.4, color="#3a352d", va="top")

    caption = (
        f"The bandwidth is not a free choice. Six labels measured on the tiles "
        f"run 14 to 32 km end to end, a median of about 22, and a Gaussian of "
        f"sigma {sigma_km:.0f} km has its half-peak ring at a radius of "
        f"{sigma_km * math.sqrt(2 * math.log(2)):.0f} km, so the surface falls "
        f"to half about one printed name away from the engraving. Intensity is "
        f"the distance to that sheet's nearest name and nothing else, so it "
        f"reads the same everywhere and a crowded corner is not mistaken for "
        f"strong evidence about one tribe. Where a tribe carries several names "
        f"its own field stretches to cover them, and that stretch is the "
        f"measure of spread in data/tribal_spread.csv: {stats['multi_label']} "
        f"of {stats['tribes']} tribes have more than one name, the widest gap "
        f"between two names of a single tribe being {stats['widest_gap']:.0f} "
        f"km. Surfaces overlap where compilers disagree or where tribes "
        f"interleaved, and the overlap is left to be seen rather than resolved."
    )
    warning = (
        f"Nothing is clipped. The frontier of 1881 was not the frontier of "
        f"2022 and {stats['outside']} of the {stats['points']} names sit on "
        f"ground that is now Algeria, so a field that stopped at the modern "
        f"line would be drawing a fact that did not exist. Neighbouring "
        f"coastlines are Natural Earth 1:50m; Tunisian boundaries are OCHA COD "
        f"2022 and are reference only, not a container. Pellissier 1853 and "
        f"Lasailly 1881 are read off the Gallica scans, placement "
        f"{stats['loo']} leave-one-out; Martel 1965 is a historian's sketch map "
        f"of 1881, a secondary source, {stats['martel_loo']} km. The per-tribe "
        f"figures are in data/tribal_spread.csv."
    )
    figure.text(0.02, 0.115,
                "\n".join(textwrap.wrap(caption, 205)
                          + textwrap.wrap(warning, 205)),
                fontsize=6.5, color="#57534a", va="top")
    figure.subplots_adjust(left=0.01, right=0.995, top=0.90, bottom=0.155,
                           wspace=0.01)
    figure.savefig(path, facecolor="white")
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sigma-km", type=float, default=DEFAULT_SIGMA_KM)
    parser.add_argument("--cutoff-km", type=float, default=DEFAULT_CUTOFF_KM)
    parser.add_argument("--no-figure", action="store_true")
    args = parser.parse_args(argv)

    points = read_points()
    lons, lats, gx, gy = grid()

    by_tribe: dict[str, list[dict]] = defaultdict(list)
    for point in points:
        by_tribe[point["tribe"]].append(point)
    fields_all = {t: field(m, gx, gy, args.sigma_km) for t, m in by_tribe.items()}

    spread = spread_table(points, fields_all, args.sigma_km,
                          REPO_ROOT / "data" / "tribal_spread.csv")

    cell = (STEP * KM_PER_DEG_LON) * (STEP * KM_PER_DEG_LAT)
    panels = []
    surfaces = {}
    for name in SOURCES:
        subset = [p for p in points if p["source"] == name]
        groups: dict[str, list[dict]] = defaultdict(list)
        for point in subset:
            groups[point["tribe"]].append(point)
        fields = {t: field(m, gx, gy, args.sigma_km) for t, m in groups.items()}
        surfaces[name] = surface(subset, gx, gy, args.sigma_km)
        panels.append((name, [(surfaces[name], SOURCE_INK[name])], fields, {
            "points": len(subset),
            "tribes": len(groups),
            "outside": sum(1 for p in subset if not p["inside"]),
            "widest": round(max(float((f >= HALF).sum()) * cell
                                for f in fields.values())),
            "country_pct": 0.0,
        }))
    panels.append(("All three, pooled",
                   [(surfaces[n], SOURCE_INK[n]) for n in SOURCES],
                   fields_all, {
                       "points": len(points),
                       "tribes": len(by_tribe),
                       "outside": sum(1 for p in points if not p["inside"]),
                       "widest": round(max(float((f >= HALF).sum()) * cell
                                           for f in fields_all.values())),
                       "country_pct": 0.0,
                   }))

    # The modern-unit index is kept, because a question the figure refuses to
    # answer - which tribe's name is nearest this imada - is still worth a table.
    imada_path = BOUNDARIES / "tun_admin4.shp"
    stats_imada = {}
    if imada_path.exists():
        imadas = load_imadas(imada_path)
        per_source = {n: nearest(imadas, [p for p in points if p["source"] == n],
                                 args.cutoff_km) for n in SOURCES}
        pooled = nearest(imadas, points, args.cutoff_km)
        write_assignment(imadas, per_source, pooled,
                         REPO_ROOT / "data" / "tribal_imada_assignment.csv")
        both = same = 0
        for unit in imadas:
            named = [per_source[n][unit["pcode"]][0] for n in SOURCES
                     if per_source[n].get(unit["pcode"], ("",))[0]]
            if len(named) >= 2:
                both += 1
                if len(set(named)) == 1:
                    same += 1
        assigned = [u for u in imadas if pooled[u["pcode"]][0]]
        stats_imada = {
            "cutoff_km": args.cutoff_km,
            "imadas_total": len(imadas),
            "imadas_assigned_pooled": len(assigned),
            "imadas_named_by_two_or_three": both,
            "of_those_agreeing": same,
            "agreement_pct": round(100 * same / both, 1) if both else 0.0,
            "_comment": ("The nearest-name index, kept as a table and no longer "
                         "drawn. It answers which tribe's name is closest to a "
                         "2022 unit, which is a question about indexing, not "
                         "about where a tribe was."),
        }

    fits = json.loads((REPO_ROOT / "data" / "tribal_fit.json").read_text())
    loo = ", ".join(f"{v['year']} {v['loo_rms_km']} km"
                    for k, v in fits.items() if not k.startswith("_"))
    martel_fit = REPO_ROOT / "data" / "martel_1965_fit.json"
    martel_loo = (json.loads(martel_fit.read_text())["loo_rms_km"]
                  if martel_fit.exists() else None)

    widest_gap = max(r["widest_label_gap_km"] for r in spread)
    stats = {
        "_about": ("Each tribe's printed names convolved with a Gaussian and "
                   "painted as a continuous surface, one hue per cartographer. "
                   "A field, not an area: no contour, and clipped to nothing."),
        "_why_not_an_area": (
            "No sheet in this collection draws a tribal boundary, so a filled "
            "polygon would be an invention. Filling administrative units adds a "
            "second error on top, confining a nineteenth-century tribe inside a "
            "2022 mesh and stopping it at a frontier that did not exist: "
            f"{sum(1 for p in points if not p['inside'])} of the labels are "
            "printed on ground that is now Algeria."),
        "sigma_km": args.sigma_km,
        "_sigma_basis": (
            "Six labels measured on the tiles run 14 to 32 km end to end, a "
            "median of about 22. A Gaussian of this sigma has its half-peak "
            "point at 1.177 sigma, so the surface falls to half about one "
            "printed name away from the engraving."),
        "half_peak_radius_km": round(args.sigma_km * math.sqrt(2 * math.log(2)), 1),
        "peak_alpha": PEAK_ALPHA,
        "gamma": GAMMA,
        "points": len(points),
        "points_by_source": {n: sum(1 for p in points if p["source"] == n)
                             for n in SOURCES},
        "tribes_by_source": {n: len({p["tribe"] for p in points
                                     if p["source"] == n}) for n in SOURCES},
        "outside_by_source": {n: sum(1 for p in points
                                     if p["source"] == n and not p["inside"])
                              for n in SOURCES},
        "points_outside_modern_tunisia": sum(1 for p in points if not p["inside"]),
        "tribes": len(by_tribe),
        "tribes_with_more_than_one_label": sum(1 for r in spread
                                               if r["labels"] > 1),
        "widest_label_gap_km": widest_gap,
        "widest_field_tribe": spread[0]["tribe"],
        "widest_field_sqkm": spread[0]["field_sqkm_half_peak"],
        "median_field_sqkm": int(np.median([r["field_sqkm_half_peak"]
                                            for r in spread])),
        "loo_rms": loo,
        "martel_loo_rms_km": martel_loo,
        "imada_index": stats_imada,
    }
    (REPO_ROOT / "data" / "tribal_spread_summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.no_figure:
        draw(panels, points, args.sigma_km, lons, lats,
             REPO_ROOT / "docs" / "img" / "tribal_spread.png",
             {**stats, "loo": loo, "martel_loo": martel_loo,
              "multi_label": stats["tribes_with_more_than_one_label"],
              "widest_gap": widest_gap,
              "outside": stats["points_outside_modern_tunisia"]})

    for title, _, _, panel in panels:
        print(f"{title:22s} {panel['points']:3d} names  {panel['tribes']:3d} "
              f"tribes  widest field {panel['widest']:>7,} km2")
    print(f"{stats['tribes_with_more_than_one_label']} of {stats['tribes']} "
          f"tribes carry more than one name; widest gap between two names of "
          f"one tribe {widest_gap:.0f} km")
    print(f"median field at half peak {stats['median_field_sqkm']:,} km2, "
          f"widest {spread[0]['tribe']} {spread[0]['field_sqkm_half_peak']:,} km2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Map the tribal annotation of three sheets onto today's imadas.

The maps name tribes and draw no tribal boundary, so a tribe has no polygon of
its own to take. Drawing each one as a dot, or as a disc of the length of its
own printed name, is honest but it is not a distribution map: it shows where
names were engraved and leaves the country between them blank.

What this draws instead is an assignment. Every imada - the *secteur*, the
finest published Tunisian unit, 2,084 of them - is given the tribe whose nearest
label lies closest to it, out to a cutoff beyond which nothing is assigned. That
is a Voronoi tessellation evaluated at imada resolution, and the reader should
hold two things about it at once:

  * The colours are a rule, not evidence. Where two names sit 60 km apart the
    boundary between their colours falls at 30 km because that is what nearest
    means, and no sheet says anything about where one tribe stopped.
  * The rule is stated, the input points are drawn on top of the fill, and the
    second panel gives the distance to the nearest name, so every part of the
    map carries its own warning: pale means the assignment is a long
    extrapolation, dark means a name is close by.

Three sources, kept apart in the data and distinguished on the figure:

    1853  Pellissier, read off the Gallica scan, Tell to about 34 N
    1881  Lasailly, read off the Gallica scan, whole face
    1881  Martel 1965, a historian's sketch map, whole country, secondary

Outputs:
    docs/img/tribal_distribution_imada.png
    data/tribal_imada_assignment.csv    one row per imada, 2,084 rows
    data/tribal_imada_summary.json

Usage:
    python3 scripts/map_tribes_on_imadas.py
    python3 scripts/map_tribes_on_imadas.py --cutoff-km 40
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shapefile
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import shape

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent.parent
BOUNDARIES = REPO_ROOT / "data" / "boundaries"

SOURCE_INK = {
    "1853 Pellissier": "#a5642a",
    "1881 Lasailly": "#2f5f8f",
    "1881 Martel (1965)": "#4a7c59",
}
MESH = "#ffffff"
LINE = "#7d746a"
COAST = "#4a453d"
UNASSIGNED = "#f4f2ed"

# Twelve muted hues, assigned by greedy graph colouring so that no two
# neighbouring tribes share one. The colour carries no meaning beyond "a
# different tribe from the one next door".
PALETTE = ["#c9b7a0", "#9fb8ad", "#c2a4a4", "#a8b5c9", "#cbc199", "#b3a3bd",
           "#9dbac3", "#d0b49a", "#a9bc9c", "#c4aab8", "#b0a894", "#8fa9b8"]

# Beyond this, an imada is left unassigned. 60 km is two and a half times the
# median printed label, so it is generous; the second panel shows what it buys.
DEFAULT_CUTOFF_KM = 60.0

KM_PER_DEG_LAT = 110.574
LAT0 = 34.5
KM_PER_DEG_LON = 111.320 * math.cos(math.radians(LAT0))


def to_km(lon: float, lat: float) -> tuple[float, float]:
    return lon * KM_PER_DEG_LON, lat * KM_PER_DEG_LAT


def read_points() -> list[dict]:
    """Every tribe label with a position, from all three sources."""
    points = []
    path = REPO_ROOT / "data" / "tribal_territories.csv"
    for row in csv.DictReader(path.open(encoding="utf-8")):
        points.append({
            "tribe": row["tribe"] or row["label_as_printed"],
            "label": row["label_as_printed"],
            "source": f"{row['year']} " + ("Pellissier" if row["year"] == "1853"
                                           else "Lasailly"),
            "primary": True,
            "lon": float(row["lon"]),
            "lat": float(row["lat"]),
        })
    martel = REPO_ROOT / "data" / "martel_1965_tribes.csv"
    if martel.exists():
        for row in csv.DictReader(martel.open(encoding="utf-8")):
            points.append({
                "tribe": row["tribe"],
                "label": row["label_as_printed"],
                "source": "1881 Martel (1965)",
                "primary": False,
                "lon": float(row["lon"]),
                "lat": float(row["lat"]),
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
        point = geometry.representative_point()
        out.append({
            "pcode": attributes["adm4_pcode"],
            "imada": attributes["adm4_name"],
            "delegation": attributes["adm3_name"],
            "gouvernorat": attributes["adm2_name"],
            "area_sqkm": float(attributes["area_sqkm"] or 0),
            "geom": geometry,
            "lon": point.x,
            "lat": point.y,
        })
    return out


def assign(imadas: list[dict], points: list[dict], cutoff_km: float) -> None:
    """Nearest label wins, out to the cutoff. Distance in the local plane."""
    px = np.array([to_km(p["lon"], p["lat"]) for p in points])
    for unit in imadas:
        ux, uy = to_km(unit["lon"], unit["lat"])
        distances = np.hypot(px[:, 0] - ux, px[:, 1] - uy)
        index = int(distances.argmin())
        distance = float(distances[index])
        unit["distance_km"] = round(distance, 1)
        if distance <= cutoff_km:
            unit["tribe"] = points[index]["tribe"]
            unit["source"] = points[index]["source"]
            unit["label"] = points[index]["label"]
        else:
            unit["tribe"] = ""
            unit["source"] = ""
            unit["label"] = ""
        # The runner-up says how contested the assignment is. Where the two are
        # close the boundary between the colours is arbitrary, and saying so in
        # a column is cheaper than pretending otherwise.
        order = np.argsort(distances)
        second = ""
        for candidate in order[1:]:
            if points[int(candidate)]["tribe"] != unit["tribe"]:
                second = points[int(candidate)]["tribe"]
                unit["runner_up_km"] = round(float(distances[int(candidate)]), 1)
                break
        unit["runner_up"] = second
        unit.setdefault("runner_up_km", "")


def colour_regions(imadas: list[dict]) -> dict[str, str]:
    """Greedy graph colouring so neighbouring tribes never share a hue."""
    assigned = [u for u in imadas if u["tribe"]]
    neighbours: dict[str, set[str]] = defaultdict(set)
    boxes = {u["pcode"]: u["geom"].bounds for u in assigned}
    for i, a in enumerate(assigned):
        ax0, ay0, ax1, ay1 = boxes[a["pcode"]]
        for b in assigned[i + 1:]:
            if a["tribe"] == b["tribe"]:
                continue
            bx0, by0, bx1, by1 = boxes[b["pcode"]]
            if ax1 < bx0 - 0.02 or bx1 < ax0 - 0.02 or ay1 < by0 - 0.02 or by1 < ay0 - 0.02:
                continue
            if a["geom"].distance(b["geom"]) < 0.01:
                neighbours[a["tribe"]].add(b["tribe"])
                neighbours[b["tribe"]].add(a["tribe"])
    order = sorted({u["tribe"] for u in assigned},
                   key=lambda t: -len(neighbours[t]))
    colours: dict[str, str] = {}
    for tribe in order:
        taken = {colours[n] for n in neighbours[tribe] if n in colours}
        colours[tribe] = next((c for c in PALETTE if c not in taken), PALETTE[0])
    return colours


def write_assignment(imadas: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["adm4_pcode", "imada", "delegation", "gouvernorat",
                         "area_sqkm", "tribe", "label_as_printed", "source",
                         "distance_km", "runner_up", "runner_up_km"])
        for unit in sorted(imadas, key=lambda u: (u["gouvernorat"], u["delegation"],
                                                  u["imada"])):
            writer.writerow([unit["pcode"], unit["imada"], unit["delegation"],
                             unit["gouvernorat"], round(unit["area_sqkm"], 2),
                             unit["tribe"], unit["label"], unit["source"],
                             unit["distance_km"], unit["runner_up"],
                             unit["runner_up_km"]])


def draw(imadas: list[dict], points: list[dict], colours: dict[str, str],
         cutoff_km: float, path: Path, stats: dict) -> None:
    reader0 = shapefile.Reader(str(BOUNDARIES / "tun_admin0.shp"))
    country = shape(reader0.shapeRecords()[0].shape.__geo_interface__)
    reader2 = shapefile.Reader(str(BOUNDARIES / "tun_admin2.shp"))
    gouvernorats = [shape(s.shape.__geo_interface__) for s in reader2.shapeRecords()]

    figure, axes = plt.subplots(1, 2, figsize=(10.4, 7.8), dpi=190)

    def parts(geometry):
        return geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]

    # Discrete bands for the distance panel. A continuous ramp would put a
    # different colour on every imada and invite the eye to read precision into
    # a number whose own inputs are good to about 10 km.
    bands = [(0, 10, "#15366b"), (10, 20, "#2f6aa8"), (20, 30, "#5f9bc9"),
             (30, 45, "#9dc4de"), (45, 60, "#cfe0ec"), (60, 1e9, "#f4f2ed")]

    def band(distance):
        for lo, hi, colour in bands:
            if lo <= distance < hi:
                return colour
        return bands[-1][2]

    for ax, panel in zip(axes, ("tribe", "distance")):
        for unit in imadas:
            if panel == "tribe":
                face = colours.get(unit["tribe"], UNASSIGNED)
            else:
                face = band(unit["distance_km"])
            for geom in parts(unit["geom"]):
                xs, ys = geom.exterior.xy
                ax.fill(xs, ys, facecolor=face, edgecolor=MESH, linewidth=0.1,
                        zorder=1)
        for unit in gouvernorats:
            for geom in parts(unit):
                xs, ys = geom.exterior.xy
                ax.plot(xs, ys, color=LINE, linewidth=0.3, alpha=0.5, zorder=2)
        for geom in parts(country):
            xs, ys = geom.exterior.xy
            ax.plot(xs, ys, color=COAST, linewidth=0.8, zorder=3)
        ax.set_xlim(7.4, 11.9)
        ax.set_ylim(30.15, 37.75)
        ax.set_aspect(1 / math.cos(math.radians(LAT0)))
        ax.set_axis_off()

    # Left: the evidence drawn over the rule, so the two never get confused.
    ax = axes[0]
    for point in points:
        ax.plot([point["lon"]], [point["lat"]], marker="o", markersize=1.9,
                markerfacecolor=SOURCE_INK[point["source"]],
                markeredgecolor="white", markeredgewidth=0.3, zorder=6)

    written: list[tuple[float, float]] = []
    centres: dict[str, list] = defaultdict(list)
    for unit in imadas:
        if unit["tribe"]:
            centres[unit["tribe"]].append((unit["lon"], unit["lat"],
                                           unit["area_sqkm"]))
    areas = {t: sum(m[2] for m in members) for t, members in centres.items()}
    # One name per tribe, and only for tribes holding enough ground to carry
    # one. The north-west is where the annotation is densest, which is the
    # finding and also what makes the names collide; the rest are in the CSV.
    biggest = sorted(areas, key=lambda t: -areas[t])[:44]
    for tribe, members in sorted(centres.items(), key=lambda kv: -areas[kv[0]]):
        if tribe not in biggest:
            continue
        weight = sum(m[2] for m in members) or 1
        lon = sum(m[0] * m[2] for m in members) / weight
        lat = sum(m[1] * m[2] for m in members) / weight
        crowded = sum(1 for a, b in written
                      if abs(a - lon) < 0.35 and abs(b - lat) < 0.18)
        ax.annotate(tribe, (lon, lat), textcoords="offset points",
                    xytext=(0, -2 - 6 * crowded), fontsize=4.1, ha="center",
                    color="#2b2823", zorder=7)
        written.append((lon, lat))

    ax.legend(handles=[Line2D([], [], marker="o", linestyle="none",
                              color=SOURCE_INK[s], markersize=4.5, label=s)
                       for s in SOURCE_INK]
                      + [Patch(facecolor=UNASSIGNED, edgecolor=LINE,
                               label=f"no name within {cutoff_km:.0f} km")],
              loc="lower left", bbox_to_anchor=(0.0, 0.03), frameon=False,
              fontsize=6.4)
    ax.set_title("Nearest name, imada by imada", fontsize=9.5,
                 color="#26231e", loc="left", pad=8)

    # Right: how far that nearest name actually is.
    ax = axes[1]
    ax.legend(handles=[Patch(facecolor=colour, edgecolor=LINE, linewidth=0.3,
                             label=(f"{lo} to {hi} km" if hi < 1e8
                                    else f"over {lo} km, unassigned"))
                       for lo, hi, colour in bands],
              loc="lower left", bbox_to_anchor=(0.0, 0.03), frameon=False,
              fontsize=6.4, title="to the nearest name", title_fontsize=6.4)
    ax.set_title("How far the nearest name is", fontsize=9.5, color="#26231e",
                 loc="left", pad=8)

    figure.suptitle("Tribal annotation of 1853 and 1881, assigned to the imadas of 2022",
                    fontsize=12, color="#26231e", x=0.02, ha="left", y=0.98)
    caption = (
        f"{stats['points']} tribe names read off three sheets, "
        f"{stats['tribes']} tribes. No sheet draws a tribal boundary, so the "
        f"colours are not boundaries: each imada takes the tribe whose\n"
        f"nearest name is closest, out to {cutoff_km:.0f} km. The line between "
        f"two colours falls halfway between two printed names because that is "
        f"what nearest means, and nothing on any sheet\nsays a tribe stopped "
        f"there. {stats['assigned']} of {stats['imadas_total']} imadas are "
        f"assigned, {stats['area_pct']:.0f}% of the country's area; "
        f"{stats['within_20']}% of them have a name within 20 km and "
        f"{stats['contested']}% have a rival\nname within 10 km of the winner. "
        f"The right panel is the health warning: pale ground is a long "
        f"extrapolation.\n"
        f"Sources: Pellissier 1853 and Lasailly 1881 read off the Gallica "
        f"scans, placement {stats['loo']} leave-one-out; Martel 1965, a "
        f"historian's sketch map of 1881 and a secondary\nsource, "
        f"{stats['martel_loo']} km. Martel alone names the Nefzaoua, the Djerid "
        f"and the Dahar. Boundaries are OCHA COD 2022: the imada says where, "
        f"not that the unit existed then."
    )
    figure.text(0.02, 0.125, caption, fontsize=6.5, color="#57534a", va="top")
    figure.subplots_adjust(left=0.02, right=0.98, top=0.93, bottom=0.17,
                           wspace=0.02)
    figure.savefig(path, facecolor="white")
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff-km", type=float, default=DEFAULT_CUTOFF_KM)
    parser.add_argument("--no-figure", action="store_true")
    args = parser.parse_args(argv)

    imada_path = BOUNDARIES / "tun_admin4.shp"
    if not imada_path.exists():
        print("data/boundaries/tun_admin4.shp is missing; run\n"
              "    python3 scripts/fetch_boundaries.py")
        return 1

    points = read_points()
    imadas = load_imadas(imada_path)
    assign(imadas, points, args.cutoff_km)
    colours = colour_regions(imadas)
    write_assignment(imadas, REPO_ROOT / "data" / "tribal_imada_assignment.csv")

    assigned = [u for u in imadas if u["tribe"]]
    total_area = sum(u["area_sqkm"] for u in imadas)
    within_20 = 100 * sum(1 for u in assigned if u["distance_km"] <= 20) / len(assigned)
    contested = 100 * sum(
        1 for u in assigned
        if isinstance(u["runner_up_km"], float)
        and u["runner_up_km"] - u["distance_km"] <= 10) / len(assigned)

    fits = json.loads((REPO_ROOT / "data" / "tribal_fit.json").read_text())
    loo = ", ".join(f"{v['year']} {v['loo_rms_km']} km"
                    for k, v in fits.items() if not k.startswith("_"))
    martel_fit = REPO_ROOT / "data" / "martel_1965_fit.json"
    martel_loo = (json.loads(martel_fit.read_text())["loo_rms_km"]
                  if martel_fit.exists() else None)

    per_tribe = defaultdict(float)
    for unit in assigned:
        per_tribe[unit["tribe"]] += unit["area_sqkm"]
    widest = max(per_tribe.items(), key=lambda kv: kv[1])

    stats = {
        "_about": ("Every imada given the tribe whose nearest read label is "
                   "closest to it, out to a cutoff. A Voronoi tessellation at "
                   "imada resolution, not a map of tribal boundaries."),
        "_the_rule_is_not_evidence": (
            "No sheet in this collection draws a tribal boundary. The line "
            "between two colours falls halfway between two printed names "
            "because that is what nearest means, and nothing on any sheet says "
            "a tribe stopped there. distance_km and runner_up_km are in the "
            "table so that every row carries its own warning."),
        "cutoff_km": args.cutoff_km,
        "points": len(points),
        "points_by_source": {s: sum(1 for p in points if p["source"] == s)
                             for s in SOURCE_INK},
        "tribes": len({p["tribe"] for p in points}),
        "tribes_assigned_ground": len(per_tribe),
        "imadas_total": len(imadas),
        "assigned": len(assigned),
        "assigned_pct": round(100 * len(assigned) / len(imadas), 1),
        "area_pct": round(100 * sum(u["area_sqkm"] for u in assigned) / total_area, 1),
        "within_20": round(within_20),
        "contested": round(contested),
        "median_distance_km": round(float(np.median([u["distance_km"] for u in assigned])), 1),
        "widest_tribe": widest[0],
        "widest_tribe_sqkm": round(widest[1]),
        "loo_rms": loo,
        "martel_loo_rms_km": martel_loo,
        "_martel_note": (
            "Martel 1965 is a historian's sketch map, not a sheet in the Gallica "
            "collection, and it is the only one of the three that covers the "
            "whole country. Without it the Nefzaoua, the Djerid and the Dahar "
            "have no name at all and the south goes blank."),
    }
    (REPO_ROOT / "data" / "tribal_imada_summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.no_figure:
        draw(imadas, points, colours, args.cutoff_km,
             REPO_ROOT / "docs" / "img" / "tribal_distribution_imada.png",
             {**stats, "loo": loo, "martel_loo": martel_loo})

    print(f"{len(points)} label points, {stats['tribes']} tribes, "
          f"cutoff {args.cutoff_km:.0f} km")
    print(f"{len(assigned)} of {len(imadas)} imadas assigned "
          f"({stats['assigned_pct']}%), {stats['area_pct']}% of the area")
    print(f"median distance to the winning name {stats['median_distance_km']} km; "
          f"{stats['within_20']}% within 20 km, {stats['contested']}% contested")
    print(f"widest: {widest[0]}, {round(widest[1]):,} km2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

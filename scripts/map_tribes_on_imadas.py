#!/usr/bin/env python3
"""Four cartographers on one page, each given the same country to fill.

The maps name tribes and draw no tribal boundary, so a tribe has no polygon of
its own. Two ways of showing that have been tried here and neither held. A dot
at each label says where a name was engraved and leaves the country between
names blank. A filled choropleth fills it, and then the fill reads as territory
however loudly the caption denies it.

This draws dot density instead. Every imada - the *secteur*, the finest
published Tunisian unit, 2,084 of them - is given the tribe whose nearest label
lies closest, out to a cutoff; the area so assigned is then sprinkled with dots
at a fixed rate, jittered at random inside the polygons. Density carries the
extent, the dots never join into an edge, and the eye reads a scatter as a
scatter. Where a cartographer knew little, his quarter of the page is thin.

Four panels, three of them one cartographer each and the fourth all of them:

    1853  Pellissier, read off the Gallica scan, Tell to about 34 N
    1881  Lasailly, read off the Gallica scan, whole face
    1881  Martel 1965, a historian's sketch map, whole country, secondary
    all   the three pooled, each dot in the colour of the sheet that won it

Read across the four and the argument is visible without a word of caption:
the same country, four times, filled to the extent that each compiler could
fill it.

Outputs:
    docs/img/tribal_distribution_imada.png
    data/tribal_imada_assignment.csv    one row per imada, 2,084 rows,
                                        each cartographer in his own column
    data/tribal_imada_summary.json

Usage:
    python3 scripts/map_tribes_on_imadas.py
    python3 scripts/map_tribes_on_imadas.py --cutoff-km 40 --km-per-dot 30
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
import textwrap
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shapefile
from matplotlib.lines import Line2D
from shapely.geometry import Point, shape

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent.parent
BOUNDARIES = REPO_ROOT / "data" / "boundaries"

# One hue per cartographer, the same three used everywhere else in this
# repository, so a sheet keeps its colour from figure to figure.
SOURCES = [
    ("1853 Pellissier", "#a5642a", "col_1853"),
    ("1881 Lasailly", "#2f5f8f", "col_1881"),
    ("1881 Martel (1965)", "#4a7c59", "col_martel"),
]
SOURCE_INK = {name: ink for name, ink, _ in SOURCES}
LAND = "#f7f5f1"
MESH = "#e8e3d9"
LINE = "#bdb5a8"
COAST = "#6b645a"

DEFAULT_CUTOFF_KM = 60.0
DEFAULT_KM_PER_DOT = 45.0
SEED = 20250914

KM_PER_DEG_LAT = 110.574
LAT0 = 34.5
KM_PER_DEG_LON = 111.320 * math.cos(math.radians(LAT0))


def to_km(lon: float, lat: float) -> tuple[float, float]:
    return lon * KM_PER_DEG_LON, lat * KM_PER_DEG_LAT


def read_points() -> list[dict]:
    """Every tribe label with a position, from all three sheets."""
    points = []
    path = REPO_ROOT / "data" / "tribal_territories.csv"
    for row in csv.DictReader(path.open(encoding="utf-8")):
        points.append({
            "tribe": row["tribe"] or row["label_as_printed"],
            "source": ("1853 Pellissier" if row["year"] == "1853"
                       else "1881 Lasailly"),
            "lon": float(row["lon"]),
            "lat": float(row["lat"]),
        })
    martel = REPO_ROOT / "data" / "martel_1965_tribes.csv"
    if martel.exists():
        for row in csv.DictReader(martel.open(encoding="utf-8")):
            points.append({
                "tribe": row["tribe"],
                "source": "1881 Martel (1965)",
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
        inside = geometry.representative_point()
        out.append({
            "pcode": attributes["adm4_pcode"],
            "imada": attributes["adm4_name"],
            "delegation": attributes["adm3_name"],
            "gouvernorat": attributes["adm2_name"],
            "area_sqkm": float(attributes["area_sqkm"] or 0),
            "geom": geometry,
            "lon": inside.x,
            "lat": inside.y,
        })
    return out


def nearest(imadas: list[dict], points: list[dict], cutoff_km: float) -> dict:
    """pcode -> (tribe, source, distance_km, runner_up, runner_up_km)."""
    if not points:
        return {}
    px = np.array([to_km(p["lon"], p["lat"]) for p in points])
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


def scatter_dots(imadas: list[dict], assignment: dict, km_per_dot: float,
                 rng: np.random.Generator) -> tuple[np.ndarray, list[str]]:
    """One dot per km_per_dot of assigned ground, at random inside the polygon.

    Rejection sampling in the polygon's own bounding box. A small imada can
    fail to place its dot and is allowed to: the density is the message and a
    forced dot at a centroid would put ink where the sampler could not.
    """
    xs, ys, owners = [], [], []
    for unit in imadas:
        tribe, source, *_ = assignment.get(unit["pcode"], ("", "", 0, "", ""))
        if not tribe:
            continue
        count = unit["area_sqkm"] / km_per_dot
        n = int(count) + (1 if rng.random() < count - int(count) else 0)
        if n == 0:
            continue
        x0, y0, x1, y1 = unit["geom"].bounds
        placed = 0
        for _ in range(n * 40):
            if placed == n:
                break
            x = rng.uniform(x0, x1)
            y = rng.uniform(y0, y1)
            if unit["geom"].contains(Point(x, y)):
                xs.append(x)
                ys.append(y)
                owners.append(source)
                placed += 1
    return np.array([xs, ys]), owners


def write_assignment(imadas: list[dict], per_source: dict, pooled: dict,
                     path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "adm4_pcode", "imada", "delegation", "gouvernorat", "area_sqkm",
            "tribe_1853_pellissier", "km_1853",
            "tribe_1881_lasailly", "km_1881",
            "tribe_1881_martel", "km_martel",
            "tribe_pooled", "source_pooled", "km_pooled",
            "runner_up", "runner_up_km", "sources_naming", "sources_agreeing",
        ])
        for unit in sorted(imadas, key=lambda u: (u["gouvernorat"],
                                                  u["delegation"], u["imada"])):
            row = [unit["pcode"], unit["imada"], unit["delegation"],
                   unit["gouvernorat"], round(unit["area_sqkm"], 2)]
            named = []
            for name, _, _ in SOURCES:
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


def draw(imadas: list[dict], points: list[dict], per_source: dict, pooled: dict,
         cutoff_km: float, km_per_dot: float, path: Path, stats: dict) -> None:
    reader0 = shapefile.Reader(str(BOUNDARIES / "tun_admin0.shp"))
    country = shape(reader0.shapeRecords()[0].shape.__geo_interface__)
    reader2 = shapefile.Reader(str(BOUNDARIES / "tun_admin2.shp"))
    gouvernorats = [shape(s.shape.__geo_interface__) for s in reader2.shapeRecords()]

    def parts(geometry):
        return geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]

    figure, axes = plt.subplots(1, 4, figsize=(12.6, 7.4), dpi=200)
    rng = np.random.default_rng(SEED)

    panels = [(name, ink, per_source[name], stats["per_source"][name])
              for name, ink, _ in SOURCES]
    panels.append(("All three, pooled", None, pooled, stats["pooled"]))

    for ax, (title, ink, assignment, panel_stats) in zip(axes, panels):
        for unit in imadas:
            for geom in parts(unit["geom"]):
                xs, ys = geom.exterior.xy
                ax.fill(xs, ys, facecolor=LAND, edgecolor=MESH, linewidth=0.08,
                        zorder=1)
        for unit in gouvernorats:
            for geom in parts(unit):
                xs, ys = geom.exterior.xy
                ax.plot(xs, ys, color=LINE, linewidth=0.3, zorder=2)
        for geom in parts(country):
            xs, ys = geom.exterior.xy
            ax.plot(xs, ys, color=COAST, linewidth=0.7, zorder=3)

        coords, owners = scatter_dots(imadas, assignment, km_per_dot, rng)
        if coords.size:
            if ink is not None:
                ax.scatter(coords[0], coords[1], s=1.3, c=ink, alpha=0.55,
                           linewidths=0, zorder=4)
            else:
                for name, hue, _ in SOURCES:
                    mask = np.array([o == name for o in owners])
                    if mask.any():
                        ax.scatter(coords[0][mask], coords[1][mask], s=1.3,
                                   c=hue, alpha=0.55, linewidths=0, zorder=4)

        # The labels themselves, on top, so the evidence is never hidden by
        # the sprinkle that was derived from it.
        shown = [p for p in points
                 if ink is None or p["source"] == title]
        for point in shown:
            ax.plot([point["lon"]], [point["lat"]], marker="o", markersize=3.0,
                    markerfacecolor=SOURCE_INK[point["source"]],
                    markeredgecolor="white", markeredgewidth=0.5, zorder=6)

        ax.set_xlim(7.4, 11.9)
        ax.set_ylim(30.15, 37.75)
        ax.set_aspect(1 / math.cos(math.radians(LAT0)))
        ax.set_axis_off()
        ax.set_title(title, fontsize=8.5, color="#26231e", loc="left", pad=6)
        ax.text(0.0, 0.22,
                f"{panel_stats['points']} names, {panel_stats['tribes']} tribes\n"
                f"{panel_stats['area_pct']:.0f}% of the country within "
                f"{cutoff_km:.0f} km\nmedian {panel_stats['median_km']:.0f} km "
                f"to the nearest",
                transform=ax.transAxes, fontsize=5.8, color="#57534a", va="top")

    axes[3].legend(handles=[Line2D([], [], marker="o", linestyle="none",
                                   color=ink, markersize=4, label=name)
                            for name, ink, _ in SOURCES],
                   loc="lower left", bbox_to_anchor=(0.0, 0.02), frameon=False,
                   fontsize=6.2)

    figure.suptitle("Where the tribes were, as four cartographers had it",
                    fontsize=12.5, color="#26231e", x=0.02, ha="left", y=0.985)
    figure.text(0.02, 0.947,
                f"One dot per {km_per_dot:.0f} km\u00b2 of ground, scattered "
                "at random inside the imadas each sheet's own names reach. The "
                "dots are a density, not a boundary, and the ringed ones are "
                "the printed names themselves.",
                fontsize=7.4, color="#3a352d", va="top")
    caption = (
        f"Every imada, the finest published Tunisian unit and "
        f"{stats['imadas_total']:,} of them, takes the tribe whose nearest "
        f"printed name is closest, out to {cutoff_km:.0f} km; its area is then "
        f"sprinkled at one dot per {km_per_dot:.0f} km\u00b2, seeded so the "
        f"scatter is reproducible. Read the four panels across and the argument "
        f"needs no caption: the same country, filled to the extent each "
        f"compiler could fill it. Pellissier's sheet was transcribed only to "
        f"about 34 N and Lasailly gives everything south of Sfax to one tribe, "
        f"so the south is Martel's alone. Pooled, "
        f"{stats['pooled']['assigned']:,} of {stats['imadas_total']:,} imadas "
        f"are reached and the median one sits "
        f"{stats['pooled']['median_km']:.0f} km from its name, about one "
        f"printed label length."
    )
    warning = (
        f"Where two sheets both reach an imada they put the same tribe on it "
        f"only {stats['agreement_pct']:.0f}% of the time "
        f"({stats['of_those_agreeing']:,} of "
        f"{stats['imadas_named_by_two_or_three']:,}). Some of that is grain "
        f"rather than contradiction, since Pellissier names fractions where the "
        f"others name the parent, but it is the number to hold against any "
        f"single panel: which cartographer you read changes the answer. "
        f"Pellissier 1853 and Lasailly 1881 are read off the Gallica scans, "
        f"placement {stats['loo']} leave-one-out; Martel 1965 is a historian's "
        f"sketch map of 1881, a secondary source, {stats['martel_loo']} km. "
        f"Boundaries are OCHA COD 2022: the imada says where, not that the unit "
        f"existed then."
    )
    figure.text(0.02, 0.115,
                "\n".join(textwrap.wrap(caption, 205)
                          + textwrap.wrap(warning, 205)),
                fontsize=6.5, color="#57534a", va="top")
    figure.subplots_adjust(left=0.02, right=0.99, top=0.90, bottom=0.155,
                           wspace=0.01)
    figure.savefig(path, facecolor="white")
    plt.close(figure)


def panel_stats(imadas: list[dict], assignment: dict, points: list[dict],
                total_area: float) -> dict:
    hit = [u for u in imadas if assignment.get(u["pcode"], ("",))[0]]
    distances = [assignment[u["pcode"]][2] for u in hit]
    return {
        "points": len(points),
        "tribes": len({p["tribe"] for p in points}),
        "assigned": len(hit),
        "assigned_pct": round(100 * len(hit) / len(imadas), 1),
        "area_pct": round(100 * sum(u["area_sqkm"] for u in hit) / total_area, 1),
        "median_km": round(float(np.median(distances)), 1) if distances else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff-km", type=float, default=DEFAULT_CUTOFF_KM)
    parser.add_argument("--km-per-dot", type=float, default=DEFAULT_KM_PER_DOT)
    parser.add_argument("--no-figure", action="store_true")
    args = parser.parse_args(argv)

    imada_path = BOUNDARIES / "tun_admin4.shp"
    if not imada_path.exists():
        print("data/boundaries/tun_admin4.shp is missing; run\n"
              "    python3 scripts/fetch_boundaries.py")
        return 1

    points = read_points()
    imadas = load_imadas(imada_path)
    total_area = sum(u["area_sqkm"] for u in imadas)

    per_source = {}
    stats_per_source = {}
    for name, _, _ in SOURCES:
        subset = [p for p in points if p["source"] == name]
        per_source[name] = nearest(imadas, subset, args.cutoff_km)
        stats_per_source[name] = panel_stats(imadas, per_source[name], subset,
                                             total_area)
    pooled = nearest(imadas, points, args.cutoff_km)
    stats_pooled = panel_stats(imadas, pooled, points, total_area)

    write_assignment(imadas, per_source, pooled,
                     REPO_ROOT / "data" / "tribal_imada_assignment.csv")

    # Where two or three sheets both reach an imada, do they name the same
    # tribe? This is the only cross-cartographer check the data supports.
    both, same = 0, 0
    for unit in imadas:
        named = [per_source[n][unit["pcode"]][0] for n, _, _ in SOURCES
                 if per_source[n].get(unit["pcode"], ("",))[0]]
        if len(named) >= 2:
            both += 1
            if len(set(named)) == 1:
                same += 1

    fits = json.loads((REPO_ROOT / "data" / "tribal_fit.json").read_text())
    loo = ", ".join(f"{v['year']} {v['loo_rms_km']} km"
                    for k, v in fits.items() if not k.startswith("_"))
    martel_fit = REPO_ROOT / "data" / "martel_1965_fit.json"
    martel_loo = (json.loads(martel_fit.read_text())["loo_rms_km"]
                  if martel_fit.exists() else None)

    stats = {
        "_about": ("Each imada given the tribe whose nearest read label is "
                   "closest, out to a cutoff, once per cartographer and once "
                   "for the three pooled. Drawn as dot density, not as fill."),
        "_the_rule_is_not_evidence": (
            "No sheet in this collection draws a tribal boundary. The "
            "assignment is a nearest-name rule and the dots are a density "
            "drawn from it, deliberately so that nothing on the figure closes "
            "into an edge. km_pooled and runner_up_km are in the table so that "
            "every row carries its own warning."),
        "cutoff_km": args.cutoff_km,
        "km_per_dot": args.km_per_dot,
        "random_seed": SEED,
        "imadas_total": len(imadas),
        "points": len(points),
        "tribes": len({p["tribe"] for p in points}),
        "per_source": stats_per_source,
        "pooled": stats_pooled,
        "imadas_named_by_two_or_three": both,
        "of_those_agreeing": same,
        "agreement_pct": round(100 * same / both, 1) if both else 0.0,
        "loo_rms": loo,
        "martel_loo_rms_km": martel_loo,
        "_martel_note": (
            "Martel 1965 is a historian's sketch map, not a sheet in the "
            "Gallica collection, and it is the only one of the three that "
            "covers the whole country. Without it the Nefzaoua, the Djerid and "
            "the Dahar have no name at all."),
    }
    (REPO_ROOT / "data" / "tribal_imada_summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.no_figure:
        draw(imadas, points, per_source, pooled, args.cutoff_km,
             args.km_per_dot,
             REPO_ROOT / "docs" / "img" / "tribal_distribution_imada.png",
             {**stats, "loo": loo, "martel_loo": martel_loo})

    for name, _, _ in SOURCES:
        s = stats_per_source[name]
        print(f"{name:22s} {s['points']:3d} names  {s['assigned']:4d} imadas "
              f"({s['area_pct']:4.1f}% of area)  median {s['median_km']:.0f} km")
    s = stats_pooled
    print(f"{'pooled':22s} {s['points']:3d} names  {s['assigned']:4d} imadas "
          f"({s['area_pct']:4.1f}% of area)  median {s['median_km']:.0f} km")
    print(f"named by two or three sheets: {both}, agreeing on the tribe: "
          f"{same} ({stats['agreement_pct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

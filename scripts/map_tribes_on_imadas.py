#!/usr/bin/env python3
"""Put the tribal annotation of the old sheets onto today's imadas.

The maps in this collection name tribes and draw no tribal boundary, so a tribe
cannot be mapped as a polygon. What can be mapped is the ground its name covers.
Six labels measured across the tiles run 14 to 32 km end to end, a median of
about 22 km, so each tribe is drawn here as a disc of 11 km radius centred on
where its name is printed: one label's worth of ground, at the grain the
annotation actually has.

The base is the contemporary imada (secteur), the finest published Tunisian
administrative unit, 2,084 of them from the OCHA Common Operational Dataset.
Two panels:

    left    the discs on the imada mesh, one colour per sheet, with a hairline
            joining the two placements of a tribe named on both
    right   every imada shaded by how many tribes' discs reach it

The right panel is the join, and it is an indexing device rather than a claim:
the imadas are of 2022 and the annotation is of 1853 and 1881, so an imada is
being used to say *where*, not to say that the unit existed.

Why one radius for every tribe, and not a measured one each. A per-label extent
would be better and was attempted: threshold the scan around the anchor, keep
the blobs that are letter-shaped, chain them outward while the gaps stay small,
and read the extent off the chain. On a clean label it works - MEKENA came back
at 147 px against about 154 measured by eye - but the sheets are not clean.
A road crossing the band, a neighbouring name, a broken letter, and the chain
either stops after two glyphs or runs away across half the sheet; tightening the
threshold to fix one case broke the other, and the estimates moved by a factor
of ten under changes that should have been cosmetic. An unstable estimator drawn
at map scale would look like a measurement, so it is not used. The six labels
measured by eye set one radius for all, and the figure says so.

Outputs:
    docs/img/tribal_distribution_imada.png
    data/tribal_imada_coverage.csv      one row per imada a disc reaches
    data/tribal_imada_summary.json

Usage:
    python3 scripts/map_tribes_on_imadas.py
    python3 scripts/map_tribes_on_imadas.py --radius-km 16
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import shapefile
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import Point, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent.parent
BOUNDARIES = REPO_ROOT / "data" / "boundaries"

# The same hues as docs/img/tribal_territories.png, so the two figures read as
# one argument: a sheet keeps its colour across every map in this repository.
YEAR_INK = {1853: "#a5642a", 1881: "#2f5f8f"}
LAND = "#f7f5f1"
MESH = "#ded8cd"
LINE = "#b9b1a3"
COAST = "#8d8579"
# Pale to dark for one, two, three or more tribes reaching an imada. Four steps
# only: the count is small and a continuous ramp would imply a precision the
# 11 km disc does not have.
STEPS = ["#f7f5f1", "#e6dcc6", "#cbb98d", "#a8894f"]

# Half the median measured label length. The measured range is 14 to 32 km.
DEFAULT_RADIUS_KM = 11.0

KM_PER_DEG_LAT = 110.574
LAT0 = 34.5


def to_km(lon: float, lat: float) -> tuple[float, float]:
    """Equirectangular about the middle of the country. Good to ~0.5% here."""
    return lon * 111.320 * math.cos(math.radians(LAT0)), lat * KM_PER_DEG_LAT


def to_km_geom(geometry):
    return transform(lambda xs, ys, z=None: (
        [x * 111.320 * math.cos(math.radians(LAT0)) for x in xs],
        [y * KM_PER_DEG_LAT for y in ys],
    ), geometry)


def read_labels(path: Path) -> list[dict]:
    rows = []
    for row in csv.DictReader(path.open(encoding="utf-8")):
        rows.append({
            "tribe": row["tribe"] or row["label_as_printed"],
            "label": row["label_as_printed"],
            "year": int(row["year"]),
            "lon": float(row["lon"]),
            "lat": float(row["lat"]),
            "inside": row["inside_tunisia"] == "1",
            "confidence": row["read_confidence"],
        })
    return rows


def load_imadas(path: Path) -> list[dict]:
    reader = shapefile.Reader(str(path))
    out = []
    for shape_rec in reader.shapeRecords():
        attributes = shape_rec.record.as_dict()
        geometry = shape(shape_rec.shape.__geo_interface__)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        out.append({
            "pcode": attributes["adm4_pcode"],
            "imada": attributes["adm4_name"],
            "delegation": attributes["adm3_name"],
            "gouvernorat": attributes["adm2_name"],
            "area_sqkm": float(attributes["area_sqkm"] or 0),
            "geom": geometry,
            "geom_km": to_km_geom(geometry),
        })
    return out


def cover(labels: list[dict], imadas: list[dict], radius_km: float) -> list[dict]:
    """Which imadas each tribe's disc reaches. A tribe read on both sheets gets
    one disc per reading and the union of them, because the disagreement between
    the two placements is itself part of what the annotation asserts."""
    tree = STRtree([u["geom_km"] for u in imadas])
    hits: dict[str, set[str]] = {u["pcode"]: set() for u in imadas}
    per_tribe: dict[str, set[str]] = {}
    for label in labels:
        disc = Point(*to_km(label["lon"], label["lat"])).buffer(radius_km)
        reached = set()
        for index in tree.query(disc):
            unit = imadas[int(index)]
            if unit["geom_km"].intersects(disc):
                hits[unit["pcode"]].add(label["tribe"])
                reached.add(unit["pcode"])
        per_tribe.setdefault(label["tribe"], set()).update(reached)
    for unit in imadas:
        unit["tribes"] = sorted(hits[unit["pcode"]])
    return per_tribe


def write_coverage(imadas: list[dict], path: Path) -> None:
    touched = [u for u in imadas if u["tribes"]]
    touched.sort(key=lambda u: (-len(u["tribes"]), u["gouvernorat"], u["imada"]))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["adm4_pcode", "imada", "delegation", "gouvernorat",
                         "area_sqkm", "tribes_n", "tribes"])
        for unit in touched:
            writer.writerow([unit["pcode"], unit["imada"], unit["delegation"],
                             unit["gouvernorat"], round(unit["area_sqkm"], 2),
                             len(unit["tribes"]), " | ".join(unit["tribes"])])


def draw(labels: list[dict], imadas: list[dict], radius_km: float,
         pairs: list[dict], path: Path, stats: dict) -> None:
    reader0 = shapefile.Reader(str(BOUNDARIES / "tun_admin0.shp"))
    country = shape(reader0.shapeRecords()[0].shape.__geo_interface__)
    reader2 = shapefile.Reader(str(BOUNDARIES / "tun_admin2.shp"))
    gouvernorats = [shape(s.shape.__geo_interface__) for s in reader2.shapeRecords()]

    figure, axes = plt.subplots(1, 2, figsize=(10.4, 7.6), dpi=190)

    def parts(geometry):
        return geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]

    for ax, panel in zip(axes, ("discs", "counts")):
        for unit in imadas:
            if panel == "discs":
                face = LAND
            else:
                face = STEPS[min(len(unit["tribes"]), 3)]
            for geom in parts(unit["geom"]):
                xs, ys = geom.exterior.xy
                ax.fill(xs, ys, facecolor=face, edgecolor=MESH, linewidth=0.12,
                        zorder=1)
        for unit in gouvernorats:
            for geom in parts(unit):
                xs, ys = geom.exterior.xy
                ax.plot(xs, ys, color=LINE, linewidth=0.45, zorder=2)
        for geom in parts(country):
            xs, ys = geom.exterior.xy
            ax.plot(xs, ys, color=COAST, linewidth=0.8, zorder=3)
        ax.set_xlim(7.3, 11.9)
        ax.set_ylim(30.15, 37.75)
        ax.set_aspect(1 / math.cos(math.radians(LAT0)))
        ax.set_axis_off()

    # Left: one disc per reading, at the grain of the annotation itself.
    ax = axes[0]
    for pair in pairs:
        ax.plot([pair["lon_a"], pair["lon_b"]], [pair["lat_a"], pair["lat_b"]],
                color="#8d8579", linewidth=0.5, zorder=4)
    deg_lat = radius_km / KM_PER_DEG_LAT
    for label in sorted(labels, key=lambda r: r["year"]):
        colour = YEAR_INK.get(label["year"], "#2f5f8f")
        circle = plt.Circle((label["lon"], label["lat"]), deg_lat,
                            facecolor=colour, edgecolor=colour, linewidth=0.35,
                            alpha=0.16 if label["inside"] else 0.09, zorder=5)
        circle.set_transform(ax.transData)
        ax.add_patch(circle)
        ax.plot([label["lon"]], [label["lat"]], marker="o", markersize=1.7,
                color=colour, alpha=0.9 if label["inside"] else 0.45, zorder=6)
    # Names, once per tribe, at the latest sheet that carries it. Only those
    # inside the modern border: the western cluster is too dense to letter and
    # the frontier tribes are named in data/tribal_territories.csv.
    latest: dict[str, dict] = {}
    for label in labels:
        if not label["inside"]:
            continue
        current = latest.get(label["tribe"])
        if current is None or label["year"] > current["year"]:
            latest[label["tribe"]] = label
    placed: list[tuple[float, float]] = []
    for label in sorted(latest.values(), key=lambda r: (-r["lat"], r["lon"])):
        crowded = sum(1 for lon, lat in placed
                      if abs(lon - label["lon"]) < 0.42 and abs(lat - label["lat"]) < 0.22)
        dx, dy = (5, 2) if crowded % 2 == 0 else (-5, -7)
        ax.annotate(label["tribe"], (label["lon"], label["lat"]),
                    textcoords="offset points", xytext=(dx, dy), fontsize=4.0,
                    ha="left" if dx > 0 else "right", color="#3a352d", zorder=7)
        placed.append((label["lon"], label["lat"]))

    ax.legend(handles=[
        Line2D([], [], marker="o", linestyle="none", color=YEAR_INK[1853],
               markersize=5, label="1853 Pellissier"),
        Line2D([], [], marker="o", linestyle="none", color=YEAR_INK[1881],
               markersize=5, label="1881 Lasailly"),
        Line2D([], [], color="#8d8579", linewidth=0.8,
               label="same tribe, two sheets"),
    ], loc="lower left", bbox_to_anchor=(0.02, 0.06), frameon=False, fontsize=7)
    ax.set_title(f"Where the names sit, at {radius_km:.0f} km radius",
                 fontsize=9.5, color="#26231e", loc="left", pad=8)

    # Right: the imadas those discs reach.
    ax = axes[1]
    ax.legend(handles=[Patch(facecolor=STEPS[i], edgecolor=MESH,
                             label=("no tribe" if i == 0 else
                                    f"{i} tribe" + ("" if i == 1 else "s")
                                    + ("" if i < 3 else " or more")))
                       for i in range(4)],
              loc="lower left", bbox_to_anchor=(0.02, 0.06), frameon=False,
              fontsize=7)
    ax.set_title("Imadas the discs reach", fontsize=9.5, color="#26231e",
                 loc="left", pad=8)

    figure.suptitle("Tribal annotation of 1853 and 1881 on the imadas of 2022",
                    fontsize=12, color="#26231e", x=0.02, ha="left", y=0.98)
    figure.text(0.02, 0.105,
                f"{stats['labels']} labels read off two sheets, {stats['tribes']} "
                f"tribes. No sheet in this collection draws a tribal boundary, so a "
                f"tribe is drawn as the ground its name covers: a disc of "
                f"{radius_km:.0f} km radius, half the median of six labels\nmeasured "
                f"at 14 to 32 km end to end. Placement accuracy is {stats['loo']} "
                f"leave-one-out, smaller than the disc; the disc is the annotation's "
                f"own grain and cannot be reduced.\nThe discs reach "
                f"{stats['imadas_touched']} of {stats['imadas_total']} imadas, "
                f"{stats['area_pct']:.0f}% of the country's area. Boundaries are "
                f"OCHA COD 2022 and the annotation is of 1853 and 1881: the imada "
                f"says where, not that the unit existed then.\n"
                f"The blank south is not evidence of absence: the 1853 sheet was "
                f"transcribed only to about 34 N, and the 1881 sheet gives the whole "
                f"country south of Sfax to one tribe, the Ouerghemma.\nThe "
                f"{stats['outside']} paler discs west of the frontier are labels on "
                f"ground that is now Algeria: the annotation was drawn before the "
                f"border and does not stop at it.",
                fontsize=6.6, color="#57534a", va="top")
    figure.subplots_adjust(left=0.02, right=0.98, top=0.93, bottom=0.16,
                           wspace=0.02)
    figure.savefig(path, facecolor="white")
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radius-km", type=float, default=DEFAULT_RADIUS_KM)
    parser.add_argument("--no-figure", action="store_true")
    args = parser.parse_args(argv)

    imada_path = BOUNDARIES / "tun_admin4.shp"
    if not imada_path.exists():
        print("data/boundaries/tun_admin4.shp is missing; run\n"
              "    python3 scripts/fetch_boundaries.py --levels 4")
        return 1

    labels = read_labels(REPO_ROOT / "data" / "tribal_territories.csv")
    imadas = load_imadas(imada_path)
    per_tribe = cover(labels, imadas, args.radius_km)

    # The hairline pairs: a tribe whose name is on both sheets.
    by_tribe: dict[str, dict[int, dict]] = {}
    for label in labels:
        by_tribe.setdefault(label["tribe"], {})[label["year"]] = label
    pairs = [{"tribe": t, "lon_a": v[1853]["lon"], "lat_a": v[1853]["lat"],
              "lon_b": v[1881]["lon"], "lat_b": v[1881]["lat"]}
             for t, v in by_tribe.items() if 1853 in v and 1881 in v]

    write_coverage(imadas, REPO_ROOT / "data" / "tribal_imada_coverage.csv")

    touched = [u for u in imadas if u["tribes"]]
    total_area = sum(u["area_sqkm"] for u in imadas)
    fits = json.loads((REPO_ROOT / "data" / "tribal_fit.json").read_text())
    loo = ", ".join(f"{v['year']} {v['loo_rms_km']} km"
                    for k, v in fits.items() if not k.startswith("_"))
    stats = {
        "_about": ("Tribal annotation read off two sheets, put onto the 2022 "
                   "imadas. Each tribe is a disc of the given radius centred on "
                   "where its name is printed."),
        "radius_km": args.radius_km,
        "_radius_basis": ("Half the median of six labels measured end to end on "
                          "the tiles, which ran 14 to 32 km. The disc is the "
                          "annotation's own grain, not a positional error."),
        "labels": len(labels),
        "tribes": len(by_tribe),
        "tribes_on_two_sheets": len(pairs),
        "imadas_total": len(imadas),
        "imadas_touched": len(touched),
        "imadas_touched_pct": round(100 * len(touched) / len(imadas), 1),
        "area_pct": round(100 * sum(u["area_sqkm"] for u in touched) / total_area, 1),
        "imadas_with_two_or_more": sum(1 for u in touched if len(u["tribes"]) >= 2),
        "max_tribes_on_one_imada": max(len(u["tribes"]) for u in touched),
        "gouvernorats_reached": len({u["gouvernorat"] for u in touched}),
        "busiest_imada": max(touched, key=lambda u: len(u["tribes"]))["imada"],
        "busiest_gouvernorat": max(
            {u["gouvernorat"] for u in touched},
            key=lambda g: sum(1 for u in touched if u["gouvernorat"] == g)),
        "median_imadas_per_tribe": sorted(len(v) for v in per_tribe.values())[
            len(per_tribe) // 2],
        "labels_outside_modern_tunisia": sum(1 for r in labels if not r["inside"]),
        "loo_rms": loo,
        "_coverage_comment": (
            "A disc reaching an imada is not the tribe holding it, and a blank "
            "imada is not empty ground. Two thirds of the country's imadas are "
            "blank here for three different reasons that this table cannot tell "
            "apart: the 1853 sheet was transcribed only to about 34 N, the 1881 "
            "sheet gives everything south of Sfax to one tribe, and the two "
            "sheets between them name 80 groups where the country had more."),
    }
    stats["area_pct"] = float(stats["area_pct"])
    (REPO_ROOT / "data" / "tribal_imada_summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.no_figure:
        draw(labels, imadas, args.radius_km, pairs,
             REPO_ROOT / "docs" / "img" / "tribal_distribution_imada.png",
             {**stats, "loo": loo,
              "outside": sum(1 for r in labels if not r["inside"])})

    print(f"{len(labels)} labels, {len(by_tribe)} tribes, radius {args.radius_km} km")
    print(f"{len(touched)} of {len(imadas)} imadas reached "
          f"({stats['imadas_touched_pct']}%), {stats['area_pct']}% of the area")
    print(f"{stats['imadas_with_two_or_more']} imadas reached by two tribes or more, "
          f"most on one imada: {stats['max_tribes_on_one_imada']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

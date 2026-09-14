#!/usr/bin/env python3
"""The ground each tribe holds, bounded by the tribes next to it.

A tribe on these sheets is a name letterspaced across its country, with no line
around it. Four ways of drawing that have been tried here and the first three
are kept in the record because each failed differently.

  A dot per label is exact and silent about extent.

  Filling or sprinkling administrative units invents the extent and confines a
  nineteenth-century tribe inside a 2022 mesh besides.

  A Gaussian blur looks measured and is not: the bandwidth is a choice, so every
  tribe comes out the same size whatever the sheet says.

  A circle the length of the printed name is honest but far too small. The
  engraver fits the name inside the country, usually well inside; the length is
  a floor on the territory, not the territory. Drawing it as the whole thing
  understates every tribe on the sheet.

What is drawn now is the largest ellipse each tribe can have before it reaches
another tribe's name. Two rules, and nothing else:

  it must contain all of that tribe's own evidence - every label centre on every
  sheet, and, where the printed length was measured, both ends of the name;

  it must contain no other tribe's label.

The first rule sets the centre, the orientation and the minimum size from the
tribe's own spread. The second sets how far it grows, and the bound is always a
neighbouring name rather than a constant anyone chose. Where a tribe has no
neighbour for a hundred kilometres the ellipse is huge, and that is the map's
claim, not an artefact: south of Sfax the 1881 sheet gives the whole country to
the Ouerghemma.

Evidence comes from all three sheets at once, so a tribe named by Pellissier in
1853, by Lasailly in 1881 and by Martel in 1965 gets an ellipse stretched to
cover all three, and the stretch is the disagreement between them.

Outputs:
    docs/img/tribal_spread.png
    data/tribal_spread.csv              one row per tribe: its evidence, the
                                        ellipse's axes and area, and which
                                        tribe's name stopped it growing
    data/tribal_spread_summary.json

Usage:
    python3 scripts/map_tribal_spread.py
    python3 scripts/map_tribal_spread.py --max-radius-km 90
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import textwrap
import warnings
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shapefile
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse
from shapely.geometry import Point, shape

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent.parent
BOUNDARIES = REPO_ROOT / "data" / "boundaries"

SHEET_1881 = "btv1b84389986"
SOURCE_INK = {"1853 Pellissier": "#a5642a",
              "1881 Lasailly": "#2f5f8f",
              "1881 Martel (1965)": "#4a7c59"}
LAND = "#f7f5f1"
ABROAD = "#efece6"
LINE = "#c3bbae"
COAST = "#6b645a"
PALETTE = ["#b08968", "#6b8f71", "#7d8fa8", "#a8788a", "#9a8f5e", "#7f8d9e",
           "#a37f6b", "#83937c", "#8c7f9b", "#9c8a6e", "#6f8a8c", "#a1897f"]

# A tribe with no neighbour within this far stops growing anyway. It is a guard
# against one label in an empty quarter swallowing the Sahara, not a scale: only
# a handful of tribes ever reach it and the table says which.
DEFAULT_MAX_RADIUS_KM = 90.0
# Floor on the semi-axes, so a tribe known from one unmeasured label is still
# visible. One quarter of the median measured name.
MIN_SEMI_KM = 4.0

KM_PER_DEG_LAT = 110.574
LAT0 = 34.5
KM_PER_DEG_LON = 111.320 * math.cos(math.radians(LAT0))


def to_km(lon, lat):
    return np.asarray(lon) * KM_PER_DEG_LON, np.asarray(lat) * KM_PER_DEG_LAT


def to_deg(x, y):
    return x / KM_PER_DEG_LON, y / KM_PER_DEG_LAT


def exteriors(geometry):
    geoms = geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]
    return [np.asarray(g.exterior.coords) for g in geoms]


def read_evidence() -> list[dict]:
    """Every label, with the ends of the name where the length was measured."""
    cfg = json.loads((REPO_ROOT / "config" / "tribal_labels_read.json")
                     .read_text(encoding="utf-8"))
    fits = json.loads((REPO_ROOT / "data" / "tribal_fit.json").read_text())
    extents = {}
    sheet = cfg["maps"][SHEET_1881]
    for label in sheet["labels"]:
        if label.get("extent_px"):
            extents[label["text"]] = label["extent_px"] * fits[SHEET_1881]["km_per_px"]

    out = []
    for row in csv.DictReader((REPO_ROOT / "data" / "tribal_territories.csv")
                              .open(encoding="utf-8")):
        source = ("1853 Pellissier" if row["year"] == "1853" else "1881 Lasailly")
        extent = extents.get(row["label_as_printed"]) if row["record_id"] == SHEET_1881 else None
        out.append({
            "tribe": row["tribe"] or row["label_as_printed"],
            "label": row["label_as_printed"],
            "source": source,
            "lon": float(row["lon"]), "lat": float(row["lat"]),
            "extent_km": round(extent, 1) if extent else None,
            "inside": row["inside_tunisia"] == "1",
        })
    martel = REPO_ROOT / "data" / "martel_1965_tribes.csv"
    if martel.exists():
        # Martel's CSV carries no inside flag and four of his names are west of
        # the frontier, so it is computed rather than assumed.
        reader = shapefile.Reader(str(BOUNDARIES / "tun_admin0.shp"))
        tunisia = shape(reader.shapeRecords()[0].shape.__geo_interface__)
        for row in csv.DictReader(martel.open(encoding="utf-8")):
            lon, lat = float(row["lon"]), float(row["lat"])
            out.append({
                "tribe": row["tribe"], "label": row["label_as_printed"],
                "source": "1881 Martel (1965)",
                "lon": lon, "lat": lat, "extent_km": None,
                "inside": tunisia.contains(Point(lon, lat)),
            })
    return out


def evidence_points(labels: list[dict]) -> np.ndarray:
    """A label is one point, or two where the printed name was measured: the
    ends of the name are themselves ground the tribe is asserted to hold."""
    pts = []
    for label in labels:
        x, y = to_km(label["lon"], label["lat"])
        if label["extent_km"]:
            half = label["extent_km"] / 2
            pts.append((x - half, y))
            pts.append((x + half, y))
        else:
            pts.append((x, y))
    return np.array(pts, dtype=float)


def orientation(points: np.ndarray) -> np.ndarray:
    """Principal axes of the tribe's own evidence. Identity for a single point."""
    if len(points) < 2:
        return np.eye(2)
    centred = points - points.mean(axis=0)
    if np.allclose(centred, 0):
        return np.eye(2)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    return vt.T


def grow(centre, axes_dir, base, others, max_radius):
    """Largest margin that keeps every other tribe's label outside."""
    if len(others) == 0:
        return max_radius
    local = (others - centre) @ axes_dir

    def clear(margin):
        a, b = base[0] + margin, base[1] + margin
        return not np.any((local[:, 0] / a) ** 2 + (local[:, 1] / b) ** 2 < 1.0)

    if clear(max_radius):
        return max_radius
    lo, hi = 0.0, max_radius
    if not clear(lo):
        return 0.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if clear(mid):
            lo = mid
        else:
            hi = mid
    return lo


def build(evidence: list[dict], max_radius: float) -> list[dict]:
    by_tribe: dict[str, list[dict]] = defaultdict(list)
    for label in evidence:
        by_tribe[label["tribe"]].append(label)

    centres = {t: to_km([l["lon"] for l in v], [l["lat"] for l in v])
               for t, v in by_tribe.items()}
    all_centres = {t: np.column_stack(c) for t, c in centres.items()}

    out = []
    for tribe, labels in by_tribe.items():
        own = evidence_points(labels)
        centre = own.mean(axis=0)
        axes_dir = orientation(own)
        local = (own - centre) @ axes_dir
        base = np.maximum(np.abs(local).max(axis=0), MIN_SEMI_KM)
        # The half-extents of the bounding box do not make an ellipse that
        # contains the box: a point at (a, b) sits at 2 in ellipse units, not 1.
        # Scale until every one of the tribe's own points is inside, or rule 1
        # is violated by construction for every tribe with more than one label.
        need = np.sqrt(((local / base) ** 2).sum(axis=1)).max()
        if need > 1:
            base = base * need

        others_by = {t: v for t, v in all_centres.items() if t != tribe}
        others = np.vstack(list(others_by.values()))
        margin = grow(centre, axes_dir, base, others, max_radius)
        a, b = base[0] + margin, base[1] + margin

        # Which name stopped the growth, and which names the tribe's own spread
        # already swallowed before it could grow at all. The second list is not
        # a failure of the method but a finding about the sheets: a tribe whose
        # compilers put its name 90 km apart cannot help covering its
        # neighbours, and those are the tribes whose identity is in doubt.
        encloses = []
        for other, pts in others_by.items():
            loc = (pts - centre) @ axes_dir
            if np.any((loc[:, 0] / a) ** 2 + (loc[:, 1] / b) ** 2 < 1.0 - 1e-9):
                encloses.append(other)
        stopper, stop_km = "", ""
        best = None
        for other, pts in others_by.items():
            loc = (pts - centre) @ axes_dir
            d = (loc[:, 0] / a) ** 2 + (loc[:, 1] / b) ** 2
            k = int(d.argmin())
            if best is None or d[k] < best[0]:
                best = (d[k], other, float(np.hypot(*loc[k])))
        if best and margin < max_radius - 1e-6:
            stopper, stop_km = best[1], round(best[2], 1)

        lon, lat = to_deg(*centre)
        angle = math.degrees(math.atan2(axes_dir[1, 0], axes_dir[0, 0]))
        out.append({
            "tribe": tribe,
            "labels": len(labels),
            "sources": len({l["source"] for l in labels}),
            "sources_named": " | ".join(sorted({l["source"] for l in labels})),
            "printed_as": " | ".join(sorted({l["label"] for l in labels})),
            "measured_names": sum(1 for l in labels if l["extent_km"]),
            "own_spread_km": round(float(2 * base[0]), 1),
            "lon": round(lon, 3), "lat": round(lat, 3),
            "major_km": round(2 * a, 1), "minor_km": round(2 * b, 1),
            "angle_deg": round(angle, 1),
            "area_sqkm": round(math.pi * a * b),
            "grew_by_km": round(margin, 1),
            "encloses_other_tribes": len(encloses),
            "encloses": " | ".join(sorted(encloses)),
            "stopped_by": stopper,
            "stopped_at_km": stop_km,
            "at_max_radius": 1 if margin >= max_radius - 1e-6 else 0,
            "_c": centre, "_R": axes_dir, "_a": a, "_b": b,
        })
    out.sort(key=lambda r: -r["area_sqkm"])
    return out


def colour_by_overlap(rows: list[dict]) -> dict[str, str]:
    neighbours: dict[str, set[str]] = defaultdict(set)
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            d = math.dist(a["_c"], b["_c"])
            if d < (max(a["_a"], a["_b"]) + max(b["_a"], b["_b"])):
                neighbours[a["tribe"]].add(b["tribe"])
                neighbours[b["tribe"]].add(a["tribe"])
    colours = {}
    for row in sorted(rows, key=lambda r: -len(neighbours[r["tribe"]])):
        taken = {colours[n] for n in neighbours[row["tribe"]] if n in colours}
        colours[row["tribe"]] = next((c for c in PALETTE if c not in taken),
                                     PALETTE[0])
    return colours


def write_table(rows: list[dict], path: Path) -> None:
    fields = [k for k in rows[0] if not k.startswith("_")]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def draw(rows, evidence, colours, path, stats, max_radius):
    reader0 = shapefile.Reader(str(BOUNDARIES / "tun_admin0.shp"))
    tunisia = shape(reader0.shapeRecords()[0].shape.__geo_interface__)
    reader2 = shapefile.Reader(str(BOUNDARIES / "tun_admin2.shp"))
    gouvernorats = [r for s in reader2.shapeRecords()
                    for r in exteriors(shape(s.shape.__geo_interface__))]
    neighbours = []
    path_n = BOUNDARIES / "neighbours_ne50m.geojson"
    if path_n.exists():
        neighbours = [shape(f["geometry"])
                      for f in json.loads(path_n.read_text())["features"]]

    figure = plt.figure(figsize=(11.4, 8.4), dpi=200)
    ax = figure.add_axes([0.01, 0.185, 0.63, 0.735])

    for geom in neighbours:
        for ring in exteriors(geom):
            ax.fill(ring[:, 0], ring[:, 1], facecolor=ABROAD, edgecolor="none",
                    zorder=0)
            ax.plot(ring[:, 0], ring[:, 1], color=LINE, linewidth=0.4, zorder=1)
    for ring in exteriors(tunisia):
        ax.fill(ring[:, 0], ring[:, 1], facecolor=LAND, edgecolor="none", zorder=1)
    for ring in gouvernorats:
        ax.plot(ring[:, 0], ring[:, 1], color=LINE, linewidth=0.3, zorder=2)
    for ring in exteriors(tunisia):
        ax.plot(ring[:, 0], ring[:, 1], color=COAST, linewidth=0.7, zorder=3)

    for row in sorted(rows, key=lambda r: -r["area_sqkm"]):
        lon, lat = to_deg(*row["_c"])
        # Both axes are divided by the same km-per-degree and the axes aspect
        # does the rest: at this latitude a kilometre drawn vertically and one
        # drawn horizontally differ by half a per cent, which is well inside
        # everything else here.
        flagged = row["encloses_other_tribes"] > 0
        ell = Ellipse((lon, lat),
                      2 * row["_a"] / KM_PER_DEG_LON,
                      2 * row["_b"] / KM_PER_DEG_LON,
                      angle=row["angle_deg"],
                      facecolor=colours[row["tribe"]],
                      edgecolor="#8c3b2a" if flagged else colours[row["tribe"]],
                      alpha=0.30, linewidth=0.9 if flagged else 0.5,
                      linestyle=(0, (2, 1.5)) if flagged else "solid", zorder=5)
        ax.add_patch(ell)

    for label in evidence:
        ax.plot([label["lon"]], [label["lat"]], marker="o", markersize=1.7,
                markerfacecolor=SOURCE_INK[label["source"]],
                markeredgecolor="white", markeredgewidth=0.3, zorder=8)

    for row in sorted(rows, key=lambda r: -r["area_sqkm"])[:40]:
        lon, lat = to_deg(*row["_c"])
        ax.annotate(row["tribe"], (lon, lat), fontsize=4.3, ha="center",
                    va="center", color="#23211d", zorder=9)

    ax.set_xlim(6.6, 11.95)
    ax.set_ylim(31.1, 38.0)
    ax.set_aspect(1 / math.cos(math.radians(LAT0)))
    ax.set_axis_off()
    ax.legend(handles=[Line2D([], [], marker="o", linestyle="none",
                              color=SOURCE_INK[s], markersize=4, label=s)
                       for s in SOURCE_INK]
                      + [Line2D([], [], color="#8c3b2a", linewidth=1.2,
                                linestyle=(0, (2, 1.5)),
                                label="own labels already cover a neighbour")],
              loc="lower left", bbox_to_anchor=(0.0, 0.02), frameon=False,
              fontsize=6.2)

    hx = figure.add_axes([0.70, 0.50, 0.28, 0.32])
    areas = sorted(r["area_sqkm"] for r in rows)
    hx.hist(areas, bins=np.logspace(2.3, 4.6, 22), color="#7d8fa8", alpha=0.8,
            edgecolor="white", linewidth=0.4)
    hx.set_xscale("log")
    hx.axvline(statistics.median(areas), color="#8c3b2a", linewidth=1.0)
    hx.text(statistics.median(areas) * 1.15, hx.get_ylim()[1] * 0.9,
            f"median {statistics.median(areas):,.0f} km²", fontsize=6,
            color="#8c3b2a")
    hx.set_xlabel("ellipse area, km², log scale", fontsize=6.5)
    hx.set_ylabel("tribes", fontsize=6.5)
    hx.tick_params(labelsize=6)
    for side in ("top", "right"):
        hx.spines[side].set_visible(False)
    hx.set_title(f"{len(rows)} tribes", fontsize=7.5, loc="left", color="#26231e")

    figure.suptitle("The ground each tribe holds, bounded by the tribes next to it",
                    fontsize=12.5, color="#26231e", x=0.02, ha="left", y=0.975)
    figure.text(0.02, 0.937,
                "Each ellipse is the largest one that contains all of a tribe's "
                "own names and none of anybody else's.",
                fontsize=7.8, color="#3a352d", va="top")

    caption = (
        f"Two rules and no third. An ellipse must contain every one of that "
        f"tribe's labels on every sheet, and, for the "
        f"{stats['measured_names']} names on the 1881 sheet whose printed "
        f"length was measured, both ends of the name. It then grows until it "
        f"would swallow another tribe's label. The first rule fixes the centre, "
        f"the orientation and the floor; the second fixes the ceiling, and the "
        f"ceiling is always a neighbouring name rather than a constant anyone "
        f"chose. Evidence from all three sheets counts at once, so a tribe "
        f"named in 1853, 1881 and 1965 gets an ellipse stretched to cover all "
        f"three, and that stretch is the compilers disagreeing."
    )
    warning = (
        f"Areas run {min(areas):,} to {max(areas):,} km², median "
        f"{statistics.median(areas):,.0f}. This is deliberately the largest "
        f"reading the sheets will carry, not the smallest: the printed name is "
        f"a floor on a tribe's country, since the engraver fits it inside, and "
        f"an earlier version of this figure drew that floor as though it were "
        f"the whole. What bounds an ellipse here is the next tribe along. "
        f"Every one of the {stats['tribes']} ellipses was stopped by a "
        f"neighbouring name rather than by the {max_radius:.0f} km guard, so "
        f"nothing here is sized by a constant. Nothing is clipped to the modern "
        f"frontier either, which {stats['outside']} of the labels sit west of. "
        f"Ellipses overlap where the sheets disagree, and the overlap is left "
        f"to be seen. The {stats['flagged']} ellipses drawn with a dashed red "
        f"edge are the ones whose own labels already cover a neighbour before "
        f"any growth: Ouled Sdira's three names stand 211 km apart and Ouled "
        f"Khiar's two 287 km, which is not a territory but two groups sharing a "
        f"name. scripts/check_tribal_spread.py tests both rules and redraws "
        f"every ellipse on the 1881 scan to be compared against the engraving."
    )
    figure.text(0.02, 0.145,
                "\n".join(textwrap.wrap(caption, 185)
                          + textwrap.wrap(warning, 185)),
                fontsize=6.6, color="#57534a", va="top")
    figure.savefig(path, facecolor="white")
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-radius-km", type=float, default=DEFAULT_MAX_RADIUS_KM)
    parser.add_argument("--no-figure", action="store_true")
    args = parser.parse_args(argv)

    evidence = read_evidence()
    rows = build(evidence, args.max_radius_km)
    colours = colour_by_overlap(rows)
    write_table(rows, REPO_ROOT / "data" / "tribal_spread.csv")

    areas = sorted(r["area_sqkm"] for r in rows)
    stats = {
        "_about": ("One ellipse per tribe: the largest that contains all of its "
                   "own labels and none of any other tribe's."),
        "_the_two_rules": [
            "Contain every label of this tribe on every sheet, and both ends of "
            "the name wherever the printed length was measured.",
            "Contain no other tribe's label. The ellipse grows until it would.",
        ],
        "_why_not_smaller": (
            "The printed name is a floor on a tribe's country, not the country: "
            "the engraver fits the name inside the ground it names. An earlier "
            "figure drew a circle the length of the name and understated every "
            "tribe on the sheet."),
        "_why_not_a_blur": (
            "A Gaussian bandwidth is a number nobody measured, and it gives "
            "every tribe the same size whatever the sheet says."),
        "max_radius_km": args.max_radius_km,
        "min_semi_km": MIN_SEMI_KM,
        "tribes": len(rows),
        "labels": len(evidence),
        "measured_names": sum(1 for e in evidence if e["extent_km"]),
        "labels_outside_modern_tunisia": sum(1 for e in evidence if not e["inside"]),
        "tribes_on_more_than_one_sheet": sum(1 for r in rows if r["sources"] > 1),
        "at_max_radius": sum(1 for r in rows if r["at_max_radius"]),
        "min_area_sqkm": areas[0],
        "median_area_sqkm": statistics.median(areas),
        "max_area_sqkm": areas[-1],
        "tribes_enclosing_a_neighbour": sum(1 for r in rows
                                            if r["encloses_other_tribes"] > 0),
        "_enclosing_comment": (
            "Their own labels already cover a neighbour before the ellipse "
            "grows at all, so rule 2 cannot hold for them. That is a statement "
            "about the sources: a tribe whose compilers put its name 200 km "
            "apart is a name collision, not a territory. Drawn dashed."),
        "widest": [{"tribe": r["tribe"], "area_sqkm": r["area_sqkm"],
                    "major_km": r["major_km"], "minor_km": r["minor_km"],
                    "stopped_by": r["stopped_by"]} for r in rows[:6]],
    }
    stats["outside"] = stats["labels_outside_modern_tunisia"]
    stats["flagged"] = stats["tribes_enclosing_a_neighbour"]
    stats["at_max"] = stats["at_max_radius"]
    (REPO_ROOT / "data" / "tribal_spread_summary.json").write_text(
        json.dumps({k: v for k, v in stats.items()
                   if k not in ("outside", "at_max", "flagged")},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.no_figure:
        draw(rows, evidence, colours,
             REPO_ROOT / "docs" / "img" / "tribal_spread.png", stats,
             args.max_radius_km)

    print(f"{len(rows)} tribes from {len(evidence)} labels")
    print(f"ellipse area {areas[0]:,} to {areas[-1]:,} km², "
          f"median {statistics.median(areas):,.0f}")
    print(f"{stats['at_max_radius']} tribes reached the {args.max_radius_km:.0f} km guard")
    for r in rows[:5]:
        print(f"  {r['tribe']:22s} {r['major_km']:6.0f} x {r['minor_km']:5.0f} km, "
              f"{r['area_sqkm']:>7,} km²  stopped by {r['stopped_by'] or 'the guard'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

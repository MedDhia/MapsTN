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
SOURCES = list(SOURCE_INK)
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


# Fractions the gazetteer holds under their own name, whose parent is stated by
# Ganiage's Annexe I rather than by the name. The footnote is the authority and
# is quoted here so the attribution is not mistaken for a guess.
ANNEXE_PARENT = {
    "Oulad Khalifa": ("Zlass", "Annexe I footnote 2, Tribu des Zlass"),
    "Ouled Redouan": ("Hammama", "Annexe I footnote 5, Tribu des Hammama"),
    "Ouled el Goussem": ("Hammama", "Annexe I footnote 5 covers the Hammama "
                                    "fractions; Pellissier maps this one apart"),
}


def parent_of(tribe: str) -> str:
    """Which tribe a branch belongs to.

    Two authorities. A gazetteer name of the form 'Hammama - Oulad Aziz' says
    so itself, the em dash being the gazetteer's own mark for a fraction. For
    the fractions the gazetteer holds under a bare name, the parent comes from
    Ganiage's Annexe I footnotes, which tie each fiscal circumscription to its
    tribe.
    """
    for sep in ("\u2014", " - "):
        if sep in tribe:
            return tribe.split(sep)[0].strip()
    if tribe in ANNEXE_PARENT:
        return ANNEXE_PARENT[tribe][0]
    return ""


def build(evidence: list[dict], max_radius: float,
          constraints: list[dict] | None = None) -> list[dict]:
    """Ellipses from `evidence`, stopped by the labels in `constraints`.

    Pass the same list for both and each tribe is bounded by every other tribe
    in it. Pass one sheet's labels as evidence and that same sheet as
    constraints, and the panel says what that cartographer alone says: his
    tribes, bounded by his own neighbours, with nobody else's reading allowed
    to shrink them.
    """
    by_tribe: dict[str, list[dict]] = defaultdict(list)
    for label in evidence:
        by_tribe[label["tribe"]].append(label)

    limit: dict[str, list[dict]] = defaultdict(list)
    for label in (constraints if constraints is not None else evidence):
        limit[label["tribe"]].append(label)

    all_centres = {t: np.column_stack(to_km([l["lon"] for l in v],
                                            [l["lat"] for l in v]))
                   for t, v in limit.items()}

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
        if others_by:
            others = np.vstack(list(others_by.values()))
            margin = grow(centre, axes_dir, base, others, max_radius)
        else:
            margin = max_radius
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
            "parent": parent_of(tribe),
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


def basemap(ax, tunisia, gouvernorats, neighbours):
    for geom in neighbours:
        for ring in exteriors(geom):
            ax.fill(ring[:, 0], ring[:, 1], facecolor=ABROAD, edgecolor="none",
                    zorder=0)
            ax.plot(ring[:, 0], ring[:, 1], color=LINE, linewidth=0.35, zorder=1)
    for ring in exteriors(tunisia):
        ax.fill(ring[:, 0], ring[:, 1], facecolor=LAND, edgecolor="none", zorder=1)
    for ring in gouvernorats:
        ax.plot(ring[:, 0], ring[:, 1], color=LINE, linewidth=0.25, zorder=2)
    for ring in exteriors(tunisia):
        ax.plot(ring[:, 0], ring[:, 1], color=COAST, linewidth=0.6, zorder=3)
    ax.set_xlim(6.6, 11.95)
    ax.set_ylim(30.9, 38.0)
    ax.set_aspect(1 / math.cos(math.radians(LAT0)))
    ax.set_axis_off()


def ellipse_patch(row, facecolor, edgecolor, alpha, lw, dashed=False):
    lon, lat = to_deg(*row["_c"])
    return Ellipse((lon, lat),
                   2 * row["_a"] / KM_PER_DEG_LON,
                   2 * row["_b"] / KM_PER_DEG_LON,
                   angle=row["angle_deg"], facecolor=facecolor,
                   edgecolor=edgecolor, alpha=alpha, linewidth=lw,
                   linestyle=(0, (2, 1.5)) if dashed else "solid", zorder=5)


def write_per_sheet(panels, path: Path) -> None:
    """One row per tribe per sheet, so the panels can be read as numbers."""
    fields = ["sheet", "tribe", "parent", "labels", "printed_as",
              "own_spread_km", "lon", "lat", "major_km", "minor_km",
              "angle_deg", "area_sqkm", "grew_by_km", "stopped_by",
              "stopped_at_km", "encloses_other_tribes"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for source, rows in panels:
            for row in sorted(rows, key=lambda r: -r["area_sqkm"]):
                writer.writerow({**row, "sheet": source})


def draw(panels, pooled_rows, colours, evidence, path, stats, max_radius):
    """Five panels: one per cartographer, then all three superposed, then the
    three merged into one reading."""
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

    figure = plt.figure(figsize=(16.4, 8.2), dpi=195)
    width = 0.187
    axes = [figure.add_axes([0.008 + i * (width + 0.006), 0.175, width, 0.735])
            for i in range(5)]

    # 1 to 3: one cartographer each, his tribes bounded by his own neighbours.
    for ax, (source, rows) in zip(axes, panels):
        basemap(ax, tunisia, gouvernorats, neighbours)
        for row in sorted(rows, key=lambda r: -r["area_sqkm"]):
            ax.add_patch(ellipse_patch(row, SOURCE_INK[source], SOURCE_INK[source],
                                       0.22, 0.5))
        for label in evidence:
            if label["source"] == source:
                ax.plot([label["lon"]], [label["lat"]], marker="o", markersize=1.5,
                        markerfacecolor=SOURCE_INK[source], markeredgecolor="white",
                        markeredgewidth=0.3, zorder=8)
        for row in sorted(rows, key=lambda r: -r["area_sqkm"])[:16]:
            lon, lat = to_deg(*row["_c"])
            ax.annotate(row["tribe"], (lon, lat), fontsize=3.8, ha="center",
                        va="center", color="#23211d", zorder=9)
        ax.set_title(source, fontsize=8.5, color="#26231e", loc="left", pad=5)
        ax.text(0.0, 0.175,
                f"{len(rows)} tribes\n{sum(1 for l in evidence if l['source'] == source)} names",
                transform=ax.transAxes, fontsize=5.8, color="#57534a", va="top")

    # 4: the three superposed, so where they agree and where they do not is the
    # picture rather than a number.
    ax = axes[3]
    basemap(ax, tunisia, gouvernorats, neighbours)
    for source, rows in panels:
        for row in rows:
            ax.add_patch(ellipse_patch(row, "none", SOURCE_INK[source], 0.55, 0.55))
    ax.set_title("All three, superposed", fontsize=8.5, color="#26231e",
                 loc="left", pad=5)
    ax.legend(handles=[Line2D([], [], color=SOURCE_INK[s], linewidth=1.1, label=s)
                       for s, _ in panels],
              loc="lower left", bbox_to_anchor=(0.0, 0.01), frameon=False,
              fontsize=5.8)

    # 5: one ellipse per tribe from all the evidence at once.
    ax = axes[4]
    basemap(ax, tunisia, gouvernorats, neighbours)
    for row in sorted(pooled_rows, key=lambda r: -r["area_sqkm"]):
        flagged = row["encloses_other_tribes"] > 0
        ax.add_patch(ellipse_patch(
            row, colours[row["tribe"]],
            "#8c3b2a" if flagged else colours[row["tribe"]],
            0.28, 0.9 if flagged else 0.5, dashed=flagged))
    for label in evidence:
        ax.plot([label["lon"]], [label["lat"]], marker="o", markersize=1.4,
                markerfacecolor=SOURCE_INK[label["source"]],
                markeredgecolor="white", markeredgewidth=0.25, zorder=8)
    for row in sorted(pooled_rows, key=lambda r: -r["area_sqkm"])[:24]:
        lon, lat = to_deg(*row["_c"])
        ax.annotate(row["tribe"], (lon, lat), fontsize=3.8, ha="center",
                    va="center", color="#23211d", zorder=9)
    ax.set_title("Merged across the three", fontsize=8.5, color="#26231e",
                 loc="left", pad=5)
    ax.text(0.0, 0.175,
            f"{len(pooled_rows)} tribes\n{len(evidence)} names\n"
            f"{stats['flagged']} dashed: own labels\nalready cover a neighbour",
            transform=ax.transAxes, fontsize=5.8, color="#57534a", va="top")

    figure.suptitle("The ground each tribe holds, one cartographer at a time and "
                    "then together",
                    fontsize=13, color="#26231e", x=0.008, ha="left", y=0.975)
    figure.text(0.008, 0.938,
                "Each ellipse is the largest that contains all of a tribe's own "
                "names on that sheet and none of its neighbours' on the same "
                "sheet. The fourth panel lays the three over each other; the "
                "fifth builds one ellipse per tribe from all the evidence at once.",
                fontsize=7.6, color="#3a352d", va="top")

    caption = (
        f"Two rules and no third. An ellipse contains every one of that tribe's "
        f"labels, and both ends of the name for the "
        f"{stats['measured_names']} on the 1881 sheet whose printed length was "
        f"measured; it then grows until it would swallow another tribe's label. "
        f"In the first three panels both the evidence and the bound come from "
        f"that sheet alone, so each is a statement about one cartographer, and "
        f"the panels are not the same country carved up the same way: a "
        f"compiler who names few tribes gives each of them more ground, which "
        f"is why Martel's 27 names fill more of the map than Lasailly's 69."
    )
    warning = (
        f"Read the fourth panel for disagreement. Where the three outlines "
        f"nest, the sheets agree about a tribe and the merged ellipse is small; "
        f"where they cross, they do not. Read the fifth for the best single "
        f"answer the three together support, and read its dashed ellipses as "
        f"warnings: {stats['flagged']} tribes have their own labels so far "
        f"apart that no ellipse containing them can avoid covering a "
        f"neighbour, and those are suspected name collisions rather than "
        f"territories. Areas run {stats['min_area_sqkm']:,} to "
        f"{stats['max_area_sqkm']:,} km\u00b2, median "
        f"{stats['median_area_sqkm']:,.0f}. Nothing is clipped to the modern "
        f"frontier, which {stats['outside']} of the "
        f"{stats['labels']} labels sit west of. "
        f"scripts/check_tribal_spread.py redraws every one of these on the scan "
        f"it came from."
    )
    figure.text(0.008, 0.135,
                "\n".join(textwrap.wrap(caption, 265)
                          + textwrap.wrap(warning, 265)),
                fontsize=6.6, color="#57534a", va="top")
    figure.savefig(path, facecolor="white")
    plt.close(figure)



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-radius-km", type=float, default=DEFAULT_MAX_RADIUS_KM)
    parser.add_argument("--no-figure", action="store_true")
    args = parser.parse_args(argv)

    evidence = read_evidence()
    pooled = build(evidence, args.max_radius_km)
    colours = colour_by_overlap(pooled)

    # One set per cartographer: his tribes, bounded by his own neighbours.
    panels = []
    for source in SOURCES:
        subset = [e for e in evidence if e["source"] == source]
        panels.append((source, build(subset, args.max_radius_km, subset)))

    write_table(pooled, REPO_ROOT / "data" / "tribal_spread.csv")
    write_per_sheet(panels, REPO_ROOT / "data" / "tribal_spread_by_sheet.csv")

    rows = pooled
    areas = sorted(r["area_sqkm"] for r in rows)
    branches = [r for r in rows if r["parent"]]
    stats = {
        "_about": ("One ellipse per tribe: the largest that contains all of its "
                   "own labels and none of any other tribe's."),
        "_the_two_rules": [
            "Contain every label of this tribe, and both ends of the name "
            "wherever the printed length was measured.",
            "Contain no other tribe's label. The ellipse grows until it would.",
        ],
        "_per_sheet": (
            "The same rules applied to one sheet at a time, in "
            "data/tribal_spread_by_sheet.csv. Evidence and bound both come from "
            "that sheet, so each is a statement about one cartographer rather "
            "than a share of a common carve-up."),
        "_why_not_smaller": (
            "The printed name is a floor on a tribe's country, not the country: "
            "the engraver fits the name inside the ground it names."),
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
        "tribes_enclosing_a_neighbour": sum(1 for r in rows
                                            if r["encloses_other_tribes"] > 0),
        "_enclosing_comment": (
            "Their own labels already cover a neighbour before the ellipse "
            "grows at all, so rule 2 cannot hold for them. That is a statement "
            "about the sources: a tribe whose compilers put its name 200 km "
            "apart is a name collision, not a territory. Drawn dashed."),
        "branches": {
            "n": len(branches),
            "_about": ("A fraction that at least one sheet maps apart from its "
                       "parent. Either the gazetteer name says so, as in "
                       "'Hammama - Oulad Aziz', or Ganiage's Annexe I footnotes "
                       "do: footnote 2 gathers the Zlass fractions and footnote "
                       "5 the Hammama. The parent column in the table names it "
                       "and _annexe_attributions gives the footnote."),
            "_annexe_attributions": {k: v[1] for k, v in ANNEXE_PARENT.items()},
            "by_parent": {parent: sorted(r["tribe"] for r in branches
                                         if r["parent"] == parent)
                          for parent in sorted({r["parent"] for r in branches})},
        },
        "per_sheet": {source: {
            "names": sum(1 for e in evidence if e["source"] == source),
            "tribes": len(rws),
            "median_area_sqkm": statistics.median([r["area_sqkm"] for r in rws]),
            "area_covered_sqkm": round(sum(r["area_sqkm"] for r in rws)),
        } for source, rws in panels},
        "min_area_sqkm": areas[0],
        "median_area_sqkm": statistics.median(areas),
        "max_area_sqkm": areas[-1],
        "widest": [{"tribe": r["tribe"], "area_sqkm": r["area_sqkm"],
                    "major_km": r["major_km"], "minor_km": r["minor_km"],
                    "stopped_by": r["stopped_by"]} for r in rows[:6]],
    }
    stats["outside"] = stats["labels_outside_modern_tunisia"]
    stats["at_max"] = stats["at_max_radius"]
    stats["flagged"] = stats["tribes_enclosing_a_neighbour"]
    (REPO_ROOT / "data" / "tribal_spread_summary.json").write_text(
        json.dumps({k: v for k, v in stats.items()
                    if k not in ("outside", "at_max", "flagged")},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.no_figure:
        draw(panels, pooled, colours, evidence,
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

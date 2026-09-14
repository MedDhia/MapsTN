#!/usr/bin/env python3
"""The spread of each tribe, as the sheet itself states it.

A tribe on these maps is a name letterspaced across the country it holds. The
engraver decides how far to spread it, and that spread is the only statement the
sheet makes about extent. Every other way of drawing it tried here invented the
number instead of reading it:

  A dot per label marks where a word was centred and says nothing about extent.

  Filling or sprinkling administrative units answers extent by inventing it,
  and confines a nineteenth-century tribe inside a 2022 mesh besides.

  Blurring the labels with a Gaussian looks like a field but the bandwidth was
  a choice, so every tribe came out the same size whatever the map said. Worse,
  it flattened the one real signal: OUERGAMA is letterspaced 1.7 times wider per
  letter than MEKENA, and that difference is the map speaking.

So the extents were measured. Each label on the 1881 Lasailly sheet was cropped
from the full scan into a contact sheet with a pixel ruler beneath it and read
by eye, end to end: 62 of 69 labels, the other 7 running into a sheet edge or
into another name. Each tribe is then drawn as a circle whose diameter is that
printed length.

Why a circle and not an ellipse: the sheet gives one number, the length of the
name along its baseline. The across-name dimension is not stated anywhere, and
an ellipse would have to invent it, which is the mistake this figure exists to
stop making. A circle adds no second parameter and no orientation.

The 1853 Pellissier and 1965 Martel sheets are not drawn as circles here. Their
names are set on long arcs and verticals rather than horizontal baselines, so
the same reading has to be done differently, and until it is done their labels
appear as points only.

Outputs:
    docs/img/tribal_spread.png
    data/tribal_spread.csv              one row per label, with its measured
                                        printed extent in pixels and kilometres
    data/tribal_spread_summary.json

Usage:
    python3 scripts/map_tribal_spread.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import textwrap
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shapefile
from matplotlib.lines import Line2D
from shapely.geometry import shape

warnings.filterwarnings("ignore")
REPO_ROOT = Path(__file__).resolve().parent.parent
BOUNDARIES = REPO_ROOT / "data" / "boundaries"

SHEET = "btv1b84389986"
SHEET_NAME = "1881 Lasailly"
OTHER_INK = {"1853 Pellissier": "#a5642a", "1881 Martel (1965)": "#4a7c59"}
INK = "#2f5f8f"
LAND = "#f7f5f1"
ABROAD = "#efece6"
MESH = "#e4dfd5"
LINE = "#c3bbae"
COAST = "#6b645a"

KM_PER_DEG_LAT = 110.574
LAT0 = 34.5
KM_PER_DEG_LON = 111.320 * math.cos(math.radians(LAT0))


def exteriors(geometry):
    geoms = geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]
    return [np.asarray(g.exterior.coords) for g in geoms]


def load_measured() -> tuple[list[dict], dict]:
    """The 1881 labels with their measured printed extent, placed on the ground."""
    cfg = json.loads((REPO_ROOT / "config" / "tribal_labels_read.json")
                     .read_text(encoding="utf-8"))
    sheet = cfg["maps"][SHEET]
    fit = json.loads((REPO_ROOT / "data" / "tribal_fit.json").read_text())[SHEET]
    km_per_px = fit["km_per_px"]

    placed = {}
    for row in csv.DictReader((REPO_ROOT / "data" / "tribal_territories.csv")
                              .open(encoding="utf-8")):
        if row["record_id"] == SHEET:
            placed[row["label_as_printed"]] = row

    out = []
    for label in sheet["labels"]:
        row = placed.get(label["text"])
        if row is None:
            continue
        out.append({
            "label": label["text"],
            "tribe": row["tribe"] or label["text"],
            "lon": float(row["lon"]),
            "lat": float(row["lat"]),
            "inside": row["inside_tunisia"] == "1",
            "extent_px": label.get("extent_px"),
            "basis": label.get("extent_basis", "not_measured"),
            "extent_km": (round(label["extent_px"] * km_per_px, 1)
                          if label.get("extent_px") else None),
        })
    return out, {"km_per_px": km_per_px, "scale": sheet["scale"]}


def load_other_points() -> list[dict]:
    out = []
    for row in csv.DictReader((REPO_ROOT / "data" / "tribal_territories.csv")
                              .open(encoding="utf-8")):
        if row["record_id"] != SHEET:
            out.append({"lon": float(row["lon"]), "lat": float(row["lat"]),
                        "source": "1853 Pellissier"})
    martel = REPO_ROOT / "data" / "martel_1965_tribes.csv"
    if martel.exists():
        for row in csv.DictReader(martel.open(encoding="utf-8")):
            out.append({"lon": float(row["lon"]), "lat": float(row["lat"]),
                        "source": "1881 Martel (1965)"})
    return out


def write_table(labels: list[dict], path: Path) -> None:
    rows = sorted(labels, key=lambda r: -(r["extent_km"] or 0))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["sheet", "label_as_printed", "tribe", "lon", "lat",
                         "extent_px", "extent_km", "extent_basis",
                         "inside_tunisia"])
        for row in rows:
            writer.writerow([SHEET_NAME, row["label"], row["tribe"], row["lon"],
                             row["lat"], row["extent_px"] or "",
                             row["extent_km"] or "", row["basis"],
                             1 if row["inside"] else 0])


def draw(labels, others, meta, path, stats):
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

    figure = plt.figure(figsize=(11.0, 8.0), dpi=200)
    ax = figure.add_axes([0.01, 0.14, 0.60, 0.76])
    hx = figure.add_axes([0.68, 0.42, 0.29, 0.40])

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

    for point in others:
        ax.plot([point["lon"]], [point["lat"]], marker="+", markersize=2.6,
                markeredgewidth=0.5, color=OTHER_INK[point["source"]], zorder=4)

    # One circle per label, diameter the printed length of the name.
    for row in labels:
        if not row["extent_km"]:
            ax.plot([row["lon"]], [row["lat"]], marker="x", markersize=2.6,
                    markeredgewidth=0.6, color="#8d8579", zorder=6)
            continue
        radius_lat = row["extent_km"] / 2 / KM_PER_DEG_LAT
        alpha = 0.30 if row["inside"] else 0.16
        circle = plt.Circle((row["lon"], row["lat"]), radius_lat,
                            facecolor=INK, edgecolor=INK, linewidth=0.45,
                            alpha=alpha, zorder=5)
        ax.add_patch(circle)
        ax.plot([row["lon"]], [row["lat"]], marker="o", markersize=1.2,
                color=INK, zorder=7)

    biggest = sorted((r for r in labels if r["extent_km"]),
                     key=lambda r: -r["extent_km"])[:22]
    for row in biggest:
        ax.annotate(f"{row['tribe']}  {row['extent_km']:.0f}",
                    (row["lon"], row["lat"]), fontsize=4.2, ha="center",
                    va="center", color="#23211d", zorder=8)

    ax.set_xlim(6.95, 11.9)
    ax.set_ylim(32.2, 37.8)
    ax.set_aspect(1 / math.cos(math.radians(LAT0)))
    ax.set_axis_off()
    ax.legend(handles=[
        Line2D([], [], marker="o", linestyle="none", color=INK, markersize=7,
               alpha=0.4, label="1881 Lasailly, circle = printed length"),
        Line2D([], [], marker="x", linestyle="none", color="#8d8579",
               markersize=4, label="1881, extent not measurable"),
        Line2D([], [], marker="+", linestyle="none",
               color=OTHER_INK["1853 Pellissier"], markersize=4,
               label="1853 Pellissier, not yet measured"),
        Line2D([], [], marker="+", linestyle="none",
               color=OTHER_INK["1881 Martel (1965)"], markersize=4,
               label="1881 Martel, not yet measured"),
    ], loc="lower left", bbox_to_anchor=(0.0, 0.0), frameon=False, fontsize=6.2)

    km = sorted(r["extent_km"] for r in labels if r["extent_km"])
    hx.hist(km, bins=np.arange(0, 55, 2.5), color=INK, alpha=0.65,
            edgecolor="white", linewidth=0.4)
    hx.axvline(statistics.median(km), color="#8c3b2a", linewidth=1.0)
    hx.text(statistics.median(km) + 1, hx.get_ylim()[1] * 0.92,
            f"median {statistics.median(km):.0f} km", fontsize=6,
            color="#8c3b2a")
    hx.set_xlabel("printed length of the name, km", fontsize=6.5)
    hx.set_ylabel("labels", fontsize=6.5)
    hx.tick_params(labelsize=6)
    for side in ("top", "right"):
        hx.spines[side].set_visible(False)
    hx.set_title(f"{len(km)} measured, {stats['unmeasured']} not",
                 fontsize=7.5, loc="left", color="#26231e")

    figure.suptitle("How much ground a tribe's name covers, measured off the sheet",
                    fontsize=12.5, color="#26231e", x=0.02, ha="left", y=0.975)
    figure.text(0.02, 0.935,
                f"Carte du théâtre de la guerre en Tunisie, Ch. Lasailly, 1881, "
                f"{meta['scale']}. Every circle's diameter is the length of the "
                f"tribe's name as engraved, read off the scan.",
                fontsize=7.6, color="#3a352d", va="top")

    caption = (
        f"A tribe on this sheet is a name letterspaced across the country it "
        f"holds, and how far the engraver spread it is the only statement the "
        f"map makes about extent. Each of the {stats['measured']} labels here "
        f"was cropped from the full scan with a pixel ruler under it and read "
        f"end to end by eye; {stats['unmeasured']} more run into a sheet edge or "
        f"another name and are drawn as crosses. The circle is centred on the "
        f"middle of the name and its diameter is that length, converted at "
        f"{meta['km_per_px']:.4f} km per scan pixel."
    )
    warning = (
        f"Why a circle and not an ellipse: the sheet states one number, the "
        f"length along the baseline. The across-name dimension is nowhere on "
        f"the map, and an ellipse would have to invent it. Nothing is clipped "
        f"either, so a circle crosses the modern frontier wherever the name "
        f"does. Measured extents run {min(km):.0f} to {max(km):.0f} km with a "
        f"median of {statistics.median(km):.0f}, which corrects the 14 to 32 km "
        f"this repository quoted from a sample of six: the sheet spreads the "
        f"great confederations far wider than that and the small tribes far "
        f"tighter. The 1853 Pellissier and 1965 Martel sheets set their names "
        f"on arcs and verticals rather than baselines, so the same reading has "
        f"to be done differently and their labels are still points."
    )
    figure.text(0.02, 0.105,
                "\n".join(textwrap.wrap(caption, 178)
                          + textwrap.wrap(warning, 178)),
                fontsize=6.6, color="#57534a", va="top")
    figure.savefig(path, facecolor="white")
    plt.close(figure)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-figure", action="store_true")
    args = parser.parse_args(argv)

    labels, meta = load_measured()
    others = load_other_points()
    write_table(labels, REPO_ROOT / "data" / "tribal_spread.csv")

    km = sorted(r["extent_km"] for r in labels if r["extent_km"])
    widest = max((r for r in labels if r["extent_km"]), key=lambda r: r["extent_km"])
    narrowest = min((r for r in labels if r["extent_km"]), key=lambda r: r["extent_km"])
    stats = {
        "_about": ("The printed length of each tribal name on the 1881 Lasailly "
                   "sheet, read by eye off contact sheets cropped from the full "
                   "scan with a pixel ruler. The map's own statement of how much "
                   "ground a tribe covers."),
        "_why_a_circle": (
            "The sheet gives one number, the length of the name along its "
            "baseline. The across-name dimension is stated nowhere, so an "
            "ellipse would have to invent it. A circle of that diameter adds no "
            "second parameter and no orientation."),
        "_what_this_replaces": (
            "Three earlier drawings, all of which supplied the extent the map "
            "did not: a dot per label, a fill or sprinkle of administrative "
            "units, and a Gaussian blur whose bandwidth was a choice. The blur "
            "was the worst of the three because it looked measured and gave "
            "every tribe the same size; OUERGAMA is letterspaced 1.7 times "
            "wider per letter than MEKENA, and that is the map speaking."),
        "sheet": SHEET_NAME,
        "scale": meta["scale"],
        "km_per_px": meta["km_per_px"],
        "labels": len(labels),
        "measured": len(km),
        "unmeasured": sum(1 for r in labels if not r["extent_km"]),
        "min_km": km[0],
        "median_km": statistics.median(km),
        "mean_km": round(statistics.mean(km), 1),
        "max_km": km[-1],
        "widest": {"tribe": widest["tribe"], "printed": widest["label"],
                   "km": widest["extent_km"]},
        "narrowest": {"tribe": narrowest["tribe"], "printed": narrowest["label"],
                      "km": narrowest["extent_km"]},
        "_earlier_claim": (
            "docs quoted 14 to 32 km from six labels measured on the tiles. "
            "With 62 measured the range is wider at both ends and the median is "
            "lower: the sample of six had missed both the small tribes and the "
            "great confederations."),
        "_not_yet_measured": (
            "The 1853 Pellissier and 1965 Martel sheets. Their names are set on "
            "long arcs and verticals rather than horizontal baselines, so the "
            "endpoints have to be read differently. Their labels stay points."),
    }
    (REPO_ROOT / "data" / "tribal_spread_summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.no_figure:
        draw(labels, others, meta,
             REPO_ROOT / "docs" / "img" / "tribal_spread.png", stats)

    print(f"{len(km)} labels measured, {stats['unmeasured']} not")
    print(f"printed length {km[0]:.1f} to {km[-1]:.1f} km, "
          f"median {statistics.median(km):.1f}, mean {stats['mean_km']}")
    print(f"widest {widest['tribe']} ({widest['label']}) {widest['extent_km']} km; "
          f"narrowest {narrowest['tribe']} {narrowest['extent_km']} km")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

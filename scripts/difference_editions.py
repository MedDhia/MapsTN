#!/usr/bin/env python3
"""Compare the houses drawn on two editions of the same sheet.

Six sheets of the series exist in two printings: an early one carrying only the
grade graticule, and a later one with the Lambert kilometric grid overprinted.
The catalogue dates them 1902 against 1931-1935, which invites a thirty-year
comparison of settlement. That comparison is not available, and the sheets say
so themselves in the credit block both printings set above the frame.

Five of the six pairs print the *same* credit block, character for character:

    La Marsa          Sauret Cap.ne {a,b} 1891                      both
    Tunis             Roget, Corniot, Martinez, Bonnefoy,
                      Espinasse, Lachouque, Delaunay 1889           both
    Sidi Bou Ali      Balland, Moreau, Montagnon, Clerc,
                      Vuillemin 1892                                both
    Halk El Mennzel   Moreau Capitaine a 1892, Wary Lieut.t b id    both
    Sousse            Wary, Corniot, Esnol 1892                     both

Same officers, same year, same wording. The later printing adds the red grid and
the red corner coordinates; it does not add a survey. Those five are reprints.

The sixth is not:

    Porto-Farina      early:  Corniot, Tantot, Thiebaut, Soulie 1891
                      late:   "D'apres les travaux: a,b,c,d,e leves en 1900,
                              revises en 1931-32; f,g,h,i,j,k,l,m,n leves en
                              1930-31 et 1932"

Porto-Farina really was resurveyed, forty years later, and its later printing
says so in a different form of words - a block index rather than a list of
officers. So the six pairs are five controls and one experiment, which is a
better design than six experiments would have been: the controls say what "no
change on the ground" looks like when measured this way.

What they say is that it looks like anything. On the four reprint pairs with
enough houses to count, the later printing of a sheet that is provably one survey
carries between 0.86 and 2.20 times as many detected houses as the earlier one,
and reproduces only 40-50% of the early drawing within the match radius.
Porto-Farina, the one pair with forty years of new fieldwork between the
printings, sits at 1.12 times - closer to unchanged than any reprint - and at
38%, two points below the lowest reprint against a ten-point spread among sheets
that are the same drawing. Neither statistic separates the resurvey from the
reprints.

That is the result. The differences between these editions are dominated by what
changed between printings and scans - plate redrawing, paper, exposure, and the
accuracy with which the early sheet can be placed from its graticule - and not by
the ground. One measurement makes that concrete: every later printing carries 2 to
20 times the red-ink density of its early twin (red_density in
data/sheet_grid.json), so a detector that works on red ink is not looking at
comparable images. Anyone who dates these sheets from the catalogue and
differences the counts will measure the print shop and call it settlement.

What it reports per pair, on the ground the two editions share:

    matched        a house on both editions within MATCH_RADIUS_M
    early_only     drawn on the early printing, absent from the later
    late_only      drawn on the later printing, absent from the early
    matched_share  matched / early count - how much of the early drawing the
                   later printing reproduces
    count_ratio    late / early count in the shared ground

MATCH_RADIUS_M is set by the georeferencing, not by cartography. The early
sheets are placed from their graticule to a median 549 m against their late
twin, so a house cannot be matched more tightly than that; 400 m is the working
figure and the sensitivity to it is reported. The share barely moves between 250
and 600 m, which is how we know the unmatched houses are absent from the other
printing rather than merely displaced.

Outputs:
    data/edition_credits.csv        the two credit blocks per pair, transcribed
    data/edition_difference.csv
    docs/img/edition_credits.png    the credit blocks themselves, as evidence
    docs/img/edition_difference.png

Usage:
    python3 scripts/difference_editions.py [--scans <dir of sheet scans>]

--scans is only needed for the credit-block figure; the scans are 700 MB and
are not in the repository (scripts/fetch_sheet_images.py fetches them).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent

# Bounded by the placement, not by the map: the early sheets sit a median 549 m
# from their late twin, so nothing finer is meaningful.
MATCH_RADIUS_M = 400.0
SENSITIVITY_RADII_M = (250.0, 400.0, 600.0)

# The shared ground is shrunk by this before counting, so that a house near the
# edge of one edition's frame is not counted against ground the other does not
# cover.
SHARED_INSET_M = 500.0

# Halk El Mennzel is nearly all sea and carries 23 houses on the shared ground.
# Its ratio (3.9x) and its steep sensitivity curve are both what 23 points do,
# not what the printings do, so the summary range is quoted over the pairs with
# enough houses to mean something and that sheet is named separately.
MIN_SHEET_HOUSES = 100

# The credit block is transcribed by hand from the crop this script renders, and
# the crop is rendered so that the transcription can be checked against it. The
# general margin OCR (scripts/read_sheet_margins.py) reads the block on eight of
# these twelve sheets and misses four: the block is engraved script at half the
# size of the footer type, it sits at a different height on the 1902 and the
# 1930s layouts, and Tesseract turns "1891" into "10" as often as not. Since the
# whole reading of this comparison turns on these twelve lines, they are read
# directly and shown rather than trusted to OCR.
#
# survey_years is every year the block gives as fieldwork; revision_years only
# those it gives as a revision. Porto-Farina's later printing is the one block
# that names either.
CREDITS = {
    # Porto-Farina B0-C36
    "oai:u-bordeaux-montaigne.fr:340371": (
        "Les travaux sur le terrain ont ete executes par M.M.rs | "
        "Corniot Cap.ne a 1891 | Thiebaut Lieut.t c 1891 | "
        "Tantot Lieut.t b id | Soulie Cap.ne d id",
        (1891,), ()),
    "oai:u-bordeaux-montaigne.fr:340370": (
        "D'apres les travaux : | a,b,c,d,e, leves en 1900, revises en 1931-32 | "
        "f,g,h,i,j,k,l,m,n, leves en 1930-31 et 1932",
        (1900, 1930, 1931, 1932), (1931, 1932)),
    # La Marsa B1-C37
    "oai:u-bordeaux-montaigne.fr:340390": (
        "Les travaux sur le terrain ont ete executes par M.r | "
        "Sauret Cap.ne {a,b} 1891", (1891,), ()),
    "oai:u-bordeaux-montaigne.fr:340389": (
        "Les travaux sur le terrain ont ete executes par M.r | "
        "Sauret Cap.ne {a,b} 1891", (1891,), ()),
    # Tunis B2-C36
    "oai:u-bordeaux-montaigne.fr:340396": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Roget Lieut.t a 1889 | Espinasse Capit.ne e 1889 | "
        "Corniot Capit.ne b d.o | Lachouque Lieut.t f d.o | "
        "Martinez Lieut.t c d.o | Delaunay d.o g d.o | "
        "Bonnefoy Capit.ne d d.o", (1889,), ()),
    "oai:u-bordeaux-montaigne.fr:340395": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Roget Lieut.t a 1889 | Espinasse Capit.ne e 1889 | "
        "Corniot Capit.ne b d.o | Lachouque Lieut.t f d.o | "
        "Martinez Lieut.t c d.o | Delaunay d.o g d.o | "
        "Bonnefoy Capit.ne d d.o", (1889,), ()),
    # Sidi Bou Ali B6-C37
    "oai:u-bordeaux-montaigne.fr:340467": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Balland Cap.ne a 1892 | Clerc Lieut.t d 1892 | "
        "Moreau id b id | Vuillemin id e id | Montagnon Lieut.t c id",
        (1892,), ()),
    "oai:u-bordeaux-montaigne.fr:340456": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Balland Cap.ne a 1892 | Clerc Lieut.t d 1892 | "
        "Moreau id b id | Vuillemin id e id | Montagnon Lieut.t c id",
        (1892,), ()),
    # Halk El Mennzel B6-C38
    "oai:u-bordeaux-montaigne.fr:340469": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Moreau Capitaine a 1892 | Wary Lieut.t b id", (1892,), ()),
    "oai:u-bordeaux-montaigne.fr:340468": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Moreau Capitaine a 1892 | Wary Lieut.t b id", (1892,), ()),
    # Sousse B7-C38
    "oai:u-bordeaux-montaigne.fr:340487": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Wary Lieut.t a 1892 | Corniot Cap.ne b 1892 | Esnol Cap.ne c 1892",
        (1892,), ()),
    "oai:u-bordeaux-montaigne.fr:340476": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Wary Lieut.t a 1892 | Corniot Cap.ne b 1892 | Esnol Cap.ne c 1892",
        (1892,), ()),
}

# The credit block sits just above the neatline's top-left corner on every sheet
# in the series, on both layouts, so the crop is taken from the neatline rather
# than from a fraction of the page - which is what the margin OCR does, and why
# it misses the sheets whose block sits lower than its window.
CREDIT_CROP_ABOVE = (0.080, 0.004)   # fractions of page height above the top
CREDIT_CROP_WIDTH = 0.20             # fraction of page width, from the left edge
CREDIT_CROP_LEFT_PAD = 120           # px left of the neatline, for the index map

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
# Three categories, so the first three categorical slots, which validate
# all-pairs in both modes. The green's contrast against the surface is below
# 3:1, which the validator flags: it is relieved by the legend, the direct
# labels on every bar, and data/edition_difference.csv as the table view.
MATCHED = "#2a78d6"
EARLY_ONLY = "#eb6834"
LATE_ONLY = "#1baf7a"


def footprint(record: dict) -> np.ndarray:
    """The sheet's four fitted corners in Lambert metres, as a polygon."""
    order = ("north_west", "north_east", "south_east", "south_west")
    return np.array([[record["corners"][name]["easting"],
                      record["corners"][name]["northing"]] for name in order])


def inset_polygon(polygon: np.ndarray, metres: float) -> np.ndarray:
    """Shrink a convex quadrilateral toward its centroid by roughly `metres`."""
    centre = polygon.mean(axis=0)
    radius = np.linalg.norm(polygon - centre, axis=1).mean()
    if radius <= metres:
        return polygon
    return centre + (polygon - centre) * (1.0 - metres / radius)


def inside(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Which points fall inside a convex polygon, by the sign of the cross
    product against every edge."""
    if len(points) == 0:
        return np.zeros(0, bool)
    signs = []
    for index in range(len(polygon)):
        a, b = polygon[index], polygon[(index + 1) % len(polygon)]
        edge = b - a
        signs.append(np.sign(edge[0] * (points[:, 1] - a[1])
                             - edge[1] * (points[:, 0] - a[0])))
    signs = np.array(signs)
    return np.all(signs >= 0, axis=0) | np.all(signs <= 0, axis=0)


def load_points(path: Path, epsg: int) -> np.ndarray:
    if not path.exists():
        return np.zeros((0, 2))
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    return np.array([[f["properties"]["easting"], f["properties"]["northing"]]
                     for f in features
                     if f["properties"]["symbol_class"] == "building"
                     and f["properties"]["epsg_source"] == epsg]
                    or [], dtype=float).reshape(-1, 2)


def match(early: np.ndarray, late: np.ndarray, radius: float):
    """Pair each early house with a late one at most `radius` away, once each.

    Greedy nearest-first, which is enough here: the alternative is an optimal
    assignment, and with the pairs this far apart relative to the radius the two
    agree to within a few counts. Returns the matched distances too, because how
    far apart the matched pairs sit is the honest measure of the placement.
    """
    if len(early) == 0 or len(late) == 0:
        return 0, len(early), len(late), np.zeros(0)
    from scipy.spatial import cKDTree
    tree = cKDTree(late)
    distances, indices = tree.query(early, distance_upper_bound=radius)
    order = np.argsort(distances)
    taken_late, kept = set(), []
    for position in order:
        if not np.isfinite(distances[position]):
            break
        target = int(indices[position])
        if target in taken_late:
            continue
        taken_late.add(target)
        kept.append(distances[position])
    matched = len(kept)
    return matched, len(early) - matched, len(late) - matched, np.array(kept)


def credit_crop(path: Path, neatline: dict):
    """The credit block, cropped relative to the neatline rather than the page."""
    from PIL import Image, ImageOps
    image = Image.open(path).convert("L")
    width, height = image.size
    box = (max(neatline["left"] - CREDIT_CROP_LEFT_PAD, 0),
           max(int(neatline["top"] - CREDIT_CROP_ABOVE[0] * height), 0),
           min(neatline["left"] + int(CREDIT_CROP_WIDTH * width), width),
           max(int(neatline["top"] - CREDIT_CROP_ABOVE[1] * height), 0))
    return ImageOps.autocontrast(image.crop(box))


def credits_figure(rows: list[dict], scans: Path, neatlines: dict,
                   path: Path) -> None:
    """The twelve credit blocks, early above late, so the claim that five pairs
    are the same survey can be checked by eye instead of taken on trust."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure_, axes = plt.subplots(len(rows) * 2, 1,
                                 figsize=(9.0, 0.66 * len(rows) * 2 + 1.2))
    figure_.patch.set_facecolor(SURFACE)
    for index, row in enumerate(rows):
        for offset, (key, label) in enumerate(
                ((row["early_record_id"], row["early_catalogue_year"] or "n.d."),
                 (row["late_record_id"], row["late_catalogue_year"] or "n.d."))):
            axis = axes[index * 2 + offset]
            axis.set_facecolor(SURFACE)
            scan = scans / f"{key}.jpg"
            if scan.exists() and key in neatlines:
                axis.imshow(credit_crop(scan, neatlines[key]), cmap="gray",
                            aspect="auto")
            axis.set_xticks([])
            axis.set_yticks([])
            for side in axis.spines.values():
                side.set_color(GRIDLINE)
            edition = "early" if offset == 0 else "later"
            same = row["same_survey"] == 1
            axis.set_ylabel(f"{row['sheet_name']}\n{edition}, {label}",
                            rotation=0, ha="right", va="center", labelpad=10,
                            fontsize=8,
                            color=INK_SECONDARY if same else INK_PRIMARY)
            if offset == 1:
                # Top-right, where the crop is blank paper: over the neatline
                # it landed on the grid labels and was unreadable.
                axis.text(0.995, 0.94,
                          "same survey as the early printing" if same
                          else "DIFFERENT survey",
                          transform=axis.transAxes, ha="right", va="top",
                          fontsize=8,
                          color=INK_MUTED if same else EARLY_ONLY)

    figure_.suptitle("The fieldwork credit each printing sets above its frame",
                     x=0.012, y=0.992, ha="left", va="top", fontsize=13,
                     color=INK_PRIMARY)
    figure_.text(0.012, 0.966,
                 "Five of the six pairs print the identical block - same "
                 "officers, same year. Porto-Farina's later printing was "
                 "resurveyed and says so.",
                 ha="left", va="top", fontsize=9, color=INK_SECONDARY)
    figure_.subplots_adjust(left=0.175, right=0.99, top=0.952, bottom=0.010,
                            hspace=0.16)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure_.savefig(path, dpi=170, facecolor=SURFACE)
    plt.close(figure_)


def figure(rows: list[dict], path: Path) -> None:
    import matplotlib
    import textwrap
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = sorted(rows, key=lambda r: -(r["matched"] + r["early_only"]))
    matched = np.array([r["matched"] for r in rows], float)
    early_only = np.array([r["early_only"] for r in rows], float)
    late_only = np.array([r["late_only"] for r in rows], float)

    figure_, axes = plt.subplots(1, 2, figsize=(11.6, 5.5),
                                 gridspec_kw={"width_ratios": [1.5, 1]})
    figure_.patch.set_facecolor(SURFACE)
    positions = np.arange(len(rows))[::-1]

    left = axes[0]
    left.set_facecolor(SURFACE)
    # edgecolor in the surface colour is the 2 px gap between stacked segments.
    bar = dict(height=0.62, zorder=3, edgecolor=SURFACE, linewidth=1.6)
    left.barh(positions, matched, color=MATCHED,
              label="drawn on both printings", **bar)
    left.barh(positions, early_only, left=matched,
              color=EARLY_ONLY, label="early printing only", **bar)
    left.barh(positions, late_only, left=matched + early_only,
              color=LATE_ONLY, label="later printing only", **bar)
    totals = matched + early_only + late_only
    for position, row, total in zip(positions, rows, totals):
        left.text(total + totals.max() * 0.015, position,
                  f"{row['count_ratio']:.2f}× as many later  ·  "
                  f"{row['matched_share']:.0%} matched",
                  va="center", ha="left", fontsize=8, color=INK_SECONDARY)
    left.set_yticks(positions)
    left.set_yticklabels(
        [f"{r['sheet_name']}\n{'resurveyed 1930-32' if not r['same_survey'] else 'same survey, reprinted'}"
         for r in rows], fontsize=8.5, color=INK_PRIMARY)
    left.set_xlabel("houses on the ground the two printings share",
                    fontsize=9, color=INK_SECONDARY)
    left.set_xlim(0, totals.max() * 1.45)
    left.grid(axis="x", color=GRIDLINE, linewidth=0.8, zorder=0)
    left.set_axisbelow(True)
    for side in ("top", "right", "left"):
        left.spines[side].set_visible(False)
    left.spines["bottom"].set_color(BASELINE)
    left.tick_params(colors=INK_MUTED, labelsize=8)
    left.legend(frameon=False, fontsize=8, loc="lower right",
                labelcolor=INK_SECONDARY)

    # The resurveyed pair is separated by emphasis, not by a fourth hue, so the
    # three categorical slots keep the meaning they have in the left panel.
    right = axes[1]
    right.set_facecolor(SURFACE)
    radii = list(SENSITIVITY_RADII_M)
    for row in rows:
        shares = [row[f"matched_share_{int(r)}m"] for r in radii]
        resurveyed = not row["same_survey"]
        right.plot(radii, shares, marker="o",
                   markersize=6 if resurveyed else 5,
                   linewidth=2.4 if resurveyed else 2,
                   color=INK_PRIMARY if resurveyed else INK_MUTED,
                   alpha=1.0 if resurveyed else 0.5, zorder=4 if resurveyed else 3)
        if resurveyed:
            right.annotate(f"{row['sheet_name']} — the one\nsheet really "
                           f"resurveyed",
                           (radii[-1], shares[-1]),
                           textcoords="offset points", xytext=(-6, -36),
                           ha="right", fontsize=8, color=INK_PRIMARY)
        elif row["early_in_shared"] < MIN_SHEET_HOUSES:
            right.annotate(f"{row['sheet_name']}\n{row['early_in_shared']} "
                           f"houses — a small-sample curve",
                           (radii[0], shares[0]),
                           textcoords="offset points", xytext=(8, -4),
                           ha="left", va="top", fontsize=7.5, color=INK_MUTED)
    right.set_xlabel("match radius (m)", fontsize=9, color=INK_SECONDARY)
    right.set_ylabel("share of the early drawing reproduced",
                     fontsize=9, color=INK_SECONDARY)
    right.set_ylim(0, 1.02)
    right.set_xticks(radii)
    right.grid(color=GRIDLINE, linewidth=0.8, zorder=0)
    right.set_axisbelow(True)
    for side in ("top", "right"):
        right.spines[side].set_visible(False)
    for side in ("bottom", "left"):
        right.spines[side].set_color(BASELINE)
    right.tick_params(colors=INK_MUTED, labelsize=8)
    right.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0%}"))

    reprints = [r for r in rows
                if r["same_survey"] and r["early_in_shared"] >= MIN_SHEET_HOUSES]
    ratios = [r["count_ratio"] for r in reprints]
    figure_.suptitle("What differencing two printings of one survey measures",
                     x=0.012, ha="left", fontsize=13.5, color=INK_PRIMARY)
    figure_.text(0.012, 0.905, "\n".join(textwrap.wrap(
                 f"On {len(reprints)} pairs that print the identical 1889-1892 "
                 f"fieldwork credit, the later printing carries "
                 f"{min(ratios):.2f}× to {max(ratios):.2f}× as many detected "
                 f"houses and reproduces under half the early drawing. The one "
                 f"pair that really was resurveyed falls inside that range.",
                 118)),
                 ha="left", va="top", fontsize=9, color=INK_SECONDARY)
    figure_.text(0.012, 0.095, "\n".join(textwrap.wrap(
                 "Houses from the legend's “Maisons” mark. Early sheets placed "
                 "from their grade graticule (median 549 m against the later "
                 "printing), which is what sets the match radius; the five flat "
                 "sensitivity lines say those unmatched houses are absent from "
                 "the other printing rather than merely displaced.", 128)),
                 ha="left", va="top", fontsize=8, color=INK_MUTED)
    figure_.subplots_adjust(left=0.155, right=0.985, top=0.785, bottom=0.225,
                            wspace=0.40)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure_.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(figure_)


FIELDS = ["designation", "sheet_name", "early_record_id", "late_record_id",
          "early_catalogue_year", "late_catalogue_year",
          "early_survey_years", "late_survey_years", "late_revision_years",
          "same_survey", "survey_gap_years",
          "shared_km2", "early_total", "late_total",
          "early_in_shared", "late_in_shared", "count_ratio",
          "matched", "early_only", "late_only", "matched_share",
          "matched_share_250m", "matched_share_400m", "matched_share_600m",
          "matched_distance_median_m", "twin_offset_m"]

CREDIT_FIELDS = ["designation", "sheet_name", "record_id", "edition",
                 "catalogue_year", "survey_years", "revision_years",
                 "credit_block", "basis"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--early", type=Path,
                        default=REPO_ROOT / "data" / "symbols_graticule",
                        help="directory of GeoJSON extracted from the early "
                             "(graticule) sheets")
    parser.add_argument("--late", type=Path,
                        default=REPO_ROOT / "data" / "symbols")
    parser.add_argument("--scans", type=Path,
                        help="directory of sheet scans, for the credit-block "
                             "figure; skipped if not given")
    parser.add_argument("--graticule", type=Path,
                        default=REPO_ROOT / "data" / "sheet_graticule.json")
    parser.add_argument("--georef", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.json")
    parser.add_argument("--table", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.csv")
    parser.add_argument("--margins", type=Path,
                        default=REPO_ROOT / "data" / "sheet_margins.csv")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "edition_difference.csv")
    parser.add_argument("--out-credits", type=Path,
                        default=REPO_ROOT / "data" / "edition_credits.csv")
    parser.add_argument("--out-figure", type=Path,
                        default=REPO_ROOT / "docs" / "img"
                                / "edition_difference.png")
    parser.add_argument("--out-credits-figure", type=Path,
                        default=REPO_ROOT / "docs" / "img"
                                / "edition_credits.png")
    args = parser.parse_args()

    graticule = json.loads(args.graticule.read_text(encoding="utf-8"))
    georef = json.loads(args.georef.read_text(encoding="utf-8"))
    sheets = {r["record_id"]: r for r in
              csv.DictReader(args.table.open(encoding="utf-8"))}
    margins = {r["record_id"]: r for r in
               csv.DictReader(args.margins.open(encoding="utf-8"))}

    rows, credit_rows = [], []
    for record_id, early_record in sorted(graticule.items()):
        late_id = early_record.get("twin_record_id")
        if "affine" not in early_record or not late_id:
            continue
        late_record = georef.get(late_id, {})
        if "corners" not in late_record:
            continue
        if early_record["epsg"] != late_record["epsg"]:
            continue

        shared = inset_polygon(footprint(early_record), SHARED_INSET_M)
        late_polygon = inset_polygon(footprint(late_record), SHARED_INSET_M)
        # Both frames cover the same nominal ground, so the intersection is
        # approximated by the smaller of the two inset quadrilaterals - which
        # avoids a polygon-clipping dependency for a difference of a few
        # hundred metres on a 32 km sheet.
        if abs(np.linalg.det(np.diff(late_polygon[:3], axis=0))) < \
           abs(np.linalg.det(np.diff(shared[:3], axis=0))):
            shared = late_polygon

        early_points = load_points(args.early / f"{record_id}.geojson",
                                   early_record["epsg"])
        late_points = load_points(args.late / f"{late_id}.geojson",
                                  late_record["epsg"])
        early_shared = early_points[inside(early_points, shared)]
        late_shared = late_points[inside(late_points, shared)]

        matched, early_only, late_only, distances = match(
            early_shared, late_shared, MATCH_RADIUS_M)
        sensitivity = {}
        for radius in SENSITIVITY_RADII_M:
            hit, _, _, _ = match(early_shared, late_shared, radius)
            sensitivity[f"matched_share_{int(radius)}m"] = round(
                hit / max(len(early_shared), 1), 4)

        area = 0.5 * abs(sum(
            shared[i][0] * shared[(i + 1) % 4][1]
            - shared[(i + 1) % 4][0] * shared[i][1] for i in range(4))) / 1e6

        early_credit = CREDITS.get(record_id)
        late_credit = CREDITS.get(late_id)
        early_years = early_credit[1] if early_credit else ()
        late_years = late_credit[1] if late_credit else ()
        # Same survey means the block gives the same fieldwork years on both
        # printings; a later printing that adds a revision or a new levé is a
        # different survey even where the old years survive in the block.
        same = int(bool(early_years) and bool(late_years)
                   and set(early_years) == set(late_years))
        designation = sheets.get(record_id, {}).get("designation", "")
        sheet_name = sheets.get(record_id, {}).get("sheet_name", "")
        for key, credit, edition in ((record_id, early_credit, "early"),
                                     (late_id, late_credit, "later")):
            if not credit:
                continue
            block, years, revisions = credit
            credit_rows.append({
                "designation": designation, "sheet_name": sheet_name,
                "record_id": key, "edition": edition,
                "catalogue_year": margins.get(key, {}).get("catalogue_year", ""),
                "survey_years": " ".join(str(y) for y in years),
                "revision_years": " ".join(str(y) for y in revisions),
                "credit_block": block,
                "basis": "read_from_sheet",
            })

        rows.append({
            "designation": designation,
            "sheet_name": sheet_name,
            "early_record_id": record_id,
            "late_record_id": late_id,
            "early_catalogue_year":
                margins.get(record_id, {}).get("catalogue_year", ""),
            "late_catalogue_year":
                margins.get(late_id, {}).get("catalogue_year", ""),
            "early_survey_years": " ".join(str(y) for y in early_years),
            "late_survey_years": " ".join(str(y) for y in late_years),
            "late_revision_years":
                " ".join(str(y) for y in (late_credit[2] if late_credit else ())),
            "same_survey": same,
            "survey_gap_years": (max(late_years) - max(early_years)
                                 if early_years and late_years else ""),
            "shared_km2": round(area, 1),
            "early_total": len(early_points),
            "late_total": len(late_points),
            "early_in_shared": len(early_shared),
            "late_in_shared": len(late_shared),
            "count_ratio": round(len(late_shared) / max(len(early_shared), 1), 3),
            "matched": matched,
            "early_only": early_only,
            "late_only": late_only,
            "matched_share": round(matched / max(len(early_shared), 1), 4),
            **sensitivity,
            "matched_distance_median_m":
                round(float(np.median(distances)), 1) if len(distances) else "",
            "twin_offset_m": early_record.get("twin_offset_m", ""),
        })

    for path, fields, table in ((args.out_csv, FIELDS, rows),
                                (args.out_credits, CREDIT_FIELDS, credit_rows)):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(table)

    print(f"{len(rows)} sheet pairs, counted on the ground each pair shares\n")
    print(f"{'sheet':17s} {'catalogue':11s} {'fieldwork':13s} {'early':>6s} "
          f"{'late':>6s} {'ratio':>6s} {'matched':>8s} {'share':>6s}")
    for row in rows:
        print(f"{(row['sheet_name'] or row['designation'])[:17]:17s} "
              f"{(str(row['early_catalogue_year'] or '?') + '-' + str(row['late_catalogue_year'] or '?')):11s} "
              f"{((row['early_survey_years'] or '?').split()[0] + '/' + (row['late_survey_years'] or '?').split()[0]):13s} "
              f"{row['early_in_shared']:6d} {row['late_in_shared']:6d} "
              f"{row['count_ratio']:6.2f} "
              f"{row['matched']:8d} {row['matched_share']:6.0%}")

    same = [r for r in rows if r["same_survey"]]
    other = [r for r in rows if not r["same_survey"]]
    counted = [r for r in same if r["early_in_shared"] >= MIN_SHEET_HOUSES]
    small = [r for r in same if r["early_in_shared"] < MIN_SHEET_HOUSES]
    if counted:
        ratios = [r["count_ratio"] for r in counted]
        shares = [r["matched_share"] for r in counted]
        print(f"\n{len(same)} of {len(rows)} pairs print the identical "
              f"fieldwork credit - reprints, not resurveys.")
        print(f"  on the {len(counted)} of them with at least "
              f"{MIN_SHEET_HOUSES} houses on the shared ground, the count "
              f"ratio spans {min(ratios):.2f}x to {max(ratios):.2f}x")
        print(f"  and the matched share {min(shares):.0%} to {max(shares):.0%} "
              f"- the noise floor of this comparison: no settlement change "
              f"smaller than that can be seen.")
        for row in small:
            print(f"  ({row['sheet_name']} is left out of the range: "
                  f"{row['early_in_shared']} houses, ratio "
                  f"{row['count_ratio']:.2f}x, which is a small sample "
                  f"talking.)")
    for row in other:
        print(f"\n{row['sheet_name']} is the one pair with new fieldwork "
              f"({row['early_survey_years']} -> {row['late_survey_years']}, "
              f"revised {row['late_revision_years'] or 'n/a'}):")
        print(f"  ratio {row['count_ratio']:.2f}x - inside the reprints' "
              f"{min(ratios):.2f}x-{max(ratios):.2f}x, and nearer 1.00 than "
              f"any of them.")
        # Points differenced after rounding, so the sentence agrees with the
        # percentages printed beside it.
        low, high = round(min(shares) * 100), round(max(shares) * 100)
        here = round(row["matched_share"] * 100)
        print(f"  matched {here}% against the reprints' {low}%-{high}% - "
              f"{abs(here - low)} points below the lowest, against a spread of "
              f"{high - low} points among sheets that are the same drawing.")
        print(f"  So neither statistic separates forty years of new fieldwork "
              f"from a reprint.")

    if rows:
        figure(rows, args.out_figure)
        if args.scans:
            neatlines = {k: v["neatline_px"]
                         for source in (graticule, georef)
                         for k, v in source.items() if "neatline_px" in v}
            credits_figure(rows, args.scans, neatlines, args.out_credits_figure)
        print(f"\n  -> {args.out_csv}\n  -> {args.out_credits}"
              f"\n  -> {args.out_figure}")
        if args.scans:
            print(f"  -> {args.out_credits_figure}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

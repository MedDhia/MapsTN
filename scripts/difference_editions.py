#!/usr/bin/env python3
"""Compare the houses drawn on two printings of the same sheet.

**Which records are two printings of one sheet, and which only look like it.**
The B-C designation a sheet prints is not a unique identifier. Three of the
eleven multiply-held cells hold two *different* sheets that both print the same
B-C: Bizerte and Djebel Ichkeul both print B0-C35 and sit 20.0 km apart; Nefza
and Ebba Ksour both print B1-C33 and sit 199 km apart; Aine Djeloula prints
B6-C37 alongside Sidi Bou Ali, 37.7 km away. A real pair sits 0.2 km apart.

What does identify the sheet is the **Roman serial number** in its title, and it
separates the two cases cleanly: every real pair shares it (VII, XIII, XIV, XX,
XXI, XLIII, XLIX, L, LVII) and none of the three collisions does (II/VI, X/LII,
XLIX/LV). So pairs are formed on the serial, and the earlier printing of each is
the one with no kilometric grid - which holds on all nine without exception.

That leaves **nine** edition pairs, not twelve.

**Seven of the nine are reprints of one survey, two are real resurveys.** Both
printings set a fieldwork credit block above the frame, and on seven pairs it is
identical character for character:

    La Marsa          Sauret 1891
    Tunis             Roget, Corniot, Martinez, Bonnefoy, Espinasse,
                      Lachouque, Delaunay 1889
    La Goulette       Lachouque, Delaunay, Maumene, Hairon, Corbieres 1889
    Enfida(ville)     Lamborot, Meillon, Maire, Lallemand, Cros, Colombat 1893
    Sidi Bou Ali      Balland, Moreau, Montagnon, Clerc, Vuillemin 1892
    Halk El Mennzel   Moreau, Wary 1892
    Sousse            Wary, Corniot, Esnol 1892

Same officers, same year, same wording. The later printing adds the red grid and
the red corner coordinates; it does not add a survey. The catalogue dates these
pairs 1902 against 1931-1936, which is two publication dates on one field
campaign - the same trap the catalogue sets for dates elsewhere in this project.

Two pairs really were resurveyed, and **both say so by changing the form of the
block** - a numbered index of sub-areas with dates, instead of a list of
officers:

    Porto-Farina  early  Corniot, Tantot, Thiebaut, Soulie 1891
                  late   "D'apres les travaux: a,b,c,d,e leves en 1900,
                         revises en 1931-32; f..n leves en 1930-31 et 1932"
    Ariana        early  Tantot, Meauze, Soulie, V. de Beaupre, Lachouque,
                         Sauret 1890-1891
                  late   "D'apres les travaux: a,b,c,d,e leves en 1890-1891,
                         revises en 1935; 1,2 leves en 1931; 3,4 leves en
                         1931-32"

So the form of the credit block is itself the screen: "Les Travaux sur le
Terrain ont ete executes par MM.rs" plus officers means an original survey,
"D'apres les travaux :" plus dated sub-areas means a compiled or revised one.

**"Reprint" here means no new fieldwork was credited - not that the plate is
untouched.** The credit block is evidence about the field survey, and La Goulette
shows the limit of that: same credited 1889 officers on both printings, and 4.00
times as many detected houses on the later one, with 59% of the early drawing
reproduced. Either the plate was re-engraved from sources that earned no
fieldwork credit - town plans, the harbour works - or the printing and scan
differ that much. Either way it is not surveyed change, which is the point.

**Seven controls and two experiments, and the counts cannot tell them apart.**
On the reprint pairs with enough houses to count, the later printing of a sheet
that is provably one survey carries between 0.86 and 4.00 times as many detected
houses as the earlier one, and reproduces 40-59% of the early drawing within the
match radius. Both resurveyed pairs fall inside both ranges: Porto-Farina at
1.12x and 38%, Ariana at 2.37x on the registration-free count.

The differences between these printings are therefore dominated by what changed
between printings and scans - plate redrawing, paper, exposure, and the accuracy
with which the early sheet can be placed - and not by the ground. Every later
printing carries 2 to 20 times the red-ink density of its early twin
(red_density in data/sheet_grid.json), so a detector that works on red ink is
not looking at comparable images, and across the nine pairs that density ratio
and the house-count ratio rise together: Spearman rho +0.75, p 0.02. That is
suggestive rather than established - drop the 23-house sheet and it falls to
+0.64, p 0.09 on eight pairs - so it is reported as an association, not a
mechanism.

**Two tiers of comparison, because two pairs cannot be placed.** El Ariana and
Enfida are two of the three graticule sheets whose latitude lines are too few to
establish a spacing, so they have no transform and never will from their own
graticule. They still support the statistic that needs no transform at all:

    tier          what it needs                       pairs
    spatial       both printings placed               7
    counts only   both neatlines detected             9 (all of them)

The registration-free count is houses inside each sheet's own detected neatline.
On the seven pairs where both are available it agrees with the shared-ground
ratio closely enough to be quoted (the script reports the agreement), which is
what licenses using it on the two pairs where it is all there is.

What it reports per pair:

    matched        a house on both printings within MATCH_RADIUS_M
    early_only     drawn on the early printing, absent from the later
    late_only      drawn on the later printing, absent from the early
    matched_share  matched / early count - how much of the early drawing the
                   later printing reproduces
    count_ratio    late / early count on the ground the two share
    count_ratio_neatline  the same ratio inside each sheet's own frame, which
                   needs no georeference and so exists for all nine pairs

MATCH_RADIUS_M is set by the georeferencing, not by cartography. The graticule
sheets are placed to a median 549 m against their late twin, so a house cannot
be matched more tightly than that; 400 m is the working figure and the
sensitivity to it is reported. The share barely moves between 250 and 600 m,
which is how we know the unmatched houses are absent from the other printing
rather than merely displaced.

Outputs:
    data/edition_credits.csv        the credit block of each sheet, transcribed
    data/edition_difference.csv
    docs/img/edition_credits.png    the credit blocks themselves, as evidence
    docs/img/edition_difference.png

Usage:
    python3 scripts/difference_editions.py [--scans <dir of sheet scans>]

--scans is only needed to render the credit-block figure and to rebuild
data/edition_neatline_counts.json; both are in the repository already, and the
scans are 700 MB and are not (scripts/fetch_sheet_images.py fetches them).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent

# Bounded by the placement, not by the map: the graticule sheets sit a median
# 549 m from their late twin, so nothing finer is meaningful.
MATCH_RADIUS_M = 400.0
SENSITIVITY_RADII_M = (250.0, 400.0, 600.0)

# The shared ground is shrunk by this before counting, so that a house near the
# edge of one printing's frame is not counted against ground the other does not
# cover.
SHARED_INSET_M = 500.0

# Halk El Mennzel is nearly all sea and carries 23 houses on the shared ground.
# Its ratio (3.9x) and its steep sensitivity curve are both what 23 points do,
# not what the printings do, so the summary range is quoted over the pairs with
# enough houses to mean something and that sheet is named separately.
MIN_SHEET_HOUSES = 100

# The credit block is transcribed by hand from the crop this script renders, and
# the crop is rendered so that the transcription can be checked against it. The
# general margin OCR (scripts/read_sheet_margins.py) misses the block on many of
# these sheets: it is engraved script at half the size of the footer type, it
# sits at a different height on the 1902 and the 1930s layouts, and Tesseract
# turns "1891" into "10" as often as not. Since the whole reading of this
# comparison turns on these eighteen lines, they are read directly and shown
# rather than trusted to OCR.
#
# survey_years is every year the block gives as fieldwork; revision_years only
# those it gives as a revision.
CREDITS = {
    # Porto-Farina VII - RESURVEYED
    "oai:u-bordeaux-montaigne.fr:340371": (
        "Les travaux sur le terrain ont ete executes par M.M.rs | "
        "Corniot Cap.ne a 1891 | Thiebaut Lieut.t c 1891 | "
        "Tantot Lieut.t b id | Soulie Cap.ne d id",
        (1891,), ()),
    "oai:u-bordeaux-montaigne.fr:340370": (
        "D'apres les travaux : | a,b,c,d,e, leves en 1900, revises en 1931-32 | "
        "f,g,h,i,j,k,l,m,n, leves en 1930-31 et 1932",
        (1900, 1930, 1931, 1932), (1931, 1932)),
    # El Ariana / Ariana XIII - RESURVEYED
    "oai:u-bordeaux-montaigne.fr:340388": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Tantot S.s Lieut.t a 1890 | V. de Beaupre Lieut.t d 1891 | "
        "Meauze Cap.ne b id | Lachouque Cap.ne e id | "
        "Soulie id c 1891 | Sauret id f id",
        (1890, 1891), ()),
    "oai:u-bordeaux-montaigne.fr:340387": (
        "D'apres les travaux : | a,b,c,d,e ; leves en 1890-1891, revises en 1935 | "
        "1,2 ; leves en 1931. | 3,4 ; leves en 1931-32.",
        (1890, 1891, 1931, 1932, 1935), (1935,)),
    # La Marsa XIV
    "oai:u-bordeaux-montaigne.fr:340390": (
        "Les travaux sur le terrain ont ete executes par M.r | "
        "Sauret Cap.ne {a,b} 1891", (1891,), ()),
    "oai:u-bordeaux-montaigne.fr:340389": (
        "Les travaux sur le terrain ont ete executes par M.r | "
        "Sauret Cap.ne {a,b} 1891", (1891,), ()),
    # Tunis XX
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
    # La Goulette XXI
    "oai:u-bordeaux-montaigne.fr:340409": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Lachouque Lieut.t a 1889 | Hairon Cap.e d 1889 | "
        "Delaunay d.o b d.o | Corbieres Lieut.t e d.o | Maumene d.o c d.o",
        (1889,), ()),
    "oai:u-bordeaux-montaigne.fr:340407": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Lachouque Lieut.t a 1889 | Hairon Cap.e d 1889 | "
        "Delaunay d.o b d.o | Corbieres Lieut.t e d.o | Maumene d.o c d.o",
        (1889,), ()),
    # Enfida / Enfidaville XLIII
    "oai:u-bordeaux-montaigne.fr:340450": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Lamborot Lieut.t a 1893 | Cros Lieut.t e 1893 | "
        "Meillon id b id | Colombat id f id | "
        "Maire id c id | Lallemand id d id", (1893,), ()),
    "oai:u-bordeaux-montaigne.fr:340449": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Lamborot Lieut.t a 1893 | Cros Lieut.t e 1893 | "
        "Meillon id b id | Colombat id f id | "
        "Maire id c id | Lallemand id d id", (1893,), ()),
    # Sidi Bou Ali XLIX
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
    # Halk El Mennzel L
    "oai:u-bordeaux-montaigne.fr:340469": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Moreau Capitaine a 1892 | Wary Lieut.t b id", (1892,), ()),
    "oai:u-bordeaux-montaigne.fr:340468": (
        "Les Travaux sur le Terrain ont ete executes par M.M.rs | "
        "Moreau Capitaine a 1892 | Wary Lieut.t b id", (1892,), ()),
    # Sousse LVII
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
# in the series, on every layout, so the crop is taken from the neatline rather
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


def load_sources(paths: dict) -> dict:
    """Every transform a sheet might have, in order of precision.

    The main grid path first, then the corner-only fit, then the graticule. A
    provisional record is skipped wherever it appears: its corners exist and its
    position does not.
    """
    merged: dict = {}
    for name in ("georef", "corner_fit", "graticule"):
        source = json.loads(paths[name].read_text(encoding="utf-8"))
        for record_id, found in source.items():
            if record_id in merged or "corners" not in found:
                continue
            if found.get("anchor_provisional") or "affine" not in found:
                continue
            if name == "georef" and not found.get("anchor_confident"):
                continue
            merged[record_id] = {**found, "position_basis": name}
    return merged


def find_pairs(series: Path, grid: dict) -> list[dict]:
    """Group the records into edition pairs on the serial number.

    Not on the B-C designation: three cells hold two different sheets that print
    the same B-C, up to 199 km apart. The serial separates them without
    exception, and the earlier printing is the one with no kilometric grid.
    """
    groups = defaultdict(list)
    for row in csv.DictReader(series.open(encoding="utf-8")):
        if row["serial"] and row["designation"]:
            groups[(row["serial"], row["designation"])].append(row)

    pairs = []
    for (serial, designation), records in sorted(groups.items(),
                                                 key=lambda item: item[0][1]):
        if len(records) != 2:
            continue
        gridded = [bool(grid.get(r["record_id"], {}).get("has_kilometric_grid"))
                   for r in records]
        if sorted(gridded) != [False, True]:
            continue
        early = records[gridded.index(False)]
        late = records[gridded.index(True)]
        pairs.append({"serial": serial, "designation": designation,
                      "sheet_name": late["sheet_name"] or early["sheet_name"],
                      "early_record_id": early["record_id"],
                      "late_record_id": late["record_id"]})
    return pairs


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


def load_points(directories: list[Path], record_id: str,
                epsg: int) -> np.ndarray:
    for directory in directories:
        path = directory / f"{record_id}.geojson"
        if not path.exists():
            continue
        features = json.loads(path.read_text(encoding="utf-8"))["features"]
        return np.array([[f["properties"]["easting"], f["properties"]["northing"]]
                         for f in features
                         if f["properties"]["symbol_class"] == "building"
                         and f["properties"]["epsg_source"] == epsg]
                        or [], dtype=float).reshape(-1, 2)
    return np.zeros((0, 2))


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
    """The credit blocks, early above late, so the claim that seven pairs are the
    same survey can be checked by eye instead of taken on trust."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure_, axes = plt.subplots(len(rows) * 2, 1,
                                 figsize=(9.4, 0.62 * len(rows) * 2 + 1.5))
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
    same = sum(1 for r in rows if r["same_survey"] == 1)
    import textwrap
    figure_.text(0.012, 0.972, "\n".join(textwrap.wrap(
                 f"{same} of the {len(rows)} pairs print the identical block - "
                 f"same officers, same year, same wording. The "
                 f"{len(rows) - same} that were really resurveyed both say so, "
                 f"and both change the form of the block to do it.", 104)),
                 ha="left", va="top", fontsize=9, color=INK_SECONDARY)
    figure_.subplots_adjust(left=0.175, right=0.99, top=0.938, bottom=0.008,
                            hspace=0.16)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure_.savefig(path, dpi=170, facecolor=SURFACE)
    plt.close(figure_)


def figure(rows: list[dict], path: Path) -> None:
    import matplotlib
    import textwrap
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    spatial = sorted([r for r in rows if r["matched"] != ""],
                     key=lambda r: -(r["matched"] + r["early_only"]))
    matched = np.array([r["matched"] for r in spatial], float)
    early_only = np.array([r["early_only"] for r in spatial], float)
    late_only = np.array([r["late_only"] for r in spatial], float)

    figure_, axes = plt.subplots(1, 2, figsize=(11.6, 5.6),
                                 gridspec_kw={"width_ratios": [1.5, 1]})
    figure_.patch.set_facecolor(SURFACE)
    positions = np.arange(len(spatial))[::-1]

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
    for position, row, total in zip(positions, spatial, totals):
        left.text(total + totals.max() * 0.015, position,
                  f"{row['count_ratio']:.2f}× as many later  ·  "
                  f"{row['matched_share']:.0%} matched",
                  va="center", ha="left", fontsize=8, color=INK_SECONDARY)
    left.set_yticks(positions)
    left.set_yticklabels(
        [f"{r['sheet_name']}\n"
         + ("same survey, reprinted" if r["same_survey"] == 1
            else f"RESURVEYED {r['late_revision_years'].replace(' ', '-')}")
         for r in spatial], fontsize=8.5, color=INK_PRIMARY)
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

    # The resurveyed pairs are separated by emphasis, not by a fourth hue, so
    # the three categorical slots keep the meaning they have in the left panel.
    right = axes[1]
    right.set_facecolor(SURFACE)
    radii = list(SENSITIVITY_RADII_M)
    for row in spatial:
        shares = [row[f"matched_share_{int(r)}m"] for r in radii]
        resurveyed = row["same_survey"] != 1
        right.plot(radii, shares, marker="o",
                   markersize=6 if resurveyed else 5,
                   linewidth=2.4 if resurveyed else 2,
                   color=INK_PRIMARY if resurveyed else INK_MUTED,
                   alpha=1.0 if resurveyed else 0.5,
                   zorder=4 if resurveyed else 3)
        if resurveyed:
            right.annotate(row["sheet_name"], (radii[-1], shares[-1]),
                           textcoords="offset points", xytext=(-6, -14),
                           ha="right", fontsize=8, color=INK_PRIMARY)
        elif row["early_in_shared"] < MIN_SHEET_HOUSES:
            right.annotate(f"{row['sheet_name']}\n{row['early_in_shared']} "
                           f"houses — a small-sample curve",
                           (radii[0], shares[0]),
                           textcoords="offset points", xytext=(8, -4),
                           ha="left", va="top", fontsize=7.5, color=INK_MUTED)
    right.plot([], [], color=INK_PRIMARY, linewidth=2.4, marker="o",
               label="really resurveyed")
    right.plot([], [], color=INK_MUTED, alpha=0.5, linewidth=2, marker="o",
               label="same survey, reprinted")
    right.legend(frameon=False, fontsize=8, loc="upper left",
                 labelcolor=INK_SECONDARY)
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

    reprints = [r for r in spatial
                if r["same_survey"] == 1
                and r["early_in_shared"] >= MIN_SHEET_HOUSES]
    ratios = [r["count_ratio"] for r in reprints]
    shares = [r["matched_share"] for r in reprints]
    resurveyed = [r for r in rows if r["same_survey"] != 1]
    figure_.suptitle("What differencing two printings of one survey measures",
                     x=0.012, ha="left", fontsize=13.5, color=INK_PRIMARY)
    figure_.text(0.012, 0.912, "\n".join(textwrap.wrap(
                 f"On {len(reprints)} pairs that print the identical 1889-1893 "
                 f"fieldwork credit, the later printing carries "
                 f"{min(ratios):.2f}× to {max(ratios):.2f}× as many detected "
                 f"houses and reproduces {min(shares):.0%}-{max(shares):.0%} of "
                 f"the early drawing. Both pairs that really were resurveyed "
                 f"fall inside those ranges.",
                 118)),
                 ha="left", va="top", fontsize=9, color=INK_SECONDARY)
    figure_.text(0.012, 0.075, "\n".join(textwrap.wrap(
                 f"Houses from the legend's “Maisons” mark. Pairs formed on the "
                 f"sheet's printed serial number, not its B-C designation. "
                 f"{len(rows) - len(spatial)} further pairs "
                 f"({', '.join(r['sheet_name'] for r in rows if r['matched'] == '')}) "
                 f"cannot be placed and appear in the CSV with counts only. "
                 f"Early sheets placed from their grade graticule (median 549 m "
                 f"against the later printing), which is what sets the match "
                 f"radius.", 128)),
                 ha="left", va="top", fontsize=8, color=INK_MUTED)
    figure_.subplots_adjust(left=0.155, right=0.985, top=0.775, bottom=0.215,
                            wspace=0.40)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure_.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(figure_)


FIELDS = ["designation", "serial", "sheet_name",
          "early_record_id", "late_record_id",
          "early_catalogue_year", "late_catalogue_year",
          "early_survey_years", "late_survey_years", "late_revision_years",
          "same_survey", "survey_gap_years", "credit_form_early",
          "credit_form_late", "comparison_tier",
          "early_position_basis", "late_position_basis",
          "shared_km2", "early_total", "late_total",
          "early_in_shared", "late_in_shared", "count_ratio",
          "early_in_neatline", "late_in_neatline", "count_ratio_neatline",
          "matched", "early_only", "late_only", "matched_share",
          "matched_share_250m", "matched_share_400m", "matched_share_600m",
          "matched_distance_median_m", "twin_offset_m"]

CREDIT_FIELDS = ["designation", "serial", "sheet_name", "record_id", "edition",
                 "catalogue_year", "survey_years", "revision_years",
                 "credit_form", "credit_block", "basis"]


def credit_form(block: str) -> str:
    """Which of the two forms the block is set in - the screen for a resurvey."""
    return "compiled" if block.lower().startswith("d'apres") else "officers"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=Path, nargs="*", default=None,
                        help="directories of extracted GeoJSON, most precise "
                             "first")
    parser.add_argument("--scans", type=Path, default=None)
    parser.add_argument("--series", type=Path,
                        default=REPO_ROOT / "data" / "tunisia_50k_series.csv")
    parser.add_argument("--graticule", type=Path,
                        default=REPO_ROOT / "data" / "sheet_graticule.json")
    parser.add_argument("--georef", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.json")
    parser.add_argument("--corner-fit", type=Path,
                        default=REPO_ROOT / "data" / "sheet_corner_fit.json")
    parser.add_argument("--grid", type=Path,
                        default=REPO_ROOT / "data" / "sheet_grid.json")
    parser.add_argument("--margins", type=Path,
                        default=REPO_ROOT / "data" / "sheet_margins.csv")
    parser.add_argument("--neatline-counts", type=Path,
                        default=REPO_ROOT / "data"
                                / "edition_neatline_counts.json")
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

    symbol_dirs = args.symbols or [REPO_ROOT / "data" / "symbols",
                                   REPO_ROOT / "data" / "symbols_corner_fit",
                                   REPO_ROOT / "data" / "symbols_graticule"]
    grid = json.loads(args.grid.read_text(encoding="utf-8"))
    placed = load_sources({"georef": args.georef,
                           "corner_fit": args.corner_fit,
                           "graticule": args.graticule})
    margins = {r["record_id"]: r for r in
               csv.DictReader(args.margins.open(encoding="utf-8"))}
    neatline_counts = (json.loads(args.neatline_counts.read_text(encoding="utf-8"))
                       if args.neatline_counts.exists() else {})

    rows, credit_rows = [], []
    for pair in find_pairs(args.series, grid):
        early_id, late_id = pair["early_record_id"], pair["late_record_id"]
        early_record, late_record = placed.get(early_id), placed.get(late_id)

        early_credit, late_credit = CREDITS.get(early_id), CREDITS.get(late_id)
        early_years = early_credit[1] if early_credit else ()
        late_years = late_credit[1] if late_credit else ()
        # Same survey means the block gives the same fieldwork years on both
        # printings; a later printing that adds a revision or a new leve is a
        # different survey even where the old years survive in the block.
        same = int(bool(early_years) and bool(late_years)
                   and set(early_years) == set(late_years))
        for key, credit, edition in ((early_id, early_credit, "early"),
                                     (late_id, late_credit, "later")):
            if not credit:
                continue
            block, years, revisions = credit
            credit_rows.append({
                "designation": pair["designation"], "serial": pair["serial"],
                "sheet_name": pair["sheet_name"],
                "record_id": key, "edition": edition,
                "catalogue_year": margins.get(key, {}).get("catalogue_year", ""),
                "survey_years": " ".join(str(y) for y in years),
                "revision_years": " ".join(str(y) for y in revisions),
                "credit_form": credit_form(block),
                "credit_block": block, "basis": "read_from_sheet",
            })

        row = {
            "designation": pair["designation"], "serial": pair["serial"],
            "sheet_name": pair["sheet_name"],
            "early_record_id": early_id, "late_record_id": late_id,
            "early_catalogue_year":
                margins.get(early_id, {}).get("catalogue_year", ""),
            "late_catalogue_year":
                margins.get(late_id, {}).get("catalogue_year", ""),
            "early_survey_years": " ".join(str(y) for y in early_years),
            "late_survey_years": " ".join(str(y) for y in late_years),
            "late_revision_years":
                " ".join(str(y) for y in (late_credit[2] if late_credit else ())),
            "same_survey": same,
            "survey_gap_years": (max(late_years) - max(early_years)
                                 if early_years and late_years else ""),
            "credit_form_early": credit_form(early_credit[0]) if early_credit else "",
            "credit_form_late": credit_form(late_credit[0]) if late_credit else "",
            "early_position_basis": (early_record or {}).get("position_basis", ""),
            "late_position_basis": (late_record or {}).get("position_basis", ""),
            "twin_offset_m": (early_record or {}).get("twin_offset_m", ""),
        }
        for field in FIELDS:
            row.setdefault(field, "")

        # The registration-free count: houses inside each sheet's own detected
        # neatline. No transform involved, so it exists for every pair.
        early_frame = (neatline_counts.get(early_id) or {}).get("buildings_in_neatline")
        late_frame = (neatline_counts.get(late_id) or {}).get("buildings_in_neatline")
        if early_frame and late_frame:
            row["early_in_neatline"] = early_frame
            row["late_in_neatline"] = late_frame
            row["count_ratio_neatline"] = round(late_frame / early_frame, 3)

        if not (early_record and late_record
                and early_record["epsg"] == late_record["epsg"]):
            row["comparison_tier"] = "counts_only"
            rows.append(row)
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

        early_points = load_points(symbol_dirs, early_id, early_record["epsg"])
        late_points = load_points(symbol_dirs, late_id, late_record["epsg"])
        if len(early_points) == 0 or len(late_points) == 0:
            row["comparison_tier"] = "counts_only"
            rows.append(row)
            continue
        early_shared = early_points[inside(early_points, shared)]
        late_shared = late_points[inside(late_points, shared)]

        matched, early_only, late_only, distances = match(
            early_shared, late_shared, MATCH_RADIUS_M)
        for radius in SENSITIVITY_RADII_M:
            hit, _, _, _ = match(early_shared, late_shared, radius)
            row[f"matched_share_{int(radius)}m"] = round(
                hit / max(len(early_shared), 1), 4)

        area = 0.5 * abs(sum(
            shared[i][0] * shared[(i + 1) % 4][1]
            - shared[(i + 1) % 4][0] * shared[i][1] for i in range(4))) / 1e6
        row.update({
            "comparison_tier": "spatial",
            "shared_km2": round(area, 1),
            "early_total": len(early_points), "late_total": len(late_points),
            "early_in_shared": len(early_shared),
            "late_in_shared": len(late_shared),
            "count_ratio": round(len(late_shared) / max(len(early_shared), 1), 3),
            "matched": matched, "early_only": early_only, "late_only": late_only,
            "matched_share": round(matched / max(len(early_shared), 1), 4),
            "matched_distance_median_m":
                round(float(np.median(distances)), 1) if len(distances) else "",
        })
        rows.append(row)

    for path, fields, table in ((args.out_csv, FIELDS, rows),
                                (args.out_credits, CREDIT_FIELDS, credit_rows)):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(table)

    spatial = [r for r in rows if r["comparison_tier"] == "spatial"]
    counts_only = [r for r in rows if r["comparison_tier"] == "counts_only"]
    print(f"{len(rows)} edition pairs, paired on the printed serial number "
          f"({len(spatial)} placed, {len(counts_only)} counts only)\n")
    print(f"{'sheet':17s} {'ser':6s} {'catalogue':11s} {'fieldwork':13s} "
          f"{'ratio':>6s} {'frame':>6s} {'matched':>8s} {'share':>6s}  survey")
    for row in rows:
        ratio = (f"{row['count_ratio']:6.2f}" if row["count_ratio"] != "" else "     -")
        frame = (f"{row['count_ratio_neatline']:6.2f}"
                 if row["count_ratio_neatline"] != "" else "     -")
        matched = f"{row['matched']:8d}" if row["matched"] != "" else "       -"
        share = (f"{row['matched_share']:6.0%}" if row["matched_share"] != ""
                 else "     -")
        print(f"{row['sheet_name'][:17]:17s} {row['serial']:6s} "
              f"{(str(row['early_catalogue_year'] or '?') + '-' + str(row['late_catalogue_year'] or '?')):11s} "
              f"{((row['early_survey_years'] or '?').split()[0] + '/' + (row['late_survey_years'] or '?').split()[0]):13s} "
              f"{ratio} {frame} {matched} {share}  "
              f"{'same' if row['same_survey'] == 1 else 'RESURVEYED'}")

    # Does the registration-free ratio agree with the shared-ground one? This is
    # what licenses quoting it on the pairs that cannot be placed.
    both = [(r["count_ratio"], r["count_ratio_neatline"]) for r in spatial
            if r["count_ratio"] != "" and r["count_ratio_neatline"] != ""]
    if both:
        gaps = [abs(a - b) for a, b in both]
        print(f"\nCalibration of the registration-free ratio: on the "
              f"{len(both)} placed pairs it differs from the shared-ground "
              f"ratio by {min(gaps):.2f}-{max(gaps):.2f} (median "
              f"{np.median(gaps):.2f}),")
        print(f"  which is why it is quoted for the {len(counts_only)} pairs "
              f"that have no transform.")

    same = [r for r in rows if r["same_survey"] == 1]
    other = [r for r in rows if r["same_survey"] != 1]
    counted = [r for r in same if r["comparison_tier"] == "spatial"
               and r["early_in_shared"] >= MIN_SHEET_HOUSES]
    small = [r for r in same if r["comparison_tier"] == "spatial"
             and r["early_in_shared"] < MIN_SHEET_HOUSES]
    if counted:
        ratios = [r["count_ratio"] for r in counted]
        shares = [r["matched_share"] for r in counted]
        print(f"\n{len(same)} of {len(rows)} pairs print the identical "
              f"fieldwork credit - reprints, not resurveys.")
        print(f"  on the {len(counted)} placed ones with at least "
              f"{MIN_SHEET_HOUSES} houses, the count ratio spans "
              f"{min(ratios):.2f}x to {max(ratios):.2f}x and the matched share "
              f"{min(shares):.0%} to {max(shares):.0%}")
        print(f"  - the noise floor of this comparison: no settlement change "
              f"smaller than that can be seen.")
        for row in small:
            print(f"  ({row['sheet_name']} is left out of the range: "
                  f"{row['early_in_shared']} houses, ratio "
                  f"{row['count_ratio']:.2f}x, a small sample talking.)")
    low, high = round(min(shares) * 100), round(max(shares) * 100)
    for row in other:
        print(f"\n{row['sheet_name']} really was resurveyed "
              f"({row['early_survey_years']} -> {row['late_survey_years']}, "
              f"revised {row['late_revision_years'] or 'n/a'}):")
        if row["comparison_tier"] == "spatial":
            here = round(row["matched_share"] * 100)
            print(f"  ratio {row['count_ratio']:.2f}x against the reprints' "
                  f"{min(ratios):.2f}x-{max(ratios):.2f}x, and nearer 1.00 "
                  f"than any of them.")
            print(f"  matched {here}% against their {low}%-{high}% - "
                  f"{abs(here - low)} points below the lowest, against a "
                  f"{high - low}-point spread among sheets that are the "
                  f"same drawing.")
        else:
            print(f"  no transform on the early printing, so counts only: "
                  f"{row['count_ratio_neatline']:.2f}x inside the frame "
                  f"({row['early_in_neatline']} -> {row['late_in_neatline']} "
                  f"houses).")
    if other:
        print(f"\nSo neither statistic separates new fieldwork from a reprint.")

    if spatial:
        figure(rows, args.out_figure)
        print(f"\n  -> {args.out_csv}\n  -> {args.out_credits}"
              f"\n  -> {args.out_figure}")
    if args.scans:
        neatlines = {}
        for source in (args.georef, args.corner_fit, args.graticule, args.grid):
            for key, value in json.loads(
                    source.read_text(encoding="utf-8")).items():
                if "neatline_px" in value:
                    neatlines.setdefault(key, value["neatline_px"])
        credits_figure(rows, args.scans, neatlines, args.out_credits_figure)
        print(f"  -> {args.out_credits_figure}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Put the ellipses back on the sheet they came from, and test the two rules.

An ellipse drawn in WGS84 over a modern basemap is easy to believe and hard to
check. This script does the opposite: it inverts the sheet's own affine, draws
each ellipse back onto the 1881 scan in scan pixels, and leaves the result for
a reader to compare against the engraved names underneath. If an ellipse does
not sit over the name it claims to describe, it shows here.

It also tests the two rules the ellipses are built on, which is cheaper than
trusting them:

    rule 1  every one of a tribe's own labels lies inside its ellipse
    rule 2  no other tribe's label lies inside it

Rule 1 must hold for all 88; a violation is a bug. Rule 2 cannot always hold,
and where it fails the failure is a finding rather than a fault: a tribe whose
compilers put its name 200 km apart has an ellipse that cannot help covering
its neighbours, and those are exactly the tribes whose identity is in doubt.
They are flagged in data/tribal_spread.csv as encloses_other_tribes.

The rules need nothing but the repository. The overlays need the full IIIF
scans, which are too large to commit, so they are looked for in a directory
given by --scans, else $MAPSTN_SCANS, else scratch/iiif beside this checkout.
When they are not there the rules still run and the overlays are skipped, and
the report says so rather than failing.

Outputs:
    docs/img/tribal_spread_check.png
    data/tribal_spread_check.json

Usage:
    python3 scripts/check_tribal_spread.py
    python3 scripts/check_tribal_spread.py --scans ~/iiif
    MAPSTN_SCANS=~/iiif python3 scripts/check_tribal_spread.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent
# The scans are 0.7 GB and are not in the repository. Look where the caller
# says, then at the environment, then at scratch/iiif beside the checkout.
DEFAULT_SCANS = REPO_ROOT / "scratch" / "iiif"


def scans_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser()
    env = os.environ.get("MAPSTN_SCANS")
    if env:
        return Path(env).expanduser()
    return DEFAULT_SCANS


def scans_label(scans: Path) -> str:
    """Where this run looked, said in a way that is the same on any machine.

    The absolute path is somebody's home directory or scratch mount, which is
    noise in a committed file and different for every reader. Inside the
    checkout it is worth naming; outside it, only the fact is.
    """
    try:
        return str(scans.relative_to(REPO_ROOT))
    except ValueError:
        return "a directory outside the checkout, given by --scans or $MAPSTN_SCANS"

SHEETS = [
    {"id": "btv1b84389986", "year": 1881, "scan": "FULL_theatre1881.jpg",
     "sheet": "1881 Lasailly", "scale": 0.22,
     "out": "tribal_spread_check.jpg", "spot": "tribal_spread_spot_1881.jpg"},
    {"id": "btv1b53136235q", "year": 1853, "scan": "FULL_pellissier.jpg",
     "sheet": "1853 Pellissier", "scale": 0.18,
     "out": "tribal_spread_check_1853.jpg", "spot": "tribal_spread_spot_1853.jpg"},
]
SHEET = SHEETS[0]["id"]
KM_PER_DEG_LAT = 110.574
LAT0 = 34.5
KM_PER_DEG_LON = 111.320 * math.cos(math.radians(LAT0))
# How far outside an ellipse a point may sit and still count as on its edge.
# The CSV rounds the axes to 0.1 km, which moves the boundary by about this.
TOL = 0.02


def rules() -> dict:
    rows = list(csv.DictReader((REPO_ROOT / "data" / "tribal_spread.csv")
                               .open(encoding="utf-8")))
    labels = []
    for row in csv.DictReader((REPO_ROOT / "data" / "tribal_territories.csv")
                              .open(encoding="utf-8")):
        labels.append((row["tribe"] or row["label_as_printed"],
                       float(row["lon"]), float(row["lat"])))
    martel = REPO_ROOT / "data" / "martel_1965_tribes.csv"
    if martel.exists():
        for row in csv.DictReader(martel.open(encoding="utf-8")):
            labels.append((row["tribe"], float(row["lon"]), float(row["lat"])))

    points = np.array([[lon * KM_PER_DEG_LON, lat * KM_PER_DEG_LAT]
                       for _, lon, lat in labels])
    names = [t for t, _, _ in labels]

    own_out, foreign_in = [], []
    for row in rows:
        centre = np.array([float(row["lon"]) * KM_PER_DEG_LON,
                           float(row["lat"]) * KM_PER_DEG_LAT])
        a, b = float(row["major_km"]) / 2, float(row["minor_km"]) / 2
        theta = math.radians(float(row["angle_deg"]))
        rot = np.array([[math.cos(theta), -math.sin(theta)],
                        [math.sin(theta), math.cos(theta)]])
        local = (points - centre) @ rot
        d = (local[:, 0] / a) ** 2 + (local[:, 1] / b) ** 2
        for i, name in enumerate(names):
            if name == row["tribe"] and d[i] > 1 + TOL:
                own_out.append({"tribe": row["tribe"], "d": round(float(d[i]), 3)})
            if name != row["tribe"] and d[i] < 1 - TOL:
                foreign_in.append({"tribe": row["tribe"], "covers": name,
                                   "d": round(float(d[i]), 3)})
    return rows, own_out, foreign_in


def sheet_rows(sheet: dict) -> list[dict]:
    """That sheet's own ellipses, not the merged ones.

    An overlay of the merged ellipse on one sheet would be testing the other
    two sheets as much as this one. The per-sheet table is built from this
    sheet's labels alone and bounded by this sheet's own neighbours, so drawing
    it here asks the only question the scan can answer: does the ellipse sit on
    the ground this engraver gave the tribe?
    """
    path = REPO_ROOT / "data" / "tribal_spread_by_sheet.csv"
    if not path.exists():
        return []
    return [r for r in csv.DictReader(path.open(encoding="utf-8"))
            if r["sheet"] == sheet["sheet"]]


def overlay(rows, sheet: dict, scans: Path) -> bool:
    """Draw the ellipses back onto one sheet, in that sheet's own pixels."""
    scan = scans / sheet["scan"]
    if not scan.exists():
        return False
    config = json.loads((REPO_ROOT / "config" / "tribal_labels_read.json")
                        .read_text(encoding="utf-8"))["maps"][sheet["id"]]
    control = config["control_points"]
    design = np.array([[p["lon"], p["lat"], 1.0] for p in control])
    target = np.array([[p["x"], p["y"]] for p in control])
    inverse, *_ = np.linalg.lstsq(design, target, rcond=None)
    residual = float(np.sqrt(((design @ inverse - target) ** 2).sum(axis=1)).mean())

    fits = json.loads((REPO_ROOT / "data" / "tribal_fit.json").read_text())
    km_per_px = fits[sheet["id"]]["km_per_px"]
    factor = sheet["scale"]

    own = sheet_rows(sheet) or rows
    image = Image.open(scan).convert("RGB")
    image = image.resize((int(image.width * factor), int(image.height * factor)),
                         Image.LANCZOS)
    draw = ImageDraw.Draw(image, "RGBA")
    for row in own:
        cx, cy = (np.array([float(row["lon"]), float(row["lat"]), 1.0])
                  @ inverse) * factor
        a = float(row["major_km"]) / 2 / km_per_px * factor
        b = float(row["minor_km"]) / 2 / km_per_px * factor
        # The scan's y grows downward, so the bearing turns the other way.
        theta = math.radians(-float(row["angle_deg"]))
        ring = []
        for t in np.linspace(0, 2 * math.pi, 96):
            x, y = a * math.cos(t), b * math.sin(t)
            ring.append((cx + x * math.cos(theta) - y * math.sin(theta),
                         cy + x * math.sin(theta) + y * math.cos(theta)))
        flagged = int(row["encloses_other_tribes"]) > 0
        draw.polygon(ring, fill=(200, 60, 40, 24) if flagged else (40, 90, 150, 24))
        draw.line(ring + [ring[0]],
                  fill=(170, 40, 25, 210) if flagged else (30, 70, 130, 185),
                  width=2)
        draw.text((cx - 12, cy - 5), row["tribe"][:16], fill=(0, 0, 0, 235))
    # A scan is photographic, so JPEG at 82 keeps it legible at a
    # sixth of the size a PNG of the same picture would take.
    image.save(REPO_ROOT / "docs" / "img" / sheet["out"], quality=82,
               optimize=True)
    sheet["residual_px"] = round(residual, 1)
    sheet["tribes_drawn"] = len(own)
    sheet["used"] = ("this sheet's own ellipses" if sheet_rows(sheet)
                     else "the merged ellipses")
    return True


SPOT = {"btv1b84389986": ["Hammama", "Zlass", "Souassi", "Frechiche"],
        "btv1b53136235q": ["Hammama", "Zlass", "Frechiche", "Mejers"]}


def spot_check(rows, sheet: dict, scans: Path, zoom: float = 0.45) -> bool:
    """A few ellipses at full scan resolution, to be held against the engraving.

    The whole-sheet overlay shows that nothing is grossly misplaced. It is too
    small to show whether an ellipse actually sits over its name, which is the
    question, so these crops are the ones to look at.
    """
    scan = scans / sheet["scan"]
    if not scan.exists():
        return False
    config = json.loads((REPO_ROOT / "config" / "tribal_labels_read.json")
                        .read_text(encoding="utf-8"))["maps"][sheet["id"]]
    control = config["control_points"]
    design = np.array([[p["lon"], p["lat"], 1.0] for p in control])
    target = np.array([[p["x"], p["y"]] for p in control])
    inverse, *_ = np.linalg.lstsq(design, target, rcond=None)
    km_per_px = json.loads((REPO_ROOT / "data" / "tribal_fit.json")
                           .read_text())[sheet["id"]]["km_per_px"]
    by_tribe = {r["tribe"]: r for r in (sheet_rows(sheet) or rows)}
    image = Image.open(scan).convert("RGB")

    panels = []
    for tribe in SPOT[sheet["id"]]:
        row = by_tribe.get(tribe)
        if row is None:
            continue
        centre = np.array([float(row["lon"]), float(row["lat"]), 1.0]) @ inverse
        a = float(row["major_km"]) / 2 / km_per_px
        b = float(row["minor_km"]) / 2 / km_per_px
        half = int(max(a, b) * 1.25)
        box = (max(0, int(centre[0] - half)), max(0, int(centre[1] - half * 0.62)),
               min(image.width, int(centre[0] + half)),
               min(image.height, int(centre[1] + half * 0.62)))
        crop = image.crop(box)
        draw = ImageDraw.Draw(crop, "RGBA")
        theta = math.radians(-float(row["angle_deg"]))
        ring = []
        for t in np.linspace(0, 2 * math.pi, 96):
            x, y = a * math.cos(t), b * math.sin(t)
            ring.append((centre[0] - box[0] + x * math.cos(theta) - y * math.sin(theta),
                         centre[1] - box[1] + x * math.sin(theta) + y * math.cos(theta)))
        draw.line(ring + [ring[0]], fill=(190, 30, 20, 255), width=9)
        crop = crop.resize((int(crop.width * zoom), int(crop.height * zoom)),
                           Image.LANCZOS)
        strip = Image.new("RGB", (crop.width, crop.height + 22), "white")
        strip.paste(crop, (0, 0))
        ImageDraw.Draw(strip).text(
            (4, crop.height + 5),
            f"{sheet['year']}  {tribe}  {row['major_km']} x {row['minor_km']} km",
            fill="black")
        panels.append(strip)
    if not panels:
        return False
    width = max(p.width for p in panels)
    out = Image.new("RGB", (width, sum(p.height + 8 for p in panels)), "white")
    y = 0
    for panel in panels:
        out.paste(panel, (0, y))
        y += panel.height + 8
    out.save(REPO_ROOT / "docs" / "img" / sheet["spot"], quality=84,
             optimize=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--scans", metavar="DIR",
        help="directory holding the full IIIF scans named in SHEETS. "
             "Falls back to $MAPSTN_SCANS, then to scratch/iiif beside the "
             "checkout. Without them the rules still run and the overlays "
             "are skipped.")
    args = parser.parse_args()
    scans = scans_dir(args.scans)

    rows, own_out, foreign_in = rules()
    flagged = [r for r in rows if int(r["encloses_other_tribes"]) > 0]
    flagged.sort(key=lambda r: -float(r["own_spread_km"]))

    drawn = {}
    for sheet in SHEETS:
        drawn[str(sheet["year"])] = {
            "written": overlay(rows, sheet, scans),
            "file": f"docs/img/{sheet['out']}",
            "inverse_affine_residual_px": sheet.get("residual_px"),
            "ellipses_drawn": sheet.get("tribes_drawn"),
            "ellipses_used": sheet.get("used"),
            "spot_check": (f"docs/img/{sheet['spot']}"
                           if spot_check(rows, sheet, scans) else None),
        }

    report = {
        "_about": ("Tests the two rules the ellipses are built on, and redraws "
                   "them on the 1881 scan so they can be compared against the "
                   "engraved names."),
        "tribes": len(rows),
        "rule_1_own_label_outside": own_out,
        "rule_1_violations": len(own_out),
        "_rule_1": ("Every label of a tribe must lie inside that tribe's "
                    "ellipse. A violation here is a bug, not a finding."),
        "rule_2_foreign_label_inside": len(foreign_in),
        "_rule_2": ("No other tribe's label should lie inside. Where it does, "
                    "the tribe's own labels are already spread across its "
                    "neighbours and no ellipse containing them can avoid it. "
                    "That is a statement about the sources, not about the "
                    "method."),
        "tribes_enclosing_a_neighbour": len(flagged),
        "worst": [{"tribe": r["tribe"], "labels": int(r["labels"]),
                   "sheets": int(r["sources"]),
                   "own_spread_km": float(r["own_spread_km"]),
                   "covers": r["encloses"]} for r in flagged[:8]],
        "_worst_comment": (
            "Read the top of this list as a list of suspected name collisions. "
            "Ouled Sdira at 211 km and Ouled Khiar at 287 km are almost "
            "certainly two different groups sharing a name, which the report "
            "already says of Ouled Khiar on other grounds; Souassi at 126 km "
            "and Riah at 119 km are the next candidates."),
        "overlays": drawn,
        "_what_the_overlays_show": (
            "Held against the engraving, the ellipses sit on their names. The "
            "Hammama ellipse lies along HAMMAMA (Tribu) across the steppe, the "
            "Zlass over ZLAAS and the Kairouan country, the Frechiche over "
            "FRECHICHE (Tribu) at Kasserine. The flagged ones do not: Souassi "
            "is a 126 by 16 km splinter running from Enfida to past Sousse, "
            "which is two placements joined rather than a territory, and that "
            "is what the flag is for."),
        "gaps_found_and_closed": [
            {"sheet": 1853, "tribe": "Frechiche", "status": "closed",
             "found": ("The spot check showed the Frechiche ellipse stopping "
                       "short of the engraving. Reading the ground at 2.25x "
                       "settled what is actually printed there: three Frachiche "
                       "names, not two."),
             "what_is_printed": (
                 "FRACHICHE OULAD ALI on an arc from (2239, 4363) to (2767, "
                 "5018); Frachiche Ouazaz on a second arc from (2203, 4912) to "
                 "(2681, 5206) with MERIDIONALE set as a second line beneath "
                 "it, so MERIDIONALE is a qualifier on that same name and not a "
                 "label of its own; and a third FRACHICHE set vertically from "
                 "(2836, 4682) to (2991, 5068), which the first reading of the "
                 "face missed."),
             "fix": ("The third name is now in config/tribal_labels_read.json "
                     "at its midpoint (2913, 4875), confidence medium. Only the "
                     "word FRACHICHE is recorded: the qualifier running down "
                     "the page after it is not legible enough to name."),
             "correction": (
                 "An earlier run of this check reported the gap as a missing "
                 "FRACHICHE MERIDIONALE label. That was wrong. MERIDIONALE "
                 "belongs to the Ouazaz name; the missing label is the third, "
                 "vertical one."),
             },
            {"sheet": 1853, "tribe": "the south", "status": "closed",
             "found": ("Finding one missed name asked what else the first "
                       "reading had missed, so the whole face was swept in "
                       "eighteen windows. The answer was the south: the face "
                       "had been read to about 34 N and never below it."),
             "what_is_printed": (
                 "Six tribal names below that line, three of them gazetteer "
                 "tribes: MATMATTA along the Matmata range, HAMERNA east of it, "
                 "OUERGUEMMA down the Dahar, and BENI YACOUB, BENI ZID and "
                 "NEFZAOUA about the chott."),
             "fix": ("All six are in config/tribal_labels_read.json. The 1853 "
                     "sheet goes from 46 labels to 52 and the collection from "
                     "142 to 148. Ouerghemma gains a second placement, so the "
                     "cross-sheet agreement table gains a 31st tribe and its "
                     "first check in the far south: the two sheets put the "
                     "Ouerghemma 35.1 km apart."),
             "not_added": (
                 "The sweep also found lineage names in the north and the "
                 "Sahel set like tribes but small enough to be douars. They "
                 "are listed under _sweep_candidates in "
                 "config/tribal_labels_read.json with approximate positions, "
                 "not added: on a sheet that marks nothing, telling a tribe "
                 "from a douar is judgement, and a wrong call is worse than a "
                 "gap."),
             }],
        "_overlays": (
            "The ellipses inverted back onto each Gallica scan in its own "
            "pixels, so they can be held against the engraved names. Only the "
            "tribes that sheet names are drawn on it. Flagged tribes are in "
            "red. inverse_affine_residual_px is how well the lon/lat to pixel "
            "transform reproduces the control towns, and it has to be small or "
            "the overlay would be testing the transform rather than the "
            "ellipses. Needs the full scans, which are too large to commit: "
            "pass --scans DIR, or set $MAPSTN_SCANS, or put them in "
            "scratch/iiif beside the checkout. Skipped when they are absent, "
            "and scans_dir records where this run looked."),
        "scans_dir": scans_label(scans),
    }
    (REPO_ROOT / "data" / "tribal_spread_check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"rule 1, own label outside its ellipse: {len(own_out)} "
          f"(must be 0)")
    print(f"rule 2, a foreign label inside: {len(foreign_in)} placements across "
          f"{len(flagged)} tribes")
    for row in flagged[:6]:
        print(f"  {row['tribe']:20s} {row['labels']} labels on "
              f"{row['sources']} sheets, own spread "
              f"{float(row['own_spread_km']):6.1f} km, covers "
              f"{row['encloses_other_tribes']}")
    for year, info in drawn.items():
        if info["written"]:
            print(f"overlay {year}: {info['ellipses_drawn']} ellipses, "
                  f"inverse affine residual {info['inverse_affine_residual_px']} px")
        else:
            print(f"overlay {year}: skipped, no scan in {scans}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

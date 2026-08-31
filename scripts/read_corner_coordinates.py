#!/usr/bin/env python3
"""Read the Lambert coordinates each sheet prints at its own four corners.

Every sheet in the series states, in red, in the margin beside each corner of
the inner neatline, the exact Lambert easting and northing of that corner - to
the metre. The Kasserine sheet says:

    NW  388.498 m / 222.548 m        NE  420.395 m / 220.122 m
    SW  386.972 m / 202.612 m        SE  418.870 m / 200.185 m

The easting is set vertically, reading bottom to top, just outside the frame
above or below the corner; the northing horizontally, just outside the frame to
its left or right. Both carry a red leader line pointing at the corner itself.

This is a better anchor than anything derived, and it is worth being precise
about why. The previous anchor voted among the red kilometre labels along the
margins, which gives an integer kilometre, and then checked the result against
the catalogue's bounding box. That check turned out to measure mostly other
things: the disagreements it reported are continuous, and an integer anchor can
only ever be wrong by a whole kilometre, so most of what it was reporting was
neatline-detection and catalogue error rather than a bad anchor. Worse, the
label vote is not independent of the catalogue at all - the window of acceptable
label values is derived from the catalogue box, so a sheet with a bad box has
its anchor forced into the wrong window. That is what happened on Djebel Mrhila,
whose printed corner reads 421.922 m against a catalogue box centred 35 km east.

Eight numbers per sheet, and they are heavily over-determined: the differences
between the four corners are fixed by the printed kilometric grid, whose spacing
and rotation are measured to about 20 m rms without any catalogue value or any
anchor entering. So a candidate reading at one corner predicts the other three,
and only the right one is corroborated by corners read independently.

That redundancy is what makes the reading usable, because the OCR is no better
here than it was on the grid labels. The glyphs are about 22 px tall - some 2 mm
of print - and a single wrong digit in the kilometre part is a 10 km error that
would pass unnoticed on its own.

It does not make the reading safe by itself, and the reason is worth stating
because it took a wrong answer to see it. Four corners of one sheet are the same
typeface in the same scan, so a digit misread at one corner is liable to be
misread the same way at another - and then two wrong readings corroborate each
other and look exactly like two right ones. Grombalia reads 628 at its
north-west corner and 660 at its north-east, both a 5 read as a 6, against a
correct 526.895 at the south-west and a correct 560 at the north-east: two
against two, and the wrong pair would have moved the sheet 100 km. Ties are
therefore broken by the margin kilometre labels, which are separate printing
read separately, and a reading that would *move* a sheet is held to a higher bar
than one that confirms where it already is.

What comes out, per sheet:

  * `origin_shift_km`   how many whole kilometres the label-voted anchor is out
  * `neatline_error_m`  what is left over, which is frame detection error and is
                        reported rather than absorbed. Measured across the
                        series: median 15 m in easting and 32 m in northing,
                        worst 258 m and 466 m - so the frame detector is far
                        better than its worst case suggested.
  * `corner_support`    how many corners corroborate, per axis

The anchor is quantised to whole kilometres deliberately. The grid lines are
whole kilometres of Lambert by construction, so the absolute placement can only
shift by a whole kilometre; the sub-kilometre remainder is the frame, not the
anchor, and folding it into the anchor would smear a known error into the one
quantity that was exact.

One further property, found while checking a correction and not designed for:
adjacent sheets print *identical* corner coordinates. Djebel Mrhila gives its
south-west corner as 420.395 m / 220.122 m, which is exactly what Kasserine
gives for its north-east. Across the 73 georeferenced sheets, 237 corner pairs
from different sheets coincide - median 67 m apart, worst 184 m, on 69 of the 73
- which both validates the whole transform independently and lets a sheet whose
own printing could not be read borrow a corner from its neighbour. See
georeference_sheets.corroborate_by_neighbours.

Requires a previous georeferencing pass, for the detected neatline that places
the search windows - so the pipeline is: detect grid, georeference, read
corners, georeference again anchored on them.

Outputs:
    data/sheet_corners.csv    one row per sheet, with the evidence
    data/sheet_corners.json   the resolved corner coordinates

Usage:
    python3 scripts/read_corner_coordinates.py --images <dir of record_id.jpg>
    python3 scripts/read_corner_coordinates.py --images <dir> --only <record_id>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image, ImageOps
from scipy import ndimage

REPO_ROOT = Path(__file__).resolve().parent.parent

# Red ink, the same test the grid-label reader uses.
RED_MINUS_GREEN, RED_MINUS_BLUE, RED_FLOOR = 40, 30, 110

# A leader line is a few pixels thick and hundreds long; a digit at ~298 dpi is
# roughly 40 px tall and 25 wide. Dropping components thinner than this in their
# narrow dimension takes the leaders out and leaves the text.
LEADER_MIN_THICKNESS = 7
LEADER_MIN_LENGTH = 90

# Search windows, as (dx0, dy0, dx1, dy1) offsets from the corner pixel. The
# easting is vertical and sits outside the frame in the y direction, the
# northing horizontal and outside in x, so each corner needs its own signs.
WINDOWS = {
    "north_west": {"easting":  (-290, -680, 170, -20),
                   "northing": (-980, -190, -10, 280)},
    "north_east": {"easting":  (-170, -680, 290, -20),
                   "northing": (  10, -190, 980, 280)},
    "south_west": {"easting":  (-290,   20, 170, 680),
                   "northing": (-980, -280, -10, 190)},
    "south_east": {"easting":  (-170,   20, 290, 680),
                   "northing": (  10, -280, 980, 190)},
}

# "388.498 m", but also "388,498" and "388 498" - the separator is the first
# thing OCR loses. The trailing "m" is what separates a corner coordinate from
# the plain kilometre label printed a few centimetres away, so it is required:
# reading the two as one number is how "222.548 m." next to "222" became 466222.
VALUE_RE = re.compile(r"(\d{3})\s*[.,'’]?\s*(\d{3})\s*[.,]?\s*m")
VALUE_RE_LOOSE = re.compile(r"(\d{3})\s*[.,'’]\s*(\d{3})")

# One text line at a time, so psm 7 applies and nothing can be joined across
# two separate pieces of printing.
OCR_PASSES = (("--psm 7", 4), ("--psm 7", 6), ("--psm 13", 4))

# Padding around a detected line, wider along it: a leading glyph sometimes
# touches the leader line and is dropped with it, and the crop has to be loose
# enough that OCR still sees it. Cropping tight lost the "3" of "388.498".
PAD_ALONG, PAD_ACROSS = 30, 10

# Red ink keeps a high red channel; black ink does not.
BLACK_INK_RED_MAX = 130
WHITELIST = "-c tessedit_char_whitelist=0123456789.,m "

# A glyph in this annotation is about 40 px tall at ~298 dpi. The bounds are
# wide enough for the "." and the superscript "m" and narrow enough to drop
# contour fragments and the tick marks along the frame.
GLYPH_MIN_PX, GLYPH_MAX_PX = 8, 110
LINE_Y_TOLERANCE = 26
LINE_X_GAP = 70
MIN_GLYPHS = 5

# Lambert Tunisie coordinates for the sheets in hand: eastings 300-700 km,
# northings 100-500 km. Anything outside is a misread, not a corner.
PLAUSIBLE = {"easting": (300_000, 700_000), "northing": (100_000, 520_000)}

# A candidate corroborates a hypothesis when it lands within this of where the
# grid predicts it. The grid itself is good to ~20 m rms; the slack is for the
# neatline, each side of which can be picked on the wrong one of three rules.
CORROBORATION_M = 400.0

# Two corners is one independent corroboration, and that is enough: readings are
# whole kilometres and the corners are about 32 km apart, so for a misread digit
# to be confirmed it would have to land within one kilometre of what another
# corner's reading predicts - about a half of one percent of the plausible
# range. The count is reported so a consumer can insist on more.
MIN_SUPPORT = 2


def ocr_image(crop: Image.Image) -> Image.Image:
    """The crop as grey text on a light ground, for Tesseract to binarise.

    Red ink on cream paper is already high contrast in the green channel, which
    the ink absorbs and the paper does not, so the green channel *is* the
    grayscale wanted and nothing needs stretching. Two earlier attempts read
    much worse: a binary red mask erodes glyphs only 22 px tall until "222.548"
    comes back as "2.6.", and a stretched red-dominance measure saturates and
    merges them into blobs. Black ink - the neatline, "20 Kil." - is dark in the
    red channel too, which is what distinguishes it from the red annotation, so
    it is whitened out rather than left for OCR to trip over.
    """
    array = np.asarray(crop).astype(np.int16)
    red, green = array[..., 0], array[..., 1]
    grey = green.copy()
    grey[red < BLACK_INK_RED_MAX] = 255
    return ImageOps.autocontrast(
        Image.fromarray(np.clip(grey, 0, 255).astype(np.uint8)))


def red_text_mask(crop: Image.Image) -> np.ndarray:
    """Red ink with the leader lines taken out."""
    array = np.asarray(crop).astype(np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    mask = ((red - green > RED_MINUS_GREEN) & (red - blue > RED_MINUS_BLUE)
            & (red > RED_FLOOR))
    labels, count = ndimage.label(mask)
    if not count:
        return mask
    for index, slices in enumerate(ndimage.find_objects(labels), start=1):
        height = slices[0].stop - slices[0].start
        width = slices[1].stop - slices[1].start
        thin = min(height, width) < LEADER_MIN_THICKNESS
        long = max(height, width) > LEADER_MIN_LENGTH
        if thin and long:
            mask[labels == index] = False
    return mask


def text_lines(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of runs of glyphs sitting on a common baseline.

    Segmenting before reading is what keeps the corner coordinate and the
    kilometre label printed beside it from being read as one number, and it lets
    every crop be a single text line, which is the case Tesseract handles best.
    """
    labels, count = ndimage.label(mask)
    if not count:
        return []
    glyphs = []
    for slices in ndimage.find_objects(labels):
        y0, y1 = slices[0].start, slices[0].stop
        x0, x1 = slices[1].start, slices[1].stop
        if not (GLYPH_MIN_PX <= y1 - y0 <= GLYPH_MAX_PX):
            continue
        if x1 - x0 > GLYPH_MAX_PX:
            continue
        glyphs.append((x0, y0, x1, y1))
    glyphs.sort(key=lambda g: (g[1], g[0]))

    lines: list[list[tuple[int, int, int, int]]] = []
    for glyph in glyphs:
        centre = (glyph[1] + glyph[3]) / 2
        for line in lines:
            last = line[-1]
            if (abs(centre - (last[1] + last[3]) / 2) <= LINE_Y_TOLERANCE
                    and glyph[0] - last[2] <= LINE_X_GAP):
                line.append(glyph)
                break
        else:
            lines.append([glyph])

    boxes = []
    for line in lines:
        if len(line) < MIN_GLYPHS:
            continue
        boxes.append((min(g[0] for g in line), min(g[1] for g in line),
                      max(g[2] for g in line), max(g[3] for g in line)))
    return boxes


def candidates(crop: Image.Image, rotate: int) -> dict:
    """What each annotation line in one window reads as.

    Two things come back, and they are not equally reliable. The kilometre - the
    leading three digits - is read well. The metres after the separator often
    are not: Kasserine's 222.548 comes back as 222.566. Since an anchor can only
    be a whole kilometre out, the kilometre is what decides it, and the metres
    are kept separately, for the frame, and only when two passes agree on them.
    """
    # Rotate the crop itself, not the mask and the rendering separately: PIL and
    # ndimage disagree about which way a positive angle turns, and mismatched
    # boxes silently found nothing at all in the corners where the easting is
    # set the other way up.
    if rotate:
        crop = crop.rotate(rotate, expand=True)
    mask = red_text_mask(crop)
    if not mask.any():
        return {"km": [], "metres": []}
    image = ocr_image(crop)

    kilometres, metres = [], []
    for x0, y0, x1, y1 in text_lines(mask):
        line = image.crop((max(0, x0 - PAD_ALONG), max(0, y0 - PAD_ACROSS),
                           x1 + PAD_ALONG, y1 + PAD_ACROSS))
        readings = []
        for config, upscale in OCR_PASSES:
            scaled = line.resize((line.width * upscale, line.height * upscale),
                                 Image.LANCZOS)
            text = pytesseract.image_to_string(
                scaled, config=f"{config} {WHITELIST}").replace("\n", " ")
            match = VALUE_RE.search(text) or VALUE_RE_LOOSE.search(text)
            if match:
                readings.append((int(match.group(1)), int(match.group(2))))
        for kilometre, metre in readings:
            kilometres.append(kilometre)
            # The metre part counts only when a second pass read it the same.
            if sum(1 for k, m in readings if k == kilometre and m == metre) > 1:
                metres.append(kilometre * 1000 + metre)
    return {"km": kilometres, "metres": metres}


def read_windows(image: Image.Image, frame: dict) -> dict:
    """Candidate values for each of the eight printed numbers."""
    width, height = image.size
    corner_pixels = {
        "north_west": (frame["left"], frame["top"]),
        "north_east": (frame["right"], frame["top"]),
        "south_west": (frame["left"], frame["bottom"]),
        "south_east": (frame["right"], frame["bottom"]),
    }
    readings: dict[str, dict[str, list[int]]] = {}
    for corner, (cx, cy) in corner_pixels.items():
        readings[corner] = {}
        for axis, (dx0, dy0, dx1, dy1) in WINDOWS[corner].items():
            box = (max(0, cx + dx0), max(0, cy + dy0),
                   min(width, cx + dx1), min(height, cy + dy1))
            if box[2] <= box[0] or box[3] <= box[1]:
                readings[corner][axis] = {"km": [], "metres": []}
                continue
            crop = image.crop(box)
            # The easting is set vertically. Which way up is not consistent
            # across the series, so both quarter turns are tried.
            rotations = (90, -90) if axis == "easting" else (0,)
            low, high = PLAUSIBLE[axis]
            merged: dict[str, list[int]] = {"km": [], "metres": []}
            for rotation in rotations:
                found = candidates(crop, rotation)
                merged["km"] += [v for v in found["km"]
                                 if low // 1000 <= v <= high // 1000]
                merged["metres"] += [v for v in found["metres"]
                                     if low <= v <= high]
            readings[corner][axis] = merged
    return readings


def resolve(readings: dict, linear: np.ndarray, corner_pixels: dict,
            axis: str, stored: dict) -> dict:
    """Pick the one reading the printed grid corroborates on the other corners.

    The grid fixes every difference between corners exactly, so a candidate at
    one corner predicts all four. A candidate produced by a misread digit
    predicts three values nothing else read; the right one is confirmed by the
    corners that were read independently.

    Ties are broken by the margin kilometre labels, which are a different piece
    of printing read separately and so are entitled to a say. They matter more
    than they look: four corners of one sheet are the same typeface scanned in
    one pass, so a digit misread at one corner is liable to be misread the same
    way at another, and then two wrong readings corroborate each other and look
    exactly like two independent right ones. The Grombalia sheet reads 628 at its
    north-west corner and 660 at its north-east, both a 5 read as a 6, against a
    correct 526.895 at the south-west and a correct 560 at the north-east - two
    against two, and the wrong pair would have moved the sheet 100 km.
    """
    column = 0 if axis == "easting" else 1
    predicted = {corner: float(linear[0, column] * x + linear[1, column] * y)
                 for corner, (x, y) in corner_pixels.items()}

    # A kilometre reading of 388 says the corner lies somewhere in [388000,
    # 389000), so it is compared as its midpoint with half a kilometre of slack,
    # plus what the neatline can be out by.
    def agrees(kilometre: int, target: float) -> bool:
        return abs(kilometre * 1000 + 500 - target) <= 500 + CORROBORATION_M

    best = None
    for source, values in readings.items():
        for kilometre in dict.fromkeys(values[axis]["km"]):
            # What this candidate implies for the placement of the whole sheet.
            offset = kilometre * 1000 + 500 - predicted[source]
            support = sum(1 for corner, others in readings.items()
                          if any(agrees(k, predicted[corner] + offset)
                                 for k in others[axis]["km"]))
            # A tie goes to the candidate that leaves the label-voted anchor
            # where it is, then to the reading more passes produced.
            agrees_with_labels = int(abs(kilometre * 1000 + 500
                                         - stored[source]) < 1000)
            weight = sum(1 for k in values[axis]["km"] if k == kilometre)
            score = (support, agrees_with_labels, weight)
            if best is None or score > best["score"]:
                best = {"score": score, "kilometre": kilometre,
                        "source": source, "support": support}
    if best is None:
        return {}

    # With the kilometre settled, take the metre part from whichever corners
    # read one consistent with it - at most one value per corner, so that four
    # OCR passes over the same printing cannot look like four corners agreeing.
    offset = best["kilometre"] * 1000 + 500 - predicted[best["source"]]
    exact = {}
    for corner, others in readings.items():
        target = predicted[corner] + offset
        near = [v for v in others[axis]["metres"]
                if abs(v - target) <= 500 + CORROBORATION_M]
        if near:
            exact[corner] = max(set(near), key=near.count)
    best["exact"] = exact
    return best


def measure(path: Path, sheet: dict) -> dict:
    """Read one sheet's corners and say what they imply for its anchor."""
    frame = sheet["neatline_px"]
    corner_pixels = {
        "north_west": (frame["left"], frame["top"]),
        "north_east": (frame["right"], frame["top"]),
        "south_west": (frame["left"], frame["bottom"]),
        "south_east": (frame["right"], frame["bottom"]),
    }
    # The linear part of the stored transform: scale, rotation and skew, all of
    # it from the printed grid spacing. Only the translation is at issue here.
    a, d, b, e, _, _ = sheet["affine"]
    linear = np.array([[a, d], [b, e]])

    image = Image.open(path).convert("RGB")
    readings = read_windows(image, frame)

    outcome: dict = {"corner_readings": readings}
    for axis, key in (("easting", "e"), ("northing", "n")):
        column = 0 if axis == "easting" else 1
        translation = sheet["affine"][4 if column == 0 else 5]
        stored = {corner: (translation + linear[0, column] * x
                           + linear[1, column] * y)
                  for corner, (x, y) in corner_pixels.items()}
        found = resolve(readings, linear, corner_pixels, axis, stored)
        outcome[f"corner_support_{key}"] = found.get("support", 0)
        if not found or found["support"] < MIN_SUPPORT:
            continue

        def stored_at(corner: str, stored: dict = stored) -> float:
            return stored[corner]

        # What the sheet says its corner is, against what the transform says.
        # An anchor can only be a whole kilometre out, so the difference is
        # split: the whole kilometres are the anchor's error, the remainder is
        # the frame's, and folding the remainder into the anchor would smear a
        # known error into the one quantity that was exact.
        #
        # Where a metre-precise reading survived, it is what the difference is
        # measured from. Standing in a kilometre reading as its own midpoint
        # instead costs up to half a kilometre of bias, and that is enough to
        # flip the rounding: La Marsa's north-east corner sits at .774 of its
        # kilometre, and assuming .500 turned a frame 443 m out into an anchor
        # reported as a kilometre out.
        exact = found["exact"]
        if exact:
            differences = [value - stored_at(corner)
                           for corner, value in exact.items()]
            basis = "printed_metres"
        else:
            differences = [found["kilometre"] * 1000 + 500
                           - stored_at(found["source"])]
            basis = "printed_kilometre"
        shift = int(round(float(np.median(differences)) / 1000.0))

        outcome[f"corner_{axis}_km"] = found["kilometre"]
        outcome[f"corner_source_{key}"] = found["source"]
        outcome[f"origin_shift_km_{key}"] = shift
        outcome[f"shift_basis_{key}"] = basis
        if exact:
            outcome[f"corner_{axis}_m"] = exact.get(found["source"],
                                                    next(iter(exact.values())))
            outcome[f"corner_exact_count_{key}"] = len(exact)
            outcome[f"neatline_error_m_{key}"] = round(
                float(np.median([d - shift * 1000.0 for d in differences])), 1)
    return outcome


FIELDS = ["record_id", "sheet_name",
          "corner_easting_km", "corner_northing_km",
          "corner_easting_m", "corner_northing_m",
          "corner_source_e", "corner_source_n",
          "corner_support_e", "corner_support_n",
          "corner_exact_count_e", "corner_exact_count_n",
          "shift_basis_e", "shift_basis_n",
          "origin_shift_km_e", "origin_shift_km_n",
          "neatline_error_m_e", "neatline_error_m_n"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--georef", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.json")
    parser.add_argument("--table", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.csv")
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "data" / "sheet_corners.json")
    parser.add_argument("--csv", type=Path,
                        default=REPO_ROOT / "data" / "sheet_corners.csv")
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()

    georef = json.loads(args.georef.read_text(encoding="utf-8"))
    names = {row["record_id"]: row["sheet_name"]
             for row in csv.DictReader(args.table.open(encoding="utf-8"))}

    results: dict[str, dict] = {}
    if args.out.exists():
        results = json.loads(args.out.read_text(encoding="utf-8"))

    targets = [r for r in georef if "affine" in georef[r]]
    if args.only:
        targets = [r for r in targets if r in args.only]

    for index, record_id in enumerate(targets, start=1):
        path = args.images / f"{record_id}.jpg"
        if not path.exists():
            continue
        outcome = measure(path, georef[record_id])
        results[record_id] = outcome
        shifts = (outcome.get("origin_shift_km_e"), outcome.get("origin_shift_km_n"))
        print(f"[{index}/{len(targets)}] {names.get(record_id, record_id)[:24]:24s} "
              f"support={outcome.get('corner_support_e', 0)}/"
              f"{outcome.get('corner_support_n', 0)} "
              f"shift={shifts} "
              f"neatline=({outcome.get('neatline_error_m_e', '')},"
              f"{outcome.get('neatline_error_m_n', '')})m", flush=True)
        args.out.write_text(json.dumps(results, indent=1, ensure_ascii=False),
                            encoding="utf-8")

    with args.csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for record_id, outcome in results.items():
            writer.writerow({
                "record_id": record_id,
                "sheet_name": names.get(record_id, ""),
                **{f: outcome.get(f, "") for f in FIELDS[2:]},
            })
    print(f"\n-> {args.csv}\n-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

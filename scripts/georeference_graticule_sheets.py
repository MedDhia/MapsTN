#!/usr/bin/env python3
"""Georeference the sheets that carry a graticule instead of a Lambert grid.

Eleven of the 96 scans have no printed kilometric grid at all, and no amount of
better detection will find one: four are catalogued 1902, none shows the
"CARROYAGE KILOMETRIQUE LAMBERT" header, and on a sheet that does have a grid the
detected lines come 20 to 32 gaps of one kilometre with a spread of 0-2 px where
on these the spread is 12-120 px with 1 to 8. There is no comb there.

What they carry instead is a graticule graduated in **centesimal grades**, the
longitude counted from the Paris meridian. The 1902 La Marsa sheet labels its top
margin 8g80, then 90, then 9g, then 10 - a step of 0.10 grad - and

    8.80 grad x 0.9 = 7.92 degrees from Paris, + 2.33722917 = 10.2572 E

against 10.2562 for the north-west corner of the 1932 sheet covering the same
ground, which is 90 m. That agreement, found before any code was written, is what
established the reading.

The absolute placement does not come from those labels, and that is a change of
plan worth recording because the first design turned on them. The step is exactly
0.10 grad, so a lattice fitted to the detected lines fixes every *relative*
index and leaves one unknown per axis - the grade of index zero. Three sources
were tried for that one number, in this order.

  The catalogue box. It settles the same question for the Lambert sheets and it
  cannot settle this one: these particular records carry the worst boxes in the
  collection, the 1902 Tunis sheet's some 25 km out in latitude against a
  10 km step.

  The printed labels. They are legible and they do get read - the longitude
  labels corroborate the final answer on four to six lines of five of the eight
  placed sheets - but they are sparse, come in three forms, and letting a single
  misread one outvote everything else put five sheets between 10 and 34 km wrong
  while every internal fit still read under 15 m rms. The latitude labels are
  not read at all.

  The sheet of the same designation. Eight of these eleven sheets are earlier
  editions of ground the Lambert path has already placed from its own printed
  grid, to about 70 m. Against a step of 8 to 10 km that is a margin of a hundred
  to one, and it never has to be right about anything finer. This is what places
  them, and the printed labels are reported as a check on the result rather than
  used to produce it.

So the graticule supplies this scan's own geometry - its scale, rotation and
skew, which nothing else can - while the series supplies where that geometry
sits. Two sheets have no such twin and rest on their own catalogue box; they are
flagged and should be treated as unplaced until checked.

Two things make the lines findable where a first attempt failed.

  They are faint and coloured. A thin blue-grey line over the sea tint does not
  cross any absolute threshold that keeps the rest of the sheet out. What finds
  it is a local-contrast filter - how much darker a pixel is than the median of
  its neighbours *across* the line direction - which responds to a thin dark
  feature at any background level and ignores broad ones.

  They are oblique to the sheet. The first search covered +/-2 degrees, on the
  assumption that a graticule-cut sheet has its meridians parallel to its frame.
  These sheets are not graticule-cut: the lines run about +4.25 and -4.50 degrees
  to the neatline, which is the same angle the Lambert grid takes on the later
  sheets of the same series.

The angle is chosen by autocorrelation of the projection at the spacing the
catalogue and the frame predict, rather than by peak height. With only four
longitude lines and two or three latitude lines on a sheet, height picks the
neatline or a long road; periodicity at a known lag picks the graticule.

What it achieves, and the caution that goes with it. Eight of the eleven sheets
are placed; six of those can be compared corner to corner with the sheet of the
same designation, and come out at a **median of 549 m and a worst case of
1085 m**. That is usable and it is about twenty-five times coarser than the
Lambert path, which fits its own grid to 17 m rms and agrees with its neighbours'
printed corners to 72 m. Every placed sheet carries
`precision_class = "graticule_coarse"` so that nothing mixes the two by accident.

Two things account for the difference. Four longitude lines crossing two latitude
lines give eight control points for a six-parameter affine, so there is very
little redundancy and the residual of the fit says little - Halk El Mennzel fits
to 10.7 m and still sits 1085 m from its twin. And latitude is the weak axis
throughout: two lines rather than four, no label agreement on any sheet, and its
scale therefore resting on a single 10 km baseline.

Three sheets are not placed at all. El Ariana, Enfida and the 1946 untitled sheet
show latitude autocorrelation of 0.11 to 0.14 against a 0.15 floor - too few
latitude lines survive the ridge filter to establish a spacing.

Outputs:
    data/sheet_graticule.json   lines, grades, fit and the twin comparison
    data/sheet_graticule.csv
    and, with --write-georef, the same transform records the Lambert path
    produces, merged into data/sheet_georef.{json,csv}

Usage:
    python3 scripts/georeference_graticule_sheets.py --images <dir>
    python3 scripts/georeference_graticule_sheets.py --images <dir> --only <id>
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image, ImageOps
from pyproj import Transformer
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from georeference_sheets import (  # noqa: E402
    ZONE_EPSG, apply_affine, find_neatline, fit_affine, write_sidecars,
)

Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent

# Paris meridian, the origin French military sheets count longitude from.
PARIS_MERIDIAN_EAST = 2.33722917
GRADES_TO_DEGREES = 0.9
GRATICULE_STEP_GRAD = 0.10

DOWNSAMPLE = 2
RIDGE_WIDTH = 15         # median taken across the line, at DOWNSAMPLE
FRAME_INSET_PX = 120     # keep the neatline and its graduation out of the body
ANGLES = np.arange(-6.0, 6.01, 0.25)
REFINE_STEP = 0.05
LAG_WINDOW = (0.85, 1.20)   # fraction of the predicted spacing to search
PEAK_SIGMA = 2.5
MIN_PEAK_SEPARATION_PX = 400
# How far off its nominal place a detected line may sit and still count as part
# of the lattice, as a fraction of the step. It has to be small. At 0.30 - a
# quarter of a kilometre either way on an eight kilometre step - the fit happily
# accepted four "lines" at 1212, 3670, 5534 and 7118 px, whose gaps are 2458,
# 1864 and 1584, and reported them as a lattice with quarter-kilometre
# residuals. A printed graticule line found by projection sits within tens of
# pixels of where the others put it, or it is not one of them.
MAX_LINE_OFFSET = 0.06
MIN_LINES = 2
MIN_AUTOCORRELATION = 0.15

# Metres per degree, near enough over a 30 km sheet for predicting a spacing.
METRES_PER_DEGREE_LAT = 110_900.0
METRES_PER_DEGREE_LON = 111_320.0


def ridge(image: np.ndarray, axis: int) -> np.ndarray:
    """How much darker each pixel is than its neighbours across the line.

    A thin dark line on any background survives this; a broad tint does not.
    The graticule on these sheets is a one-pixel blue-grey rule drawn over a pale
    sea wash, and no absolute threshold separates it from the rest of the sheet.
    """
    size = (1, RIDGE_WIDTH) if axis == 0 else (RIDGE_WIDTH, 1)
    return np.clip(ndimage.median_filter(image, size=size) - image, 0, None)


def project(image: np.ndarray, axis: int, angle: float) -> np.ndarray:
    """Sum along one axis after shearing, so tilted lines stack up."""
    height, width = image.shape
    tangent = math.tan(math.radians(angle))
    if axis == 0:
        shifts = (np.arange(height) * tangent).round().astype(int)
        accumulator = np.zeros(width)
        for row in range(height):
            accumulator += np.roll(image[row], -shifts[row])
    else:
        shifts = (np.arange(width) * tangent).round().astype(int)
        accumulator = np.zeros(height)
        for column in range(width):
            accumulator += np.roll(image[:, column], -shifts[column])
    return accumulator


def detrend(accumulator: np.ndarray) -> np.ndarray:
    window = 121
    return accumulator - np.convolve(accumulator, np.ones(window) / window, "same")


def periodicity(sharp: np.ndarray, expected_lag: float) -> tuple[float, int]:
    """Strength and lag of the best periodicity near the expected spacing."""
    centred = sharp - sharp.mean()
    correlation = np.correlate(centred, centred, "full")[len(centred) - 1:]
    if correlation[0] <= 0:
        return 0.0, 0
    correlation = correlation / correlation[0]
    low = int(expected_lag * LAG_WINDOW[0])
    high = min(int(expected_lag * LAG_WINDOW[1]), len(correlation) - 1)
    if high <= low:
        return 0.0, 0
    index = low + int(np.argmax(correlation[low:high]))
    return float(correlation[index]), index


def peaks(sharp: np.ndarray) -> list[int]:
    threshold = sharp.std() * PEAK_SIGMA
    separation = MIN_PEAK_SEPARATION_PX // DOWNSAMPLE
    found: list[int] = []
    for index in range(1, len(sharp) - 1):
        if (sharp[index] > threshold and sharp[index] >= sharp[index - 1]
                and sharp[index] >= sharp[index + 1]):
            if not found or index - found[-1] > separation:
                found.append(index)
            elif sharp[index] > sharp[found[-1]]:
                found[-1] = index
    return found


def lattice(positions: list[int], spacing: float) -> tuple[list[tuple[int, int]], float]:
    """Fit an evenly spaced lattice to the detected positions.

    Returns the inliers as (index, position) and the refined spacing. Fitting a
    lattice rather than accepting the peaks as they come does two jobs at once.
    It drops whatever the ridge filter found that is not a graticule line - a
    long road, a boundary, the edge of a wash - and it fixes the *relative*
    index of every line it keeps, which is what makes the grades internally
    consistent.

    That consistency is the point. Rounding each line's grade independently from
    the catalogue box put two adjacent latitude lines on the Tunis sheet two
    steps apart instead of one, because the box is some five kilometres out in
    latitude there and the step is nine. The lattice cannot express that: it
    leaves exactly one unknown per axis, the grade of index zero, and only that
    one number has to be got right from elsewhere.
    """
    if len(positions) < 2:
        return [(0, p) for p in positions], spacing
    best = None
    for reference in positions:
        for scale in np.arange(0.94, 1.061, 0.005):
            step = spacing * scale
            kept, offsets = [], []
            for position in positions:
                offset = (position - reference) / step
                index = round(offset)
                if abs(offset - index) <= MAX_LINE_OFFSET:
                    kept.append((int(index), position))
                    offsets.append(abs(offset - index))
            score = (len(kept), -float(np.mean(offsets)) if offsets else 0.0)
            if best is None or score > best[0]:
                best = (score, kept, step)
    _, kept, step = best
    kept.sort()
    if len(kept) >= 2:
        indices = np.array([i for i, _ in kept], float)
        places = np.array([p for _, p in kept], float)
        design = np.column_stack([indices, np.ones(len(indices))])
        solution, *_ = np.linalg.lstsq(design, places, rcond=None)
        if solution[0] > 0:
            step = float(solution[0])
    # One line per index. A spurious peak within a third of a spacing of a real
    # line takes the same index, and then two lines are handed the same grade -
    # which is impossible and wrecked the fit before it was caught. The one
    # nearest its nominal position wins.
    reference = kept[0][1] - kept[0][0] * step
    chosen: dict[int, tuple[float, int]] = {}
    for index, position in kept:
        error = abs(position - (reference + index * step))
        if index not in chosen or error < chosen[index][0]:
            chosen[index] = (error, position)
    base = min(chosen)
    return [(i - base, p) for i, (_, p) in sorted(chosen.items())], step


LABEL_RE = re.compile(r"\d+")
# Along the margin, the grade label sits centred on its tick within about 30 px;
# the kilometre numbers of the graduated scale are 120 px or more away.
LABEL_ALONG = (-140, 140)
# Across it, measured from the inner neatline: the grade label centres about
# 88 px outside, the kilometre numbers about 50, the heavy outer rule about 150.
# The window takes all of that and the reading is filtered afterwards, because a
# window tight enough to exclude the kilometre numbers is only 70 px deep and
# would not survive the frame being detected 30 px out.
LABEL_ACROSS = (-150, -25)
LABEL_UPSCALE = (3, 5)
LABEL_WHITELIST = "-c tessedit_char_whitelist=0123456789"
GLYPH_MIN_PX, GLYPH_MAX_PX = 12, 90
ROW_TOLERANCE_PX = 22
# A candidate has to land this close to where the catalogue puts the line. Wide
# enough that the catalogue's own error never decides anything - the worst box
# seen is 5 km, which is 0.06 grad - and narrow enough to throw out a kilometre
# number misread as a grade, which is wrong by a whole grade or more.
LABEL_CATALOGUE_WINDOW_GRAD = 0.5


def text_rows(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of glyph runs sharing a baseline, top to bottom."""
    labels, count = ndimage.label(mask)
    if not count:
        return []
    glyphs = []
    for slices in ndimage.find_objects(labels):
        y0, y1 = slices[0].start, slices[0].stop
        x0, x1 = slices[1].start, slices[1].stop
        if GLYPH_MIN_PX <= y1 - y0 <= GLYPH_MAX_PX and x1 - x0 <= GLYPH_MAX_PX:
            glyphs.append((x0, y0, x1, y1))
    rows: list[list] = []
    for glyph in sorted(glyphs, key=lambda g: g[1]):
        centre = (glyph[1] + glyph[3]) / 2
        for row in rows:
            if abs(centre - (row[0][1] + row[0][3]) / 2) <= ROW_TOLERANCE_PX:
                row.append(glyph)
                break
        else:
            rows.append([glyph])
    return [(min(g[0] for g in row), min(g[1] for g in row),
             max(g[2] for g in row), max(g[3] for g in row)) for row in rows]


def label_candidates(image: Image.Image, centre: int, frame: dict,
                     axis: int) -> list[float]:
    """Every grade the printing beside one tick could be stating.

    Three forms appear on these sheets and all three are useful:

        "9g"        a whole grade
        "8g 40'"    a whole grade and centesimal minutes
        "50'"       the minutes alone, the grade carried over from the last

    Returned as absolute grades where the whole part was printed, and as a
    fraction below 1 where only the minutes were. Nothing is decided here; the
    caller filters against the catalogue and votes.
    """
    if axis == 0:
        box = (centre + LABEL_ALONG[0], frame["top"] + LABEL_ACROSS[0],
               centre + LABEL_ALONG[1], frame["top"] + LABEL_ACROSS[1])
    else:
        box = (frame["left"] + LABEL_ACROSS[0], centre + LABEL_ALONG[0],
               frame["left"] + LABEL_ACROSS[1], centre + LABEL_ALONG[1])
    box = (max(0, int(box[0])), max(0, int(box[1])),
           min(image.size[0], int(box[2])), min(image.size[1], int(box[3])))
    if box[2] - box[0] < 20 or box[3] - box[1] < 20:
        return []

    crop = image.crop(box).convert("L")
    if axis == 1:
        crop = crop.rotate(-90, expand=True)   # latitude labels read up the sheet
    crop = ImageOps.autocontrast(crop)
    array = np.asarray(crop)
    mask = array < (int(array.mean()) - 25)

    values = []
    for x0, y0, x1, y1 in text_rows(mask):
        row = crop.crop((max(0, x0 - 8), max(0, y0 - 8), x1 + 8, y1 + 8))
        for upscale in LABEL_UPSCALE:
            scaled = row.resize((row.width * upscale, row.height * upscale),
                                Image.LANCZOS)
            text = pytesseract.image_to_string(
                scaled, config=f"--psm 7 {LABEL_WHITELIST}")
            values += interpret_label(LABEL_RE.findall(text))
    return values


def interpret_label(groups: list[str]) -> list[float]:
    """The centesimal minutes a set of digit groups could mean, or [].

    Only the minutes are taken, never the whole grade, and only minutes that are
    a multiple of ten. The graticule steps by 0.10 grad, so every printed label
    is 10, 20, ... 90 or a bare whole grade, and requiring that throws out most
    misreads for free - it is what stops a stray "06" from placing the Tunis
    sheet 26 km out. The whole grade is left to the caller, which is a far easier
    question: it changes once every ten steps, so ninety kilometres of slack.
    """
    numbers = [g for g in groups if 1 <= len(g) <= 2]
    if not numbers:
        return []
    candidates = []
    for number in numbers:
        if len(number) == 2 and int(number) % 10 == 0 and int(number) > 0:
            candidates.append(int(number) / 100.0)
        elif len(number) == 1:
            # A bare whole grade - "9g" - which is to say zero minutes.
            candidates.append(0.0)
    return candidates


def measure_axis(body: np.ndarray, axis: int, expected_lag: float) -> dict:
    """The graticule lines of one family: angle, spacing and line constants."""
    # Once, not once per angle: the ridge filter is a median over a 15-pixel
    # window of a seven-megapixel array and does not depend on the shear.
    ridged = ridge(body, axis)

    def scored(angle: float) -> dict:
        sharp = detrend(project(ridged, axis, angle))
        strength, lag = periodicity(sharp, expected_lag)
        return {"strength": strength, "angle": angle, "lag": lag,
                "sharp": sharp}

    best = None
    for angle in ANGLES:
        candidate = scored(float(angle))
        if best is None or candidate["strength"] > best["strength"]:
            best = candidate
    for angle in np.arange(best["angle"] - 0.20, best["angle"] + 0.201,
                           REFINE_STEP):
        candidate = scored(float(angle))
        if candidate["strength"] > best["strength"]:
            best = candidate

    positions = peaks(best["sharp"])
    indexed, step = lattice(positions, best["lag"] or 1.0)
    return {"angle_deg": round(best["angle"], 2),
            "autocorrelation": round(best["strength"], 3),
            "spacing_px": round(step * DOWNSAMPLE, 1),
            "peaks_found": len(positions),
            "lines": len(indexed),
            "indices": [i for i, _ in indexed],
            "positions_px": [int(p) * DOWNSAMPLE for _, p in indexed]}


def body_and_offsets(path: Path, frame: dict):
    image = Image.open(path).convert("RGB")
    width, height = image.size
    grey = np.asarray(image.resize((width // DOWNSAMPLE, height // DOWNSAMPLE),
                                   Image.BILINEAR)).astype(np.float32).mean(axis=2)
    inset = FRAME_INSET_PX // DOWNSAMPLE
    top = frame["top"] // DOWNSAMPLE + inset
    bottom = frame["bottom"] // DOWNSAMPLE - inset
    left = frame["left"] // DOWNSAMPLE + inset
    right = frame["right"] // DOWNSAMPLE - inset
    return grey[top:bottom, left:right], (left * DOWNSAMPLE, top * DOWNSAMPLE)


def line_constants(positions: list[int], angle: float, axis: int,
                   offset: tuple[int, int]) -> tuple[list[float], float]:
    """Positions in full-resolution image coordinates, as line constants.

    Same convention as the Lambert path: u = x - tan(a)*y is constant along a
    longitude line, v = y - tan(b)*x along a latitude line.
    """
    tangent = math.tan(math.radians(angle))
    column_offset, row_offset = offset
    if axis == 0:
        return [p + column_offset - row_offset * tangent
                for p in positions], tangent
    return [p + row_offset - column_offset * tangent
            for p in positions], tangent


def catalogue_grade(constant: float, tangent: float, axis: int,
                    frame: dict, box: dict) -> float:
    """Roughly what grade a line is, from a lon/lat box across the frame.

    The box may be the sheet's catalogue extent or, far better, the extent of
    the sheet of the same designation that the Lambert path already placed. All
    that is asked of it is which whole 0.10 grad a line is, where the lines are
    8 to 10 km apart - so a reference good to a few hundred metres decides it
    with a margin of twenty to one, and one good to 20 km decides nothing.
    """
    centre_x = (frame["left"] + frame["right"]) / 2
    centre_y = (frame["top"] + frame["bottom"]) / 2
    if axis == 0:
        x = constant + tangent * centre_y
        fraction = (x - frame["left"]) / (frame["right"] - frame["left"])
        degrees = box["west"] + fraction * (box["east"] - box["west"])
        return (degrees - PARIS_MERIDIAN_EAST) / GRADES_TO_DEGREES
    y = constant + tangent * centre_x
    fraction = (y - frame["top"]) / (frame["bottom"] - frame["top"])
    degrees = box["north"] + fraction * (box["south"] - box["north"])
    return degrees / GRADES_TO_DEGREES


def resolve_grades(image: Image.Image, frame: dict, axis: int,
                   indices: list[int], constants: list[float],
                   tangent: float, box: dict) -> tuple[list[float], str, int]:
    """Give every detected line its grade, from the labels the sheet prints.

    The lattice has already fixed the differences: line of index k is
    `base + k * 0.10` grad for one unknown base per axis. So a single label read
    anywhere along the margin places the whole family, and every further label is
    a vote on the same number.

    Latitude ascends up the sheet while pixel rows descend, so the sign is
    opposite there - worth stating because getting it wrong yields a sheet that
    is plausibly placed and mirrored.
    """
    sign = 1 if axis == 0 else -1
    # Where the line meets the margin the label is printed in, not where it
    # crosses the middle of the sheet. The lines run four degrees off the frame,
    # so over half a sheet height that is 179 px - wider than the window.
    centre_across = frame["top"] if axis == 0 else frame["left"]

    # The reference places the lines; the printed labels check the result. That
    # order is the opposite of the one tried first, and the reason is how good
    # each source turned out to be. A sheet of the same designation, already
    # placed from its own Lambert grid, locates a line to about 100 m against a
    # step of 8 to 10 km - a margin of a hundred to one, so its verdict is never
    # in doubt. The labels are four or five sparse annotations per sheet in three
    # different forms, and letting a single misread one outvote the reference put
    # five sheets between 10 and 34 km wrong while every internal fit still came
    # out under 15 m rms. Agreement is reported as `label_agreement`.
    rough_base = (catalogue_grade(constants[0], tangent, axis, frame, box)
                  - sign * indices[0] * GRATICULE_STEP_GRAD)
    base = round(rough_base / GRATICULE_STEP_GRAD) * GRATICULE_STEP_GRAD

    agreement = 0
    for index, constant in zip(indices, constants):
        centre = constant + tangent * centre_across
        expected = base + sign * index * GRATICULE_STEP_GRAD
        wanted = round(expected - math.floor(expected), 2)
        for minutes in label_candidates(image, int(centre), frame, axis):
            if abs(minutes - wanted) < 0.005 or (wanted == 0.0
                                                 and minutes == 0.0):
                agreement += 1
    basis, support = "reference_extent", agreement

    grades = [round(base + sign * index * GRATICULE_STEP_GRAD, 3)
              for index in indices]
    return grades, basis, support


def to_degrees(grade: float, axis: int) -> float:
    if axis == 0:
        return grade * GRADES_TO_DEGREES + PARIS_MERIDIAN_EAST
    return grade * GRADES_TO_DEGREES


def intersections(longitudes, latitudes, tan_lon, tan_lat):
    determinant = 1.0 - tan_lon * tan_lat
    points = []
    for u, lon_grade in longitudes:
        for v, lat_grade in latitudes:
            x = (u + tan_lon * v) / determinant
            y = (v + tan_lat * u) / determinant
            points.append((x, y, lon_grade, lat_grade))
    return points


def georeference(path: Path, box: dict, zone: str,
                 reference: dict | None = None) -> dict:
    """Place one graticule sheet.

    `box` sizes the search - it only has to be roughly the sheet's extent to
    predict a line spacing. `reference` is what settles the absolute grade of
    each line, and the two are kept separate on purpose, because the catalogue
    boxes on these particular records are the worst in the collection: the 1902
    Tunis sheet's is some 25 km out in latitude, which is a quarter of a
    graticule step short of useless. Where a sheet of the same designation has
    already been placed from its own Lambert grid, its extent is the reference
    instead, and it is good to about 100 m against an 8 km step.
    """
    frame = find_neatline(path)
    if not frame:
        return {"error": "neatline not found"}

    centre_latitude = (box["north"] + box["south"]) / 2
    width_km = ((box["east"] - box["west"]) * METRES_PER_DEGREE_LON
                * math.cos(math.radians(centre_latitude)) / 1000)
    px_per_km = (frame["right"] - frame["left"]) / max(width_km, 1e-6)
    step_lon_px = (GRATICULE_STEP_GRAD * GRADES_TO_DEGREES
                   * METRES_PER_DEGREE_LON
                   * math.cos(math.radians(centre_latitude)) / 1000 * px_per_km)
    step_lat_px = (GRATICULE_STEP_GRAD * GRADES_TO_DEGREES
                   * METRES_PER_DEGREE_LAT / 1000 * px_per_km)

    body, offset = body_and_offsets(path, frame)
    longitude = measure_axis(body, 0, step_lon_px / DOWNSAMPLE)
    latitude = measure_axis(body, 1, step_lat_px / DOWNSAMPLE)

    outcome = {"neatline_px": frame,
               "px_per_km_from_catalogue": round(px_per_km, 1),
               "predicted_spacing_px": {"longitude": round(step_lon_px),
                                        "latitude": round(step_lat_px)},
               "longitude": {k: v for k, v in longitude.items()
                             if k != "positions_px"},
               "latitude": {k: v for k, v in latitude.items()
                            if k != "positions_px"}}

    if min(longitude["autocorrelation"],
           latitude["autocorrelation"]) < MIN_AUTOCORRELATION:
        outcome["error"] = "no periodic graticule found"
        return outcome
    if longitude["lines"] < MIN_LINES or latitude["lines"] < MIN_LINES:
        outcome["error"] = "too few graticule lines"
        return outcome

    lon_constants, tan_lon = line_constants(
        longitude["positions_px"], longitude["angle_deg"], 0, offset)
    lat_constants, tan_lat = line_constants(
        latitude["positions_px"], latitude["angle_deg"], 1, offset)

    image = Image.open(path).convert("RGB")
    anchor_box = reference or box
    lon_grades, lon_basis, lon_support = resolve_grades(
        image, frame, 0, longitude["indices"], lon_constants, tan_lon,
        anchor_box)
    lat_grades, lat_basis, lat_support = resolve_grades(
        image, frame, 1, latitude["indices"], lat_constants, tan_lat,
        anchor_box)
    outcome["grade_reference"] = "same_designation_sheet" if reference else "catalogue"
    outcome["grade_basis"] = {"longitude": lon_basis, "latitude": lat_basis}
    outcome["label_agreement"] = {"longitude": lon_support,
                                  "latitude": lat_support}

    lon_pairs = sorted(zip(lon_grades, lon_constants))
    lat_pairs = sorted(zip(lat_grades, lat_constants))

    points = intersections([(c, g) for g, c in lon_pairs],
                           [(c, g) for g, c in lat_pairs], tan_lon, tan_lat)
    to_lambert = Transformer.from_crs("EPSG:4326", f"EPSG:{ZONE_EPSG[zone]}",
                                      always_xy=True)
    pixels = np.array([(x, y) for x, y, _, _ in points], float)
    world = np.array([to_lambert.transform(to_degrees(lon_grade, 0),
                                           to_degrees(lat_grade, 1))
                      for _, _, lon_grade, lat_grade in points], float)
    solution, residuals = fit_affine(pixels, world)

    to_wgs84 = Transformer.from_crs(f"EPSG:{ZONE_EPSG[zone]}", "EPSG:4326",
                                    always_xy=True)
    corners = {}
    for name, (x, y) in {
        "north_west": (frame["left"], frame["top"]),
        "north_east": (frame["right"], frame["top"]),
        "south_west": (frame["left"], frame["bottom"]),
        "south_east": (frame["right"], frame["bottom"]),
    }.items():
        easting, northing = apply_affine(solution, x, y)
        lon, lat = to_wgs84.transform(easting, northing)
        corners[name] = {"lon": round(lon, 6), "lat": round(lat, 6),
                         "easting": round(easting, 1),
                         "northing": round(northing, 1)}

    outcome.update({
        "lambert_zone": zone,
        "epsg": ZONE_EPSG[zone],
        "graticule": {
            "tan_lon": round(tan_lon, 6),
            "tan_lat": round(tan_lat, 6),
            "longitude_grades": [g for g, _ in lon_pairs],
            "latitude_grades": [g for g, _ in lat_pairs],
        },
        "control_points": len(points),
        "affine": [round(float(v), 6) for v in
                   (solution[0, 0], solution[0, 1], solution[1, 0],
                    solution[1, 1], solution[2, 0], solution[2, 1])],
        "residual_rms_m": round(float(np.sqrt((residuals ** 2).mean())), 2),
        "residual_max_m": round(float(residuals.max()), 2),
        "degrees_of_freedom": len(points) * 2 - 6,
        # These transforms are about twenty-five times coarser than the ones the
        # Lambert grid gives, and the flag is here so nothing mixes them by
        # accident. Measured against the sheet of the same designation: median
        # 549 m, worst 1085 m, where the Lambert path fits its own grid to 17 m
        # rms and agrees with its neighbours' printed corners to 72 m.
        "precision_class": "graticule_coarse",
        "corners": corners,
    })
    return outcome


def twin_offset(outcome: dict, twin: dict) -> dict:
    """Corner-to-corner distance against the sheet of the same designation.

    The external check, and the one to judge this by: the two editions were
    printed thirty years apart and georeferenced from different printing - a
    graticule in grades here, a Lambert kilometric grid there - so agreement
    between them is not something either method could have arranged.
    """
    distances = []
    for name, corner in outcome["corners"].items():
        other = twin["corners"].get(name)
        if not other:
            continue
        distances.append(math.hypot(corner["easting"] - other["easting"],
                                     corner["northing"] - other["northing"]))
    if not distances:
        return {}
    return {"twin_offset_m": round(float(np.median(distances)), 1),
            "twin_offset_max_m": round(float(max(distances)), 1)}


FIELDS = ["record_id", "designation", "sheet_name", "lambert_zone",
          "lon_angle_deg", "lat_angle_deg", "lon_autocorrelation",
          "lat_autocorrelation", "lon_lines", "lat_lines",
          "lon_label_agreement", "lat_label_agreement",
          "lon_spacing_px", "lon_spacing_predicted_px",
          "lat_spacing_px", "lat_spacing_predicted_px",
          "control_points", "degrees_of_freedom",
          "residual_rms_m", "residual_max_m",
          "twin_record_id", "twin_offset_m", "twin_offset_max_m", "error"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--georef", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.json")
    parser.add_argument("--georef-csv", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.csv")
    parser.add_argument("--partner", type=Path,
                        default=REPO_ROOT / "data" / "partner_records.json")
    parser.add_argument("--grid", type=Path,
                        default=REPO_ROOT / "data" / "sheet_grid.csv")
    parser.add_argument("--out-json", type=Path,
                        default=REPO_ROOT / "data" / "sheet_graticule.json")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "sheet_graticule.csv")
    parser.add_argument("--sidecars", type=Path,
                        default=REPO_ROOT / "data" / "georef_graticule")
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()

    georef = json.loads(args.georef.read_text(encoding="utf-8"))
    partner = json.loads(args.partner.read_text(encoding="utf-8"))
    sheets = {row["record_id"]: row for row in
              csv.DictReader(args.georef_csv.open(encoding="utf-8"))}
    zones = {row["record_id"]: row["lambert_zone"] for row in
             csv.DictReader(args.grid.open(encoding="utf-8"))}

    # A sheet of the same designation that the Lambert path already placed, and
    # placed properly: a provisional transform has corners like any other and no
    # position at all, its translation still zero. Referencing one put the La
    # Goulette sheet 17 km out while its own internal fit read 6.8 m.
    twins: dict[str, str] = {}
    for record_id, row in sheets.items():
        record = georef.get(record_id, {})
        if (row["designation"] and "corners" in record
                and not record.get("anchor_provisional")
                and record.get("anchor_confident")):
            twins.setdefault(row["designation"], record_id)

    targets = [r for r in georef
               if georef[r].get("error") == "no kilometric grid"]
    if args.only:
        targets = [r for r in targets if r in args.only]

    results: dict = {}
    if args.out_json.exists():
        results = json.loads(args.out_json.read_text(encoding="utf-8"))

    for index, record_id in enumerate(sorted(targets), start=1):
        path = args.images / f"{record_id}.jpg"
        row = sheets.get(record_id, {})
        name = row.get("sheet_name") or record_id[-6:]
        box = partner.get(record_id, {}).get("bbox")
        zone = zones.get(record_id)
        if not path.exists():
            continue
        designation = row.get("designation") or ""
        if zone not in ZONE_EPSG and twins.get(designation):
            zone = georef[twins[designation]].get("lambert_zone")
        if not box and not twins.get(designation):
            results[record_id] = {"error": "no extent to reference"}
        elif zone not in ZONE_EPSG:
            # Latitude decides it, and these sheets are all far from the
            # 34.4-34.9 band where that is ambiguous.
            results[record_id] = {"error": f"no Lambert zone ({zone or 'unset'})"}
        else:
            twin = twins.get(row.get("designation") or "")
            if twin == record_id:
                twin = None
            reference = None
            if twin:
                corners = georef[twin]["corners"].values()
                reference = {
                    "west": min(c["lon"] for c in corners),
                    "east": max(c["lon"] for c in corners),
                    "south": min(c["lat"] for c in corners),
                    "north": max(c["lat"] for c in corners),
                }
            outcome = georeference(path, box or reference, zone, reference)
            if twin and "corners" in outcome:
                outcome["twin_record_id"] = twin
                outcome.update(twin_offset(outcome, georef[twin]))
            results[record_id] = outcome
            if "affine" in outcome:
                write_sidecars(args.sidecars, record_id, outcome, path)

        outcome = results[record_id]
        if "error" in outcome and "affine" not in outcome:
            detail = ""
            if "longitude" in outcome:
                detail = (f" (autocorr "
                          f"{outcome['longitude']['autocorrelation']}/"
                          f"{outcome['latitude']['autocorrelation']}, lines "
                          f"{outcome['longitude']['lines']}/"
                          f"{outcome['latitude']['lines']})")
            print(f"  {index}/{len(targets)} {name[:22]:<22} - "
                  f"{outcome['error']}{detail}", flush=True)
        else:
            print(f"  {index}/{len(targets)} {name[:22]:<22} "
                  f"angles=({outcome['longitude']['angle_deg']:+.2f},"
                  f"{outcome['latitude']['angle_deg']:+.2f}) "
                  f"lines={outcome['longitude']['lines']}/"
                  f"{outcome['latitude']['lines']} "
                  f"rms={outcome['residual_rms_m']}m "
                  f"twin={outcome.get('twin_offset_m', '-')}m", flush=True)
        args.out_json.write_text(json.dumps(results, ensure_ascii=False,
                                            indent=2), encoding="utf-8")

    rows = []
    for record_id, outcome in sorted(results.items()):
        row = sheets.get(record_id, {})
        rows.append({
            "record_id": record_id,
            "designation": row.get("designation", ""),
            "sheet_name": row.get("sheet_name", ""),
            "lambert_zone": outcome.get("lambert_zone", ""),
            "lon_angle_deg": outcome.get("longitude", {}).get("angle_deg", ""),
            "lat_angle_deg": outcome.get("latitude", {}).get("angle_deg", ""),
            "lon_autocorrelation":
                outcome.get("longitude", {}).get("autocorrelation", ""),
            "lat_autocorrelation":
                outcome.get("latitude", {}).get("autocorrelation", ""),
            "lon_label_agreement":
                outcome.get("label_agreement", {}).get("longitude", ""),
            "lat_label_agreement":
                outcome.get("label_agreement", {}).get("latitude", ""),
            "lon_lines": outcome.get("longitude", {}).get("lines", ""),
            "lat_lines": outcome.get("latitude", {}).get("lines", ""),
            "lon_spacing_px": outcome.get("longitude", {}).get("spacing_px", ""),
            "lon_spacing_predicted_px":
                outcome.get("predicted_spacing_px", {}).get("longitude", ""),
            "lat_spacing_px": outcome.get("latitude", {}).get("spacing_px", ""),
            "lat_spacing_predicted_px":
                outcome.get("predicted_spacing_px", {}).get("latitude", ""),
            "control_points": outcome.get("control_points", ""),
            "degrees_of_freedom": outcome.get("degrees_of_freedom", ""),
            "residual_rms_m": outcome.get("residual_rms_m", ""),
            "residual_max_m": outcome.get("residual_max_m", ""),
            "twin_record_id": outcome.get("twin_record_id", ""),
            "twin_offset_m": outcome.get("twin_offset_m", ""),
            "twin_offset_max_m": outcome.get("twin_offset_max_m", ""),
            "error": outcome.get("error", ""),
        })
    with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    placed = [r for r in rows if r["residual_rms_m"] != ""]
    print(f"\n{len(rows)} graticule sheets: {len(placed)} placed")
    checked = [r for r in placed if r["twin_offset_m"] != ""]
    if checked:
        offsets = [float(r["twin_offset_m"]) for r in checked]
        print(f"  against the sheet of the same designation, on {len(checked)}: "
              f"median {np.median(offsets):.0f} m, max {max(offsets):.0f} m")
    print(f"  -> {args.out_json}\n  -> {args.out_csv}\n  -> {args.sidecars}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

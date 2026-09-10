#!/usr/bin/env python3
"""Separate the sheet into its printing plates, and survey what each one holds.

**This corrects the approach the earlier symbol work took, and the correction is
the point.** Everything before this separated features with hand-set
inequalities on raw RGB - `(r - g > 45) & (r - b > 40) & (r > 110)` for the red
plate - and then hunted symbols inside the result with fixed-size templates and
patched thresholds. That reached 40% precision on the koubba and 0% on the
trigonometric point, and each round of patching found a new confusable.

The mistake was skipping the physics. These are lithographic sheets printed from
a few ink plates. A scanned pixel is paper seen through some amount of one ink,
and by Beer-Lambert reflectances multiply while **optical densities add**:

    D = -log10(I / I_paper)     is linear in how much ink was laid down.

So an ink is a *direction* in density space and the amount laid down is the
length along it. Separating the plates is a question about direction, which raw
RGB thresholds answer only by accident.

**Why this is a classification and not an unmixing.** The first attempt solved
for the amount of every ink at every pixel by least squares. That is
underdetermined - RGB gives three numbers and this series uses six inks - and
`lstsq` returns a minimum-norm answer that smears the plates into each other:
the blue watercourses came out split between two blue-ish inks and both were
too faint to trace. But the printing is *sparse*. Away from an overprint a pixel
carries one ink over paper. So the well-posed question is not "how much of each"
but "which one, and how much of it", and that is the nearest ink direction by
spectral angle. Same physics, and well-posed.

Well-posed is not the same as answerable, though, and the next section is the
part worth reading: on these scans this separates *two* of the six plates.

**What survived validation, and what did not.** The first version of this
module was written and checked on one 600x400 window of flat desert on
Kasserine, and most of what it claimed did not survive being run on whole
sheets. The claims below are the ones that did, with the measurements that
settle them; the ones that failed are kept here because they are the useful
part.

*Separable, validated at sheet scale:*

  * The **red plate** is clean: 1.14% of the Kasserine map face, and it holds
    the kilometric grid, the maintained roads (as the double lines they are
    printed as) and the settlement clusters, with no relief, no contours and no
    lettering. Red sits 25-30 degrees off every other ink direction, which is
    why it separates when nothing else does. The 1936 legend prints maintained
    roads in red and tracks in black, so this much of the road classification
    does come free.
  * The **blue plate** is legibly the drainage network by eye, but is not a
    traced product: over 85 sheets the linker recovers a median of 8.6% of it
    into runs, against 58% for red. Faint (median 0.60% of the face) and broken.

*Not separable on these scans - the finding that matters most:*

The remaining inks cannot be told apart pixel by pixel, and the reason is the
scans, not the method. These are JPEG **4:2:0** files: chroma is stored at half
resolution, while the strokes are 2 px wide. So a stroke's colour is smeared
over its neighbours and the density directions form a *continuum* rather than
modes - k-means centroids move as k goes from 5 to 8, and restricting to the
darkest stroke cores does not sharpen them but collapses five of six clusters
toward neutral. Any claim to have "measured" five ink directions by clustering,
including the one this module made first, is k-means slicing a continuum.

Concretely wrong, and worth stating plainly:

  * **The black plate is not the road network.** Over the whole Kasserine face
    it is 22.8% of the pixels, because it carries all of the relief hachuring
    in the mountains; in the one flat window originally tested there was no
    relief, so it looked like a clean network of tracks and lettering.
  * **A green ink was missing entirely.** The vegetation wash is about 12% of
    inked pixels and its direction is (0.631, 0.489, 0.603) - roughly 7 degrees
    from black, so adding it does not fix the black plate, it explains it.
  * The **paper white cannot be a single number.** Across one map face it runs
    154 to 230 in red, and paper darkening is near-neutral, so a single bright
    value makes every toned region read as faint black ink.

*What is extractable, then.* Not point symbols: the earlier symbol work only
ever tried those, and they sit at the resolution floor - a 13 px glyph with 1-2
px strokes. The tractable class is the **linear** one, traced off a plate by
`network()` below, and the red plate is where it is cleanest.

Usage:
    python3 scripts/separate_ink_plates.py --images <dir> --survey
    python3 scripts/separate_ink_plates.py --images <dir> --demo <record_id> \\
        --window X0 Y0 X1 Y1
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent

# Unit directions in (R, G, B) optical density, from clustering the directions
# of inked pixels. Only `red` and `blue` are far enough from the rest to be
# real; the other four are where k-means put boundaries in a continuum, and are
# listed so the survey can report them, not because they are four inks.
INK_DIRECTIONS = {
    "black": (0.546, 0.580, 0.602),
    "red": (0.090, 0.657, 0.737),
    "brown": (0.350, 0.620, 0.695),
    "blue": (0.798, 0.525, 0.269),
    "green": (0.631, 0.489, 0.603),
    "wash": (0.681, 0.566, 0.459),
}
# Only two of these six are separable on these scans; see the module docstring
# under "what survived validation". `red` is clean at sheet scale and `blue` is
# usable. The rest are recorded because they are the modes the data shows, not
# because a pixel assigned to one of them is reliably that ink.
SEPARABLE_PLATES = ("red", "blue")
# ...and so these four are reported as one plate wherever a mask is going to be
# used rather than measured. They lie within about 7 degrees of each other, so
# splitting them moves pixels between plates for no reason and actively costs:
# with green split out of black, the spot height 652 in the demo window stops
# reading correctly, because part of the digit went to the other plate.
DARK_PLATES = ("black", "brown", "green", "wash")
PLATE_GROUPS = {"dark": DARK_PLATES, "red": ("red",), "blue": ("blue",)}
# One row per ink, plus the combined dark plate.
ROWS_PER_SHEET = len(INK_DIRECTIONS) + 1
INK_NAMES = list(INK_DIRECTIONS)
_DIRS = np.array([INK_DIRECTIONS[k] for k in INK_NAMES], dtype=np.float32)
_DIRS /= np.linalg.norm(_DIRS, axis=1, keepdims=True)

# Density below this is paper, foxing and scanner noise rather than ink. 0.10 in
# density is about 20% of the way to the darkest ink on these sheets.
INK_FLOOR = 0.10
# The paper is the brightest mode of the scan; a high percentile finds it
# without needing a clean margin, and the 97th rather than the maximum avoids
# the specular blank the scanner leaves outside the sheet.
PAPER_PERCENTILE = 97
# ...but one number for a whole sheet is not enough. Measured on Kasserine, the
# paper white across the map face runs from 154 to 230 in red - toning, foxing
# and the scanner's own falloff - and paper darkening is close to neutral, so
# with a single bright value every toned region reads as faint *black* ink and
# the black plate came out at 30% of the face instead of about 4%. So the
# denominator of the density is a smooth field, estimated on a downscaled copy:
# a high percentile over a window far wider than any map feature is the paper
# showing through, and 41 px at 1/16 scale is 650 px on the sheet.
PAPER_FIELD_DOWNSCALE = 16
PAPER_FIELD_PERCENTILE = 95
PAPER_FIELD_WINDOW = 41
PAPER_FIELD_SMOOTH = 15
# Rows per block when separating a whole scan: the density array is three
# float32 planes, so a 66-megapixel sheet is 800 MB done in one go.
BLOCK_ROWS = 2048

# Dash geometry, measured on the black plate of four sheets rather than chosen:
# a dash is 16-19 px long and 30-80 px in area, and the gap to the next dash in
# the same run is under 20 px (mutual-nearest collinear pairs, median 6-32 px).
# Both numbers matter. A dash is far smaller than any run, so a size filter has
# to be applied to the linked chain and never to the fragment; and a gap of 20
# px cannot be closed isotropically, because a disk that bridges 20 px along the
# line also welds two tracks running 40 px apart.
MIN_FRAGMENT_PX = 12
MAX_LINK_PX = 26.0
# Continuation is a corridor in pixels, not a tolerance in degrees. Requiring
# the vector between two dash ends to lie within 20 degrees of the dash axis
# fails on any curving track: across a 10 px gap a lateral offset of 4 px is
# already 22 degrees, and only 0.64 candidates per endpoint survived. The
# perpendicular offset is the quantity that is actually small and stays small
# however long the gap.
LINK_OFFSET_PX = 5.0
LINK_ORIENT_DEG = 35.0
LINK_PASSES = 3
MIN_NETWORK_PX = 400
# The type on these sheets is 16-18 px tall, near Tesseract's lower limit.
OCR_SCALE = 2


def paper_white(image: Image.Image, sample: int = 1200,
                face: dict | None = None) -> np.ndarray:
    """The scan's paper colour, sampled inside the map face where possible.

    Sampling the scan's top-left corner instead reads whatever the scanner had
    behind the sheet, and on these plates the paper white is the denominator of
    every density, so getting it from the wrong surface shifts every ink
    direction at once.
    """
    if face:
        box = (face["left"], face["top"],
               min(face["left"] + sample, face["right"]),
               min(face["top"] + sample * 2 // 3, face["bottom"]))
    else:
        box = (0, 0, sample, sample * 2 // 3)
    patch = np.asarray(image.crop(box))
    return np.percentile(patch.reshape(-1, 3), PAPER_PERCENTILE, axis=0)


def paper_field(image: Image.Image,
                down: int = PAPER_FIELD_DOWNSCALE,
                percentile: int = PAPER_FIELD_PERCENTILE,
                window: int = PAPER_FIELD_WINDOW,
                smooth: int = PAPER_FIELD_SMOOTH) -> np.ndarray:
    """The paper white as a smooth field over the sheet, at 1/`down` scale.

    See `PAPER_FIELD_DOWNSCALE` for why a scalar will not do. Estimated on the
    downscaled copy, which costs about five seconds on a 66-megapixel sheet and
    is where a wide percentile window is affordable.

    The estimate is biased dark inside large solid blocks of ink, where even the
    high percentile sees ink rather than paper. On this series that means dense
    hachuring, and the effect there is conservative - it reads slightly less ink
    than there is, rather than inventing any.
    """
    small = np.asarray(image.resize((max(image.width // down, 1),
                                     max(image.height // down, 1)),
                                    Image.BOX)).astype(np.float32)
    field = np.empty_like(small)
    for channel in range(small.shape[2]):
        lit = ndimage.percentile_filter(small[..., channel], percentile,
                                        size=window, mode="nearest")
        field[..., channel] = ndimage.uniform_filter(lit, size=smooth,
                                                     mode="nearest")
    return field


def field_block(field: np.ndarray, top: int, bottom: int,
                width: int, down: int = PAPER_FIELD_DOWNSCALE) -> np.ndarray:
    """The paper field resampled to cover full-resolution rows [top, bottom)."""
    first = max(top // down - 1, 0)
    last = min(bottom // down + 2, field.shape[0])
    patch = field[first:last]
    tall = (last - first) * down
    grown = np.asarray(
        Image.fromarray(patch.astype(np.uint8)).resize((width, tall),
                                                       Image.BILINEAR)
    ).astype(np.float32)
    start = top - first * down
    block = grown[start:start + (bottom - top)]
    # Downscaling floors, so the field is up to `down` rows short of the image;
    # hold the last row rather than let the final block fall off the end.
    if len(block) < bottom - top:
        block = np.vstack([block,
                           np.repeat(block[-1:], bottom - top - len(block),
                                     axis=0)])
    return block


def map_face(record_id: str, table: Path) -> dict | None:
    """The detected neatline for a sheet - the map face, without its margins.

    Measuring a plate over the whole scan measures the title block, the legend,
    the kilometric footer scale and the scanner surround along with the map: on
    Kasserine that put the "black plate" at 22.7% of the image and left the
    network share meaningless at 0.909. The georeferencing step already found
    the neatline on 85 of the 96 sheets, so the honest denominator is free.
    """
    if not table.exists():
        return None
    with table.open(encoding="utf-8") as handle:
        found = json.load(handle).get(record_id) or {}
    frame = found.get("neatline_px")
    if not frame:
        return None
    return {key: int(frame[key]) for key in ("top", "bottom", "left", "right")}


def separate(rgb: np.ndarray, paper: np.ndarray,
             floor: float = INK_FLOOR) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """One plate mask per ink, plus the amount of ink at every pixel.

    Each inked pixel is assigned to the single ink whose direction it lies
    closest to. See the module docstring for why this is a classification
    rather than a least-squares unmixing.

    `paper` is either one RGB white for the whole array or a white per pixel;
    over anything wider than about a thousand pixels it needs to be the latter
    (see `paper_field`).
    """
    intensity = np.clip(rgb.astype(np.float32), 1, 255)
    white = paper[None, None, :] if paper.ndim == 1 else paper
    density = -np.log10(intensity / np.maximum(white, 1.0))
    amount = np.linalg.norm(density, axis=2)
    unit = density / np.maximum(amount, 1e-6)[..., None]
    nearest = np.argmax(unit @ _DIRS.T, axis=2)
    inked = amount > floor
    return ({name: inked & (nearest == index)
             for index, name in enumerate(INK_NAMES)}, amount)


def separate_scan(image: Image.Image, paper: np.ndarray | None = None,
                  floor: float = INK_FLOOR) -> dict[str, np.ndarray]:
    """`separate` over a whole scan, in row blocks to bound the memory.

    With `paper` left out the paper white is estimated as a field over the whole
    image, which is what a whole sheet needs.
    """
    width, height = image.size
    field = paper_field(image) if paper is None else None
    plates = {name: np.zeros((height, width), bool) for name in INK_NAMES}
    for start in range(0, height, BLOCK_ROWS):
        stop = min(start + BLOCK_ROWS, height)
        block = np.asarray(image.crop((0, start, width, stop)))
        white = (paper if field is None
                 else field_block(field, start, stop, width))
        found, _ = separate(block, white, floor)
        for name in INK_NAMES:
            plates[name][start:stop] = found[name]
    return plates


def plate_group(plates: dict[str, np.ndarray], group: str) -> np.ndarray:
    """One usable mask: `red`, `blue`, or `dark` for the four that do not split."""
    names = PLATE_GROUPS[group]
    mask = plates[names[0]].copy()
    for name in names[1:]:
        mask |= plates[name]
    return mask


def stroke_widths(mask: np.ndarray) -> np.ndarray:
    """Stroke width sampled on the medial axis.

    For a stroke of width w the medial axis sits w/2 from the nearest edge, so
    twice the distance transform on the skeleton is the width. This is what
    tells a 2 px path from a 4 px cart track, which is the legend's own
    distinction.
    """
    from skimage.morphology import skeletonize
    if not mask.any():
        return np.zeros(0)
    distance = ndimage.distance_transform_edt(mask)
    return 2.0 * distance[skeletonize(mask)]


def fragments(mask: np.ndarray,
              min_area: int = MIN_FRAGMENT_PX) -> list[dict]:
    """Each inked fragment with its principal axis and its two endpoints.

    A dash is an ellipse-like blob whose long axis is the direction the line was
    running when it was drawn. That axis is what makes the linking below
    directional, so it is computed from the second moments rather than from the
    bounding box, which would give 45 degrees for every diagonal dash.

    All of it runs as label-wide reductions rather than a loop over components.
    A whole-sheet plate has of the order of a hundred thousand fragments, and a
    Python loop with an eigendecomposition per fragment puts the survey into the
    hours; the closed form for the principal axis of a 2x2 symmetric matrix,
    `2*theta = atan2(2*Cxy, Cxx - Cyy)`, is the same answer without the loop.
    """
    labels, count = ndimage.label(mask)
    if not count:
        return []
    rows, columns = np.nonzero(labels)
    owner = labels[rows, columns]
    x, y = columns.astype(np.float64), rows.astype(np.float64)

    area = np.bincount(owner, minlength=count + 1)
    sum_x = np.bincount(owner, weights=x, minlength=count + 1)
    sum_y = np.bincount(owner, weights=y, minlength=count + 1)
    sum_xx = np.bincount(owner, weights=x * x, minlength=count + 1)
    sum_yy = np.bincount(owner, weights=y * y, minlength=count + 1)
    sum_xy = np.bincount(owner, weights=x * y, minlength=count + 1)

    keep = np.nonzero(area >= min_area)[0]
    keep = keep[keep > 0]
    if not len(keep):
        return []
    weight = area[keep].astype(np.float64)
    mean_x, mean_y = sum_x[keep] / weight, sum_y[keep] / weight
    cov_xx = sum_xx[keep] / weight - mean_x * mean_x
    cov_yy = sum_yy[keep] / weight - mean_y * mean_y
    cov_xy = sum_xy[keep] / weight - mean_x * mean_y
    angle = 0.5 * np.arctan2(2.0 * cov_xy, cov_xx - cov_yy)
    axis_x, axis_y = np.cos(angle), np.sin(angle)

    # Extent along each fragment's own axis, again as a labelled reduction.
    index = np.zeros(count + 1, np.int64)
    index[keep] = np.arange(len(keep))
    kept = area[owner] >= min_area
    slot = index[owner[kept]]
    along = ((x[kept] - mean_x[slot]) * axis_x[slot]
             + (y[kept] - mean_y[slot]) * axis_y[slot])
    low = np.full(len(keep), np.inf)
    high = np.full(len(keep), -np.inf)
    np.minimum.at(low, slot, along)
    np.maximum.at(high, slot, along)

    centre = np.column_stack([mean_x, mean_y])
    axis = np.column_stack([axis_x, axis_y])
    return [{"axis": axis[i], "area": int(area[keep[i]]),
             "ends": (centre[i] + axis[i] * low[i],
                      centre[i] + axis[i] * high[i])}
            for i in range(len(keep))]


def link_corridor(shapes: list[dict], max_gap: float = MAX_LINK_PX,
                  max_offset: float = LINK_OFFSET_PX,
                  orient_deg: float = LINK_ORIENT_DEG
                  ) -> list[tuple[np.ndarray, np.ndarray]]:
    """Join each fragment end to the one fragment that continues it.

    A dashed line is not a connected component, and the obvious fix - closing
    the mask with a disk - is wrong twice over: a disk big enough to bridge a 20
    px dash gap also welds together two tracks running 40 px apart, and it does
    nothing about the size filter deleting the individual dashes first.

    So the dashes are linked as a graph. An end continues into another when the
    second end lies in a narrow *corridor* projected forward along the first
    fragment's axis - within `max_gap` ahead and `max_offset` to the side - and
    the two fragments point roughly the same way.

    Scoring candidates by the *angle* between the gap vector and the axis, which
    is the obvious way to say "collinear", does not work: across a 10 px gap a
    perfectly ordinary 4 px lateral offset is already 22 degrees, so on the
    held-out sheet only 0.64 candidates per endpoint survived and every curving
    track broke apart. The perpendicular offset is the quantity that is small
    and stays small however long the gap, so that is what the corridor bounds.
    """
    if not shapes:
        return []
    from scipy.spatial import cKDTree
    ends = np.array([end for shape in shapes for end in shape["ends"]])
    owner = np.repeat(np.arange(len(shapes)), 2)
    # Which way is "forward" out of each end: away from the fragment's centre.
    outward = np.array([direction
                        for shape in shapes
                        for direction in (-shape["axis"], shape["axis"])])
    tree = cKDTree(ends)
    orient_cos = np.cos(np.radians(orient_deg))

    joins, seen = [], set()
    for source in range(len(ends)):
        here = owner[source]
        axis, ahead = shapes[here]["axis"], outward[source]
        side = np.array([-ahead[1], ahead[0]])
        for target in tree.query_ball_point(ends[source], max_gap):
            there = owner[target]
            if there == here:
                continue
            offset = ends[target] - ends[source]
            forward = float(offset @ ahead)
            if not 0.0 < forward <= max_gap:
                continue
            if abs(float(offset @ side)) > max_offset:
                continue
            if abs(axis @ shapes[there]["axis"]) < orient_cos:
                continue
            pair = (min(source, target), max(source, target))
            if pair in seen:
                continue
            seen.add(pair)
            joins.append((ends[source], ends[target]))
    return joins


def _draw_joins(mask: np.ndarray, joins) -> np.ndarray:
    if not joins:
        return mask
    from PIL import ImageDraw
    canvas = Image.fromarray(np.zeros(mask.shape, np.uint8))
    pen = ImageDraw.Draw(canvas)
    for start, stop in joins:
        pen.line([tuple(start), tuple(stop)], fill=1, width=2)
    return mask | np.asarray(canvas).astype(bool)


def network(mask: np.ndarray, minimum: int = MIN_NETWORK_PX,
            passes: int = LINK_PASSES):
    """Link the dashes into runs, drop what is still too short, and skeletonize.

    The linking is *iterated*, which costs nothing and needs no extra constant:
    after one pass a chain of dashes is a long thin object whose principal axis
    is far better determined than a single 19 px dash's, so the second pass
    links ends the first could not orient. It converges on its own - on three
    test windows the third pass found 0, 1 and 2 new links - and gains 8-9
    points of the plate over a single pass.

    The size filter runs *after* linking, because a single dash is 30-80 px and
    any threshold that admits one admits every speck of foxing on the sheet.

    Returns the skeleton and the linked mask.
    """
    from skimage.morphology import skeletonize
    linked = mask.copy()
    for _ in range(passes):
        joins = link_corridor(fragments(linked))
        if not joins:
            break
        linked = _draw_joins(linked, joins)
    # Own size filter rather than `remove_small_objects`, whose `min_size`
    # keyword and its off-by-one are mid-deprecation in scikit-image 0.26.
    labels, count = ndimage.label(linked)
    if count:
        sizes = np.bincount(labels.ravel(), minlength=count + 1)
        sizes[0] = 0                                     # label 0 is the paper
        linked = np.isin(labels, np.nonzero(sizes >= minimum)[0])
    return skeletonize(linked), linked


def text_mask(mask: np.ndarray, pad: int = 2,
              min_confidence: float = 20.0,
              max_height: int = 40,
              scale: int = OCR_SCALE) -> tuple[np.ndarray, list[dict]]:
    """Where the type is on a plate, and what it says.

    **Run this on what the network leaves behind, never on the plate itself.**
    Masking the type first, to clear the way for the tracing, looks like the
    natural order and is wrong: given a dashed track, `--psm 11` reads the row
    of dashes as punctuation - on one held-out window it returned `'-'`, `'=,'`,
    `'aan,'`, `'FEES.'` and blocked 6319 of the plate's 8041 pixels, 79% of it,
    deleting the very network it was meant to clean. Dashes chain collinearly
    and type does not, so `network()` runs first and separates the two; the
    leftovers are where the type actually is.

    Digits on this series are 16-18 px tall, near the bottom of Tesseract's
    range, so the plate goes in upscaled: at 1:1 a spot height of 656 reads as
    "636", at 2x it reads correctly. Coordinates come back in the plate's own
    frame. `--psm 11` (sparse text) is required - the layout modes that assume
    running text find almost nothing on a map.
    """
    import pytesseract
    page = Image.fromarray((~mask * 255).astype(np.uint8))
    if scale > 1:
        page = page.resize((page.width * scale, page.height * scale),
                           Image.LANCZOS)
    data = pytesseract.image_to_data(page, config="--psm 11",
                                     output_type=pytesseract.Output.DICT)
    found, blocked = [], np.zeros_like(mask)
    for index, raw in enumerate(data["text"]):
        token = raw.strip()
        if not token:
            continue
        confidence = float(data["conf"][index])
        left, top = data["left"][index] // scale, data["top"][index] // scale
        wide, high = data["width"][index] // scale, data["height"][index] // scale
        found.append({"text": token, "conf": confidence,
                      "x": left + wide / 2.0, "y": top + high / 2.0,
                      "w": wide, "h": high})
        if confidence > min_confidence and high <= max_height:
            blocked[max(top - pad, 0):top + high + pad,
                    max(left - pad, 0):left + wide + pad] = True
    return blocked, found


FIELDS = ["record_id", "sheet_name", "plate", "ink_share",
          "width_median_px", "width_p10_px", "width_p90_px",
          "components", "components_over_200px",
          "network_px", "network_share_of_plate", "network_skeleton_px"]

# Tracing is the expensive step. Trace the two plates that separate, plus the
# combined dark plate - not because that one is a network, but because its
# network share is the number that shows it is not.
TRACED_PLATES = ("dark", "red", "blue")


def survey_sheet(path: Path, record_id: str, name: str,
                 face: dict | None = None) -> list[dict]:
    image = Image.open(path).convert("RGB")
    if face:
        image = image.crop((face["left"], face["top"],
                            face["right"], face["bottom"]))
    plates = separate_scan(image)
    # Report every measured ink, so the continuum is visible in the table, plus
    # the combined dark plate. `red` and `blue` are groups of one and are
    # already in `plates` under their own names.
    measured = dict(plates)
    measured["dark"] = plate_group(plates, "dark")
    rows = []
    for plate, mask in measured.items():
        widths = stroke_widths(mask)
        labels, count = ndimage.label(mask)
        sizes = (np.bincount(labels.ravel(), minlength=count + 1)[1:]
                 if count else np.zeros(0))
        row = {
            "record_id": record_id, "sheet_name": name, "plate": plate,
            "ink_share": round(float(mask.mean()), 5),
            "width_median_px": round(float(np.median(widths)), 1) if len(widths) else "",
            "width_p10_px": round(float(np.percentile(widths, 10)), 1) if len(widths) else "",
            "width_p90_px": round(float(np.percentile(widths, 90)), 1) if len(widths) else "",
            "components": int(count),
            "components_over_200px": int((sizes > 200).sum()),
            "network_px": "", "network_share_of_plate": "",
            "network_skeleton_px": "",
        }
        if plate in TRACED_PLATES:
            skeleton, linked = network(mask)
            inked = max(int(mask.sum()), 1)
            row["network_px"] = int(linked.sum())
            row["network_share_of_plate"] = round(linked.sum() / inked, 3)
            row["network_skeleton_px"] = int(skeleton.sum())
        rows.append(row)
    return rows


def demo(path: Path, window, out: Path, group: str = "dark") -> None:
    """Trace one plate's network on one window, and read the type on it."""
    import re
    from PIL import ImageDraw
    image = Image.open(path).convert("RGB")
    paper = paper_white(image)
    crop = np.asarray(image.crop(window))
    plates, _ = separate(crop, paper)
    black = plate_group(plates, group)

    # Both products read the same plate, and neither is subtracted from the
    # other. Masking the type before tracing destroys the network (see
    # `text_mask`); and taking the network out before reading costs accuracy the
    # other way, because a digit whose strokes chain into a run goes with it -
    # on this window it turns the spot height 656 back into "636".
    skeleton, linked = network(black)
    _, tokens = text_mask(black)
    legible = [t for t in tokens
               if t["conf"] > 40 and 8 <= t["h"] <= 34
               and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.]*", t["text"])]

    share = 100.0 * linked.sum() / max(black.sum(), 1)
    print(f"{group} plate {int(black.sum()):7d} px")
    print(f"  network {int(linked.sum()):7d} px ({share:.0f}% of the plate), "
          f"skeleton {int(skeleton.sum()):6d} px")
    widths = stroke_widths(linked)
    if len(widths):
        print(f"  stroke width: median {np.median(widths):.1f} px, "
              f"p10 {np.percentile(widths, 10):.1f}, "
              f"p90 {np.percentile(widths, 90):.1f}")
    print(f"  type: {len(legible)} legible of {len(tokens)} tokens")
    for t in legible:
        print(f"    {t['text']:>8s} at ({t['x']:.0f},{t['y']:.0f})  "
              f"conf {t['conf']:.0f}")

    scale = 2
    overlay = image.crop(window).resize(
        ((window[2] - window[0]) * scale, (window[3] - window[1]) * scale),
        Image.LANCZOS)
    draw = ImageDraw.Draw(overlay)
    rows, columns = np.nonzero(skeleton)
    for x, y in zip(columns, rows):
        draw.point((x * scale, y * scale), fill=(0, 190, 0))
        draw.point((x * scale + 1, y * scale), fill=(0, 190, 0))
    for t in legible:
        if re.fullmatch(r"\d{2,4}", t["text"]):
            draw.ellipse([t["x"] * scale - 9, t["y"] * scale - 9,
                          t["x"] * scale + 9, t["y"] * scale + 9],
                         outline=(230, 90, 20), width=3)
    out.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(out)
    print(f"  -> {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--survey", action="store_true",
                        help="measure every plate on every sheet")
    parser.add_argument("--demo", default=None, metavar="RECORD_ID")
    parser.add_argument("--window", nargs=4, type=int, default=None,
                        metavar=("X0", "Y0", "X1", "Y1"))
    parser.add_argument("--plate", default="dark", choices=sorted(PLATE_GROUPS),
                        help="which plate the demo traces")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--table", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.csv")
    parser.add_argument("--faces", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.json",
                        help="where the detected neatlines come from")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "ink_plates.csv")
    parser.add_argument("--out-demo", type=Path,
                        default=REPO_ROOT / "docs" / "img" / "ink_plates_network.png")
    args = parser.parse_args()

    if args.demo:
        window = tuple(args.window or (3300, 2400, 3900, 2800))
        demo(args.images / f"{args.demo}.jpg", window, args.out_demo,
             args.plate)
        return 0

    if not args.survey:
        parser.error("pass --survey or --demo")

    names = {r["record_id"]: r.get("sheet_name", "")
             for r in csv.DictReader(args.table.open(encoding="utf-8"))}
    files = sorted(args.images.glob("*.jpg"))
    if args.limit:
        files = files[:args.limit]
    rows, skipped = [], 0
    for index, path in enumerate(files, 1):
        record_id = path.stem
        face = map_face(record_id, args.faces)
        if not face:
            # No neatline means no honest denominator; the alternative is to
            # measure the title block and the scanner surround as if they were
            # map, which is the error this whole column set exists to avoid.
            skipped += 1
            print(f"  {index}/{len(files)} {record_id} skipped: no neatline",
                  flush=True)
            continue
        try:
            rows.extend(survey_sheet(path, record_id,
                                     names.get(record_id, ""), face))
        except Exception as error:                       # noqa: BLE001
            print(f"  {index}/{len(files)} {record_id} failed: {error}",
                  flush=True)
            continue
        recent = {r["plate"]: r for r in rows[-ROWS_PER_SHEET:]}
        print(f"  {index}/{len(files)} {names.get(record_id, record_id)[:22]:22s} "
              f"red {recent['red']['ink_share']:.4f} "
              f"net {recent['red']['network_share_of_plate']}  "
              f"dark {recent['dark']['ink_share']:.3f}", flush=True)

    with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n{len(rows)} plate measurements on "
          f"{len(rows) // ROWS_PER_SHEET} sheets -> {args.out_csv}")
    if skipped:
        print(f"{skipped} sheets skipped for want of a detected neatline")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Extract legend symbols from a sheet and give each one a ground coordinate.

Three classes, chosen because the legend defines them and the printing separates
them cleanly at this scan resolution:

  building   "Maisons" - individual solid red marks. Outside the built-up areas
             every house is drawn separately, so a count is a settlement-density
             measure at a far finer grain than any place-name layer.
  well       "Puits et fontaine" - a thin blue open ring, about 10 px across.
             PROVISIONAL, and not extracted by default. Across ten sheets whose
             transforms fit to 12-14 m the counts run from 4 (Djebel Semmama) to
             2158 (Oued-Zarga). Some of that spread is real - a dry massif has
             fewer wells than the Medjerda valley - but a factor of 500 is not,
             and the overlays show the detector firing on blue hatching in
             marshy ground. Pass --classes building,well to include it.
  shrine     "Eglise, chapelle, koubba" - the marabout glyph, a dome on a narrow
             stem above a disc. PROVISIONAL, and not extracted by default.
             132 candidates on 78 sheets, and a random sample of 30 checked
             against their pixel masks is **40% right** - 12 clear marabouts,
             13 clearly not, and 5 that looked plausible in profile and turned
             out to be track junctions or hatching when the masks were printed.
             So it is a candidate list to check by eye, not a count to cite:
             about 53 of the 132 are expected to be real. Pass
             --classes building,shrine to include it.
  vegetation "Bois / Broussailles / Oliviers / Palmiers" - the teal stipple, one
             ring per tree or small group. Available but NOT extracted by
             default, because it is not yet reliable: the stipple is dense and
             saturated on the Sahel sheets and faint on the steppe ones, and a
             threshold that finds 268 rings in a Kasserine window finds 3 when
             tightened enough to stop it tracing the black lettering. It needs
             per-sheet calibration before its counts mean anything. Pass
             --classes building,well,vegetation to include it anyway.

Wells and vegetation stipple look alike in shape and are told apart by hue
alone: on the Sfax sheet a well ring runs about (78, 106, 143) in RGB, blue well
above green, while the vegetation ring has green at or above blue. Getting that
the wrong way round turns every olive tree into a well, so the two masks are
deliberately exclusive and the counts are reported separately.

A ring is not a blob. Connected-component labelling finds only a tenth of the
rings, because the stroke is one or two pixels wide and breaks wherever it
crosses another feature, so each ring falls apart into arcs that no size filter
can recognise. Matching an annulus template instead scores the whole shape at
once, and asks for the middle to be empty as well as the rim to be inked, which
is what distinguishes a ring from a filled dot.

Coordinates come from scripts/georeference_sheets.py, so every symbol carries a
Lambert easting and northing and a WGS84 longitude and latitude, and inherits
that sheet's stated accuracy.

Whether a sheet's absolute anchor was confirmed is deliberately NOT copied onto
each symbol. It is a property of the sheet, and duplicating it per feature is
what let two copies drift apart. Consumers join it from
data/sheet_georef.csv on record_id.

Outputs:
    data/symbols/<record_id>.geojson   EPSG:4326, one feature per symbol
    data/symbols_summary.csv           counts per sheet and class
    optional --overlay <dir>           the crop with detections drawn, for
                                       checking by eye rather than by count

Usage:
    python3 scripts/extract_symbols.py --images <dir> --only <record_id>
    python3 scripts/extract_symbols.py --images <dir> --overlay data/overlays
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Transformer
from scipy import ndimage
from scipy.signal import fftconvolve
from scipy.spatial import cKDTree

warnings.filterwarnings("ignore", message=".*lose important projection.*")
Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent

# Five decimal places is about a metre. Seven, the default of the first version,
# implies a centimetre on coordinates whose stated accuracy is twenty metres, and
# spends a third of the file size saying so.
COORD_DECIMALS = 5

# Ring radii in pixels, at the series' measured 236 px/km. A legend ring is
# about 0.5 mm on paper, so 10 px across.
RING_RADII = (4.5, 5.0, 5.5, 6.0)
RING_THICKNESS = 1.8
RING_SCORE = 0.30
RING_SUPPRESS_PX = 9          # no two ring centres closer than this

# Classes printed in the same red as the kilometric grid, so the grid has to be
# cut out of each of them geometrically before anything is measured.
RED_CLASSES = {"building", "shrine"}

# The koubba, all of it measured off the legend glyph the sheet prints: 27 x 16
# px, 262 px of ink, a dome 10 px wide over a stem of 6 above a disc of 16.
# Bands are that shape with room for scan variation and for the ink bleeding
# into a contour it touches.
KOUBBA_MIN_PX = 120
KOUBBA_MAX_PX = 700
KOUBBA_HEIGHT_PX = (20, 40)
KOUBBA_WIDTH_PX = (9, 28)
KOUBBA_DISC_MIN_PX = 9        # narrower than this and the lobe is not a disc
KOUBBA_STEM_MIN_PX = 3        # rows the stem must occupy between the two lobes
# The legend gives waist/disc = 6/16 = 0.375 and dome/disc = 10/16 = 0.625.
KOUBBA_WAIST_SHARE = 0.50
KOUBBA_DOME_SHARE = (0.40, 0.90)
# A koubba stands alone; red TEXT does not. This is the test that mattered most,
# and it was found by checking a random sample rather than by reasoning: of 24
# detections without it, 18 were red type - the kilometric labels printed along
# the grid lines ("49", "50", "59") and the red place-name lettering ("QU",
# "ISI", "NORU"). A digit or a letter is exactly a narrow neck above a wide
# bowl, so the waist test cannot see the difference. What separates them is that
# type is set in lines: its neighbours sit a character-width away. The glyph is
# a standalone map symbol in open country.
#
# Measured over 7 087 glyph-sized red components on four sheets, the nearest
# such neighbour is a median 29 px away and 72% are within 46 px. The two
# koubbas confirmed by eye sit 192 px and 171 px from any company.
#
# A blanket distance cut at 46 px was tried and is too blunt: on the Sousse
# sheet it threw away 12 of 13 waist-passing candidates, and a koubba drawn
# beside a village is not type. Type is better identified by what makes it type
# - a shared baseline and a shared height with the character next to it - so
# that test does the work and this distance is relaxed to catch only the
# densest hatching.
KOUBBA_ISOLATION_PX = 26.0
# Type set in a line shares a bottom edge to within a few px and a height to
# within a third. A house or a patch of hatching beside a koubba shares
# neither.
KOUBBA_TEXT_GAP_PX = 70.0
KOUBBA_TEXT_BASELINE_PX = 5
KOUBBA_TEXT_HEIGHT_SHARE = 0.30
# The company searched is only components in the same size band, so a koubba
# beside one house is still isolated - a house is smaller than this band.
KOUBBA_COMPANY_PX = (60, 900)

BUILDING_MIN_PX = 12          # a 0.4 mm mark is about 16 px of ink
BUILDING_MAX_PX = 400
BUILDING_MAX_ASPECT = 6.0
# The house mark is a filled rectangle. The red numerals printed on the map -
# spot heights and grid labels - are the same colour and a similar size, but
# they are strokes, so they fill much less of their bounding box.
BUILDING_MIN_FILL = 0.55
# Detections are clipped to a box the size of the sheet's catalogued extent -
# which is what its "Coordonnees (E ... / N ...)" statement describes, the
# neatline - centred where the sheet's own transform puts its frame.
#
# Taking size from one source and position from the other is deliberate, because
# each is reliable for only one of them.
#
#   The detected neatline is the wrong source for size. Its box comes out a
#   median 6% smaller than the catalogued one but ranges from 40% smaller to
#   larger, because each side of the frame is three rules and the detector picks
#   a different one on different sheets. The catalogued size does not vary with
#   how a scan came out.
#
#   The catalogue box is the wrong source for position. On Djebel Mrhila it is
#   36 km east of where the sheet prints its own corner coordinates, and
#   clipping on it threw away four fifths of that sheet's houses - 735 down to
#   152 - once the anchor was corrected. The transform's position now rests on
#   the sheet's own printing (see read_corner_coordinates.py), so it is the
#   better centre by a wide margin.
#
# The legend and the red grid labels lie outside the box either way.
CLIP_INSET_DEG = 0.002        # about 200 m, to stay clear of the neatline itself


GRID_EXCLUDE_PX = 6           # how far from a grid line to ignore red ink
GRID_BLOCK_ROWS = 512         # rows per pass when masking out the grid
ISOLATION_RADIUS = 2.6        # multiples of the ring radius
ISOLATION_MAX_DENSITY = 0.12  # ink share allowed around an isolated ring


def masks(array: np.ndarray, wanted: set[str]) -> dict[str, np.ndarray]:
    """Colour masks, built only for the classes asked for.

    Building all three costs three full-resolution int16 channels and three
    boolean masks of a 66-megapixel scan whether they are used or not, which on
    a default run that wants houses alone is most of the memory traffic.
    """
    red, green, blue = (array[..., 0].astype(np.int16),
                        array[..., 1].astype(np.int16),
                        array[..., 2].astype(np.int16))
    recipes = {
        # Solid printed red - the same red as the grid, which is why the grid is
        # masked out geometrically rather than by colour.
        "building": lambda: ((red - green > 45) & (red - blue > 40)
                            & (red > 110)),
        # The koubba is printed in the same red as the house, so the mask is the
        # same and all the work is in the shape - see find_koubbas.
        "shrine": lambda: ((red - green > 45) & (red - blue > 40)
                           & (red > 110)),
        # Blue above green: this is what separates a well from an olive tree.
        "well": lambda: ((blue - red > 25) & (blue - green > 12) & (blue > 80)),
        # Green must actually be green, not merely the greenest channel of a
        # grey edge: relaxing this to catch fainter stipple made the detector
        # trace the black lettering and the tracks instead.
        "vegetation": lambda: ((green - red > 16) & (green - blue > 4)
                               & (green > 80)
                               & (green - np.minimum(red, blue) > 24)),
    }
    return {name: recipe() for name, recipe in recipes.items()
            if name in wanted}


def grid_stripe(shape: tuple[int, int], lines: dict,
                origin: tuple[int, int]) -> np.ndarray:
    """Pixels within a few px of a printed grid line.

    The houses and the grid are printed in the same red, and at a grid crossing
    the two lines make a compact blob that no size or aspect filter can tell
    from a house - the first run returned the crossings and the red grid labels
    as buildings. But the grid's geometry is already known exactly from the
    georeferencing, so it can simply be cut out.
    """
    rows, columns = shape
    stripe = np.zeros(shape, bool)
    columns_axis = np.arange(columns, dtype=np.float32) + origin[0]
    eastings = np.asarray(lines["easting_constants"], dtype=np.float32)
    northings = np.asarray(lines["northing_constants"], dtype=np.float32)

    # In row blocks rather than whole-image index grids. np.mgrid over a
    # 66-megapixel scan is two int64 arrays of half a gigabyte each, and then
    # every one of the ~55 grid lines makes another full-size temporary: on the
    # Kasserine sheet that was two minutes of system time per sheet, more than
    # the detection itself. A block of a few hundred rows fits in cache.
    for start in range(0, rows, GRID_BLOCK_ROWS):
        stop = min(start + GRID_BLOCK_ROWS, rows)
        rows_axis = (np.arange(start, stop, dtype=np.float32)
                     + origin[1])[:, None]
        block = stripe[start:stop]

        # Distance to the nearest easting line, via its line constant.
        u = columns_axis[None, :] - lines["tan_e"] * rows_axis
        block |= nearest_distance(u, eastings) < GRID_EXCLUDE_PX
        v = rows_axis - lines["tan_n"] * columns_axis[None, :]
        block |= nearest_distance(v, northings) < GRID_EXCLUDE_PX
    return stripe


def nearest_distance(values: np.ndarray, sorted_lines: np.ndarray) -> np.ndarray:
    """Distance from each value to the closest entry of `sorted_lines`.

    One searchsorted plus two subtractions, instead of one full-size comparison
    per line.
    """
    if sorted_lines.size == 0:
        return np.full(values.shape, np.inf, dtype=np.float32)
    index = np.searchsorted(sorted_lines, values)
    left = sorted_lines[np.clip(index - 1, 0, sorted_lines.size - 1)]
    right = sorted_lines[np.clip(index, 0, sorted_lines.size - 1)]
    return np.minimum(np.abs(values - left), np.abs(values - right))


def ring_template(outer: float, thickness: float):
    size = int(np.ceil(outer * 2)) + 3
    grid = np.mgrid[0:size, 0:size]
    centre = (size - 1) / 2
    distance = np.hypot(grid[0] - centre, grid[1] - centre)
    inner = outer - thickness
    return ((distance <= outer) & (distance >= inner)).astype(np.float32), \
           (distance < inner).astype(np.float32)


def find_rings(mask: np.ndarray) -> list[tuple[float, float]]:
    """Annulus template match over a range of radii, then keep the best peaks."""
    signal = mask.astype(np.float32)
    best_score = None
    for outer in RING_RADII:
        rim, middle = ring_template(outer, RING_THICKNESS)
        on_rim = fftconvolve(signal, rim[::-1, ::-1], mode="same") / max(rim.sum(), 1)
        in_middle = (fftconvolve(signal, middle[::-1, ::-1], mode="same")
                     / max(middle.sum(), 1))
        # Inked rim, empty middle. Without the second term a filled dot and a
        # ring score the same.
        score = on_rim - 0.8 * in_middle
        best_score = score if best_score is None else np.maximum(best_score, score)

    peaks = (best_score == ndimage.maximum_filter(best_score, size=RING_SUPPRESS_PX))
    peaks &= best_score > RING_SCORE

    # A well is an isolated ring; a watercourse is a chain of them. Without this
    # test the detector traced the oued down the middle of the sheet and called
    # every bend a well. Requiring the neighbourhood beyond the ring to be
    # mostly empty keeps the isolated symbol and drops the chain.
    outer = max(RING_RADII)
    surround = ring_template(outer * ISOLATION_RADIUS, outer * ISOLATION_RADIUS)[1]
    density = (fftconvolve(signal, surround[::-1, ::-1], mode="same")
               / max(surround.sum(), 1))
    peaks &= density < ISOLATION_MAX_DENSITY

    rows, columns = np.nonzero(peaks)
    return [(float(x), float(y)) for x, y in zip(columns, rows)]


def is_same_line(box, other, height: int) -> bool:
    """Whether `other` reads as the next character along from `box`.

    Type is identified by what makes it type: a neighbour sitting beside it,
    close, on the same baseline, at the same height. This is what separates a
    red kilometric label or place name - which has exactly the koubba's
    narrow-neck-over-wide-bowl profile in characters like 4, 9, Q and U - from
    a map symbol standing on its own.
    """
    gap = max(other[1].start - box[1].stop, box[1].start - other[1].stop)
    if gap > KOUBBA_TEXT_GAP_PX:
        return False
    if abs(other[0].stop - box[0].stop) > KOUBBA_TEXT_BASELINE_PX:
        return False
    other_height = other[0].stop - other[0].start
    return abs(other_height - height) <= KOUBBA_TEXT_HEIGHT_SHARE * height


def find_koubbas(mask: np.ndarray) -> list[tuple[float, float]]:
    """The marabout: a dome on a narrow stem above a disc.

    Measured off the sheet's own legend row, which prints the glyph at 27 x 16
    px with 262 px of ink. Its row-width profile, top to bottom, is

        1 3 5 5 5 4 3 3 3 3 3 3 4 5 6 6 7 7 8 8 8 7 7 6 4   (halved, as drawn)

    - a dome about 10 px wide, a stem that narrows to 6, then a disc that
    widens to 16. That **waist** is the whole discriminator, and it is what
    every cheaper test lacked:

      * Colour cannot help. The koubba is the same red as the house mark.
      * Roundness cannot help. IoU(square, inscribed disc) = pi/4 = 0.785 at
        any size, so no threshold separates a disc from a house.
      * Convex-hull solidity alone cannot help. Two houses drawn touching merge
        into one non-convex component, and so does a red road junction; on
        Kasserine that left about 30% precision.

    The waist is structural rather than statistical: a filled quadrilateral has
    no local minimum in its width profile, a merged pair of houses has no
    *narrow* one between two lobes of the right proportions, and a road
    fragment has no lobes at all. The disc must also be the larger lobe, which
    is what orients the glyph and rejects the head-heavy blobs.

    Returns the centroid of the *disc*, not of the whole glyph: the disc is the
    koubba and the dome is drawn above it, so the whole-glyph centroid sits
    high by about 6 px, which is 26 m on the ground.

    **The legend simplifies the glyph, as it does for the trig point.** The
    legend row draws the marabout with a *filled* bulb; on the map body it is
    usually a hollow ring with a fork above it. This finder catches both because
    it measures ink per row rather than assuming a solid lobe, which is luck
    rather than design - but it is why the same thresholds work on both forms.

    **What it still gets wrong**, measured on a random sample of 30 of its 132
    detections, checked against pixel masks: 40% are real. The survivors that
    are not are track and road junctions, red hatching in built-up areas, and
    dense clusters of touching houses - all of which can present a narrow neck
    over a wider lobe. Recall is bounded too, and deliberately: a koubba inside
    a hatched town fails the isolation cut by design.
    """
    labels, count = ndimage.label(mask)
    if count == 0:
        return []
    sizes = ndimage.sum(mask, labels, range(1, count + 1))
    boxes = ndimage.find_objects(labels)
    centres = ndimage.center_of_mass(mask, labels, range(1, count + 1))

    # Every glyph-sized red component, so a candidate can be asked whether it
    # has company. Type does; a koubba does not.
    glyph_sized = [i for i in range(count)
                   if KOUBBA_COMPANY_PX[0] <= sizes[i] <= KOUBBA_COMPANY_PX[1]]
    company = np.array([(centres[i][1], centres[i][0])
                        for i in glyph_sized]).reshape(-1, 2)
    tree = cKDTree(company) if len(company) else None

    found = []
    for index, box in enumerate(boxes):
        area = sizes[index]
        if not KOUBBA_MIN_PX <= area <= KOUBBA_MAX_PX:
            continue
        height = box[0].stop - box[0].start
        width = box[1].stop - box[1].start
        if not KOUBBA_HEIGHT_PX[0] <= height <= KOUBBA_HEIGHT_PX[1]:
            continue
        if not KOUBBA_WIDTH_PX[0] <= width <= KOUBBA_WIDTH_PX[1]:
            continue

        component = labels[box] == index + 1
        widths = component.sum(axis=1).astype(float)
        # The disc is the widest row of the lower half; the dome the widest
        # above it; the waist the narrowest row between the two.
        middle = len(widths) // 2
        disc_row = int(np.argmax(widths[middle:])) + middle
        disc = widths[disc_row]
        if disc < KOUBBA_DISC_MIN_PX or disc_row < KOUBBA_STEM_MIN_PX:
            continue
        dome_row = int(np.argmax(widths[:disc_row]))
        dome = widths[dome_row]
        if disc_row - dome_row < KOUBBA_STEM_MIN_PX:
            continue
        waist_row = int(np.argmin(widths[dome_row:disc_row + 1])) + dome_row
        waist = widths[waist_row]

        if waist > KOUBBA_WAIST_SHARE * disc:
            continue
        if not (KOUBBA_DOME_SHARE[0] * disc <= dome <= KOUBBA_DOME_SHARE[1] * disc):
            continue
        # The disc is the lower and the larger lobe. Without this the detector
        # accepts the same profile upside down, which is a house with a track
        # leaving it.
        if disc <= dome:
            continue

        # Company: the second nearest glyph-sized component, because the
        # nearest is this candidate itself. Only the densest hatching is cut
        # here; type is caught by the baseline test below.
        if tree is not None and len(company) > 1:
            here = (centres[index][1], centres[index][0])
            distances, _ = tree.query(here, k=2)
            if float(np.atleast_1d(distances)[-1]) < KOUBBA_ISOLATION_PX:
                continue

        # Is this a character in a line of type? Its neighbour would sit beside
        # it on the same baseline at the same height.
        if any(is_same_line(box, boxes[other], height)
               for other in glyph_sized if other != index):
            continue

        lobe = component[waist_row:, :]
        rows, columns = np.nonzero(lobe)
        found.append((float(box[1].start + columns.mean()),
                      float(box[0].start + waist_row + rows.mean())))
    return found


def find_blobs(mask: np.ndarray) -> list[tuple[float, float]]:
    """Compact solid marks: the houses, with roads and grid lines rejected."""
    labels, count = ndimage.label(mask)
    if count == 0:
        return []
    sizes = ndimage.sum(mask, labels, range(1, count + 1))
    boxes = ndimage.find_objects(labels)
    centres = ndimage.center_of_mass(mask, labels, range(1, count + 1))

    found = []
    for index, box in enumerate(boxes):
        area = sizes[index]
        if not BUILDING_MIN_PX <= area <= BUILDING_MAX_PX:
            continue
        height = box[0].stop - box[0].start
        width = box[1].stop - box[1].start
        if max(height, width) / max(min(height, width), 1) > BUILDING_MAX_ASPECT:
            continue
        if area / (height * width) < BUILDING_MIN_FILL:
            continue
        found.append((float(centres[index][1]), float(centres[index][0])))
    return found


def extract(path: Path, window: tuple[int, int, int, int] | None,
            lines: dict | None = None, wanted: tuple[str, ...] = ("building",)):
    image = Image.open(path).convert("RGB")
    if window:
        image = image.crop(window)
        origin = (window[0], window[1])
    else:
        origin = (0, 0)
    array = np.asarray(image)
    layers = masks(array, set(wanted))
    # Every class drawn in the same red as the grid needs the grid cut out, not
    # just the houses: a grid crossing is a wildly non-convex compound blob, and
    # the koubba finder looks for exactly that shape.
    if lines:
        stripe = None
        for name in RED_CLASSES & set(layers):
            if stripe is None:
                stripe = grid_stripe(layers[name].shape, lines, origin)
            layers[name] = layers[name] & ~stripe

    finders = {"building": find_blobs, "well": find_rings,
               "vegetation": find_rings, "shrine": find_koubbas}
    found = {name: finders[name](layer) for name, layer in layers.items()}
    shifted = {name: [(x + origin[0], y + origin[1]) for x, y in points]
               for name, points in found.items()}
    return shifted, image, found


def clip_box(sheet: dict, box: dict | None) -> dict | None:
    """The catalogued extent, re-centred on where the transform puts the frame.

    Keeps the catalogue's width and height and discards its position. Returns
    None when there is no catalogued size to borrow.
    """
    if not box:
        return None
    corners = sheet.get("corners")
    if not corners:
        return box
    fitted_lon = sum(c["lon"] for c in corners.values()) / 4
    fitted_lat = sum(c["lat"] for c in corners.values()) / 4
    east_west = (box["east"] - box["west"]) / 2
    north_south = (box["north"] - box["south"]) / 2
    return {"west": fitted_lon - east_west, "east": fitted_lon + east_west,
            "south": fitted_lat - north_south, "north": fitted_lat + north_south}


def to_geojson(found: dict, affine: list, epsg: int, record_id: str,
               box: dict | None) -> dict:
    a, d, b, e, c, f = affine
    to_wgs84 = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    features = []
    for name, points in found.items():
        for x, y in points:
            easting = a * x + b * y + c
            northing = d * x + e * y + f
            lon, lat = to_wgs84.transform(easting, northing)
            if box and not (box["west"] + CLIP_INSET_DEG <= lon
                            <= box["east"] - CLIP_INSET_DEG
                            and box["south"] + CLIP_INSET_DEG <= lat
                            <= box["north"] - CLIP_INSET_DEG):
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point",
                             "coordinates": [round(lon, COORD_DECIMALS),
                                             round(lat, COORD_DECIMALS)]},
                "properties": {
                    "record_id": record_id,
                    "symbol_class": name,
                    "pixel_x": round(x, 1),
                    "pixel_y": round(y, 1),
                    "easting": round(easting, 1),
                    "northing": round(northing, 1),
                    "epsg_source": epsg,
                },
            })
    return {"type": "FeatureCollection", "features": features}


COLOURS = {"building": (255, 0, 255), "well": (0, 0, 255),
           "vegetation": (0, 160, 0)}


def draw_overlay(image: Image.Image, local: dict, out: Path) -> None:
    canvas = image.copy()
    pen = ImageDraw.Draw(canvas)
    for name, points in local.items():
        colour = COLOURS[name]
        for x, y in points:
            pen.ellipse([x - 9, y - 9, x + 9, y + 9], outline=colour, width=2)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=90)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--georef", type=Path,
                        default=REPO_ROOT / "data" / "sheet_georef.json")
    parser.add_argument("--partner", type=Path,
                        default=REPO_ROOT / "data" / "partner_records.json")
    parser.add_argument("--series", type=Path,
                        default=REPO_ROOT / "data" / "tunisia_50k_series.csv")
    parser.add_argument("--out-dir", type=Path,
                        default=REPO_ROOT / "data" / "symbols")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "symbols_summary.csv")
    parser.add_argument("--overlay", type=Path, default=None)
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--classes", default="building",
                        help="comma-separated symbol classes to extract")
    parser.add_argument("--window", nargs=4, type=int, default=None,
                        metavar=("X0", "Y0", "X1", "Y1"),
                        help="restrict to a pixel window, for checking")
    args = parser.parse_args()

    georef = json.loads(args.georef.read_text(encoding="utf-8"))
    partner = json.loads(args.partner.read_text(encoding="utf-8"))
    sheets = {r["record_id"]: r
              for r in csv.DictReader(args.series.open(encoding="utf-8"))}

    targets = sorted(args.images.glob("*.jpg"))
    if args.only:
        targets = [t for t in targets if t.stem in set(args.only)]

    rows = []
    wanted = [c.strip() for c in args.classes.split(",") if c.strip()]
    for index, path in enumerate(targets, 1):
        record_id = path.stem
        reference = georef.get(record_id, {})
        name = sheets.get(record_id, {}).get("sheet_name") or record_id[-6:]
        if "affine" not in reference:
            print(f"  {index}/{len(targets)} {name[:22]:<22} - not georeferenced")
            continue
        if reference.get("anchor_provisional"):
            # Scale and rotation without a position. Extracting from it would
            # produce coordinates that look exactly like the others and are
            # wrong by however many kilometres the anchor turns out to be.
            print(f"  {index}/{len(targets)} {name[:22]:<22} - anchor provisional")
            continue

        window = tuple(args.window) if args.window else None
        found, image, local = extract(path, window, reference.get("grid_lines"),
                                      tuple(wanted))
        collection = to_geojson(
            found, reference["affine"], reference["epsg"], record_id,
            clip_box(reference, partner.get(record_id, {}).get("bbox")))
        kept = len(collection["features"])
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / f"{record_id}.geojson").write_text(
            json.dumps(collection), encoding="utf-8")

        if args.overlay:
            draw_overlay(image, local, args.overlay / f"{record_id}.jpg")

        # Counted after the clip, so the table matches the GeoJSON.
        counts = {k: 0 for k in ("building", "shrine", "well", "vegetation")}
        for feature in collection["features"]:
            counts[feature["properties"]["symbol_class"]] += 1
        rows.append({
            "record_id": record_id,
            "sheet_name": sheets.get(record_id, {}).get("sheet_name", ""),
            "anchor_confident": int(bool(reference.get("anchor_confident"))),
            "clipped_out": sum(len(v) for v in found.values()) - kept,
            "residual_rms_m": reference.get("residual_rms_m", ""),
            **counts,
            "total": kept,
        })
        print(f"  {index}/{len(targets)} {name[:22]:<22} "
              + " ".join(f"{k}={counts[k]}" for k in wanted), flush=True)

    if rows:
        fields = ["record_id", "sheet_name", "anchor_confident",
                  "residual_rms_m", "building", "shrine", "well", "vegetation", "total",
                  "clipped_out"]
        # Merge, do not replace. The GeoJSON per sheet is written per sheet, but
        # this table was rewritten from whatever the run happened to process, so
        # a --only run over five sheets silently cut the other seventy-three out
        # of it - the files were all still there and the summary of them was not.
        merged: dict[str, dict] = {}
        if args.out_csv.exists():
            for row in csv.DictReader(args.out_csv.open(encoding="utf-8")):
                for field in ("building", "shrine", "well", "vegetation", "total",
                              "clipped_out"):
                    row[field] = int(row[field] or 0)
                merged[row["record_id"]] = row
        merged.update({row["record_id"]: row for row in rows})
        ordered = [merged[key] for key in sorted(merged)]
        with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(ordered)
        print(f"\n{len(rows)} sheets this run; {len(ordered)} in the table, "
              f"{sum(r['total'] for r in ordered)} symbols")
        print(f"  -> {args.out_dir}/\n  -> {args.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Measure whether the trigonometric-point symbol can be extracted. It cannot.

`config/legend_vocabulary.json` rated this class "easy" and noted that it
doubles as georeferencing control - the surveyed stations the sheet was built
on, with their heights printed. That made it the obvious next class to build.
It was the wrong call, and this script is the measurement that says so, kept in
the repository so the verdict can be re-checked rather than taken on trust.

**What the symbol actually is.** The legend draws a solid black triangle beside
a height: "375 |>". On the map body the glyph is different - an *open* triangle
about 13 px across with 1-2 px strokes and a dot at its centre, with the height
printed beside it. The legend simplifies; the body draws the real convention,
where the dot is the station and the triangle marks it as trigonometric.

**Three measurements, each of which rules out a route.**

1. *Colour does not separate the ink.* At the series' ~298 dpi, every thin dark
   stroke is one muddy class. Median chroma (max channel - min channel) over ink
   pixels, on the Kasserine sheet:

       black spot-height digits   20
       brown contours             28
       black lettering            29
       red grid line              29
       the trig triangle          41

   The triangle is *more* saturated than the contours it must be told apart
   from, and the black digits are *less* saturated than the black lettering.
   There is no threshold here. Only strongly saturated red separates, which is
   why the house and well detectors work and this one cannot.

2. *A purpose-built template scores a real one below the sheet's own noise.* The
   glyph is an open triangle with a centre dot, so the natural detector is the
   three-part test the well detector uses for a ring - inked on the rim, empty
   in the gap, inked at the centre. Run over the whole sheet against a confirmed
   trig point at (7226, 1369) on Kasserine:

       score at the confirmed trig point   1.655
       99.9th percentile of the sheet      1.782
       maximum                             2.000

   More than 66 000 pixels of the sheet look *more* like a trig point than a
   real trig point does. This is not a threshold that needs tuning; the ordering
   is wrong.

3. *Shape cannot separate the red variants from a house either.* The legend also
   designates a church and a marabout as trigonometric points, and those are
   drawn in saturated red - the one ink that does separate. But they sit in the
   same size band as the house mark, and the obvious roundness test is
   arithmetically incapable of the job: a square scores

       IoU(square, inscribed circle) = pi r^2 / 4 r^2 = pi/4 = 0.785

   against its own inscribed disc, at any size. Every house passed a 0.75
   threshold. Replacing it with an empty-corners test reached about 18%
   precision - 5 real glyphs in 28 candidates - because a house drawn as a
   diamond also leaves its bounding-box corners empty. Solidity against the
   convex hull is defeated by the red grid crossings unless the grid is masked
   first, which is a fix, but 18% precision is not.

**Why it is not merely a tuning problem.** The house mark is a *solid* 0.4 mm
block of saturated red - 16 px of ink that no thin line can imitate. The well is
a 0.5 mm ring in saturated blue, and isolated. The trig point is a 1.1 mm
*outline* whose strokes are 0.15 mm - 1.8 px at 298 dpi - drawn in an ink shared
with the contours, in the densest ink on the sheet, and routinely overprinted by
the dashed tracks and vegetation symbols that cross it. The confirmed example on
Kasserine has a dashed track running straight through it.

**What would work, and what it would cost.** Rescanning at 600 dpi would put the
strokes at 4 px and make the compound template viable. Short of that, the
tractable route is to invert the problem - find the printed height labels first,
which are large and legible, and test only their immediate neighbourhood for a
triangle. That reduces the false-positive opportunity from 66 million pixels to
a few hundred small windows. It needs a digit-cluster finder and OCR, which is
most of the toponym-OCR machinery that remains the long pole of this project.
It is a real piece of work, not a threshold change.

Usage:
    python3 scripts/probe_trig_points.py --images <dir of record_id.jpg>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.signal import fftconvolve

Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent

# Kasserine, the sheet the measurements above were taken on: mountainous, so it
# carries relief and spot heights in quantity, and its legend is the 1936
# functional edition exemplar.
PROBE_RECORD = "oai:u-bordeaux-montaigne.fr:340532"
# The one trigonometric point confirmed by eye on that sheet, and the legend's
# own glyph, both in scan pixels.
CONFIRMED_TRIG_PX = (7226, 1369)
LEGEND_GLYPH_PX = (7626, 6266)

# Windows on the probe sheet, each containing one kind of ink and little else.
INK_SAMPLES = {
    "black spot-height digits": (4050, 2650, 4130, 2700),
    "brown contours": (6500, 4700, 6600, 4780),
    "black lettering": (3300, 2350, 3500, 2420),
    "red grid line": (4000, 2000, 4100, 2010),
    "the trig triangle": (7216, 1358, 7240, 1382),
}

INK_LUMINANCE = 150          # anything darker than this is ink, not paper
TRIANGLE_SIDES = (15.0, 17.0, 19.0, 21.0)
RIM_PX = 2.6
DOT_PX = 2.4
GAP_WEIGHT = 1.4


def ink(array: np.ndarray) -> np.ndarray:
    return array.mean(axis=2) < INK_LUMINANCE


def chroma(array: np.ndarray) -> np.ndarray:
    return array.max(axis=2) - array.min(axis=2)


def triangle_parts(side: float):
    """Rim, gap and centre of an apex-up equilateral triangle.

    The same three-part shape as the well detector's annulus: something must be
    inked, something must be empty, and something inside must be inked again.
    """
    size = int(np.ceil(side)) + 5
    size += 1 - size % 2
    rows = np.arange(size)[:, None] - (size - 1) / 2.0
    columns = np.arange(size)[None, :] - (size - 1) / 2.0
    circumradius = side / np.sqrt(3.0)
    edges = []
    for corner in range(3):
        angle = -np.pi / 2 + corner * 2 * np.pi / 3
        edges.append(columns * np.cos(angle) + rows * np.sin(angle))
    depth = circumradius / 2.0 - np.max(edges, axis=0)
    solid = depth > 0
    rim = solid & (depth < RIM_PX)
    centre = np.hypot(rows, columns) <= DOT_PX
    gap = solid & ~rim & ~centre
    return (rim.astype(np.float32), gap.astype(np.float32),
            centre.astype(np.float32))


def compound_score(mask: np.ndarray) -> np.ndarray:
    """Best score over the plausible glyph sizes."""
    signal = mask.astype(np.float32)
    best = None
    for side in TRIANGLE_SIDES:
        rim, gap, centre = triangle_parts(side)

        def share(template):
            return (fftconvolve(signal, template[::-1, ::-1], mode="same")
                    / max(template.sum(), 1))

        score = share(rim) + share(centre) - GAP_WEIGHT * share(gap)
        best = score if best is None else np.maximum(best, score)
    return best


def report_chroma(image: Image.Image) -> None:
    print("1. Ink chroma by category - median over ink pixels in each window.\n"
          "   If colour separated these classes, the trig triangle would sit "
          "apart. It does not.\n")
    print(f"   {'ink':28s} {'px':>6s} {'luminance':>10s} {'chroma':>7s} "
          f"{'p90':>5s}")
    for label, box in INK_SAMPLES.items():
        array = np.asarray(image.crop(box)).astype(np.int16)
        inked = ink(array)
        if inked.sum() < 20:
            print(f"   {label:28s} too little ink in the window")
            continue
        values = chroma(array)[inked]
        print(f"   {label:28s} {inked.sum():6d} "
              f"{np.median(array.mean(axis=2)[inked]):10.0f} "
              f"{np.median(values):7.0f} {np.percentile(values, 90):5.0f}")


def report_template(image: Image.Image) -> None:
    print("\n2. The compound template, over the whole sheet.\n"
          "   A confirmed trig point should stand near the top. It does not "
          "reach the 99.9th percentile.\n")
    array = np.asarray(image).astype(np.int16)
    mask = ink(array)
    print(f"   ink share of the sheet {mask.mean():.3f}")
    score = compound_score(mask)
    for label, (x, y) in (("confirmed trig point", CONFIRMED_TRIG_PX),
                          ("the legend's own glyph", LEGEND_GLYPH_PX)):
        window = score[max(y - 7, 0):y + 7, max(x - 7, 0):x + 7]
        print(f"   score at {label:24s} {window.max():.3f}")
    for percentile in (99.0, 99.9, 99.99):
        print(f"   {percentile:6.2f}th percentile of the sheet "
              f"{np.percentile(score, percentile):.3f}")
    print(f"   maximum {score.max():.3f}")
    above = int((score > score[CONFIRMED_TRIG_PX[1] - 7:CONFIRMED_TRIG_PX[1] + 7,
                               CONFIRMED_TRIG_PX[0] - 7:CONFIRMED_TRIG_PX[0] + 7]
                 .max()).sum())
    print(f"\n   {above:,} pixels of this sheet score higher than the "
          f"confirmed trig point.")
    print("   That is the verdict: the ordering is wrong, so no threshold "
          "recovers the class.")


def report_geometry() -> None:
    print("\n3. Why roundness cannot separate the red variants from a house.\n")
    for side in (9, 13, 17, 21):
        rows = np.arange(side)[:, None] - (side - 1) / 2.0
        columns = np.arange(side)[None, :] - (side - 1) / 2.0
        disc = np.hypot(rows, columns) <= side / 2.0
        square = np.ones((side, side), bool)
        iou = (disc & square).sum() / (disc | square).sum()
        print(f"   a solid {side:2d}x{side:2d} square scores IoU {iou:.3f} "
              f"against its own inscribed disc")
    print(f"\n   The limit is pi/4 = {np.pi / 4:.3f}, independent of size, so a "
          f"roundness threshold\n   below that admits every house mark and one "
          f"above it rejects every disc.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True,
                        help="directory of record_id.jpg scans")
    parser.add_argument("--record", default=PROBE_RECORD)
    parser.add_argument("--skip-template", action="store_true",
                        help="skip measurement 2, which convolves the whole "
                             "scan and takes about a minute")
    args = parser.parse_args()

    path = args.images / f"{args.record}.jpg"
    if not path.exists():
        print(f"no scan at {path}", file=sys.stderr)
        return 1
    image = Image.open(path).convert("RGB")
    print(f"Probing {args.record} ({image.size[0]}x{image.size[1]})\n")
    report_chroma(image)
    if not args.skip_template:
        report_template(image)
    report_geometry()
    print("\nConclusion: the trigonometric-point symbol is below the floor of "
          "these scans.\n"
          "config/legend_vocabulary.json records this against the class, in "
          "place of the\n'easy' it used to claim.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

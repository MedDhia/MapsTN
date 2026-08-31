#!/usr/bin/env python3
"""Find how many distinct legends the series uses, and which sheet carries which.

The legend is a controlled vocabulary printed on the sheet, but it is not one
vocabulary and it is not on every sheet. Reading two exemplars at full
resolution shows the 1902 sheets naming four well-maintained road classes
(nationale, départementale, de grande communication, vicinal ou autre) where the
1930s sheets name three (de grand parcours, de moyenne communication, vicinal),
and the shrine row reading "Église, chapelle et marabout" early and "Église,
chapelle, koubba" late. Meanwhile the coupures spéciales print no symbol legend
at all - only a scale bar and an imprint - and rely on the series convention.

Coding a variable across the series without knowing which of the three a sheet
is silently pools two schemes and invents a legend for sheets that have none.

This does not attempt to transcribe. Tesseract on engraved copperplate italic
returns "Chemin d'erploitation et sentier mulclier" for "Chemin d'exploitation
et sentier muletier" - enough to ask whether a phrase is present, useless as a
transcription. The wording itself is read by eye from one exemplar per edition
and recorded in config/legend_vocabulary.json.

Two things had to be got right for the marker test to mean anything.

*Where the legend is.* A fixed fraction of sheet height does not work: the
legend starts at 0.84 of the Kasserine sheet and 0.89 of the 1902 Tunis sheet,
so a window tuned on one lands in the middle of the other's map and returns
noise. The margin is found instead by locating the paper within the dark
scanning board, then the largest brightness step in the lower half of it - the
map body is far darker than the margin below the neatline.

*Which words discriminate.* Most of the legend does not. Both editions print
"de commune de plein exercice", both name Oliviers and Palmiers in the Bois
inset, both write "Ravine sans eau en été", and both carry "Marabout" a second
time in "Clocher, Marabout: points trigonométriques" - so testing for
"marabout" alone matches every sheet. Only the road ladder and the word
"koubba" separate the editions, and the road ladder is in the leftmost panel,
which is also where OCR survives best.

Outputs:
    data/sheet_legends.json    per sheet: band, OCR text, variant
    data/sheet_legends.csv

Usage:
    python3 scripts/read_sheet_legends.py --images <dir of record_id.jpg>
    python3 scripts/read_sheet_legends.py --images <dir> --recompute
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

import pytesseract

Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent

PAPER_BRIGHTNESS = 140       # cream paper against the dark scanning board
PAPER_ROW_SHARE = 0.6        # share of a row that must be paper to count as paper
SEARCH_FROM = 0.55           # look for the neatline below this share of the paper
BAND_SKIP = 0.004            # start just below the neatline, not on it
PANELS = 6
BAND_UPSCALE = 2
ROADS_UPSCALE = 3
ROADS_WIDTH = 0.45           # the road ladder lives in the leftmost part
THRESHOLD = 0.4              # ink/paper cut, in standard deviations below mean

# Phrases that - unlike most of the legend - actually differ between editions,
# matched by bounded edit distance rather than by regex.
#
# A regex on "grand parcours" left thirteen sheets unclassified whose legend is
# plainly there: the phrase came back as "grand PaPCOUS", "frandpercours",
# "srandp arcours", "$rand PAPCOUTS". Every one of those is within three edits
# of the target once spacing and case are stripped, and none is within three
# edits of anything in the other edition, so a fuzzy match gains the sheets
# without risking a confusion.
#
# "Route" is kept as the anchor for the 1900s markers: a bare "nationale"
# matches "Institut Géographique National" in the imprint line, which put every
# IGN sheet in the 1900s edition, including one with no legend at all.
VARIANT_MARKERS = {
    # Truncated at "commun" because the 1902 sheet abbreviates its row as
    # "Chemin de grande commun.on et d'interet commun" - matching the full word
    # missed every sheet of that edition. Carrying the leading words is not
    # decoration: "grandecommun" and "moyennecommun" share a tail and sit close
    # enough that a garbled prefix satisfied both, which made three sheets
    # ambiguous. With the phrase in front they cannot collide.
    "1900s_administrative": ["routenationale", "routedepartementale",
                             "chemindegrandecommun"],
    "1930s_functional": ["grandparcours", "routedemoyennecommun", "koubba"],
}
# One edit per five characters, capped at two. A fixed budget of three was
# tried and is wrong: on a 1200-character noisy string a six-letter needle like
# "koubba" is within three edits of something by chance, which put both sheets
# that have no legend at all into an edition. Scaling with length allows
# "grandparcours" the two edits its worst real reading needs while giving
# "koubba" only one.
def edit_budget(needle: str) -> int:
    return max(1, min(2, len(needle) // 5))
# "Voies carrossables" heads the legend on every sheet that has one, and is the
# single most reliably OCR'd phrase in the band.
LEGEND_PRESENT_RE = re.compile(r"carross|chemins?\s*de\s*fer|passages?\s*de\s*riv",
                               re.IGNORECASE)
# The scale block and imprint are printed even on sheets with no symbol legend,
# so they separate "this sheet has no legend" from "nothing was read at all".
# Several alternatives because "Échelle" itself OCRs as "echolle" often enough
# to matter; the scale-bar numerals and the publisher line are set in clean
# type and survive where the engraved script does not.
MARGIN_READ_RE = re.compile(
    r"[eé]ch[eo]lle|kilom|m[eè]tres|50[.,]\s?000|g[eé]ographique|"
    r"reproduction|tirage|interdite",
    re.IGNORECASE)


def find_margin_band(image: Image.Image) -> tuple[float, float]:
    """Fractions of image height for the margin below the bottom neatline."""
    width, height = image.size
    array = np.asarray(image.resize((width // 8, height // 8),
                                    Image.BILINEAR)).astype(np.float32)
    rows, columns = array.shape

    paper = array > PAPER_BRIGHTNESS
    paper_rows = np.where(paper.mean(axis=1) > PAPER_ROW_SHARE)[0]
    paper_columns = np.where(paper.mean(axis=0) > PAPER_ROW_SHARE)[0]
    if paper_rows.size == 0 or paper_columns.size == 0:
        return (0.82, 0.99)
    top, bottom = paper_rows[0], paper_rows[-1]
    left, right = paper_columns[0], paper_columns[-1]

    inner = array[top:bottom, left:right]
    inner_height, inner_width = inner.shape
    profile = inner[:, int(inner_width * 0.15):int(inner_width * 0.85)].mean(axis=1)

    # The neatline is where the page stops being map and starts being margin,
    # which is a step up in brightness rather than a dark line: at this
    # downsampling the line itself is a couple of pixels and blurs away.
    span = max(3, inner_height // 120)
    step = np.zeros(inner_height)
    for index in range(span, inner_height - span):
        step[index] = (profile[index:index + span].mean()
                       - profile[index - span:index].mean())
    start = int(inner_height * SEARCH_FROM)
    neatline = top + start + int(np.argmax(step[start:]))

    return (min(neatline / rows + BAND_SKIP, 0.97), bottom / rows)


def ocr(image: Image.Image, box: tuple[int, int, int, int], upscale: int) -> str:
    crop = image.crop(box)
    if crop.width < 10 or crop.height < 10:
        return ""
    crop = crop.resize((crop.width * upscale, crop.height * upscale), Image.LANCZOS)
    array = np.asarray(crop)
    cut = array.mean() - array.std() * THRESHOLD
    binary = Image.fromarray(np.where(array < cut, 0, 255).astype(np.uint8))
    return " ".join(pytesseract.image_to_string(
        binary, lang="fra", config="--psm 6").split())


def read_band(path: Path) -> dict:
    image = Image.open(path).convert("L")
    width, height = image.size
    band_top, band_bottom = find_margin_band(image)
    top, bottom = int(height * band_top), int(height * band_bottom)

    pieces = [ocr(image, (int(width * p / PANELS), top,
                          int(width * (p + 1) / PANELS), bottom), BAND_UPSCALE)
              for p in range(PANELS)]
    roads = ocr(image, (0, top, int(width * ROADS_WIDTH), bottom), ROADS_UPSCALE)

    return {
        "band_top": round(band_top, 4),
        "band_bottom": round(band_bottom, 4),
        "legend_text": " ".join(" ".join(pieces).split())[:1200],
        "roads_text": roads[:600],
    }


def squash(text: str) -> str:
    """Lowercase letters only: OCR scatters spacing and punctuation freely."""
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", text.lower())
                  .encode("ascii", "ignore").decode())


def edit_distance(a: str, b: str, cap: int) -> int:
    """Levenshtein distance, abandoned once it is known to exceed `cap`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        if min(current) > cap:
            return cap + 1
        previous = current
    return previous[-1]


def contains_fuzzy(haystack: str, needle: str, cap: int) -> bool:
    """Is `needle` present in `haystack` within `cap` edits, anywhere?"""
    if needle in haystack:
        return True
    length = len(needle)
    for start in range(0, max(1, len(haystack) - length + cap + 1)):
        for width in range(max(1, length - cap), length + cap + 1):
            window = haystack[start:start + width]
            if window and edit_distance(window, needle, cap) <= cap:
                return True
    return False


def classify(found: dict) -> dict:
    text = squash(f"{found.get('legend_text', '')} {found.get('roads_text', '')}")
    hits = {name: [m for m in markers
                   if contains_fuzzy(text, m, edit_budget(m))]
            for name, markers in VARIANT_MARKERS.items()}
    scores = {name: len(found_markers) for name, found_markers in hits.items()}

    raw = f"{found.get('legend_text', '')} {found.get('roads_text', '')}"
    has_legend = bool(LEGEND_PRESENT_RE.search(raw))
    best = max(scores, key=lambda n: scores[n])
    other = min(scores, key=lambda n: scores[n])

    if not has_legend and max(scores.values()) == 0:
        variant = "no_symbol_legend" if MARGIN_READ_RE.search(raw) else "unread"
        confidence = "band_read" if variant == "no_symbol_legend" else "none"
    elif scores[best] == 0:
        variant, confidence = "legend_present_edition_unread", "none"
    elif scores[best] == scores[other]:
        # The two vocabularies do not overlap on paper, so a tie is an
        # unreadable sheet rather than a hybrid one.
        variant, confidence = "ambiguous", "tied"
    else:
        variant = best
        confidence = "strong" if scores[best] >= 2 else "weak"

    return {
        "legend_variant": variant,
        "legend_confidence": confidence,
        "has_symbol_legend": has_legend,
        "marker_hits": {n: sorted(f) for n, f in hits.items() if f},
        "marker_scores": scores,
    }


CSV_FIELDS = [
    "record_id", "designation", "sheet_name", "catalogue_year",
    "legend_variant", "legend_confidence", "has_symbol_legend",
    "markers_1900s", "markers_1930s", "band_top",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--series", type=Path,
                        default=REPO_ROOT / "data" / "tunisia_50k_series.csv")
    parser.add_argument("--out-json", type=Path,
                        default=REPO_ROOT / "data" / "sheet_legends.json")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "sheet_legends.csv")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--recompute", action="store_true",
                        help="re-classify the cached OCR text without re-reading "
                             "the scans")
    args = parser.parse_args()

    sheets = {r["record_id"]: r
              for r in csv.DictReader(args.series.open(encoding="utf-8"))}

    results: dict = {}
    if args.out_json.exists():
        results = json.loads(args.out_json.read_text(encoding="utf-8"))

    if args.recompute:
        for record_id, found in results.items():
            if "legend_text" in found:
                base = {k: found[k] for k in
                        ("band_top", "band_bottom", "legend_text", "roads_text")
                        if k in found}
                results[record_id] = {**base, **classify(base)}
        print(f"re-classified {len(results)} cached readings")

    files = sorted(args.images.glob("*.jpg"))
    pending = [] if args.recompute else [f for f in files if f.stem not in results]
    cached = len(files) - len(pending)
    if args.limit:
        pending = pending[:args.limit]
    print(f"{len(files)} scans, {cached} cached, {len(pending)} to read")

    for index, path in enumerate(pending, 1):
        try:
            band = read_band(path)
            results[path.stem] = {**band, **classify(band)}
        except Exception as error:
            results[path.stem] = {"error": str(error)}
        found = results[path.stem]
        name = sheets.get(path.stem, {}).get("sheet_name") or path.stem
        print(f"  {index}/{len(pending)} {name[:22]:<22} "
              f"band={found.get('band_top', '-')} "
              f"{found.get('legend_variant', '-'):<30} "
              f"{found.get('legend_confidence', '-')}", flush=True)
        args.out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    args.out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    rows = []
    for record_id, found in sorted(results.items()):
        sheet = sheets.get(record_id, {})
        scores = found.get("marker_scores", {})
        rows.append({
            "record_id": record_id,
            "designation": sheet.get("designation", ""),
            "sheet_name": sheet.get("sheet_name", ""),
            "catalogue_year": sheet.get("revision_year") or sheet.get("published_year", ""),
            "legend_variant": found.get("legend_variant", ""),
            "legend_confidence": found.get("legend_confidence", ""),
            "has_symbol_legend": int(bool(found.get("has_symbol_legend"))),
            "markers_1900s": scores.get("1900s_administrative", ""),
            "markers_1930s": scores.get("1930s_functional", ""),
            "band_top": found.get("band_top", ""),
        })

    with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{len(rows)} sheets: {dict(Counter(r['legend_variant'] for r in rows))}")
    for name in VARIANT_MARKERS:
        years = sorted(int(r["catalogue_year"]) for r in rows
                       if r["legend_variant"] == name and r["catalogue_year"])
        if years:
            print(f"  {name}: catalogue years {years[0]}-{years[-1]}, n={len(years)}")
    print(f"  -> {args.out_json}\n  -> {args.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

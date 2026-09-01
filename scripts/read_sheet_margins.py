#!/usr/bin/env python3
"""Read the marginalia off each sheet: who surveyed it, when, and to what spec.

The catalogue gives one date per sheet. The sheet gives at least three, and they
are decades apart. The Kairouan sheet is catalogued as 1927; printed on it are
fieldwork of 1898, a revision, and a print run of September 1936. Medenine is
catalogued 1933 and carries fieldwork of 1906-07. For anything that reads change
over time off these maps, the fieldwork date is the one that matters, and it is
the one the catalogue does not have.

Four blocks are read, each in a fixed part of the margin:

  top-left    an index diagram cutting the sheet into lettered zones, with an
              officer and a year against each letter. This is why the survey
              date is a range, not a date: one sheet is several field seasons.
  bottom      publisher, contour interval, print run, price. The publisher
              changes from Service geographique de l'Armee to Institut
              geographique national in 1940, which dates a print on its own.
  right       the magnetic declination diagram, with the epoch it is good for.
  top-centre  the sheet name and its grid designation.

OCR on engraved copperplate script is poor - names come back mangled and are not
worth keeping. Years are four digits in a narrow plausible range, so they
survive OCR damage where names do not, and years are what the research needs.
Each field records how it was obtained so a reader can tell a parsed value from
a guessed one.

Outputs:
    data/sheet_margins.json
    data/sheet_margins.csv

Usage:
    python3 scripts/read_sheet_margins.py --images <dir of record_id.jpg>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import pytesseract

Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent

# Fieldwork on this series runs from the first survey after the 1881 protectorate
# to the 1940s. A wider window (1850-1959) let OCR noise through as fieldwork
# dates: a "1854" on the Cap Bon sheet, and 1950-52 on four sheets whose real
# fieldwork was in the 1890s.
YEAR_RE = re.compile(r"\b(188\d|189\d|19[0-4]\d)\b")
EQUIDISTANCE_RE = re.compile(r"[ée]quidistance.{0,40}?(\d{1,3})\s*m", re.IGNORECASE)
TIRAGE_RE = re.compile(r"tirage\s*(?:de\s*)?([A-Za-zÀ-ÿ]+)?\s*(\d{4})", re.IGNORECASE)
PRICE_RE = re.compile(r"prix\s*[:.]?\s*(\d{1,4})\s*fr", re.IGNORECASE)
REVISED_RE = re.compile(r"r[ée]vis[ée]?\w*\s+(?:en\s+)?(\d{4})", re.IGNORECASE)
# The declination note reads "La declinaison magnetique ... au 1er janvier 1942".
# Anchoring on "declinaison" fails: in fine red type it OCRs as "Uéclinalwun",
# "Dalinalen", "Léchinaiess". "janvier" survives, and the year range rejects the
# occasional 1288.
DECLINATION_EPOCH_RE = re.compile(
    r"j[au]nv\w{0,4}\.?\s*(18[5-9]\d|19[0-5]\d)", re.IGNORECASE)
# "Dresse, heliograve et publie par le Service geographique de l'Armee en 1936"
IMPRINT_YEAR_RE = re.compile(
    r"(?:arm[ée]e|national)\D{0,12}?(\d{4})", re.IGNORECASE)

IGN_RE = re.compile(r"institut\s+g[ée]ographique\s+national", re.IGNORECASE)
SGA_RE = re.compile(r"service\s+g[ée]ographique\s+de\s+l\s*['’]?\s*arm[ée]e", re.IGNORECASE)

# Fractions of the image; the sheet layout is stable enough across the series
# that fixed windows beat trying to find the blocks. The footer is cut into
# thirds: Tesseract's runtime grows badly with page width, and a 9500 px strip
# takes minutes as one image and seconds as three.
# Two credits windows, not one tall one. The 1902 sheets set the block higher
# than the 1930s sheets, but a window covering both also swallows the title and
# the grid labels, and Tesseract in single-block mode degrades badly on mixed
# content: widening the window cost three of the four fieldwork dates it had
# already found. So each candidate position is read separately and the one that
# actually contains the block is chosen by its anchor phrase.
CREDITS_WINDOWS = [
    (0.02, 0.045, 0.32, 0.120),   # 1920s-1940s sheets
    (0.02, 0.012, 0.34, 0.080),   # 1902 sheets
]
CREDITS_ANCHOR_RE = re.compile(r"travau|terrain|ex[ée]cut", re.IGNORECASE)

# A third window, taken from the detected neatline instead of the page. The two
# fixed windows above are set at page fractions, and between them they classify
# the credits block on 35 of the 96 scans. The block actually sits just above the
# neatline's top-left corner on every layout in the series, and adding a window
# cropped there takes it to 50, the anchor phrase from 67 sheets to 86, and the
# fieldwork year from 65 to 71 - among the seven newly read are Porto-Farina
# 1900, Enfida 1893 and Halk El Mennzel 1892, all three confirming a block that
# had been read by eye. Every one of the seven also moves from an unanchored
# reading to an anchored one.
#
# It costs one year: Nebeur's 1914 was an unanchored reading, and the neatline
# crop reads its block properly but OCRs the date as "19/4". That is the right
# trade - an anchored no-answer over an unanchored guess.
#
# Measured against eighteen blocks read by eye: 10 agree, 0 contradict, 8 the OCR
# still cannot read - so the window only ever adds, and its misses stay misses
# rather than becoming wrong answers.
#
# It needs the neatline, which comes from the georeferencing, so it is skipped
# when that is not available - which is why it supplements the page windows
# rather than replacing them.
CREDITS_NEATLINE_ABOVE = (0.085, 0.003)   # page-height fractions above the top
CREDITS_NEATLINE_WIDTH = 0.26             # page-width fraction from the left
CREDITS_NEATLINE_LEFT_PAD = 140           # px left of the neatline
# Below this the window is degenerate and is skipped rather than cropped.
CREDITS_NEATLINE_MIN_PX = 60

# The two forms the block is set in, and the difference matters: an original
# survey lists the officers who did it, a revised or compiled sheet indexes
# sub-areas with their dates. On the nine sheets held in two printings, the form
# is what distinguishes the two that were really resurveyed (Porto-Farina,
# Ariana) from the seven that are reprints of one survey - see
# scripts/difference_editions.py.
# "apres les travaux" without the leading "D'": the apostrophe comes back as a
# typographic quote, a backtick or nothing at all, and Bizerte OCRs the whole
# opening as "| | D D 'apres les travaux :" - which the stricter pattern missed.
# Dropping the D' costs nothing, because "apres les travaux" does not occur in
# the officers form ("Les Travaux sur le Terrain ont ete executes par...").
CREDITS_COMPILED_RE = re.compile(r"apr[eèéêë]s\s+l?e?s?\s*travau", re.IGNORECASE)
CREDITS_OFFICERS_RE = re.compile(r"travau.{0,20}terr?ain", re.IGNORECASE)

WINDOWS = {
    "footer": [(0.00, 0.820, 0.35, 1.000),
               (0.35, 0.820, 0.70, 1.000),
               (0.70, 0.820, 1.00, 1.000)],
    "declination": [(0.86, 0.280, 1.00, 0.720)],
}
# The footer is set in ordinary type at 300 dpi and needs no help; the credits
# block is engraved script at half the size.
UPSCALE = {"footer": 1, "declination": 2}
CREDITS_UPSCALE = 2
# How far below the crop's mean to put the ink/paper cut. The credits block is
# dense black script and tolerates a high cut; the footer is fine light type on
# foxed paper and loses whole lines unless the cut sits close to the mean.
THRESHOLD = {"footer": 0.4, "declination": 0.9}
CREDITS_THRESHOLD = 0.9
# The declination note is printed in red, so it is picked out by colour rather
# than by darkness - against cream paper it is not dark at all.
RED_WINDOWS = {"declination"}


def binarise(crop: Image.Image, invert_threshold: float) -> Image.Image:
    array = np.asarray(crop.convert("L"))
    # Paper is cream and ink is dark; a fixed threshold fails on foxed sheets,
    # so threshold relative to this crop's own distribution.
    threshold = array.mean() - array.std() * invert_threshold
    return Image.fromarray(np.where(array < threshold, 0, 255).astype(np.uint8))


def binarise_red(crop: Image.Image) -> Image.Image:
    array = np.asarray(crop.convert("RGB")).astype(np.int16)
    red, green, blue = array[..., 0], array[..., 1], array[..., 2]
    mask = (red - green > 40) & (red - blue > 30) & (red > 110)
    return Image.fromarray(np.where(mask, 0, 255).astype(np.uint8))


def ocr(image: Image.Image, window: tuple[float, float, float, float],
        upscale: int = 2, invert_threshold: float = 0.9,
        red: bool = False) -> str:
    width, height = image.size
    x0, y0, x1, y1 = window
    crop = image.crop((int(x0 * width), int(y0 * height),
                       int(x1 * width), int(y1 * height)))
    if upscale > 1:
        crop = crop.resize((crop.width * upscale, crop.height * upscale),
                           Image.LANCZOS)
    binary = binarise_red(crop) if red else binarise(crop, invert_threshold)
    return " ".join(pytesseract.image_to_string(
        binary, lang="fra", config="--psm 6").split())


def neatline_window(image: Image.Image,
                    neatline: dict) -> tuple[float, float, float, float] | None:
    """The credits window as page fractions, derived from the detected neatline.

    None when the neatline leaves no room above it. Kalaat es Senam's detected
    frame has top = -60 - the detector put it just off the page - so both edges
    of the window clamp to zero, and a zero-height crop is not a crop: Tesseract
    raises and the sheet loses every field, not just this one. Guarding here
    rather than at the call site because the window is what is degenerate.
    """
    width, height = image.size
    x0 = max(neatline["left"] - CREDITS_NEATLINE_LEFT_PAD, 0) / width
    y0 = max(neatline["top"] - CREDITS_NEATLINE_ABOVE[0] * height, 0) / height
    x1 = min(neatline["left"] / width + CREDITS_NEATLINE_WIDTH, 1.0)
    y1 = max(neatline["top"] - CREDITS_NEATLINE_ABOVE[1] * height, 0) / height
    if (x1 - x0) * width < CREDITS_NEATLINE_MIN_PX:
        return None
    if (y1 - y0) * height < CREDITS_NEATLINE_MIN_PX:
        return None
    return (x0, y0, x1, y1)


def read_text(path: Path, neatline: dict | None = None) -> dict:
    """Everything that costs a Tesseract call. Kept apart from the parsing so a
    changed rule can be re-applied to the cached text - see --recompute."""
    image = Image.open(path).convert("RGB")
    text = {f"{name}_text": " ".join(
                ocr(image, window, UPSCALE[name], THRESHOLD[name],
                    red=name in RED_WINDOWS)
                for window in windows)[:400]
            for name, windows in WINDOWS.items()}

    # Years are only trusted from a window that demonstrably contains the
    # credits block. Without the anchor test, a window that caught the grid
    # labels instead returned a "fieldwork year" of 1951 for a sheet surveyed
    # in the 1890s.
    windows = list(CREDITS_WINDOWS)
    if neatline:
        from_neatline = neatline_window(image, neatline)
        if from_neatline:
            windows.append(from_neatline)
    candidates = [ocr(image, window, CREDITS_UPSCALE, CREDITS_THRESHOLD)
                  for window in windows]
    anchored = [c for c in candidates if CREDITS_ANCHOR_RE.search(c)]
    # Falling back to an unanchored window keeps the sheets whose anchor phrase
    # OCR'd badly - the block is there, "Les Travaux" is not legible - but those
    # years are worth less than anchored ones and are labelled as such.
    text["credits_text"] = (anchored[0] if anchored
                            else max(candidates, key=len))[:400]
    text["survey_years_basis"] = "anchored" if anchored else "unanchored"
    text["credits_window"] = ("neatline"
                              if neatline and anchored
                              and anchored[0] == candidates[-1]
                              else "page_fraction")
    return text


def extract(text: dict) -> dict:
    found: dict = {k: v for k, v in text.items()}

    survey_years = sorted({int(y) for y in YEAR_RE.findall(text["credits_text"])})
    if survey_years:
        found["survey_years"] = survey_years
        found["survey_year_min"] = survey_years[0]
        found["survey_year_max"] = survey_years[-1]
        found["survey_years_read"] = len(survey_years)

    # Which of the two forms the block is set in. "compiled" is tested first:
    # a revised sheet's block often still contains the word "travaux", so the
    # officers pattern would match it too.
    credits = text["credits_text"]
    if CREDITS_COMPILED_RE.search(credits):
        found["credit_form"] = "compiled"
    elif CREDITS_OFFICERS_RE.search(credits):
        found["credit_form"] = "officers"

    footer = text["footer_text"]
    equidistance = EQUIDISTANCE_RE.search(footer)
    if equidistance:
        found["contour_interval_m"] = int(equidistance.group(1))
    tirage = TIRAGE_RE.search(footer)
    if tirage:
        found["print_run_year"] = int(tirage.group(2))
        if tirage.group(1):
            found["print_run_month"] = tirage.group(1)
    price = PRICE_RE.search(footer)
    if price:
        found["price_francs"] = int(price.group(1))
    revised = REVISED_RE.search(footer)
    if revised:
        found["revised_on_sheet"] = int(revised.group(1))

    # The imprint line names the compiling body, which dates the sheet on its
    # own: the Service geographique de l'Armee became the Institut geographique
    # national in 1940. Both can appear on one sheet - drawn by the SGA before
    # the war, printed by the IGN after it - so IGN is tested first only to name
    # the later of the two, and the imprint year is kept separately.
    if IGN_RE.search(footer):
        found["publisher_on_sheet"] = "IGN"
    elif SGA_RE.search(footer):
        found["publisher_on_sheet"] = "SGA"
    imprint = IMPRINT_YEAR_RE.search(footer)
    if imprint and 1850 <= int(imprint.group(1)) <= 1955:
        found["imprint_year"] = int(imprint.group(1))

    epoch = DECLINATION_EPOCH_RE.search(text["declination_text"])
    if epoch:
        found["declination_epoch"] = int(epoch.group(1))
    return found


def analyse(path: Path, neatline: dict | None = None) -> dict:
    return extract(read_text(path, neatline))


CSV_FIELDS = [
    "record_id", "designation", "sheet_name",
    "catalogue_year", "survey_year_min", "survey_year_max", "survey_years_read",
    "survey_years_basis", "credit_form", "credits_window",
    "revised_on_sheet", "imprint_year", "print_run_month", "print_run_year",
    "publisher_on_sheet", "contour_interval_m", "declination_epoch",
    "price_francs", "catalogue_to_survey_gap_years",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--series", type=Path,
                        default=REPO_ROOT / "data" / "tunisia_50k_series.csv")
    parser.add_argument("--out-json", type=Path,
                        default=REPO_ROOT / "data" / "sheet_margins.json")
    parser.add_argument("--out-csv", type=Path,
                        default=REPO_ROOT / "data" / "sheet_margins.csv")
    parser.add_argument("--neatlines", type=Path, nargs="*",
                        default=[REPO_ROOT / "data" / "sheet_georef.json",
                                 REPO_ROOT / "data" / "sheet_graticule.json",
                                 REPO_ROOT / "data" / "sheet_corner_fit.json",
                                 REPO_ROOT / "data" / "sheet_grid.json"],
                        help="where to look for a detected neatline, for the "
                             "credits window taken from it")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--recompute", action="store_true",
                        help="re-parse the cached OCR text without re-reading "
                             "the scans")
    args = parser.parse_args()

    sheets = {r["record_id"]: r
              for r in csv.DictReader(args.series.open(encoding="utf-8"))}

    # The neatline the georeferencing detected, for the third credits window.
    # Absent on the first pass over a fresh checkout, which is why the two page
    # windows stay: this only ever adds coverage.
    neatlines: dict = {}
    for source in args.neatlines:
        if not source.exists():
            continue
        for key, value in json.loads(
                source.read_text(encoding="utf-8")).items():
            if isinstance(value, dict) and "neatline_px" in value:
                neatlines.setdefault(key, value["neatline_px"])

    results: dict = {}
    if args.out_json.exists():
        results = json.loads(args.out_json.read_text(encoding="utf-8"))

    if args.recompute:
        for record_id, found in results.items():
            if "credits_text" in found:
                results[record_id] = extract(
                    {k: v for k, v in found.items() if k.endswith("_text")
                     or k == "survey_years_basis"})
        print(f"re-parsed {len(results)} cached OCR readings")

    files = sorted(args.images.glob("*.jpg"))
    pending = [] if args.recompute else [f for f in files if f.stem not in results]
    cached = len(files) - len(pending)
    if args.limit:
        pending = pending[:args.limit]
    print(f"{len(files)} scans, {cached} cached, {len(pending)} to read")

    for index, path in enumerate(pending, 1):
        try:
            results[path.stem] = analyse(path, neatlines.get(path.stem))
        except Exception as error:
            results[path.stem] = {"error": str(error)}
        found = results[path.stem]
        name = sheets.get(path.stem, {}).get("sheet_name") or path.stem
        print(f"  {index}/{len(pending)} {name[:22]:<22} "
              f"survey={found.get('survey_year_min', '-')}-{found.get('survey_year_max', '-')} "
              f"tirage={found.get('print_run_year', '-')} "
              f"equid={found.get('contour_interval_m', '-')}m "
              f"pub={found.get('publisher_on_sheet', '-')} "
              f"form={found.get('credit_form', '-')}", flush=True)
        args.out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    # Write it back here too. The only other write is inside the loop over
    # pending scans, and --recompute leaves that loop empty - so a re-parse used
    # to update the CSV and leave the JSON holding the previous rules, exactly
    # the bug detect_sheet_grid.py had.
    args.out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    rows = []
    dropped = 0
    for record_id, found in sorted(results.items()):
        sheet = sheets.get(record_id, {})
        catalogue_year = sheet.get("revision_year") or sheet.get("published_year") or ""

        # Fieldwork cannot postdate the sheet that reports it. Where the
        # catalogue gives a year, drop any read year later than it: those are
        # OCR damage, and they were inflating the survey range on four sheets
        # (1890-1952 on Djebel Ichkeul, whose real range ends in the 1890s).
        years = found.get("survey_years") or []
        if years and catalogue_year:
            kept = [y for y in years if y <= int(catalogue_year)]
            if kept != years:
                dropped += 1
                found = {**found,
                         "survey_year_min": kept[0] if kept else "",
                         "survey_year_max": kept[-1] if kept else "",
                         "survey_years_read": len(kept)}

        gap = ""
        if catalogue_year and found.get("survey_year_min"):
            gap = int(catalogue_year) - int(found["survey_year_min"])
        rows.append({
            "record_id": record_id,
            "designation": sheet.get("designation", ""),
            "sheet_name": sheet.get("sheet_name", ""),
            "catalogue_year": catalogue_year,
            "catalogue_to_survey_gap_years": gap,
            **{k: found.get(k, "") for k in CSV_FIELDS
               if k not in ("record_id", "designation", "sheet_name",
                            "catalogue_year", "catalogue_to_survey_gap_years")},
        })

    with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    dated = [r for r in rows if r["survey_year_min"]]
    print(f"\n{len(rows)} sheets: {len(dated)} with a fieldwork year read off the sheet")
    if dropped:
        print(f"  {dropped} sheet(s) had an OCR'd year later than the sheet itself, dropped")
    if dated:
        gaps = [int(r["catalogue_to_survey_gap_years"]) for r in dated
                if r["catalogue_to_survey_gap_years"] != ""]
        if gaps:
            print(f"  catalogue year runs a median {int(np.median(gaps))} years "
                  f"later than the fieldwork (max {max(gaps)})")
    print(f"  -> {args.out_json}\n  -> {args.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

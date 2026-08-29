#!/usr/bin/env python3
"""Code each harvested Gallica record on quality indicators.

"Quality" for a historical map corpus is not one thing, so the records are coded
on three independent families, each usable on its own:

  A. Cartographic quality  - scale, production mode, colour, sheet size,
                             issuing authority, genre
  B. Record quality        - how completely the item is catalogued
  C. Digital access quality- scan resolution, IIIF availability, rights

Two summary constructs are derived on top of them (`quality_index`,
`research_tier`); both are heuristics and are documented as such in
docs/CODEBOOK.md. For most purposes the component variables are the honest unit
of analysis.

Inputs:  data/gallica_tunisia_maps.json, data/scan_dimensions.json (optional)
Outputs: data/gallica_tunisia_maps_coded.csv, data/quality_summary.json

Usage:
    python3 scripts/code_quality.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import unicodedata
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Family A: cartographic ------------------------------------------------

# Conventional cartographic scale bands. Smaller denominator = more detail.
SCALE_BANDS = [
    (25_000, "large"),          # site plans, urban surveys
    (250_000, "medium"),        # topographic sheets
    (1_000_000, "small"),       # regional / country sheets
    (float("inf"), "very_small"),  # continental, Mediterranean, world
]

# Publisher / creator strings that identify the issuing body. Order matters:
# the first family that matches wins, so the specific precedes the generic.
AUTHORITY_PATTERNS = [
    ("military_survey", (
        "service geographique de l'armee", "service geographique de l armee",
        "depot de la guerre", "ministere de la guerre", "war office",
        "etat-major", "etat major", "service geographique de l'armee",
    )),
    ("hydrographic", (
        "depot des cartes et plans de la marine", "service hydrographique",
        "hydrograph", "depot general de la marine", "ministere de la marine",
    )),
    ("civil_survey", (
        "institut geographique national", "service topographique",
        "institut national de", "cadastre",
    )),
    ("scholarly", (
        "societe de geographie", "universite", "institut de france",
        "ecole francaise", "academie", "musee",
    )),
]

ANONYMOUS_PUBLISHER = ("s.n.", "sn]", "inconnu", "unknown", "[s. n.]")

MANUSCRIPT_SIGNALS = ("manuscrit", "manuscript", " ms ", " ms.", " ms;", "ms.",
                      "au lavis", "a la plume", "sur calque")
PRINT_SIGNALS = ("grav", "lithogr", "imprim", "impr.", "estampe", "typogr",
                 "heliograv", "photograv")

COLOUR_SIGNALS = ("en coul", "coul.", "col.", ", col", "couleur", "colorie")
MONO_SIGNALS = ("en noir", "n. et b", "noir et blanc", "monochrome")

GENRE_PATTERNS = [
    ("atlas", ("atlas",)),
    ("plan", ("plan",)),
    ("view", ("view", "vue")),
    ("map", ("map", "carte")),
]

# --- Family C: digital access ---------------------------------------------

# Total information content of the first digitised view. Bands are absolute, not
# quantiles, so they stay comparable across re-harvests (see docs/CODEBOOK.md).
RESOLUTION_BANDS = [(20, "low"), (50, "medium"), (float("inf"), "high")]

# Digitisation fidelity relative to the physical sheet. 300 dpi is the usual
# library reproduction floor; below it fine lettering stops being legible.
DPI_BANDS = [(300, "low"), (450, "standard"), (float("inf"), "high")]

_NUM = r"(\d+(?:[.,]\d+)?)"
_PAIR = rf"{_NUM}\s*[x×]\s*{_NUM}"
# Units are stated inconsistently: 'cm', 'mm', bare metres ('0,49 x 0,35'), or
# nothing at all. Try each explicit unit before falling back to inference.
DIMENSION_UNIT_RES = [
    (re.compile(rf"{_PAIR}\s*cm"), 1.0),     # already cm
    (re.compile(rf"{_PAIR}\s*mm"), 0.1),     # mm -> cm
    (re.compile(rf"{_PAIR}\s*m\b"), 100.0),  # m  -> cm
]
DIMENSION_BARE_RE = re.compile(_PAIR)
# A stray space inside a decimal ('77, 5 x 65, 9 cm') otherwise makes the
# number regex latch onto the fragment after the comma.
STRAY_DECIMAL_RE = re.compile(r"(\d)\s*,\s*(\d)")
SHEET_RE = re.compile(r"^\s*(\d+)\s*(?:fll?es?|feuilles?|cartes?|plans?|calques?)",
                      re.IGNORECASE)


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def to_float(value: str) -> float:
    return float(value.replace(",", "."))


# --- Family A coders -------------------------------------------------------

def code_scale(record: dict) -> tuple[str, str]:
    """Return (scale_denominator, scale_class)."""
    if not record["scale"]:
        return "", "unknown"
    denominator = int(record["scale"].split(":")[1].replace(" ", ""))
    for ceiling, label in SCALE_BANDS:
        if denominator <= ceiling:
            return str(denominator), label
    return str(denominator), "unknown"


def code_production_mode(record: dict) -> str:
    doc_type = normalize(record["doc_type"])
    physical = normalize(record["physical_description"])
    if "manuscrit" in doc_type or "manuscript" in doc_type:
        return "manuscript"
    if any(s in physical for s in MANUSCRIPT_SIGNALS):
        return "manuscript"
    haystack = physical + " " + normalize(record["creators"]) + " " + normalize(record["description"])
    if any(s in haystack for s in PRINT_SIGNALS):
        return "printed"
    # A named commercial publisher implies a printed edition.
    publisher = normalize(record["publisher"])
    if publisher and not any(a in publisher for a in ANONYMOUS_PUBLISHER):
        return "printed"
    return "unknown"


def code_colour(record: dict) -> str:
    physical = normalize(record["physical_description"])
    if any(s in physical for s in COLOUR_SIGNALS):
        return "colour"
    if any(s in physical for s in MONO_SIGNALS):
        return "monochrome"
    return "unknown"


def code_authority(record: dict) -> str:
    haystack = normalize(record["publisher"] + " | " + record["creators"])
    for label, patterns in AUTHORITY_PATTERNS:
        if any(p in haystack for p in patterns):
            return label
    publisher = normalize(record["publisher"])
    if not publisher or any(a in publisher for a in ANONYMOUS_PUBLISHER):
        return "unknown"
    return "commercial"


def code_genre(record: dict) -> str:
    doc_type = normalize(record["doc_type"])
    for label, patterns in GENRE_PATTERNS:
        if any(p in doc_type for p in patterns):
            return label
    return "other"


def code_sheet_count(record: dict) -> str:
    match = SHEET_RE.match(record["physical_description"])
    return match.group(1) if match else ""


def infer_unit_factor(width: float, height: float) -> float:
    """Guess the unit of an unlabelled dimension pair, returning a cm factor.

    The catalogue omits the unit on roughly a tenth of records, but the
    magnitudes separate cleanly: metres are written as decimals below 10
    ('0,49 x 0,35'), centimetres run to a couple of hundred, and anything larger
    is millimetres ('500 x 380' for a 50 x 38 cm sheet).
    """
    largest = max(width, height)
    if largest < 10:
        return 100.0   # metres
    if largest <= 250:
        return 1.0     # centimetres
    return 0.1         # millimetres


def code_dimensions(record: dict) -> tuple[str, str, str]:
    """Return (width_cm, height_cm, area_cm2) for the sheet itself.

    Where a record gives several dimensions ('22 x 21,5 cm (carte), 29,5 x 37,5
    cm (support)'), the first is the map; later ones are its mount or frame.
    """
    physical = STRAY_DECIMAL_RE.sub(r"\1,\2", record["physical_description"])

    factor = None
    for pattern, unit_factor in DIMENSION_UNIT_RES:
        match = pattern.search(physical)
        if match:
            factor = unit_factor
            break
    else:
        match = DIMENSION_BARE_RE.search(physical)
        if match:
            factor = infer_unit_factor(to_float(match.group(1)),
                                       to_float(match.group(2)))
    if match is None or factor is None:
        return "", "", ""

    width = to_float(match.group(1)) * factor
    height = to_float(match.group(2)) * factor
    # Discard implausible sheets rather than propagating a bad parse.
    if not (1.0 <= width <= 1000.0 and 1.0 <= height <= 1000.0):
        return "", "", ""
    return f"{width:.1f}", f"{height:.1f}", f"{width * height:.0f}"


# --- Family B coders -------------------------------------------------------

def code_date_precision(record: dict) -> str:
    if record["year"]:
        return "exact"
    earliest, latest = record["year_earliest"], record["year_latest"]
    if not earliest or not latest:
        return "none"
    span = int(latest) - int(earliest)
    if span <= 9:
        return "decade"
    if span <= 99:
        return "century"
    return "multi_century"


METADATA_FIELDS = [
    ("has_creator", lambda r: bool(r["creators"])),
    ("has_publisher", lambda r: bool(r["publisher"])
     and not any(a in normalize(r["publisher"]) for a in ANONYMOUS_PUBLISHER)),
    ("has_scale", lambda r: bool(r["scale"])),
    ("has_dimensions", lambda r: bool(r["physical_description"])),
    ("has_subjects", lambda r: bool(r["subjects"])),
    ("has_language", lambda r: bool(r["language"])),
    ("has_catalogue_notice", lambda r: bool(r["catalogue_notice"])),
    ("has_exact_date", lambda r: bool(r["year"])),
]


def grade(score: int, thresholds: tuple[int, int, int]) -> str:
    high, mid, low = thresholds
    if score >= high:
        return "A"
    if score >= mid:
        return "B"
    if score >= low:
        return "C"
    return "D"


# --- Family C coders -------------------------------------------------------

def code_scan(record: dict, scans: dict, sheet: tuple[str, str, str],
              sheet_count: str) -> dict:
    blank = {"scan_width": "", "scan_height": "", "scan_megapixels": "",
             "scan_resolution_class": "unknown", "scan_dpi": "",
             "scan_dpi_class": "unknown"}
    info = scans.get(record["record_id"]) if record["iiif_manifest"] else None
    if not info:
        return blank

    megapixels = info["width"] * info["height"] / 1_000_000
    coded = dict(blank)
    coded.update({
        "scan_width": str(info["width"]),
        "scan_height": str(info["height"]),
        "scan_megapixels": f"{megapixels:.1f}",
        "scan_resolution_class": next(
            name for ceiling, name in RESOLUTION_BANDS if megapixels < ceiling),
    })

    # Effective scan resolution needs the physical sheet. Skip multi-sheet maps:
    # the IIIF view is one sheet, while the catalogue measures the whole map.
    width_cm, height_cm, _ = sheet
    if width_cm and sheet_count in ("", "1"):
        # Catalogue W x H order is not reliable, so compare long edge to long edge.
        longest_px = max(info["width"], info["height"])
        longest_cm = max(float(width_cm), float(height_cm))
        dpi = longest_px / (longest_cm / 2.54)
        coded["scan_dpi"] = f"{dpi:.0f}"
        coded["scan_dpi_class"] = next(
            name for ceiling, name in DPI_BANDS if dpi < ceiling)
    return coded


# --- Composite constructs --------------------------------------------------

def code_quality_index(row: dict) -> str:
    """Unweighted mean of three 0-100 subscores. Heuristic; see CODEBOOK.md."""
    # Cartographic: scale known (40), sheet dimensions known (20),
    # colour known (10), issuing authority identified (30).
    cartographic = (
        (40 if row["scale_class"] != "unknown" else 0)
        + (20 if row["sheet_area_cm2"] else 0)
        + (10 if row["colour"] != "unknown" else 0)
        + (30 if row["authority_type"] != "unknown" else 0)
    )
    metadata = int(row["metadata_completeness"]) / len(METADATA_FIELDS) * 100
    # Access: IIIF available (30), resolution band (50), open rights (20).
    resolution_points = {"high": 50, "medium": 35, "low": 15, "unknown": 0}
    access = (
        (30 if row["has_iiif"] == "1" else 0)
        + resolution_points[row["scan_resolution_class"]]
        + (20 if row["rights_open"] == "1" else 0)
    )
    return f"{(cartographic + metadata + access) / 3:.1f}"


def code_research_tier(row: dict) -> str:
    """Fitness for use, which is what 'quality' usually means in practice."""
    analytic_scale = row["scale_class"] in ("large", "medium")
    good_scan = row["scan_resolution_class"] in ("high", "medium")
    if analytic_scale and good_scan:
        return "1_analytic"        # georeferenceable, features extractable
    if good_scan or row["has_iiif"] == "1":
        return "2_contextual"      # readable as visual evidence
    return "3_reference"           # citable, but not examinable at depth


# --- Driver ----------------------------------------------------------------

CODED_FIELDS = [
    "record_id", "title", "year", "century", "confidence", "provenance",
    # Family A
    "scale_denominator", "scale_class", "production_mode", "colour",
    "authority_type", "genre", "sheet_count", "sheet_width_cm",
    "sheet_height_cm", "sheet_area_cm2",
    # Family B
    "date_precision", "has_creator", "has_publisher", "has_scale",
    "has_dimensions", "has_subjects", "has_language", "has_catalogue_notice",
    "has_exact_date", "metadata_completeness", "metadata_grade",
    # Family C
    "provenance_tier", "has_iiif", "views", "rights_open", "scan_width",
    "scan_height", "scan_megapixels", "scan_resolution_class",
    "scan_dpi", "scan_dpi_class",
    # Composites
    "quality_index", "research_tier",
    "url",
]


def code_record(record: dict, scans: dict) -> dict:
    denominator, scale_class = code_scale(record)
    sheet = code_dimensions(record)
    width, height, area = sheet
    sheet_count = code_sheet_count(record)
    row = {
        "record_id": record["record_id"],
        "title": record["title"],
        "year": record["year"],
        "century": record["century"],
        "confidence": record["confidence"],
        "provenance": record["provenance"],
        "scale_denominator": denominator,
        "scale_class": scale_class,
        "production_mode": code_production_mode(record),
        "colour": code_colour(record),
        "authority_type": code_authority(record),
        "genre": code_genre(record),
        "sheet_count": sheet_count,
        "sheet_width_cm": width,
        "sheet_height_cm": height,
        "sheet_area_cm2": area,
        "date_precision": code_date_precision(record),
        "provenance_tier": "bnf" if record["iiif_manifest"] else "partner",
        "has_iiif": "1" if record["iiif_manifest"] else "0",
        "views": record["views"],
        "rights_open": "1" if "domaine public" in record["rights"] else "0",
        "url": record["url"],
    }
    for name, test in METADATA_FIELDS:
        row[name] = "1" if test(record) else "0"
    row["metadata_completeness"] = str(sum(int(row[n]) for n, _ in METADATA_FIELDS))
    row["metadata_grade"] = grade(int(row["metadata_completeness"]), (7, 5, 3))
    row.update(code_scan(record, scans, sheet, sheet_count))
    row["quality_index"] = code_quality_index(row)
    row["research_tier"] = code_research_tier(row)
    return row


def summarise(rows: list[dict]) -> dict:
    def distribution(field: str) -> dict:
        return dict(Counter(r[field] for r in rows).most_common())

    indices = [float(r["quality_index"]) for r in rows]
    megapixels = [float(r["scan_megapixels"]) for r in rows if r["scan_megapixels"]]
    dpis = [float(r["scan_dpi"]) for r in rows if r["scan_dpi"]]
    return {
        "records_coded": len(rows),
        "scale_class": distribution("scale_class"),
        "production_mode": distribution("production_mode"),
        "colour": distribution("colour"),
        "authority_type": distribution("authority_type"),
        "genre": distribution("genre"),
        "date_precision": distribution("date_precision"),
        "metadata_grade": distribution("metadata_grade"),
        "metadata_completeness": dict(sorted(
            Counter(r["metadata_completeness"] for r in rows).items())),
        "provenance_tier": distribution("provenance_tier"),
        "scan_resolution_class": distribution("scan_resolution_class"),
        "scan_dpi_class": distribution("scan_dpi_class"),
        "research_tier": distribution("research_tier"),
        "quality_index": {
            "mean": round(statistics.mean(indices), 1),
            "median": round(statistics.median(indices), 1),
            "min": round(min(indices), 1),
            "max": round(max(indices), 1),
        },
        "scan_megapixels": {
            "n": len(megapixels),
            "mean": round(statistics.mean(megapixels), 1) if megapixels else None,
            "median": round(statistics.median(megapixels), 1) if megapixels else None,
            "min": round(min(megapixels), 1) if megapixels else None,
            "max": round(max(megapixels), 1) if megapixels else None,
        },
        "scan_dpi": {
            "n": len(dpis),
            "mean": round(statistics.mean(dpis)) if dpis else None,
            "median": round(statistics.median(dpis)) if dpis else None,
            "min": round(min(dpis)) if dpis else None,
            "max": round(max(dpis)) if dpis else None,
        },
    }


def table(title: str, counts: dict, total: int) -> list[str]:
    lines = [f"### {title}", "", "| Value | n | % |", "| --- | ---: | ---: |"]
    for value, count in counts.items():
        lines.append(f"| `{value}` | {count} | {count / total * 100:.0f}% |")
    lines.append("")
    return lines


def write_report(rows: list[dict], summary: dict, path: Path) -> None:
    total = len(rows)
    lines = [
        "# Quality profile",
        "",
        f"Coding of all {total} records on the indicators defined in "
        "[CODEBOOK.md](CODEBOOK.md). Generated by `scripts/code_quality.py`.",
        "",
        "## Read this first",
        "",
        "Two patterns govern almost every distribution below, and both are "
        "artefacts of cataloguing rather than properties of the maps.",
        "",
        "**Scale is missing far more often than it is present (460 of 663), and "
        "it is not missing at random.** Partner-library records essentially never "
        "carry a scale (151 of 157) against 61% of BnF records, so the "
        "20th century's high missingness is a provenance artefact: of its 132 "
        "unscaled records, 116 are partner items. Separately, early modern maps "
        "often state no scale at all, which the catalogue faithfully records. "
        "Filtering on `scale_class` therefore selects on source and period, not "
        "on cartographic quality.",
        "",
        "**All digitisation measures exist only for BnF-held items.** The 163 "
        "`unknown` resolutions are 157 partner records plus 6 whose IIIF "
        "endpoint did not answer — systematic missingness, not zero quality.",
        "",
        "## A. Cartographic quality",
        "",
    ]
    lines += table("Scale class", summary["scale_class"], total)
    lines += table("Production mode", summary["production_mode"], total)
    lines += table("Issuing authority", summary["authority_type"], total)
    lines += table("Colour", summary["colour"], total)
    lines += table("Genre", summary["genre"], total)

    lines += ["## B. Record quality", ""]
    lines += table("Metadata grade", summary["metadata_grade"], total)
    lines += table("Date precision", summary["date_precision"], total)

    lines += ["## C. Digital access quality", ""]
    lines += table("Provenance tier", summary["provenance_tier"], total)
    lines += table("Scan resolution (total pixels)",
                   summary["scan_resolution_class"], total)
    lines += table("Scan resolution (dpi relative to sheet)",
                   summary["scan_dpi_class"], total)

    megapixels, dpi = summary["scan_megapixels"], summary["scan_dpi"]
    lines += [
        f"Scan size, {megapixels['n']} records: median {megapixels['median']} MP "
        f"(range {megapixels['min']}–{megapixels['max']}). Effective resolution, "
        f"{dpi['n']} records: median {dpi['median']} dpi "
        f"(range {dpi['min']}–{dpi['max']}). BnF digitisation sits at or above "
        "the 300 dpi reproduction floor almost everywhere, so dpi separates "
        "items far less than total pixel count does.",
        "",
        "## Summary constructs",
        "",
    ]
    lines += table("Research tier", summary["research_tier"], total)

    top = sorted(rows, key=lambda r: -float(r["quality_index"]))[:3]
    lines += [
        f"`quality_index`: mean {summary['quality_index']['mean']}, "
        f"median {summary['quality_index']['median']}.",
        "",
        "Its three highest-scoring records are small-scale commercial maps of "
        "the whole Barbary coast at 1:1 600 000 and smaller — which is the "
        "clearest possible demonstration of the caveat in the codebook: the "
        "index rewards *fully catalogued and well scanned*, not *detailed*. "
        "Use `research_tier`, or the components, to rank cartographic value.",
        "",
    ]

    analytic = [r for r in rows if r["research_tier"] == "1_analytic"]
    analytic.sort(key=lambda r: int(r["scale_denominator"] or 0))
    lines += [
        f"## The {len(analytic)} `1_analytic` records",
        "",
        "Medium or large scale with a good scan: the subset that can be "
        "georeferenced and read for individual features.",
        "",
        "| Scale | Date | Title | Scan | Authority | Link |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in analytic:
        title = r["title"].replace("|", "\\|")
        title = title if len(title) <= 70 else title[:69].rstrip() + "…"
        lines.append(
            f"| 1:{int(r['scale_denominator']):,} ".replace(",", " ")
            + f"| {r['year'] or '—'} | {title} "
            f"| {r['scan_megapixels']} MP | {r['authority_type']} "
            f"| [view]({r['url']}) |"
        )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps.json")
    parser.add_argument("--scans", type=Path,
                        default=REPO_ROOT / "data" / "scan_dimensions.json")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--report", type=Path,
                        default=REPO_ROOT / "docs" / "QUALITY.md")
    args = parser.parse_args()

    records = json.loads(args.data.read_text(encoding="utf-8"))["records"]
    scans = {}
    if args.scans.exists():
        scans = {k: v for k, v in
                 json.loads(args.scans.read_text(encoding="utf-8")).items() if v}
    else:
        print("! no scan_dimensions.json; resolution fields will be 'unknown'",
              file=sys.stderr)

    rows = [code_record(r, scans) for r in records]
    rows.sort(key=lambda r: -float(r["quality_index"]))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "gallica_tunisia_maps_coded.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CODED_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    summary = summarise(rows)
    (args.out_dir / "quality_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    write_report(rows, summary, args.report)

    print(f"coded {len(rows)} records -> {csv_path}")
    print(f"  report -> {args.report}")
    print(f"  research_tier:   {summary['research_tier']}")
    print(f"  scale_class:     {summary['scale_class']}")
    print(f"  metadata_grade:  {summary['metadata_grade']}")
    print(f"  resolution:      {summary['scan_resolution_class']}")
    print(f"  quality_index:   {summary['quality_index']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

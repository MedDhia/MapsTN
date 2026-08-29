#!/usr/bin/env python3
"""Code depicted feature classes and regional coverage for each map.

Two questions, two variable blocks:

  A. What is drawn on the sheet - wells, shrines, mosques, forts, rural versus
     urban settlement, ruins - at the granularity of a map legend rather than a
     catalogue subject heading.
  B. Which part of Tunisia it covers, and whether that coverage is complete.

The honest problem with A: catalogue metadata does not record this. Across the
whole corpus the Dublin Core mentions mosques in 0 records, tribes in 0, oases in
0, wells in 5. These features are drawn on the map, not catalogued. So feature
coding here is a *scale-and-series model* calibrated against sheets inspected
directly through IIIF (config/inspected_sheets.json), not a per-sheet census.
Every row says which basis it rests on in `features_basis`.

The honest problem with B: titles lie about completeness. 'Carte de la Régence
de Tunis' (1881) covers only the north and centre; 'Carte de la Tunisie' (1895)
is one sheet of a pair and its record never says so. So `coverage_complete` is
only ever `yes` for sheets someone has actually looked at.

Outputs:
    data/gallica_tunisia_maps_features.csv
    data/features_summary.json
    docs/FEATURES-REGIONS.md

Usage:
    python3 scripts/code_features_regions.py
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

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- A. Feature detail bands ----------------------------------------------
# What a sheet can physically show is governed by its scale. The feature lists
# below are what was actually observed on inspected sheets in each band, not a
# theoretical maximum. See docs/FEATURES-REGIONS.md.
SCALE_BANDS = [
    (100_000, "topographic"),
    (500_000, "regional"),
    (2_000_000, "synoptic"),
    (float("inf"), "overview"),
]

BAND_FEATURES = {
    "topographic": [
        "wells_springs", "shrines_marabouts", "forts_ksour", "ruins_henchirs",
        "rural_settlement", "tracks", "vegetation", "contours", "wadis",
    ],
    "regional": [
        "settlement_hierarchy", "roads", "railways", "relief", "hydrography",
        "admin_limits",
    ],
    "synoptic": [
        "settlement_hierarchy", "railways", "roads", "relief", "chotts_sebkhas",
    ],
    "overview": ["coastline", "principal_towns"],
    "unknown": [],
}

# Feature generics as they appear in French and transliterated Arabic on these
# maps and in their own glossaries. Used to pick up the minority of records
# whose catalogue text does name a feature class.
FEATURE_TERMS = {
    "wells_springs": r"\bpuits\b|\bbir\b|\bbiar\b|\bain\b|\baioun\b|\bhassi\b|\boglat\b|citerne|\bsource",
    "shrines_marabouts": r"marabout|\bkoubba\b|\bqubba\b|\bzaouia\b|zawiy|\bsidi\b|\bsidy\b|\blella\b|mausolee",
    "mosques": r"mosquee|\bjamaa\b|djamaa|\bmesjid\b|masjid|minaret|\bmedersa\b",
    "forts_ksour": r"\bbordj\b|\bborj\b|\bksar\b|\bksour\b|\bkalaa\b|\bkasbah\b|casbah|citadelle|redoute|fortification|\bfort\b|\bforts\b",
    "ruins_henchirs": r"\bruines\b|\bhenchir\b|archeolog|antique|\bromain|\bpunique|byzantin|amphitheatre|\bthermes\b",
    "rural_settlement": r"\bdouar\b|\bmechta\b|\bgourbi\b|hameau|\bvillage\b|\bferme\b|\bcolonie\b",
    "urban_fabric": r"\bmedina\b|faubourg|\bquartier\b|\bsouk\b|\bsouq\b|\brues\b|voirie|parcellaire",
    "european_village": r"village francais|village europeen|centre de colonisation|colonisation officielle",
    "tribes": r"\btribu\b|\btribus\b|\boulad\b|\bouled\b|\bbeni\b|fraction",
    "oases_palm": r"\boasis\b|palmeraie|\bdattier|\bjerid\b|\bdjerid\b",
    "chotts_sebkhas": r"\bchott\b|\bsebkha\b|\bsebkhet\b|\bsebkra\b|saline",
    "wadis": r"\boued\b|\bwadi\b|\bwed\b|\bchaabe",
    "mines": r"\bmines?\b|miniere|phosphate|gisement|\bcarriere",
    "ports_lighthouses": r"\bport\b|\bports\b|mouillage|\brade\b|\bphare\b|\bquai\b",
    "railways": r"chemin[s]? de fer|voie ferree|ferroviaire|railway",
    "roads": r"\broutes?\b|itinerair|voies? de commun|\bpiste",
    "admin_limits": r"administrativ|caidat|controle civil|circonscription|frontiere|territoire militaire",
}

# --- B. Regional gazetteer -------------------------------------------------
# Historic/geographic regions of Tunisia. Keyed on toponyms as they appear in
# French cartography, including older spellings.
REGIONS = {
    "tunis_capital": (
        "tunis", "goulette", "carthage", "la marsa", "bardo", "sidi bou said",
        "rades", "hammam lif", "manouba", "megrine", "kram",
    ),
    "cap_bon": (
        "cap bon", "nabeul", "hammamet", "kelibia", "korba", "menzel temime",
        "grombalia", "soliman", "korbous", "beni khiar",
    ),
    "bizerte_nord": (
        "bizerte", "biserta", "ferryville", "menzel bourguiba", "ghar el melh",
        "porto farina", "ras jebel", "utique", "mateur", "cap negro",
        "la galite", "cap blanc", "cap serrat",
    ),
    "nord_ouest": (
        "beja", "jendouba", "tabarka", "khroumirie", "kroumirie", "le kef",
        "siliana", "teboursouk", "dougga", "ain draham", "bou salem",
        "makthar", "maktar", "ghardimaou", "souk el arba", "testour",
    ),
    "sahel": (
        "sousse", "monastir", "mahdia", "ksar hellal", "moknine", "hergla",
        "enfida", "enfidaville", "chebba", "el djem", "thysdrus", "bekalta",
        "sahel tunisien",
    ),
    "centre": (
        "kairouan", "qirwan", "kasserine", "sidi bouzid", "sbeitla", "thala",
        "feriana", "haffouz", "sbiba", "hajeb el aioun",
    ),
    "sfax_kerkennah": ("sfax", "kerkennah", "mahares", "skhira", "graiba"),
    "sud_ouest_jerid": (
        "tozeur", "nefta", "gafsa", "kebili", "chott el djerid", "chott djerid",
        "douz", "metlaoui", "redeyef", "degache", "el hamma", "nefzaoua",
    ),
    "sud_est_djeffara": (
        "gabes", "medenine", "tataouine", "zarzis", "ben gardane", "djerba",
        "jerba", "gerbi", "matmata", "ghomrassen", "dehiba", "zarzis",
        "djeffara", "foum tataouine", "houmt souk",
    ),
}

# Approximate bounding boxes for the same regions. Where a sheet has published
# coordinates these are used instead of toponym matching: more reliable, and it
# works for sheets whose place names no gazetteer would carry - the 1:50 000
# series names its sheets after villages like Halk el Menzel or Metline.
REGION_BOXES = {
    "tunis_capital":    {"west": 9.85, "east": 10.55, "south": 36.55, "north": 37.15},
    "cap_bon":          {"west": 10.35, "east": 11.20, "south": 36.30, "north": 37.10},
    "bizerte_nord":     {"west": 8.95, "east": 10.35, "south": 36.85, "north": 37.60},
    "nord_ouest":       {"west": 8.20, "east": 9.95, "south": 35.75, "north": 37.10},
    "sahel":            {"west": 10.15, "east": 11.20, "south": 35.15, "north": 36.35},
    "centre":           {"west": 8.45, "east": 10.30, "south": 34.75, "north": 36.05},
    "sfax_kerkennah":   {"west": 10.15, "east": 11.35, "south": 34.15, "north": 35.20},
    "sud_ouest_jerid":  {"west": 7.49, "east": 9.60, "south": 32.75, "north": 34.85},
    "sud_est_djeffara": {"west": 9.45, "east": 11.60, "south": 30.23, "north": 34.25},
}

NATIONAL_TERMS = (
    "tunisie", "tunisia", "regence de tunis", "royaume de tunis",
    "regence de tunisie",
)

# Places and regions outside Tunisia. Where these dominate, the sheet is not a
# map of Tunisia even if Tunisia appears on it.
SUPRANATIONAL_TERMS = (
    "barbarie", "berberie", "afrique", "africa", "mediterranee", "algerie",
    "alger", "tripoli", "tripolitaine", "maroc", "maghreb", "monde", "europe",
    "orbis", "sicile", "italie", "malte", "egypte", "levant", "empire ottoman",
)

SHEET_PARTITION_RE = re.compile(
    r"\b\d+\s*(?:re|e|eme|ere)?\s*feuille\b|feuille\s+(?:nord|sud|est|ouest)"
    r"|\bfeuille\s+n[o°]\s*\d+|\b(?:nord|sud)\b\s*$"
    # The 1:50 000 national series numbers its sheets 'Flle. N° XXXVI-B4-C37,
    # Bou Ficha'. Without this the leading 'Tunisie' made each sheet look like
    # a map of the whole country.
    r"|\bfll?e\.?\s*n[o°]|\bfeuille\s+[ivxlcdm]+\b")
SERIES_SHEET_RE = re.compile(r"\bfll?e\.?\s*n[o°]\s*[ivxlcdm\d]")

# 'Tunis, Régence de' and 'Régence de Tunis' name the country, not the capital.
# Masking them before region matching stops every coastal chart of the Regency
# from being filed under the capital region.
REGENCY_RE = re.compile(
    r"tunis,?\s*(?:regence|province|royaume)\s*d[e\']?|"
    r"(?:regence|province|royaume)\s+de\s+tunis(?:ie)?")

URBAN_PLAN_RE = re.compile(
    r"\bplan de la ville\b|\bplan de tunis\b|\bplan d[eu]\b.*\bville\b"
    r"|\bplan general de\b|\bpianta\b|\bcitta di\b")
ENVIRONS_RE = re.compile(r"\benvirons d[eu]\b|\benvirons des\b|\bbanlieue\b")


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def blob(record: dict, catalogue: dict) -> str:
    return normalize(" | ".join((
        record["title"], record["alt_titles"], record["subjects"],
        record["description"], record["coverage"], record["doc_type"],
        " ".join(catalogue.get("geo_headings", [])),
        " ".join(catalogue.get("genre_headings", [])),
    )))


def scale_band(scale_denominator: str) -> str:
    if not scale_denominator:
        return "unknown"
    denominator = int(scale_denominator)
    for ceiling, name in SCALE_BANDS:
        if denominator <= ceiling:
            return name
    return "unknown"


def features_in_text(text: str) -> list[str]:
    return [name for name, pattern in FEATURE_TERMS.items()
            if re.search(pattern, text)]


def _word_re(terms: tuple[str, ...]) -> re.Pattern:
    """Whole-word alternation. Without the boundaries 'tunis' matches inside
    'tunisie', which put 589 of 663 records in the capital region."""
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b")


REGION_RES = {name: _word_re(terms) for name, terms in REGIONS.items()}
NATIONAL_RE = _word_re(NATIONAL_TERMS)
SUPRANATIONAL_RE = _word_re(SUPRANATIONAL_TERMS)
# Hydrographic charts of 'Tunis, Régence de -- Côtes' carry a national-sounding
# subject heading but map a coastal strip, not the country.
COASTAL_RE = re.compile(r"\bcotes?\b|sondages? sous-marins?|\bhydrograph")


def regions_from_bbox(box: dict) -> list[str]:
    """Regions a sheet's published extent actually overlaps.

    A region counts when the intersection covers at least 15% of whichever box
    is smaller, so a 1:50 000 sheet sitting inside one region matches it, and a
    national sheet matches every region it spans without matching on a sliver.
    """
    sheet_area = (box["east"] - box["west"]) * (box["north"] - box["south"])
    if sheet_area <= 0:
        return []
    hits = []
    for name, region in REGION_BOXES.items():
        width = min(box["east"], region["east"]) - max(box["west"], region["west"])
        height = min(box["north"], region["north"]) - max(box["south"], region["south"])
        if width <= 0 or height <= 0:
            continue
        region_area = ((region["east"] - region["west"])
                       * (region["north"] - region["south"]))
        if (width * height) / min(sheet_area, region_area) >= 0.15:
            hits.append(name)
    return hits


def code_regions(text: str, title_text: str) -> tuple[list[str], bool, bool]:
    """Return (regions, national_is_the_subject, supranational_present).

    National scope is judged from the title, not from anywhere in the record:
    'Tunis, Régence de -- Côtes' is a standing subject heading on scores of
    coastal charts and would otherwise make almost every one of them national.
    """
    masked = REGENCY_RE.sub(" COUNTRY ", text)
    regions = [name for name, pattern in REGION_RES.items()
               if pattern.search(masked)]
    national = bool(NATIONAL_RE.search(title_text))
    supranational = bool(SUPRANATIONAL_RE.search(text))
    return regions, national, supranational


def code_coverage_scope(regions: list[str], national: bool, supranational: bool,
                        band: str, urban: bool, coastal: bool,
                        series_sheet: bool) -> str:
    if urban and len(regions) <= 1:
        return "locality"
    # A chart of the Regency's coast spans the country lengthwise but maps a
    # strip, not the territory; it is neither national nor a single region.
    if coastal and not urban:
        return "coastal_strip"
    if series_sheet:
        return "locality"
    if national:
        return "national"
    if supranational:
        return "supranational"
    if len(regions) >= 2:
        return "multi_region"
    if len(regions) == 1:
        return "locality" if band == "topographic" else "single_region"
    return "undetermined"


def code_settlement_focus(text: str, band: str, genre: str) -> str:
    if URBAN_PLAN_RE.search(text) or (genre == "plan" and band == "topographic"):
        return "urban_plan"
    if ENVIRONS_RE.search(text):
        return "town_and_hinterland"
    if band in ("topographic", "regional"):
        return "rural_regional"
    if band in ("synoptic", "overview"):
        return "small_scale_no_settlement_detail"
    return "undetermined"


FIELDS = [
    "record_id", "title", "year", "confidence", "scale_denominator",
    # A
    "feature_band", "expected_features", "features_in_metadata",
    "features_observed", "features_basis", "settlement_focus",
    # B
    "regions_covered", "regions_basis", "n_regions", "coverage_scope",
    "sheet_partition",
    "coverage_complete", "coverage_note", "coverage_basis",
    "url",
]


def code_record(record: dict, geo: dict, quality: dict, catalogue: dict,
                partner: dict, inspected: dict) -> dict:
    text = blob(record, catalogue)
    title_text = normalize(record["title"] + " | " + record["alt_titles"])
    denominator = quality["scale_denominator"]
    band = scale_band(denominator)
    regions, national, supranational = code_regions(text, title_text)
    regions_basis = "gazetteer"
    box = partner.get("bbox") or catalogue.get("bbox")
    if box:
        spatial = regions_from_bbox(box)
        if spatial:
            regions, regions_basis = spatial, "bbox"
    urban = bool(URBAN_PLAN_RE.search(text))
    coastal = bool(COASTAL_RE.search(text))
    series_sheet = bool(SERIES_SHEET_RE.search(title_text))
    scope = code_coverage_scope(regions, national, supranational, band, urban,
                                coastal, series_sheet)

    seen = inspected.get(record["record_id"])
    partition = bool(SHEET_PARTITION_RE.search(text))

    if seen:
        complete = seen["coverage_complete"]
        note = seen["coverage_note"]
        basis = "image"
        observed = " | ".join(seen["features_observed"])
        features_basis = "image"
    else:
        observed = ""
        features_basis = "scale_model" if band != "unknown" else "none"
        note = ""
        basis = "title_and_gazetteer"
        if scope != "national":
            complete = "no"
        elif partition:
            complete = "partial"
            note = "Catalogue text names a sheet of a set."
        else:
            # Titles claiming the country are not evidence that the sheet shows
            # all of it, so this stays open until someone looks.
            complete = "unverified"
            note = "National in title; completeness not verified against the image."

    return {
        "record_id": record["record_id"],
        "title": record["title"],
        "year": record["year"],
        "confidence": record["confidence"],
        "scale_denominator": denominator,
        "feature_band": band,
        "expected_features": " | ".join(BAND_FEATURES[band]),
        "features_in_metadata": " | ".join(features_in_text(text)),
        "features_observed": observed,
        "features_basis": features_basis,
        "settlement_focus": code_settlement_focus(text, band, quality["genre"]),
        # A national sheet covers the country rather than an enumerable set of
        # regions, and its title names no sub-region to match on.
        "regions_covered": " | ".join(regions) if regions
                           else ("national_extent" if scope == "national" else ""),
        "regions_basis": regions_basis if regions else (
            "scope" if scope == "national" else "none"),
        "n_regions": str(len(regions)),
        "coverage_scope": scope,
        "sheet_partition": "1" if partition else "0",
        "coverage_complete": complete,
        "coverage_note": note,
        "coverage_basis": basis,
        "url": record["url"],
    }


def summarise(rows: list[dict]) -> dict:
    total = len(rows)
    distribution = lambda f: dict(Counter(r[f] for r in rows).most_common())
    metadata_features = Counter(
        f for r in rows for f in r["features_in_metadata"].split(" | ") if f)
    region_counts = Counter(
        g for r in rows for g in r["regions_covered"].split(" | ") if g)
    tunisian = [r for r in rows if r["confidence"] == "high"]
    return {
        "records": total,
        "feature_band": distribution("feature_band"),
        "features_named_in_metadata": dict(metadata_features.most_common()),
        "features_basis": distribution("features_basis"),
        "settlement_focus": distribution("settlement_focus"),
        "regions_covered": dict(region_counts.most_common()),
        "regions_basis": distribution("regions_basis"),
        "coverage_scope": distribution("coverage_scope"),
        "coverage_complete": distribution("coverage_complete"),
        "high_confidence_coverage_scope":
            dict(Counter(r["coverage_scope"] for r in tunisian).most_common()),
    }


def table(title: str, counts: dict, total: int, note: str = "") -> list[str]:
    lines = [f"### {title}", ""]
    if note:
        lines += [note, ""]
    lines += ["| Value | n | % |", "| --- | ---: | ---: |"]
    for value, count in counts.items():
        lines.append(f"| `{value or '—'}` | {count} | {count / total * 100:.0f}% |")
    return lines + [""]


def write_report(rows: list[dict], summary: dict, inspected: dict,
                 path: Path) -> None:
    total = len(rows)
    lines = [
        "# Depicted features and regional coverage",
        "",
        f"Coding of all {total} records. Generated by "
        "`scripts/code_features_regions.py`; variables are defined in "
        "[CODEBOOK-FEATURES.md](CODEBOOK-FEATURES.md).",
        "",
        "## Why this could not be done from metadata",
        "",
        "Wells, shrines and mosques are drawn on maps; they are not catalogued. "
        "Across all 663 records the Dublin Core names **mosques in 0 records, "
        "tribes in 0, oases in 0, cemeteries in 0 and wells in 5**. Any coding "
        "built only on catalogue text would report that this collection shows "
        "none of these things, which is false.",
        "",
        "So the feature coding is a **scale-and-series model calibrated against "
        "sheets inspected directly through IIIF**. Every row records its basis "
        "in `features_basis`: `image` for the sheets actually examined, "
        "`scale_model` for the inference.",
        "",
        "## What the sheets actually show",
        "",
    ]
    for record_id, sheet in inspected.items():
        lines += [
            f"**{sheet['title']}** ({sheet['year'] or 'n.d.'}, {sheet['scale']}) — "
            f"[view](https://gallica.bnf.fr/ark:/12148/{record_id})",
            "",
            f"{sheet['legend_note']}",
            "",
        ]
    lines += [
        "The 1920 Taride sheet is the most useful of these, because it carries "
        "its own glossary of Arabic feature generics — the map documents the "
        "very vocabulary this coding looks for: *Aïn / Bir* = well or spring, "
        "*Bordj* = fortified post, *Kalâa / Ksar* = fort or fortified village, "
        "*Koubba* and *Zaouia* = chapel, *Sidi* = saint, *Souk* = market, "
        "*Oued* = river, *Chott / Sebkra* = salt lake. Its settlement hierarchy "
        "runs Capitale, Ville importante, Ville secondaire, Village ou centre "
        "important, Hameau or village indigène — and it marks a **Limite nord du "
        "Territoire Militaire**, the boundary of the militarily administered "
        "south.",
        "",
        "At 1:50 000 the sign vocabulary is far richer: the Kef sheet uses "
        "`Mvet` for marabout, `Za` for zaouia, `Ae` for aïn, `Kat` for kalâa "
        "and `Hr` for henchir, with *Puits* written out. The Medenine sheet "
        "shows wells as dense blue circles, marabouts as red dome symbols, a "
        "koubba (`Kba Sdi ben Bekr`), ksour and guerar granary clusters — and a "
        "separately labelled **Village Français** beside the indigenous centre, "
        "which is the settler/indigenous distinction drawn directly on the map.",
        "",
        "## A. Feature depiction",
        "",
    ]
    lines += table("Scale band", summary["feature_band"], total,
                   "What a sheet can show is set by its scale. `topographic` "
                   "(≤1:100 000) is the only band that carries wells, shrines "
                   "and individual buildings.")
    lines += table("Basis for the feature coding", summary["features_basis"], total)
    lines += table("Feature classes named in catalogue text",
                   summary["features_named_in_metadata"], total,
                   "Sparse by construction — this is what the catalogue happens "
                   "to mention, not what the maps show.")
    lines += table("Settlement focus", summary["settlement_focus"], total)

    lines += ["## B. Regional coverage", ""]
    lines += table("Regions covered", summary["regions_covered"], total,
                   "A sheet can cover several. Counts are of records touching "
                   "the region.")
    lines += table("Coverage scope", summary["coverage_scope"], total)
    lines += table("Coverage scope, high-confidence records only",
                   summary["high_confidence_coverage_scope"],
                   max(1, sum(summary["high_confidence_coverage_scope"].values())))

    lines += [
        "## Complete maps of Tunisia",
        "",
        "**`coverage_complete` is only `yes` where a sheet has been looked at.** "
        "Titles are not reliable evidence: *Carte de la Régence de Tunis* (1881, "
        "1:500 000) sounds like the whole country and covers only the north and "
        "centre, while *Carte de la Tunisie* (1895, 1:800 000) is captioned "
        "'1re feuille Nord' in its top margin and its catalogue record never "
        "mentions the partition.",
        "",
    ]
    lines += table("Completeness", summary["coverage_complete"], total)

    national = [r for r in rows if r["coverage_scope"] == "national"]
    national.sort(key=lambda r: (r["coverage_complete"] != "yes", r["year"] or "9999"))
    lines += [
        f"### The {len(national)} records whose scope is national",
        "",
        "| Date | Scale | Title | Complete | Basis | Link |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in national:
        title = r["title"].replace("|", "\\|")
        title = title if len(title) <= 58 else title[:57].rstrip() + "…"
        scale = f"1:{int(r['scale_denominator']):,}".replace(",", " ") \
            if r["scale_denominator"] else "—"
        lines.append(
            f"| {r['year'] or '—'} | {scale} | {title} "
            f"| `{r['coverage_complete']}` | {r['coverage_basis']} "
            f"| [view]({r['url']}) |")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps.json")
    parser.add_argument("--geo", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps_geospatial.csv")
    parser.add_argument("--quality", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps_coded.csv")
    parser.add_argument("--catalogue", type=Path,
                        default=REPO_ROOT / "data" / "catalogue_records.json")
    parser.add_argument("--partner", type=Path,
                        default=REPO_ROOT / "data" / "partner_records.json")
    parser.add_argument("--inspected", type=Path,
                        default=REPO_ROOT / "config" / "inspected_sheets.json")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--report", type=Path,
                        default=REPO_ROOT / "docs" / "FEATURES-REGIONS.md")
    args = parser.parse_args()

    records = json.loads(args.data.read_text(encoding="utf-8"))["records"]
    geo = {r["record_id"]: r for r in csv.DictReader(args.geo.open(encoding="utf-8"))}
    quality = {r["record_id"]: r for r in
               csv.DictReader(args.quality.open(encoding="utf-8"))}
    catalogue = json.loads(args.catalogue.read_text(encoding="utf-8")) \
        if args.catalogue.exists() else {}
    inspected = json.loads(args.inspected.read_text(encoding="utf-8"))["sheets"]

    partner = json.loads(args.partner.read_text(encoding="utf-8")) \
        if args.partner.exists() else {}

    rows = [code_record(r, geo.get(r["record_id"], {}), quality[r["record_id"]],
                        catalogue.get(r["record_id"], {}),
                        partner.get(r["record_id"], {}), inspected)
            for r in records if r["record_id"] in quality]

    order = {"yes": 0, "partial": 1, "unverified": 2, "no": 3}
    rows.sort(key=lambda r: (order[r["coverage_complete"]], r["year"] or "9999"))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.out_dir / "gallica_tunisia_maps_features.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    summary = summarise(rows)
    (args.out_dir / "features_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(rows, summary, inspected, args.report)

    print(f"coded {len(rows)} records -> {out_csv}")
    print(f"  report -> {args.report}")
    for key in ("feature_band", "coverage_scope", "coverage_complete",
                "settlement_focus"):
        print(f"  {key}: {summary[key]}")
    print(f"  regions: {summary['regions_covered']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

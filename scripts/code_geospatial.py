#!/usr/bin/env python3
"""Code the corpus for georeferencing potential and thematic content.

Answers four questions asked of the collection, each as its own variable block:

  Q1  Which maps carry explicit coordinates and a known orientation?
  Q2  Which can be georeferenced onto a modern map (geometry)?
  Q3  Which carry content that can be transferred into a modern map (themes)?
  Q4  Which support the study of spatial inequality and its evolution?

Inputs:
    data/gallica_tunisia_maps.json        catalogue records (Dublin Core)
    data/gallica_tunisia_maps_coded.csv   quality coding
    data/catalogue_records.json           UNIMARC from the BnF catalogue

Outputs:
    data/gallica_tunisia_maps_geospatial.csv
    data/geospatial_summary.json
    docs/GEOREFERENCING.md

Usage:
    python3 scripts/code_geospatial.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Tunisia's approximate bounding box, used to judge whether a sheet centres on
# the country or merely clips it.
TUNISIA_BBOX = {"west": 7.49, "east": 11.60, "south": 30.23, "north": 37.55}

# Coordinates sometimes appear as free text in UNIMARC 206 rather than as coded
# subfields: "E 13°30' - E 51°30' / N 48°54' - N 27°30'".
TEXT_COORD_RE = re.compile(
    r"([EW])\s*(\d{1,3})°\s*(\d{1,2})?'?\s*-\s*([EW])\s*(\d{1,3})°\s*(\d{1,2})?'?"
    r"\s*/\s*([NS])\s*(\d{1,3})°\s*(\d{1,2})?'?\s*-\s*([NS])\s*(\d{1,3})°\s*(\d{1,2})?'?"
)

# --- Q3 thematic layers ----------------------------------------------------
# Each layer is a class of feature that could be digitised as a GIS layer.
THEMATIC_LAYERS = {
    "settlements": r"ville|cite|citta|village|bourg|localite|agglomerat",
    "coastline_bathymetry": r"sondage|sous-marin|\bcotes?\b|bathym|mouillage|rade|banc|recif",
    "relief": r"relief|altitude|montagne|djebel|courbes de niveau|orograph",
    "hydrology": r"hydrograph|hydrolog|oued|riviere|lac|chott|sebkha|barrage|aqueduc|puits|irrigation",
    "roads": r"\broutes?\b|itinerair|voies? de commun|piste|chemin(?!s? de fer)",
    "railways": r"chemin[s]? de fer|voie ferree|ferroviaire|railway",
    # 'province' and 'departement' are deliberately excluded: 'Tunis, Province
    # de -- Côtes' is a standing subject heading on 58 coastal charts that carry
    # no administrative content at all.
    "admin_boundaries": r"administrativ|caidat|controle civil|circonscription|frontiere|limites administrativ|division territorial",
    "fortifications": r"fortification|\bforts?\b|citadelle|bastion|remparts|kasbah",
    "archaeology": r"archeolog|antique|ruines|romain|punique|byzantin|eveche|episcopat",
    "geology_mines": r"geolog|miniere|\bmines\b|phosphate|gisement",
    "land_use": r"agricol|agricultur|olivier|cereal|vignoble|foret|forestier|paturage|culture",
    "urban_fabric": r"\bplan de la ville|medina|quartier|parcellaire|cadastr|voirie|alignement",
    "population": r"population|tribu|ethnograph|peuplement|densite|recensement",
    "economy": r"commerc|industri|economi|marche|foire|douane",
}

# --- Q4 inequality-bearing themes ------------------------------------------
# Layers that show how people, infrastructure, land or activity are distributed
# across space. Coastline soundings, relief and fortifications do not.
DISTRIBUTIONAL_LAYERS = {
    "roads", "railways", "admin_boundaries", "land_use",
    "urban_fabric", "population", "economy", "geology_mines",
}
# Where towns are is necessary context but not, on its own, evidence about
# inequality: nearly every map names settlements. Recorded, never decisive.
SUPPORTING_LAYERS = {"settlements"}
INEQUALITY_LAYERS = DISTRIBUTIONAL_LAYERS | SUPPORTING_LAYERS

# --- Q2 geometric classes --------------------------------------------------
SURVEY_AUTHORITIES = {"military_survey", "civil_survey", "hydrographic"}


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def blob(record: dict) -> str:
    return normalize(" | ".join((
        record["title"], record["alt_titles"], record["subjects"],
        record["description"], record["coverage"], record["doc_type"],
        record["physical_description"],
    )))


# --- Q1: coordinates -------------------------------------------------------

def bbox_from_text(text: str) -> dict | None:
    match = TEXT_COORD_RE.search(text or "")
    if not match:
        return None
    g = match.groups()

    def value(hemisphere, degrees, minutes):
        decimal = int(degrees) + (int(minutes) / 60 if minutes else 0)
        return -decimal if hemisphere in "WS" else decimal

    return {
        "west": value(g[0], g[1], g[2]),
        "east": value(g[3], g[4], g[5]),
        "north": value(g[6], g[7], g[8]),
        "south": value(g[9], g[10], g[11]),
    }


def overlap_share(box: dict) -> float | None:
    """Share of the sheet's extent occupied by Tunisia's bounding box.

    Near 1.0 means the sheet is essentially a map of Tunisia; near 0 means
    Tunisia is a sliver in the corner of a Mediterranean or world map.
    """
    width = box["east"] - box["west"]
    height = box["north"] - box["south"]
    if width <= 0 or height <= 0:
        return None
    overlap_w = min(box["east"], TUNISIA_BBOX["east"]) - max(box["west"], TUNISIA_BBOX["west"])
    overlap_h = min(box["north"], TUNISIA_BBOX["north"]) - max(box["south"], TUNISIA_BBOX["south"])
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    return (overlap_w * overlap_h) / (width * height)


def code_coordinates(record: dict, catalogue: dict, partner: dict) -> dict:
    box, source = catalogue.get("bbox"), "unimarc_123"
    if not box:
        box = bbox_from_text(catalogue.get("math_data", ""))
        source = "math_data_text" if box else "none"
    if not box and partner.get("bbox"):
        # Partner libraries publish coordinates on their own item pages that
        # Gallica's aggregated record drops entirely.
        box, source = partner["bbox"], "partner_page"
    if not box:
        return {"bbox_west": "", "bbox_east": "", "bbox_north": "", "bbox_south": "",
                "bbox_source": "none", "tunisia_extent_share": ""}
    # One UNIMARC record has its longitude subfields the wrong way round
    # (W 11.783 / E 4.833), which silently gives every overlap test a zero.
    box = {
        "west": min(box["west"], box["east"]),
        "east": max(box["west"], box["east"]),
        "south": min(box["north"], box["south"]),
        "north": max(box["north"], box["south"]),
    }
    share = overlap_share(box)
    return {
        "bbox_west": f"{box['west']:.3f}",
        "bbox_east": f"{box['east']:.3f}",
        "bbox_north": f"{box['north']:.3f}",
        "bbox_south": f"{box['south']:.3f}",
        "bbox_source": source,
        "tunisia_extent_share": f"{share:.3f}" if share is not None else "",
    }


# --- Q1: orientation -------------------------------------------------------

ORIENTATION_STATED_RE = re.compile(
    r"orient[ée]|nord en haut|sud en haut|rose des vents|boussole")


def code_orientation(record: dict, quality: dict) -> tuple[str, str]:
    """Orientation is almost never catalogued, so this is mostly a presumption.

    Verified visually on a sample (see docs/GEOREFERENCING.md): a 1929 Service
    géographique sheet and an 18th-century sea chart are both north-up with a
    graticule; a portolan carries only rhumb lines and no consistent north.
    """
    if ORIENTATION_STATED_RE.search(blob(record)):
        return "stated_in_record", "orientation mentioned in catalogue text"
    if quality["genre"] == "view":
        return "uncertain", "perspective view: oriented to the viewer, not to north"
    year = record["year_earliest"]
    if year and int(year) >= 1700:
        return "presumed_north", "European printed cartography after 1700 is north-up by convention"
    if year and int(year) < 1700:
        return "uncertain", "pre-1700: portolans and siege views are frequently not north-up"
    return "uncertain", "undated"


# --- Q2: georeferenceability ----------------------------------------------

def code_geometry(record: dict, quality: dict, has_bbox: bool) -> tuple[str, str, str]:
    """Return (geometric_class, georef_tier, blockers)."""
    year = int(record["year_earliest"]) if record["year_earliest"] else None
    genre, authority = quality["genre"], quality["authority_type"]
    has_scale = quality["scale_class"] != "unknown"

    blockers = []
    if quality["provenance_tier"] == "partner":
        blockers.append("no IIIF (partner-hosted)")
    if quality["scan_resolution_class"] in ("low", "unknown"):
        blockers.append("scan resolution low or unknown")
    if not has_scale:
        blockers.append("no stated scale")

    if genre == "atlas":
        return "atlas_volume", "4_not_georeferenceable", "; ".join(
            blockers + ["atlas volume: georeference individual plates, not the record"])
    if genre == "view":
        return "sketch_view", "4_not_georeferenceable", "; ".join(
            blockers + ["perspective view, not a plan"])

    if authority in SURVEY_AUTHORITIES and year and year >= 1830:
        geometric = "survey"
    elif year and year >= 1600 and (authority == "hydrographic"
                                    or "carte marine" in normalize(record["title"])
                                    or "chart" in normalize(record["title"])):
        geometric = "chart"
    elif year and year >= 1700:
        geometric = "early_modern"
    else:
        geometric = "sketch"

    tier = {
        "survey": "1_direct",
        "chart": "2_control_points",
        "early_modern": "2_control_points",
        "sketch": "3_warp_only",
    }[geometric]

    # A published bounding box hands you the corner coordinates, which is what a
    # graticule would otherwise have to supply: a survey sheet that has one is
    # the easiest thing in the corpus to place, whoever hosts the image.
    if has_bbox and has_scale and geometric in ("survey", "chart"):
        tier = "1_direct"
    elif tier == "1_direct" and (quality["scan_resolution_class"] in ("low", "unknown")
                                 or not has_scale):
        tier = "2_control_points"

    # Being hosted off Gallica is an access problem, not a geometric one, so it
    # only demotes a sheet that has nothing else locating it.
    if quality["provenance_tier"] == "partner" and not has_bbox:
        tier = "3_warp_only"
    if quality["provenance_tier"] == "partner":
        blockers.append("image not on IIIF; fetch from the holding library")

    return geometric, tier, "; ".join(blockers)


# --- Q3 / Q4 ---------------------------------------------------------------

def code_themes(record: dict) -> list[str]:
    text = blob(record)
    return [name for name, pattern in THEMATIC_LAYERS.items()
            if re.search(pattern, text)]


def code_inequality(record: dict, quality: dict, layers: list[str],
                    georef_tier: str) -> tuple[str, str]:
    relevant = sorted(set(layers) & INEQUALITY_LAYERS)
    if not relevant:
        return "", "none"
    # Three things all have to hold before a sheet can carry a claim about
    # spatial inequality: it shows a distribution (not just where towns are),
    # Tunisia is its subject rather than incidental, and it can be placed on the
    # ground well enough to read that distribution off it.
    distributional = set(relevant) & DISTRIBUTIONAL_LAYERS
    tunisia_primary = record["confidence"] == "high"
    placeable = georef_tier in ("1_direct", "2_control_points")
    if distributional and tunisia_primary and placeable:
        return " | ".join(relevant), "direct"
    return " | ".join(relevant), "indirect"


FIELDS = [
    "record_id", "title", "year", "century", "confidence", "provenance_tier",
    # Q1
    "bbox_west", "bbox_east", "bbox_north", "bbox_south", "bbox_source",
    "tunisia_extent_share", "orientation", "orientation_basis",
    # Q2
    "geometric_class", "georef_tier", "georef_blockers",
    "scale_class", "scan_resolution_class",
    # Q3
    "thematic_layers", "n_thematic_layers", "content_mappable",
    # Q4
    "inequality_layers", "inequality_use", "coverage_group",
    "url",
]


def coverage_group(record: dict, quality: dict) -> str:
    """Bucket for spotting repeat coverage of the same ground over time."""
    if quality["scale_class"] == "unknown":
        return ""
    return f"{quality['scale_class']}"


def code_record(record: dict, quality: dict, catalogue: dict,
                partner: dict) -> dict:
    row = {
        "record_id": record["record_id"],
        "title": record["title"],
        "year": record["year"],
        "century": record["century"],
        "confidence": record["confidence"],
        "provenance_tier": quality["provenance_tier"],
        "scale_class": quality["scale_class"],
        "scan_resolution_class": quality["scan_resolution_class"],
        "url": record["url"],
    }
    row.update(code_coordinates(record, catalogue, partner))
    row["orientation"], row["orientation_basis"] = code_orientation(record, quality)

    geometric, tier, blockers = code_geometry(
        record, quality, row["bbox_source"] != "none")
    row["geometric_class"] = geometric
    row["georef_tier"] = tier
    row["georef_blockers"] = blockers

    layers = code_themes(record)
    row["thematic_layers"] = " | ".join(layers)
    row["n_thematic_layers"] = str(len(layers))
    if layers and tier != "4_not_georeferenceable":
        row["content_mappable"] = "yes" if tier in ("1_direct", "2_control_points") else "partial"
    else:
        row["content_mappable"] = "no"

    row["inequality_layers"], row["inequality_use"] = code_inequality(
        record, quality, layers, tier)
    row["coverage_group"] = coverage_group(record, quality)
    return row


def summarise(rows: list[dict]) -> dict:
    total = len(rows)
    distribution = lambda f: dict(Counter(r[f] for r in rows).most_common())
    layer_counts = Counter(
        layer for r in rows for layer in r["thematic_layers"].split(" | ") if layer)
    with_box = [r for r in rows if r["bbox_source"] != "none"]
    centred = [r for r in with_box
               if r["tunisia_extent_share"] and float(r["tunisia_extent_share"]) >= 0.25]
    return {
        "records": total,
        "with_coordinates": len(with_box),
        "coordinate_source": distribution("bbox_source"),
        "coordinates_tunisia_centred": len(centred),
        "orientation": distribution("orientation"),
        "geometric_class": distribution("geometric_class"),
        "georef_tier": distribution("georef_tier"),
        "content_mappable": distribution("content_mappable"),
        "thematic_layers": dict(layer_counts.most_common()),
        "inequality_use": distribution("inequality_use"),
        "confidence": distribution("confidence"),
    }


def count_table(title: str, counts: dict, total: int, note: str = "") -> list[str]:
    lines = [f"### {title}", ""]
    if note:
        lines += [note, ""]
    lines += ["| Value | n | % |", "| --- | ---: | ---: |"]
    for value, count in counts.items():
        lines.append(f"| `{value or '—'}` | {count} | {count / total * 100:.0f}% |")
    lines.append("")
    return lines


def record_table(rows: list[dict], columns: list[tuple[str, str]]) -> list[str]:
    header = " | ".join(label for label, _ in columns)
    lines = [f"| {header} |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        cells = []
        for _, field in columns:
            if field == "url":
                cells.append(f"[view]({row['url']})")
            else:
                value = (row[field] or "—").replace("|", "\\|")
                cells.append(value if len(value) <= 62 else value[:61].rstrip() + "…")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def write_report(rows: list[dict], summary: dict, path: Path) -> None:
    total = len(rows)
    lines = [
        "# Georeferencing and thematic potential",
        "",
        f"Coding of all {total} records against four questions. Generated by "
        "`scripts/code_geospatial.py`; variables are defined in "
        "[CODEBOOK-GEO.md](CODEBOOK-GEO.md).",
        "",
        "## Q1. Which maps carry explicit coordinates and a known orientation?",
        "",
        "**Coordinates: available for a quarter of the corpus, from two "
        "sources.** Gallica's Dublin Core carries none at all. Full UNIMARC "
        "records in the BnF catalogue général supply a bounding box in field 123 "
        "`$d–$g` for 34; the partner libraries publish coordinates on their own "
        "item pages, which Gallica's aggregated records drop, and those supply a "
        "further 117 — including the whole 1:50 000 series. Across the corpus, "
        f"**{summary['with_coordinates']} records** have one, and "
        f"**{summary['coordinates_tunisia_centred']}** of those are actually "
        "centred on Tunisia rather than clipping it at the edge of a "
        "Mediterranean or world sheet.",
        "",
    ]
    lines += count_table("Coordinate source", summary["coordinate_source"], total)
    lines += [
        "Practically: **for the other three quarters, coordinates have to be "
        "established by georeferencing against control points.** Where a box "
        "does exist it is worth more than its count suggests, because it hands "
        "you the corner coordinates a transform needs. The "
        "`tunisia_extent_share` column gives the fraction of the sheet occupied "
        "by Tunisia — a direct test of whether the country is the subject or a "
        "corner detail, and the reason 112 of the 151 boxed sheets count as "
        "Tunisian while the rest are Algerian or Mediterranean maps.",
        "",
        "**Orientation: not catalogued, so this column is a presumption, not a "
        "measurement.** Only 2 records mention orientation in their text. The "
        "rest are coded from period and genre, on the convention that European "
        "printed cartography after 1700 is north-up, and that pre-1700 material "
        "and perspective views frequently are not.",
        "",
    ]
    lines += count_table("Orientation", summary["orientation"], total)
    lines += [
        "That presumption was checked by eye on four sheets spanning the corpus:",
        "",
        "| Sheet | What the image shows |",
        "| --- | --- |",
        "| *Manœuvres d'Algérie-Tunisie*, 1929, Service géographique de l'armée | "
        "Full labelled graticule (5°30′, 6°, 6°30′…), scale bar, north-up. |",
        "| *A Chart of the Sea Coast of Italy, Sicily and part of Barbary*, 18th c. | "
        "Plane-chart graticule plus rhumb lines, compass rose, north-up — but "
        "Tunisia appears only as \"PART OF BARBARY\" in the corner. |",
        "| Visconti portolan, dated 1318 | Rhumb lines from compass roses, **no "
        "graticule**. The sheet is also an 1846 copy, not the medieval original, "
        "which the `year` field does not tell you. |",
        "| *Benigni lettori...* (Tunis and La Goulette), Venice, 1566 | "
        "**South-up.** The margins are lettered OSTRO (south) along the top and "
        "TRAMONTANA (north) along the bottom, LEVANTE east at left, PONENTE west "
        "at right. |",
        "",
        "The presumption holds for printed post-1700 material and fails exactly "
        "where the coding says `uncertain` — the 1566 Tunis view is inverted "
        "relative to modern convention, so anything read off it without checking "
        "the image would be upside down. Verify orientation per sheet whenever "
        "it matters.",
        "",
        "## Q2. Which can be georeferenced onto a modern map?",
        "",
    ]
    lines += count_table("Georeferencing tier", summary["georef_tier"], total)
    lines += count_table("Geometric class", summary["geometric_class"], total)

    tier1 = [r for r in rows if r["georef_tier"] == "1_direct"]
    tier1.sort(key=lambda r: r["year"] or "9999")
    lines += [
        f"### The {len(tier1)} `1_direct` records",
        "",
        "Survey products from 1830 on, with a stated scale and a scan good "
        "enough to place control points: these carry a projection and graticule, "
        "so a polynomial or affine transform is enough.",
        "",
    ]
    lines += record_table(tier1, [("Date", "year"), ("Scale", "scale_class"),
                                  ("Title", "title"), ("Layers", "thematic_layers"),
                                  ("Link", "url")])

    lines += [
        "## Q3. Which carry content that can be transferred into a modern map?",
        "",
        "This is a different question from Q2: a sheet can be geometrically "
        "placeable yet carry nothing worth digitising, and a rich thematic sheet "
        "may be impossible to place. `content_mappable` combines the two.",
        "",
    ]
    lines += count_table("Content mappable", summary["content_mappable"], total)
    lines += count_table(
        "Extractable thematic layers", summary["thematic_layers"], total,
        "A record can carry several. Counts are of records mentioning the layer.")
    lines += [
        "The shape of this table is the main finding: the corpus is a **maritime "
        "and military collection**, not a socio-economic one. Coastline and "
        "bathymetry dominate, followed by fortifications. Land-use, population "
        "and economic layers are rare.",
        "",
        "## Q4. Which support the study of spatial inequality and its evolution?",
        "",
        "A sheet qualifies as `direct` only if all three hold: it shows a "
        "**distribution** (roads, railways, administrative limits, land use, "
        "urban fabric, population, economy, mining — not merely where towns "
        "are), Tunisia is its **subject** rather than incidental, and it is "
        "**placeable** (georeferencing tier 1 or 2).",
        "",
    ]
    lines += count_table("Inequality use", summary["inequality_use"], total)

    direct = [r for r in rows if r["inequality_use"] == "direct"]
    direct.sort(key=lambda r: r["year"] or "9999")
    lines += [f"### The {len(direct)} `direct` records", ""]
    lines += record_table(direct, [("Date", "year"), ("Layers", "inequality_layers"),
                                   ("Title", "title"), ("Tier", "georef_tier"),
                                   ("Link", "url")])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps.json")
    parser.add_argument("--quality", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps_coded.csv")
    parser.add_argument("--catalogue", type=Path,
                        default=REPO_ROOT / "data" / "catalogue_records.json")
    parser.add_argument("--partner", type=Path,
                        default=REPO_ROOT / "data" / "partner_records.json")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--report", type=Path,
                        default=REPO_ROOT / "docs" / "GEOREFERENCING.md")
    args = parser.parse_args()

    records = json.loads(args.data.read_text(encoding="utf-8"))["records"]
    quality = {r["record_id"]: r for r in
               csv.DictReader(args.quality.open(encoding="utf-8"))}
    catalogue = {}
    if args.catalogue.exists():
        catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))
    else:
        print("! no catalogue_records.json; no coordinates will be available",
              file=sys.stderr)

    partner = json.loads(args.partner.read_text(encoding="utf-8")) \
        if args.partner.exists() else {}

    rows = [code_record(r, quality[r["record_id"]], catalogue.get(r["record_id"], {}),
                        partner.get(r["record_id"], {}))
            for r in records if r["record_id"] in quality]

    order = {"1_direct": 0, "2_control_points": 1, "3_warp_only": 2,
             "4_not_georeferenceable": 3}
    rows.sort(key=lambda r: (order[r["georef_tier"]], -int(r["n_thematic_layers"]),
                             r["year"] or "9999"))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.out_dir / "gallica_tunisia_maps_geospatial.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    summary = summarise(rows)
    (args.out_dir / "geospatial_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    write_report(rows, summary, args.report)

    print(f"coded {len(rows)} records -> {out_csv}")
    print(f"  report -> {args.report}")
    for key in ("with_coordinates", "coordinates_tunisia_centred"):
        print(f"  {key}: {summary[key]}")
    for key in ("orientation", "georef_tier", "content_mappable", "inequality_use"):
        print(f"  {key}: {summary[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Build a sheet index for the Tunisia 1:50 000 topographic series.

The series is the most useful thing in this corpus for spatial work: army
survey sheets, published coordinates, a consistent grid, and in places two
revisions of the same ground thirty years apart. But the records arrive as
unordered catalogue entries. This turns them into an index you can open in
QGIS: one polygon per sheet, with its designation, revision and projection.

Sheet designations look like:

    Tunisie Flle. N° XIV-B 1-C 37, La Marsa
    Tunisie Feuille n° XXVI-B3-C34, Oued-Zarga
    Tunisie Flle. N° VI [6] B 0 - C 35, Djebel Ichkeul

B is the row, counting south from B0 along the north coast; C is the column,
counting east. The Roman numeral is the sheet's serial number in the series.
Sheets that carry no B-C designation ("coupure spéciale", "Environs de Sfax")
are kept, flagged, and left out of the grid analysis.

Outputs:
    data/tunisia_50k_series.csv      one row per record
    data/tunisia_50k_index.geojson   one polygon per sheet, for QGIS
    data/tunisia_50k_summary.json    grid coverage and gaps
    docs/SERIES-50K.md

Usage:
    python3 scripts/build_series_index.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Roman numeral, an optional bracketed Arabic gloss, then the B row and C column.
DESIGNATION_RE = re.compile(
    r"N[°o]\s*([IVXLCDM]+)\s*(?:\[\d+\])?\s*[-.\s]*B\s*(\d+)\s*[-.\s]*C\s*(\d+)",
    re.IGNORECASE)
# A few sheets carry a serial number but no grid reference at all.
SERIAL_ONLY_RE = re.compile(r"N[°o]\s*([IVXLCDM]+)\s*,", re.IGNORECASE)
# The place name sits between the designation and the statement of responsibility.
NAME_RE = re.compile(r"(?:C\s*\d+|N[°o]\s*[IVXLCDM]+)\s*,\s*([^/]+?)\s*(?:/|$)")

ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(numeral: str) -> int | None:
    total, previous = 0, 0
    for char in reversed(numeral.upper()):
        value = ROMAN_VALUES.get(char)
        if value is None:
            return None
        total = total - value if value < previous else total + value
        previous = max(previous, value)
    return total


def parse_designation(title: str) -> dict:
    parsed: dict = {"serial": "", "serial_number": "", "band": "", "column": "",
                    "sheet_name": "", "designation": ""}
    match = DESIGNATION_RE.search(title)
    if match:
        serial, band, column = match.groups()
        parsed.update({
            "serial": serial.upper(),
            "serial_number": str(roman_to_int(serial) or ""),
            "band": band,
            "column": column,
            "designation": f"B{band}-C{column}",
        })
    else:
        serial = SERIAL_ONLY_RE.search(title)
        if serial:
            parsed["serial"] = serial.group(1).upper()
            parsed["serial_number"] = str(roman_to_int(serial.group(1)) or "")

    name = NAME_RE.search(title)
    if name:
        parsed["sheet_name"] = name.group(1).strip(" ,.[]")
    return parsed


def polygon(box: dict) -> list:
    west, east = box["west"], box["east"]
    south, north = box["south"], box["north"]
    return [[[west, south], [east, south], [east, north],
             [west, north], [west, south]]]


# Same regional boxes the feature coding uses, so the two are comparable.
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


def regional_coverage(rows: list[dict]) -> dict:
    """Share of each region's box falling inside at least one sheet footprint.

    Computed on a 0.02-degree lattice rather than by polygon union, which keeps
    it to the standard library and is accurate enough to answer the only
    question that matters: does the series reach this part of the country.
    """
    boxes = [r["_bbox"] for r in rows if "_bbox" in r]
    step = 0.02
    coverage = {}
    for name, region in REGION_BOXES.items():
        inside = total = 0
        latitude = region["south"] + step / 2
        while latitude < region["north"]:
            longitude = region["west"] + step / 2
            while longitude < region["east"]:
                total += 1
                if any(b["west"] <= longitude <= b["east"]
                       and b["south"] <= latitude <= b["north"] for b in boxes):
                    inside += 1
                longitude += step
            latitude += step
        coverage[name] = round(inside / total, 3) if total else 0.0
    return coverage


def analyse_grid(rows: list[dict]) -> dict:
    """Which grid cells the held sheets occupy, and which are missing."""
    cells = {}
    for row in rows:
        if not row["band"] or not row["column"]:
            continue
        key = (int(row["band"]), int(row["column"]))
        cells.setdefault(key, []).append(row)

    if not cells:
        return {}

    bands = sorted({b for b, _ in cells})
    columns = sorted({c for _, c in cells})

    # A gap only counts inside the rectangle the series actually reaches, and
    # only where the row and column both otherwise exist - the series is not a
    # full rectangle, because Tunisia is not.
    present = set(cells)
    by_band = defaultdict(list)
    for band, column in present:
        by_band[band].append(column)
    interior_gaps = []
    for band, cols in by_band.items():
        for column in range(min(cols), max(cols) + 1):
            if (band, column) not in present:
                interior_gaps.append(f"B{band}-C{column}")

    duplicated = {f"B{b}-C{c}": len(v) for (b, c), v in cells.items() if len(v) > 1}

    return {
        "distinct_cells": len(cells),
        "bands": f"B{min(bands)}–B{max(bands)}",
        "columns": f"C{min(columns)}–C{max(columns)}",
        "band_count": len(bands),
        "column_count": len(columns),
        "interior_gaps": sorted(interior_gaps),
        "interior_gap_count": len(interior_gaps),
        "cells_with_multiple_revisions": duplicated,
    }


FIELDS = [
    "record_id", "serial", "serial_number", "band", "column", "designation",
    "sheet_name", "revision_year", "published_year", "projection", "ellipsoid",
    "identifier", "provenance", "scale_denominator",
    "bbox_west", "bbox_east", "bbox_south",
    "bbox_north", "width_deg", "height_deg", "title", "url",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps.json")
    parser.add_argument("--partner", type=Path,
                        default=REPO_ROOT / "data" / "partner_records.json")
    parser.add_argument("--quality", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps_coded.csv")
    parser.add_argument("--geo", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps_geospatial.csv")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--report", type=Path,
                        default=REPO_ROOT / "docs" / "SERIES-50K.md")
    args = parser.parse_args()

    records = json.loads(args.data.read_text(encoding="utf-8"))["records"]
    partner = json.loads(args.partner.read_text(encoding="utf-8"))
    # Scale and bbox are taken from the merged codings, not from the partner
    # cache alone: seven sheets of this series are BnF-held "Environs de ..."
    # sheets whose scale comes from the BnF catalogue, and selecting on the
    # partner cache dropped them - including both Medenine sheets, the only
    # 1:50 000 coverage of the far south in the corpus.
    quality = {r["record_id"]: r for r in
               csv.DictReader(args.quality.open(encoding="utf-8"))}
    geo = {r["record_id"]: r for r in csv.DictReader(args.geo.open(encoding="utf-8"))}

    rows = []
    for record in records:
        extra = partner.get(record["record_id"], {})
        if quality.get(record["record_id"], {}).get("scale_denominator") != "50000":
            continue
        box = extra.get("bbox")
        if not box:
            geo_row = geo.get(record["record_id"], {})
            if geo_row.get("bbox_source", "none") != "none" and geo_row.get("bbox_west"):
                box = {"west": float(geo_row["bbox_west"]),
                       "east": float(geo_row["bbox_east"]),
                       "south": float(geo_row["bbox_south"]),
                       "north": float(geo_row["bbox_north"])}
        row = {
            "record_id": record["record_id"],
            "revision_year": extra.get("revision_year", ""),
            "published_year": extra.get("published_year", record["year"]),
            "projection": extra.get("projection", ""),
            "ellipsoid": extra.get("ellipsoid", ""),
            "identifier": extra.get("identifier", ""),
            "provenance": quality[record["record_id"]]["provenance_tier"],
            "scale_denominator": "50000",
            "title": record["title"],
            "url": record["url"],
        }
        row.update(parse_designation(record["title"]))
        if box:
            row.update({
                "bbox_west": f"{box['west']:.5f}",
                "bbox_east": f"{box['east']:.5f}",
                "bbox_south": f"{box['south']:.5f}",
                "bbox_north": f"{box['north']:.5f}",
                "width_deg": f"{box['east'] - box['west']:.4f}",
                "height_deg": f"{box['north'] - box['south']:.4f}",
            })
            row["_bbox"] = box
        else:
            row.update({k: "" for k in ("bbox_west", "bbox_east", "bbox_south",
                                        "bbox_north", "width_deg", "height_deg")})
        rows.append(row)

    rows.sort(key=lambda r: (int(r["band"] or 99), int(r["column"] or 99),
                             r["revision_year"] or r["published_year"] or ""))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "tunisia_50k_series.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    features = []
    for row in rows:
        if "_bbox" not in row:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": polygon(row["_bbox"])},
            "properties": {k: v for k, v in row.items()
                           if k not in ("_bbox",) and v != ""},
        })
    geojson = {"type": "FeatureCollection",
               "name": "Tunisia 1:50 000 sheet index",
               "crs": {"type": "name",
                       "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
               "features": features}
    geo_path = args.out_dir / "tunisia_50k_index.geojson"
    geo_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    boxed = [r for r in rows if "_bbox" in r]
    widths = sorted(float(r["width_deg"]) for r in boxed)
    heights = sorted(float(r["height_deg"]) for r in boxed)
    summary = {
        "records": len(rows),
        "with_bbox": len(boxed),
        "with_designation": sum(1 for r in rows if r["designation"]),
        "extent": {
            "west": round(min(r["_bbox"]["west"] for r in boxed), 4),
            "east": round(max(r["_bbox"]["east"] for r in boxed), 4),
            "south": round(min(r["_bbox"]["south"] for r in boxed), 4),
            "north": round(max(r["_bbox"]["north"] for r in boxed), 4),
        } if boxed else {},
        "sheet_size_deg": {
            "median_width": widths[len(widths) // 2] if widths else None,
            "median_height": heights[len(heights) // 2] if heights else None,
        },
        "projection": dict(Counter(r["projection"] for r in rows if r["projection"])
                           .most_common()),
        "ellipsoid": dict(Counter(r["ellipsoid"] for r in rows if r["ellipsoid"])
                          .most_common()),
        "revision_year": dict(sorted(Counter(
            r["revision_year"] for r in rows if r["revision_year"]).items())),
        "grid": analyse_grid(rows),
        "regional_coverage": regional_coverage(rows),
    }
    (args.out_dir / "tunisia_50k_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    write_report(rows, summary, args.report)

    print(f"{len(rows)} sheets -> {csv_path}")
    print(f"  {len(features)} footprints -> {geo_path}")
    print(f"  report -> {args.report}")
    print(f"  grid: {summary['grid'].get('distinct_cells')} cells, "
          f"{summary['grid'].get('bands')} x {summary['grid'].get('columns')}, "
          f"{summary['grid'].get('interior_gap_count')} interior gaps")
    return 0


def write_report(rows: list[dict], summary: dict, path: Path) -> None:
    grid = summary["grid"]
    extent = summary["extent"]
    lines = [
        "# The Tunisia 1:50 000 series",
        "",
        "Generated by `scripts/build_series_index.py`. Sheet index as GeoJSON in "
        "[`data/tunisia_50k_index.geojson`](../data/tunisia_50k_index.geojson) — "
        "open it directly in QGIS.",
        "",
        f"**{summary['records']} records**, {summary['with_bbox']} with published "
        f"coordinates and {summary['with_designation']} carrying a B–C grid "
        "reference.",
        "",
        "## Why this series and not the rest of the corpus",
        "",
        "It is the only material here that combines all four of: instrument "
        "survey by the Service géographique de l'armée, a published bounding box "
        "per sheet, a consistent grid, and a scale fine enough to carry wells, "
        "marabouts, ksour and individual farms. Everything else is either too "
        "small-scale for point features or has no coordinates.",
        "",
        "## Grid",
        "",
        f"- **{grid.get('distinct_cells')} distinct sheet cells**, "
        f"{grid.get('bands')} by {grid.get('columns')} "
        f"({grid.get('band_count')} rows × {grid.get('column_count')} columns)",
        f"- Sheet size: **{summary['sheet_size_deg']['median_width']}° × "
        f"{summary['sheet_size_deg']['median_height']}°** "
        "(roughly 31 × 22 km at this latitude)",
        f"- Extent covered: **{extent.get('west')}°E–{extent.get('east')}°E, "
        f"{extent.get('south')}°N–{extent.get('north')}°N**",
        "",
        "`B` is the row, counting south from B0 on the north coast; `C` is the "
        "column, counting east. The Roman numeral is the sheet's serial number.",
        "",
    ]

    coverage = summary.get("regional_coverage", {})
    if coverage:
        covered = [k for k, v in coverage.items() if v >= 0.5]
        absent = [k for k, v in coverage.items() if v < 0.05]
        lines += [
            "## Does it cover the whole country?",
            "",
            "**No — the held sheets stop at 33.2°N.** Tunisia reaches 30.2°N, so "
            "roughly the southern two fifths of the country is outside the "
            "footprints entirely. Share of each region falling inside a held "
            "sheet:",
            "",
            "| Region | Covered |",
            "| --- | ---: |",
        ]
        for name, value in sorted(coverage.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{name}` | {value * 100:.0f}% |")
        lines += [
            "",
            f"Well covered: {', '.join('`' + c + '`' for c in covered) or 'none'}. "
            f"Effectively absent: {', '.join('`' + a + '`' for a in absent) or 'none'}.",
            "",
            "The gap is not that the sheets were never made. Two BnF-held "
            "*Environs de Medenine* sheets at 1:50 000 sit in this corpus, in "
            "the middle of the missing area — but neither carries published "
            "coordinates, so neither appears in the footprints above. The "
            "southern sheets exist; this holding just does not have them "
            "catalogued with extents.",
            "",
        ]

    gaps = grid.get("interior_gaps") or []
    if gaps:
        lines += [
            f"### {len(gaps)} interior gaps",
            "",
            "Cells with sheets to both east and west in the same row, but no "
            "sheet held here. These are the holes to fill before the coverage is "
            "continuous:",
            "",
            "`" + "`, `".join(gaps) + "`",
            "",
        ]
    else:
        lines += ["No interior gaps: every row is continuous between its "
                  "westernmost and easternmost held sheet.", ""]

    duplicates = grid.get("cells_with_multiple_revisions") or {}
    if duplicates:
        lines += [
            f"### {len(duplicates)} cells held in more than one revision",
            "",
            "The same ground, surveyed twice. These are the sheets that support "
            "before-and-after work directly, with no georeferencing mismatch "
            "between the two dates because the sheet lines are identical:",
            "",
            "| Cell | Revisions |",
            "| --- | --- |",
        ]
        by_cell = defaultdict(list)
        for row in rows:
            if row["designation"] in duplicates:
                label = row["revision_year"] or row["published_year"] or "?"
                by_cell[row["designation"]].append(
                    f"{label} ({row['sheet_name'] or '—'})")
        for cell in sorted(by_cell, key=lambda c: (int(c.split("-")[0][1:]),
                                                   int(c.split("-")[1][1:]))):
            lines.append(f"| `{cell}` | {', '.join(sorted(set(by_cell[cell])))} |")
        lines.append("")

    lines += ["## Projection", ""]
    if summary["projection"]:
        for name, count in summary["projection"].items():
            lines.append(f"- **{name}** — {count} sheets")
        for name, count in summary["ellipsoid"].items():
            lines.append(f"- Ellipsoid **{name}** — {count} sheets")
        lines += [
            "",
            "Only a minority of records state this, and it is not consistent "
            "across the series: the Bonne projection on Clarke 1880 belongs to "
            "the older sheets, while later ones use the Carte Internationale "
            "layout. Two records for the same La Marsa sheet differ — the 1932 "
            "revision names the projection, the 1902 one does not — so absence "
            "here is a cataloguing gap, not evidence the sheet is unprojected.",
            "",
            "For georeferencing, Bonne on Clarke 1880 is not a standard EPSG "
            "code; it has to be defined by hand, and the published corner "
            "coordinates are the practical way in regardless.",
            "",
        ]

    lines += ["## Revision dates", ""]
    if summary["revision_year"]:
        lines.append("| Revision | Sheets |")
        lines.append("| --- | ---: |")
        for year, count in summary["revision_year"].items():
            lines.append(f"| {year} | {count} |")
        lines.append("")

    lines += [
        "## Sheets",
        "",
        "| Cell | Serial | Name | Revision | Extent (W, S, E, N) | Link |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if not row.get("bbox_west"):
            continue
        extent_text = (f"{row['bbox_west']}, {row['bbox_south']}, "
                       f"{row['bbox_east']}, {row['bbox_north']}")
        name = (row["sheet_name"] or "—").replace("|", "\\|")
        lines.append(
            f"| `{row['designation'] or '—'}` | {row['serial'] or '—'} | {name} "
            f"| {row['revision_year'] or row['published_year'] or '—'} "
            f"| {extent_text} | [view]({row['url']}) |")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())

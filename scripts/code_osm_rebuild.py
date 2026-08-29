#!/usr/bin/env python3
"""Score each map for how much of it could be rebuilt from OpenStreetMap.

"Rebuild" is used in one specific sense throughout: OSM records the present, so
no historical map can be recreated from it. What can be built is a **modern
counterpart of the same layers**, against which the historical sheet can be
compared feature by feature. A map scores well here when the things it draws
have OSM equivalents, and badly when they do not - regardless of how good a map
it is.

The per-layer confidences come from config/osm_crosswalk.json, which is grounded
in measurements taken inside the map sheets' own extents
(scripts/probe_osm_coverage.py -> data/osm_coverage.json), not from assumptions
about OSM tagging in general.

Outputs:
    data/gallica_tunisia_maps_osm.csv
    data/osm_rebuild_summary.json
    docs/OSM-REBUILD.md

Usage:
    python3 scripts/code_osm_rebuild.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.25, "none": 0.0}

# Georeferencing has to work before any comparison is possible: a layer you
# cannot place on the ground cannot be compared with an OSM layer.
GEOREF_FACTOR = {
    "1_direct": 1.0,
    "2_control_points": 0.8,
    "3_warp_only": 0.4,
    "4_not_georeferenceable": 0.0,
}


def layers_of(feature_row: dict, geo_row: dict) -> list[str]:
    """Every layer attributed to a record, from whichever coding saw it.

    `features_observed` is what someone saw on the image and is preferred;
    `expected_features` is the scale model; the geospatial coding's
    `thematic_layers` catches names the feature coding uses differently.
    """
    seen = []
    for field, source in ((feature_row.get("features_observed"), "observed"),
                          (feature_row.get("expected_features"), "expected")):
        if field:
            seen = [v for v in field.split(" | ") if v]
            if source == "observed":
                break
    extra = [v for v in (geo_row.get("thematic_layers") or "").split(" | ") if v]
    # Names that differ between the two codings but mean the same layer.
    alias = {"hydrology": "water", "settlement_hierarchy": "settlements",
             "fortifications": "forts_ksour", "geology_mines": "mines",
             "coastline_bathymetry": "coastline_bathymetry"}
    merged = list(seen)
    for value in extra:
        value = alias.get(value, value)
        if value not in merged:
            merged.append(value)
    return merged


def score(layers: list[str], crosswalk: dict, georef_tier: str) -> tuple[str, str, str, str]:
    """Return (score, band, rebuildable_layers, blocked_layers)."""
    known = [l for l in layers if l in crosswalk]
    if not known:
        return "", "unknown", "", ""

    weights = [CONFIDENCE_WEIGHT[crosswalk[l]["confidence"]] for l in known]
    layer_score = sum(weights) / len(weights)
    total = layer_score * GEOREF_FACTOR.get(georef_tier, 0.0)

    rebuildable = [l for l in known
                   if crosswalk[l]["confidence"] in ("high", "medium")]
    blocked = [l for l in known if crosswalk[l]["confidence"] == "none"]

    if total >= 0.65:
        band = "most_of_it"
    elif total >= 0.40:
        band = "partly"
    elif total > 0.0:
        band = "little"
    else:
        band = "none"
    return f"{total:.2f}", band, " | ".join(rebuildable), " | ".join(blocked)


FIELDS = [
    "record_id", "title", "year", "scale_denominator", "georef_tier",
    "layers", "osm_rebuild_score", "osm_rebuild", "rebuildable_layers",
    "blocked_layers", "url",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps_features.csv")
    parser.add_argument("--geo", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps_geospatial.csv")
    parser.add_argument("--crosswalk", type=Path,
                        default=REPO_ROOT / "config" / "osm_crosswalk.json")
    parser.add_argument("--coverage", type=Path,
                        default=REPO_ROOT / "data" / "osm_coverage.json")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--report", type=Path,
                        default=REPO_ROOT / "docs" / "OSM-REBUILD.md")
    args = parser.parse_args()

    crosswalk = json.loads(args.crosswalk.read_text(encoding="utf-8"))["layers"]
    features = {r["record_id"]: r for r in
                csv.DictReader(args.features.open(encoding="utf-8"))}
    geo = {r["record_id"]: r for r in csv.DictReader(args.geo.open(encoding="utf-8"))}
    coverage = json.loads(args.coverage.read_text(encoding="utf-8")) \
        if args.coverage.exists() else {}

    rows = []
    for record_id, feature_row in features.items():
        geo_row = geo.get(record_id, {})
        layers = layers_of(feature_row, geo_row)
        value, band, rebuildable, blocked = score(
            layers, crosswalk, geo_row.get("georef_tier", "3_warp_only"))
        rows.append({
            "record_id": record_id,
            "title": feature_row["title"],
            "year": feature_row["year"],
            "scale_denominator": feature_row["scale_denominator"],
            "georef_tier": geo_row.get("georef_tier", ""),
            "layers": " | ".join(layers),
            "osm_rebuild_score": value,
            "osm_rebuild": band,
            "rebuildable_layers": rebuildable,
            "blocked_layers": blocked,
            "url": feature_row["url"],
        })

    order = {"most_of_it": 0, "partly": 1, "little": 2, "none": 3, "unknown": 4}
    rows.sort(key=lambda r: (order[r["osm_rebuild"]],
                             -float(r["osm_rebuild_score"] or 0)))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.out_dir / "gallica_tunisia_maps_osm.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    layer_counts = Counter(l for r in rows for l in r["layers"].split(" | ") if l)
    summary = {
        "records": len(rows),
        "osm_rebuild": dict(Counter(r["osm_rebuild"] for r in rows).most_common()),
        "layers_present": dict(layer_counts.most_common()),
        "layer_confidence": {k: v["confidence"] for k, v in crosswalk.items()},
        "sheets_probed": len([v for v in coverage.values() if "error" not in v]),
    }
    (args.out_dir / "osm_rebuild_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    write_report(rows, summary, crosswalk, coverage, args.report)

    print(f"coded {len(rows)} records -> {out_csv}")
    print(f"  report -> {args.report}")
    print(f"  osm_rebuild: {summary['osm_rebuild']}")
    return 0


def write_report(rows, summary, crosswalk, coverage, path: Path) -> None:
    total = len(rows)
    probed = [v for v in coverage.values() if "error" not in v]

    lines = [
        "# What can be rebuilt from OpenStreetMap",
        "",
        "Generated by `scripts/code_osm_rebuild.py`. Crosswalk in "
        "[`config/osm_crosswalk.json`](../config/osm_crosswalk.json); coverage "
        "measurements in [`data/osm_coverage.json`](../data/osm_coverage.json).",
        "",
        "## What \"rebuild\" can and cannot mean",
        "",
        "OSM records the present. **No historical map here can be recreated from "
        "it.** What can be built is a modern counterpart of the same layers, so "
        "the historical sheet can be compared against it feature by feature — "
        "which road existed then and not now, which village has grown, which "
        "well has gone. A map scores well below when the things it draws have "
        "OSM equivalents, and badly when they do not, regardless of how good a "
        "map it is.",
        "",
        "## Measured, not assumed",
        "",
        f"OSM coverage was probed inside the published extents of "
        f"{len(probed)} of the 1:50 000 sheets, rather than inferred from "
        "general tagging practice. Overpass and Geofabrik both refuse "
        "connections from this environment, so the probe uses the main OSM API's "
        "`/map` call; a 1:50 000 sheet is about 0.067 square degrees, inside its "
        "0.25 limit, and dense urban sheets are quartered and summed.",
        "",
        "Counts below are per sheet.",
        "",
        "| Layer | OSM tags | Confidence | What the probe found |",
        "| --- | --- | --- | --- |",
    ]
    for name, entry in sorted(crosswalk.items(),
                              key=lambda kv: (-CONFIDENCE_WEIGHT[kv[1]["confidence"]],
                                              kv[0])):
        tags = ", ".join(f"`{t}`" for t in entry["osm"]) if entry["osm"] else "—"
        if len(tags) > 78:
            tags = tags[:77] + "…"
        lines.append(f"| `{name}` | {tags} | **{entry['confidence']}** | "
                     f"{entry.get('observed', '—')} |")
    lines.append("")

    lines += [
        "## The finding",
        "",
        "**The infrastructure layers rebuild well; the fine-grained ones do not "
        "exist in OSM at all.**",
        "",
        "Roads run to 455–1577 ways per sheet, railways to 59, administrative "
        "boundaries appear on every sheet probed, and buildings to over 2000 in "
        "settled areas. Against that, **every sheet probed returned zero typed "
        "shrines, zero forts or ksour, zero ruins and zero mines**, and at most "
        "two typed wells.",
        "",
        "Those absent classes are precisely what makes the 1:50 000 series "
        "valuable — the marabouts, koubbas, ksour, henchirs and wells read off "
        "the Medenine and Kef sheets. So the relationship runs the other way "
        "from what one might expect: **OSM cannot supply them, and the "
        "historical sheets could supply OSM.**",
        "",
        "Partial recovery is possible through toponymy, because Tunisian place "
        "names carry the feature class: 1–3 objects per sheet are named *Bir*, "
        "2–3 *Sidi* or *Koubba*, about one *Ksar*. That is one to two orders of "
        "magnitude below the density drawn on the sheets. A caution for anyone "
        "matching names: in Tunisia the OSM `name` tag is usually **Arabic "
        "script**, with the French transliteration in `name:fr` — matching Latin "
        "forms against `name` alone finds almost nothing.",
        "",
        "Coverage is also very uneven. One probed sheet held 4134 tagged "
        "objects; another, in the rural north-west, held **7**.",
        "",
        "## How the corpus scores",
        "",
    ]
    counts = summary["osm_rebuild"]
    lines += ["| Band | n | % |", "| --- | ---: | ---: |"]
    for band in ("most_of_it", "partly", "little", "none", "unknown"):
        if band in counts:
            lines.append(f"| `{band}` | {counts[band]} | "
                         f"{counts[band] / total * 100:.0f}% |")
    lines.append("")

    best = [r for r in rows if r["osm_rebuild"] == "most_of_it"][:30]
    lines += [
        f"### The strongest candidates",
        "",
        "Highest-scoring records: layers OSM covers well, and georeferenceable "
        "enough to lay the two side by side.",
        "",
        "| Score | Date | Title | Rebuildable layers | Link |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in best:
        title = r["title"].replace("|", "\\|")
        title = title if len(title) <= 52 else title[:51].rstrip() + "…"
        layers = r["rebuildable_layers"].replace("|", ",")
        layers = layers if len(layers) <= 46 else layers[:45].rstrip() + "…"
        lines.append(f"| {r['osm_rebuild_score']} | {r['year'] or '—'} | {title} "
                     f"| {layers} | [view]({r['url']}) |")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())

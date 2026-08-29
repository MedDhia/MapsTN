#!/usr/bin/env python3
"""Measure what OpenStreetMap holds inside the extent of individual map sheets.

The question this answers is not "how much OSM data is there in Tunisia" but
"for this sheet, how much of what it draws could be rebuilt from OSM today".
So it queries the OSM API for each sheet's own published bounding box and counts
features in the tag families that correspond to the historical layers coded in
data/gallica_tunisia_maps_features.csv.

It counts two different things, and the difference matters:

  typed features - a well tagged man_made=water_well, a shrine tagged
                   historic=tomb. Recoverable as geometry with attributes.
  toponym generics - any OSM object whose *name* begins Bir, Aïn, Sidi, Henchir,
                   Ksar, Bordj, Koubba, Zaouia. Tunisian toponymy preserves the
                   feature class in the name, so these are recoverable as
                   locations even where nobody has typed them properly. For the
                   1:50 000 sheets this is usually the larger number.

Note on endpoints: Overpass and Geofabrik are unreachable from some networks
(both reset the connection here), so this deliberately uses the main OSM API's
/map call, which is available. That caps a request at 0.25 square degrees, which
comfortably fits a 1:50 000 sheet (~0.067) but not a national map.

Usage:
    python3 scripts/probe_osm_coverage.py --limit 8
    python3 scripts/probe_osm_coverage.py --record-id oai:u-bordeaux-montaigne.fr:340396
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OSM_API = "https://api.openstreetmap.org/api/0.6/map"
USER_AGENT = "MapsTN-coverage-probe/1.0 (historical map corpus research)"
MAX_AREA_DEG2 = 0.25  # OSM API limit on a /map call

# Historical layer -> OSM tag tests. Each test is (key, value-regex or None).
TYPED_FEATURES = {
    "roads": [("highway", r"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|track|path)$")],
    "railways": [("railway", r"^(rail|narrow_gauge|abandoned|disused|razed)$")],
    "settlements": [("place", r"^(city|town|village|hamlet|isolated_dwelling|locality)$")],
    "wells_springs": [("man_made", r"^(water_well|cistern|water_tower)$"), ("natural", r"^spring$")],
    "mosques": [("religion", r"^muslim$")],
    "shrines_marabouts": [("historic", r"^(tomb|shrine|memorial)$"), ("building", r"^shrine$")],
    "forts_ksour": [("historic", r"^(castle|fort|city_gate)$"), ("building", r"^(castle|fortification)$")],
    "ruins_henchirs": [("historic", r"^(ruins|archaeological_site)$")],
    "mines": [("man_made", r"^(mineshaft|adit)$"), ("landuse", r"^quarry$")],
    "water": [("natural", r"^(water|wetland|salt_pond)$"), ("waterway", r".+")],
    "land_use": [("landuse", r"^(farmland|orchard|vineyard|forest|meadow)$")],
    "buildings": [("building", r".+")],
    "admin_boundaries": [("boundary", r"^administrative$")],
}

# Feature generics as they survive in Tunisian place names, in both scripts.
# This matters more than it looks: in Tunisia OSM the plain `name` tag is
# usually Arabic and the French transliteration sits in `name:fr`, so matching
# Latin forms against `name` alone finds almost nothing.
TOPONYM_GENERICS = {
    "bir (well)": r"^(bir|biar|bi'r)\b|^(بئر|بير)",
    "ain (spring)": r"^(ain|ayn|aioun)\b|^(عين)",
    "sidi (shrine)": r"^(sidi|sayyidi|lalla|lella)\b|^(سيدي|لالة|سيدى)",
    "henchir (ruin)": r"^(henchir|hanchir)\b|^(هنشير|هنشير)",
    "ksar (fort)": r"^(ksar|qsar|ksour)\b|^(قصر|قصور)",
    "bordj (fort)": r"^(bordj|borj|burj)\b|^(برج)",
    "koubba/zaouia": r"^(koubba|qubba|zaouia|zawiya|zaouiet)\b|^(قبة|زاوية)",
    "oued (wadi)": r"^(oued|wadi|wed)\b|^(واد|وادي)",
    "djebel (hill)": r"^(djebel|jebel|jbel)\b|^(جبل)",
}
# Every tag that can carry a place name here.
NAME_KEYS = ("name", "name:fr", "name:ar", "alt_name", "int_name",
             "official_name", "old_name")


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def fetch_map(south: float, west: float, north: float, east: float,
              retries: int = 2, timeout: int = 180) -> bytes | None:
    url = f"{OSM_API}?bbox={west:.5f},{south:.5f},{east:.5f},{north:.5f}"
    delay = 5.0
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            # 400 = too many nodes or bbox too large; not worth retrying.
            if error.code in (400, 509):
                return error.code
            if attempt == retries:
                return None
            time.sleep(delay)
            delay *= 2
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == retries:
                return None
            time.sleep(delay)
            delay *= 2
    return None


def count_features(payload: bytes) -> tuple[dict, dict, int]:
    """Return (typed counts, toponym counts, total tagged objects)."""
    typed = Counter()
    toponyms = Counter()
    tagged = 0

    compiled = {layer: [(k, re.compile(v)) for k, v in tests]
                for layer, tests in TYPED_FEATURES.items()}
    generics = {name: re.compile(pattern)
                for name, pattern in TOPONYM_GENERICS.items()}

    root = ET.fromstring(payload)
    for element in root:
        if element.tag not in ("node", "way", "relation"):
            continue
        tags = {t.get("k"): t.get("v") for t in element.findall("tag")}
        if not tags:
            continue
        tagged += 1
        for layer, tests in compiled.items():
            if any(key in tags and pattern.match(tags[key] or "")
                   for key, pattern in tests):
                typed[layer] += 1
        candidates = [normalize(tags[k]) for k in NAME_KEYS if tags.get(k)]
        if candidates:
            for label, pattern in generics.items():
                # One object, one count, however many name tags it carries.
                if any(pattern.match(n) for n in candidates):
                    toponyms[label] += 1
    return dict(typed), dict(toponyms), tagged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geo", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps_geospatial.csv")
    parser.add_argument("--quality", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps_coded.csv")
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "data" / "osm_coverage.json")
    parser.add_argument("--limit", type=int, default=8,
                        help="how many sheets to probe")
    parser.add_argument("--record-id", action="append", default=[],
                        help="probe specific records instead of a spread")
    parser.add_argument("--pause", type=float, default=6.0,
                        help="seconds between API calls; the OSM API is a shared "
                             "resource and this is not a bulk endpoint")
    args = parser.parse_args()

    geo = list(csv.DictReader(args.geo.open(encoding="utf-8")))
    quality = {r["record_id"]: r for r in
               csv.DictReader(args.quality.open(encoding="utf-8"))}

    def area(row):
        return ((float(row["bbox_east"]) - float(row["bbox_west"]))
                * (float(row["bbox_north"]) - float(row["bbox_south"])))

    candidates = [r for r in geo
                  if r["bbox_source"] != "none" and r["bbox_west"]
                  and 0 < area(r) <= MAX_AREA_DEG2]

    if args.record_id:
        chosen = [r for r in candidates if r["record_id"] in args.record_id]
    else:
        # Spread the sample across regions rather than sampling one cluster.
        features = {r["record_id"]: r for r in csv.DictReader(
            (REPO_ROOT / "data" / "gallica_tunisia_maps_features.csv").open(encoding="utf-8"))}
        by_region: dict[str, dict] = {}
        for row in sorted(candidates, key=area):
            regions = features.get(row["record_id"], {}).get("regions_covered", "")
            key = regions.split(" | ")[0] if regions else "unknown"
            by_region.setdefault(key, row)
        chosen = list(by_region.values())[:args.limit]

    print(f"{len(candidates)} sheets small enough to probe; sampling {len(chosen)}")

    results = {}
    for index, row in enumerate(chosen, 1):
        south, west = float(row["bbox_south"]), float(row["bbox_west"])
        north, east = float(row["bbox_north"]), float(row["bbox_east"])
        payload = fetch_map(south, west, north, east)
        # An urban sheet can hold more than the 50 000 nodes one call returns.
        # Split it into quadrants and sum rather than discarding the sheet.
        if payload == 400:
            mid_lat, mid_lon = (south + north) / 2, (west + east) / 2
            quadrants = [(south, west, mid_lat, mid_lon), (south, mid_lon, mid_lat, east),
                         (mid_lat, west, north, mid_lon), (mid_lat, mid_lon, north, east)]
            typed_sum, topo_sum, tagged_sum, ok = Counter(), Counter(), 0, 0
            for qs, qw, qn, qe in quadrants:
                part = fetch_map(qs, qw, qn, qe)
                if isinstance(part, bytes):
                    t, g, n = count_features(part)
                    typed_sum.update(t); topo_sum.update(g); tagged_sum += n; ok += 1
                time.sleep(args.pause)
            if ok:
                results[row["record_id"]] = {
                    "title": row["title"],
                    "scale_denominator": quality[row["record_id"]]["scale_denominator"],
                    "bbox": {"south": south, "west": west, "north": north, "east": east},
                    "area_deg2": round(area(row), 4),
                    "tagged_objects": tagged_sum,
                    "typed_features": dict(typed_sum),
                    "toponym_generics": dict(topo_sum),
                    "note": f"summed from {ok} of 4 quadrants; single call exceeded the node cap",
                }
                print(f"  [{index}/{len(chosen)}] {tagged_sum:>6} tagged | "
                      f"{sum(topo_sum.values()):>4} toponym generics | "
                      f"{row['title'][:38]} (quartered)")
                continue
        if not isinstance(payload, bytes):
            reason = ("too dense for one API call (over 50 000 nodes)"
                      if payload == 400 else
                      "API declined (bandwidth limit)" if payload == 509
                      else "fetch failed")
            print(f"  [{index}/{len(chosen)}] SKIPPED ({reason}) {row['title'][:40]}")
            results[row["record_id"]] = {"title": row["title"], "error": reason}
            time.sleep(args.pause)
            continue
        typed, toponyms, tagged = count_features(payload)
        results[row["record_id"]] = {
            "title": row["title"],
            "scale_denominator": quality[row["record_id"]]["scale_denominator"],
            "bbox": {"south": south, "west": west, "north": north, "east": east},
            "area_deg2": round(area(row), 4),
            "tagged_objects": tagged,
            "typed_features": typed,
            "toponym_generics": toponyms,
        }
        print(f"  [{index}/{len(chosen)}] {tagged:>6} tagged | "
              f"{sum(toponyms.values()):>4} toponym generics | {row['title'][:44]}")
        time.sleep(args.pause)

    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

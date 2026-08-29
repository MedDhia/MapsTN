#!/usr/bin/env python3
"""Fetch UNIMARC catalogue records from the BnF for maps that have a notice.

Gallica's SRU exposes only Dublin Core, which drops the fields that matter for
georeferencing. The BnF catalogue général exposes full UNIMARC over its own SRU
endpoint, where cartographic material carries:

    123 $b            scale denominator
    123 $d $e $f $g   bounding box: westernmost, easternmost, northernmost,
                      southernmost, as [NSEW]DDDMMSS
    206 $a $b         mathematical data as free text (scale statements, and
                      sometimes coordinates or a prime meridian in words)
    607 $a $y $z      structured geographic subject headings
    608 $a            form / genre

Results are cached in data/catalogue_records.json; re-runs only fetch what is
missing.

Usage:
    python3 scripts/fetch_catalogue_records.py
    python3 scripts/fetch_catalogue_records.py --refresh
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRU_ENDPOINT = "https://catalogue.bnf.fr/api/SRU"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

NOTICE_ARK_RE = re.compile(r"ark:/12148/cb\w+")
FIELD_RE = re.compile(
    r'<[^>]*datafield[^>]*tag="(\d{3})"[^>]*>(.*?)</[^>]*datafield>', re.S)
SUBFIELD_RE = re.compile(r'code="(\w)"[^>]*>([^<]*)<')
# 123 $d-$g look like 'E0133000' / 'W0092300': hemisphere, 3-digit degrees,
# 2-digit minutes, 2-digit seconds.
COORD_RE = re.compile(r"^([NSEW])(\d{3})(\d{2})(\d{2})$")

WANTED_TAGS = {"123", "206", "607", "608", "930", "120", "121"}


def fetch(ark: str, retries: int = 3, timeout: int = 45) -> str | None:
    params = {
        "version": "1.2",
        "operation": "searchRetrieve",
        "query": f'bib.persistentid all "{ark}"',
        "recordSchema": "unimarcxchange",
        "maximumRecords": "1",
    }
    url = f"{SRU_ENDPOINT}?{urllib.parse.urlencode(params)}"
    delay = 2.0
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == retries:
                return None
            time.sleep(delay)
            delay *= 2
    return None


def parse_coordinate(value: str) -> float | None:
    """'E0133000' -> 13.5 decimal degrees; west and south come back negative."""
    match = COORD_RE.match(value.strip())
    if not match:
        return None
    hemisphere, degrees, minutes, seconds = match.groups()
    decimal = int(degrees) + int(minutes) / 60 + int(seconds) / 3600
    return -decimal if hemisphere in "WS" else decimal


def parse_record(xml: str) -> dict:
    fields: dict[str, list] = {}
    for tag, body in FIELD_RE.findall(xml):
        if tag not in WANTED_TAGS:
            continue
        fields.setdefault(tag, []).append(SUBFIELD_RE.findall(body))

    parsed: dict = {"tags_present": sorted(fields)}

    for subfields in fields.get("123", []):
        codes = dict(subfields)
        box = {
            "west": parse_coordinate(codes.get("d", "")),
            "east": parse_coordinate(codes.get("e", "")),
            "north": parse_coordinate(codes.get("f", "")),
            "south": parse_coordinate(codes.get("g", "")),
        }
        if all(v is not None for v in box.values()):
            # Subfield order is not always respected in the source records.
            parsed["bbox"] = {
                "west": min(box["west"], box["east"]),
                "east": max(box["west"], box["east"]),
                "south": min(box["north"], box["south"]),
                "north": max(box["north"], box["south"]),
            }
        if codes.get("b"):
            parsed.setdefault("scale_123", codes["b"])

    math_text = []
    for subfields in fields.get("206", []):
        math_text.append(" ".join(value for _, value in subfields))
    if math_text:
        parsed["math_data"] = " | ".join(t.strip() for t in math_text if t.strip())

    places = []
    for subfields in fields.get("607", []):
        parts = [value for code, value in subfields if code in "axyz"]
        if parts:
            places.append(" -- ".join(parts))
    if places:
        parsed["geo_headings"] = places

    genres = [value for subfields in fields.get("608", [])
              for code, value in subfields if code == "a"]
    if genres:
        parsed["genre_headings"] = genres

    shelf = [value for subfields in fields.get("930", [])
             for code, value in subfields if code == "a"]
    if shelf:
        parsed["shelfmark"] = shelf[0]

    for tag in ("120", "121"):
        coded = [value for subfields in fields.get(tag, [])
                 for code, value in subfields if code == "a"]
        if coded:
            parsed[f"coded_{tag}"] = coded[0]

    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps.json")
    parser.add_argument("--cache", type=Path,
                        default=REPO_ROOT / "data" / "catalogue_records.json")
    parser.add_argument("--pause", type=float, default=0.25)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    records = json.loads(args.data.read_text(encoding="utf-8"))["records"]
    targets = {}
    for record in records:
        match = NOTICE_ARK_RE.search(record["catalogue_notice"] or "")
        if match:
            targets[record["record_id"]] = match.group(0)

    cache: dict = {}
    if args.cache.exists() and not args.refresh:
        cache = json.loads(args.cache.read_text(encoding="utf-8"))

    pending = [k for k in targets if k not in cache]
    print(f"{len(targets)} records with a catalogue notice, "
          f"{len(targets) - len(pending)} cached, {len(pending)} to fetch")

    for index, record_id in enumerate(pending, 1):
        xml = fetch(targets[record_id])
        cache[record_id] = parse_record(xml) if xml else {}
        if index % 50 == 0 or index == len(pending):
            boxes = sum(1 for v in cache.values() if v.get("bbox"))
            print(f"  {index}/{len(pending)} fetched, {boxes} with a bounding box")
            args.cache.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        time.sleep(args.pause)

    args.cache.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    boxes = sum(1 for v in cache.values() if v.get("bbox"))
    math = sum(1 for v in cache.values() if v.get("math_data"))
    print(f"\n{len(cache)} catalogue records; {boxes} carry a bounding box, "
          f"{math} carry mathematical data -> {args.cache}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

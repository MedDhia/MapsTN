#!/usr/bin/env python3
"""Recover scale and coordinates for partner-library records from their own site.

Gallica's aggregated index strips partner records down to almost nothing: the 89
sheets of the Tunisia 1:50 000 topographic series arrive with no scale, no
coordinates, no catalogue notice and no IIIF manifest. Their own item pages at
the Université Bordeaux Montaigne "1886" collection carry both, in a rendered
MARC 255 statement:

    Coordonnées : 1:50 000 (E 9°51'26'' -- E 10°13'34'' / N 36°51'18'' -- N 36°39'25'')

This fetches those pages and parses scale and bounding box out of them, which
moves the series from "unknown scale, no coordinates" to the best-located
material in the corpus.

Results are cached in data/partner_records.json.

Usage:
    python3 scripts/fetch_partner_records.py
    python3 scripts/fetch_partner_records.py --refresh
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SCALE_RE = re.compile(r"1\s*[:/]\s*([\d\s]{2,})")
# Degrees, minutes and seconds, with the site's doubled-prime notation.
_D = r"(\d{1,3})\s*°\s*(?:(\d{1,2})\s*['ʹ′])?\s*(?:(\d{1,2})\s*(?:''|″|\"))?"
# The separator between the two bounds is written '--' on some records and a
# single '-' on others; requiring '--' lost 98 of 120 boxes.
_SEP = r"\s*-{1,2}\s*"
BBOX_RE = re.compile(
    rf"([EW])\s*{_D}{_SEP}([EW])\s*{_D}\s*/\s*([NS])\s*{_D}{_SEP}([NS])\s*{_D}")
COORD_BLOCK_RE = re.compile(r"Coordonn[ée]es\s*:\s*(.{0,220})", re.IGNORECASE)


def fetch(url: str, retries: int = 3, timeout: int = 45) -> str | None:
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


def plain_text(page: str) -> str:
    page = re.sub(r"<script.*?</script>", " ", page, flags=re.S)
    page = re.sub(r"<style.*?</style>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def to_decimal(hemisphere: str, degrees: str, minutes: str, seconds: str) -> float:
    value = int(degrees) + int(minutes or 0) / 60 + int(seconds or 0) / 3600
    return -value if hemisphere in "WS" else value


def parse(page: str) -> dict:
    text = plain_text(page)
    block = COORD_BLOCK_RE.search(text)
    if not block:
        return {}
    segment = block.group(1)

    parsed: dict = {}
    scale = SCALE_RE.search(segment)
    if scale:
        digits = re.sub(r"\D", "", scale.group(1))
        if digits and int(digits) >= 10:
            parsed["scale_denominator"] = int(digits)

    box = BBOX_RE.search(segment)
    if box:
        g = box.groups()
        west = to_decimal(g[0], g[1], g[2], g[3])
        east = to_decimal(g[4], g[5], g[6], g[7])
        north = to_decimal(g[8], g[9], g[10], g[11])
        south = to_decimal(g[12], g[13], g[14], g[15])
        # The site prints the latitude pair north-then-south; sort defensively so
        # a reversed pair cannot produce a negative-height box.
        parsed["bbox"] = {
            "west": min(west, east), "east": max(west, east),
            "north": max(north, south), "south": min(north, south),
        }
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps.json")
    parser.add_argument("--cache", type=Path,
                        default=REPO_ROOT / "data" / "partner_records.json")
    parser.add_argument("--pause", type=float, default=0.4)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    records = json.loads(args.data.read_text(encoding="utf-8"))["records"]
    targets = {r["record_id"]: r["url"] for r in records
               if r["provenance"] != "Gallica" and r["url"].startswith("http")}

    cache: dict = {}
    if args.cache.exists() and not args.refresh:
        cache = json.loads(args.cache.read_text(encoding="utf-8"))

    pending = [k for k in targets if k not in cache]
    print(f"{len(targets)} partner records, {len(targets) - len(pending)} cached, "
          f"{len(pending)} to fetch")

    for index, record_id in enumerate(pending, 1):
        page = fetch(targets[record_id])
        cache[record_id] = parse(page) if page else {}
        if index % 25 == 0 or index == len(pending):
            scales = sum(1 for v in cache.values() if v.get("scale_denominator"))
            boxes = sum(1 for v in cache.values() if v.get("bbox"))
            print(f"  {index}/{len(pending)}: {scales} with scale, {boxes} with bbox")
            args.cache.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        time.sleep(args.pause)

    args.cache.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    scales = sum(1 for v in cache.values() if v.get("scale_denominator"))
    boxes = sum(1 for v in cache.values() if v.get("bbox"))
    print(f"\n{len(cache)} partner records: {scales} with a scale, "
          f"{boxes} with a bounding box -> {args.cache}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

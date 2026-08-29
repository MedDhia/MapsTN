#!/usr/bin/env python3
"""Fetch digitised image dimensions for BnF-held records from Gallica's IIIF API.

Scan resolution is the one quality signal the SRU catalogue record does not
carry, so it has to be requested per item from the IIIF Image API:

    https://gallica.bnf.fr/iiif/ark:/12148/<id>/f1/info.json  ->  {width, height}

Results are cached in data/scan_dimensions.json, so re-runs only fetch records
that are new or previously failed. Partner-library records are skipped: their
images live on the partner's own IIIF server, not Gallica's.

Usage:
    python3 scripts/fetch_scan_dimensions.py
    python3 scripts/fetch_scan_dimensions.py --refresh   # ignore the cache
"""

from __future__ import annotations

import argparse
import json
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


def fetch_info(record_id: str, timeout: int = 30) -> dict | None:
    """Return {'width', 'height'} for a record's first view, or None."""
    url = f"https://gallica.bnf.fr/iiif/ark:/12148/{record_id}/f1/info.json"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    width, height = payload.get("width"), payload.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return {"width": width, "height": height}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps.json")
    parser.add_argument("--cache", type=Path,
                        default=REPO_ROOT / "data" / "scan_dimensions.json")
    parser.add_argument("--pause", type=float, default=0.25)
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch every record, ignoring the cache")
    args = parser.parse_args()

    records = json.loads(args.data.read_text(encoding="utf-8"))["records"]
    targets = [r["record_id"] for r in records if r["iiif_manifest"]]

    cache: dict[str, dict | None] = {}
    if args.cache.exists() and not args.refresh:
        cache = json.loads(args.cache.read_text(encoding="utf-8"))

    # Retry entries that previously failed; keep successful ones.
    pending = [i for i in targets if not cache.get(i)]
    print(f"{len(targets)} BnF records, {len(targets) - len(pending)} cached, "
          f"{len(pending)} to fetch")

    for index, record_id in enumerate(pending, 1):
        cache[record_id] = fetch_info(record_id)
        if index % 50 == 0 or index == len(pending):
            got = sum(1 for v in cache.values() if v)
            print(f"  {index}/{len(pending)} fetched, {got} with dimensions")
            args.cache.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        time.sleep(args.pause)

    args.cache.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    resolved = sum(1 for v in cache.values() if v)
    print(f"\n{resolved}/{len(targets)} records have scan dimensions -> {args.cache}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

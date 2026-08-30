#!/usr/bin/env python3
"""Find the full-resolution scan behind each partner sheet, and cache the page text.

Two things this repository needs before any pixel work is possible.

1. A downloadable image URL. The Bordeaux Montaigne item pages carry the scan at
   /files/original/<sha1>.jpg - a plain JPEG, no IIIF, no tiling. Nothing in the
   catalogue metadata points at it; it has to be scraped off the page.

2. The page text itself, cached. Every metadata question so far ("does this
   record state a projection?", "what fieldwork date does it give?") has been
   answered by refetching 96 pages and grepping. Caching the rendered text makes
   those questions local and makes the answers auditable: a claim about what a
   record says can be checked against the stored text rather than against a
   network round trip that may return something different next week.

The image is not downloaded here - the series is several gigabytes and the disk
allowance is finite. This records where each scan is and how big it is, so that
a later step can fetch the ones it needs.

Outputs:
    data/sheet_images.json      record_id -> {image_url, bytes, ...}
    data/partner_pages.json     record_id -> rendered page text

Usage:
    python3 scripts/fetch_sheet_images.py
    python3 scripts/fetch_sheet_images.py --refresh
"""

from __future__ import annotations

import argparse
import csv
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

ORIGINAL_RE = re.compile(r"https?://[^\"'\s<>]*/files/original/[0-9a-f]{8,}\.jpe?g",
                         re.IGNORECASE)
# The page advertises the download size in words: "(jpg, 8.57 Mo)".
SIZE_RE = re.compile(r"r[ée]solution maximale\s*\(\s*jpe?g\s*,\s*([\d.,]+)\s*(Mo|Ko|Go)\)",
                     re.IGNORECASE)
MULTIPLIER = {"ko": 1e3, "mo": 1e6, "go": 1e9}


def fetch(url: str, retries: int = 3, timeout: int = 60) -> str | None:
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
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).strip()


def parse(page: str) -> dict:
    text = plain_text(page)
    found: dict = {"page_text": text}

    image = ORIGINAL_RE.search(page)
    if image:
        found["image_url"] = image.group(0)

    size = SIZE_RE.search(text)
    if size:
        value = float(size.group(1).replace(",", "."))
        found["stated_bytes"] = int(value * MULTIPLIER[size.group(2).lower()])
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", type=Path,
                        default=REPO_ROOT / "data" / "tunisia_50k_series.csv")
    parser.add_argument("--images", type=Path,
                        default=REPO_ROOT / "data" / "sheet_images.json")
    parser.add_argument("--pages", type=Path,
                        default=REPO_ROOT / "data" / "partner_pages.json")
    parser.add_argument("--pause", type=float, default=0.4)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    sheets = [r for r in csv.DictReader(args.series.open(encoding="utf-8"))
              if r["url"].startswith("http") and r["provenance"] == "partner"]

    images: dict = {}
    pages: dict = {}
    if not args.refresh:
        for path, store in ((args.images, images), (args.pages, pages)):
            if path.exists():
                store.update(json.loads(path.read_text(encoding="utf-8")))

    pending = [s for s in sheets if s["record_id"] not in images]
    print(f"{len(sheets)} partner sheets, {len(sheets) - len(pending)} cached, "
          f"{len(pending)} to fetch")

    for index, sheet in enumerate(pending, 1):
        page = fetch(sheet["url"])
        found = parse(page) if page else {}
        pages[sheet["record_id"]] = found.pop("page_text", "")
        images[sheet["record_id"]] = {
            "designation": sheet["designation"],
            "sheet_name": sheet["sheet_name"],
            "item_url": sheet["url"],
            **found,
        }
        if index % 20 == 0 or index == len(pending):
            print(f"  {index}/{len(pending)}")
            args.images.write_text(json.dumps(images, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
            args.pages.write_text(json.dumps(pages, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        time.sleep(args.pause)

    args.images.write_text(json.dumps(images, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    args.pages.write_text(json.dumps(pages, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    with_url = [v for v in images.values() if v.get("image_url")]
    total = sum(v.get("stated_bytes", 0) for v in with_url)
    print(f"\n{len(images)} sheets: {len(with_url)} with a downloadable scan")
    print(f"  total download size: {total / 1e9:.2f} GB")
    print(f"  -> {args.images}\n  -> {args.pages}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

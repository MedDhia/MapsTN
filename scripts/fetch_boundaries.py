#!/usr/bin/env python3
"""Download contemporary Tunisian administrative boundaries as shapefiles.

Source is the OCHA **Common Operational Dataset** for Tunisia, published on the
Humanitarian Data Exchange under CC BY-IGO. Its levels do not run the way the
usual ADM0/1/2 convention suggests, and assuming they do puts every label one
step out - the counts are what settle it:

    admin0  the state                     1
    admin1  grandes regions               6    (North East, Centre West, ...)
    admin2  gouvernorats                 24
    admin3  delegations                 264
    admin4  secteurs / imadas          finer

Levels 0 to 3 are kept by default, because gouvernorat and delegation are the
units Tunisian statistics are published at, and so the levels at which anything
extracted from the 1930s sheets can be set beside a modern number. Level 4 is
available with --levels but is not kept: 15 MB of geometry is a poor trade for a
join nobody has asked for yet.

Two sources were tried first and both failed, which is worth recording so nobody
repeats the attempt:

  geoBoundaries (gbOpen) is the obvious choice and is ODbL, but it serves every
  file from GitHub through Git LFS. The pointer files download fine and the
  objects do not: resolving them needs the LFS batch API on github.com, which
  this environment's git proxy refuses for repositories outside the session's
  own. The 132-byte "shapefile" that arrives is an LFS pointer, and a script
  that does not check would write it out as if it were data.

  GADM is reachable, but its licence discourages redistribution. A boundary file
  that cannot be committed next to the data it joins to is little use here.

A note on what the join can and cannot mean. These are contemporary boundaries.
The sheets record fieldwork from the 1880s to the 1930s, when the units were
French civil and military circumscriptions that do not correspond to today's
gouvernorats. Aggregating historical objects into modern units is a way of
indexing them and comparing against modern data, not a claim that the unit
existed at the time. The historical boundaries the sheets themselves draw -
"limite de commune de plein exercice" and the rest - are a separate extraction,
still to be done.

Outputs:
    data/boundaries/tun_admin{0,1,2,3}.{shp,shx,dbf,prj,cpg}
    data/boundaries/SOURCE.md   provenance, licence and attribution

Usage:
    python3 scripts/fetch_boundaries.py
    python3 scripts/fetch_boundaries.py --levels 0 1 2 3
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = "cod-ab-tun"
PACKAGE_API = "https://data.humdata.org/api/3/action/package_show?id={dataset}"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
KEEP_SUFFIXES = (".shp", ".shx", ".dbf", ".prj", ".cpg")
UNITS = {0: "state", 1: "grandes régions", 2: "gouvernorats",
         3: "délégations", 4: "secteurs / imadas"}

# A Git LFS pointer is a few hundred bytes of text beginning with this line. It
# is the shape of a silent failure: it downloads with HTTP 200 and, unchecked,
# gets written out where a shapefile should be.
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"


def fetch(url: str, retries: int = 3, timeout: int = 300) -> bytes | None:
    delay = 2.0
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == retries:
                return None
            time.sleep(delay)
            delay *= 2
            continue
        if payload.startswith(LFS_POINTER):
            return None
        return payload
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", nargs="*", type=int, default=[0, 1, 2, 3])
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "data" / "boundaries")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    metadata_bytes = fetch(PACKAGE_API.format(dataset=DATASET))
    if not metadata_bytes:
        print("HDX package metadata unavailable")
        return 1
    package = json.loads(metadata_bytes)["result"]

    resource = next((r for r in package["resources"] if r["format"] == "SHP"),
                    None)
    if resource is None:
        print("no SHP resource in the HDX package")
        return 1

    print(f"{package['title']}\n  licence: {package.get('license_title')}\n"
          f"  updated: {package.get('metadata_modified')}\n"
          f"  fetching {resource['name']}")
    payload = fetch(resource["url"])
    if not payload:
        print("  download failed")
        return 1
    print(f"  {len(payload) / 1e6:.1f} MB")

    # Only the plain levels, not the "_em" edge-matched duplicates, and not the
    # adminlines/adminpoints layers - none of which this join needs.
    wanted = {f"tun_admin{level}" for level in args.levels}
    written: dict[int, list[str]] = {level: [] for level in args.levels}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            path = Path(name)
            if path.suffix.lower() not in KEEP_SUFFIXES:
                continue
            if path.stem not in wanted:
                continue
            (args.out / path.name).write_bytes(archive.read(name))
            level = int(path.stem.removeprefix("tun_admin"))
            written[level].append(path.name)

    for level in args.levels:
        print(f"  admin{level} ({UNITS.get(level, '?')}): "
              f"{len(written[level])} files")

    lines = [
        "# Contemporary boundary source",
        "",
        "Downloaded by `scripts/fetch_boundaries.py`. Not edited by hand.",
        "",
        f"**{package['title']}** — OCHA Common Operational Dataset, via the",
        "Humanitarian Data Exchange.",
        "",
        f"- Licence: **{package.get('license_title')}** — attribution required.",
        f"- HDX dataset: `{DATASET}`",
        f"- Resource: `{resource['name']}`",
        f"- Metadata last modified: {package.get('metadata_modified')}",
        "",
        "| Level | Tunisian unit | Files kept |",
        "| --- | --- | --- |",
    ]
    for level in args.levels:
        lines.append(f"| admin{level} | {UNITS.get(level, '—')} | "
                     f"{len(written[level])} |")
    lines += [
        "",
        "Level 4 exists in the source and is not kept: 15 MB of geometry.",
        "`--levels 0 1 2 3 4` fetches it if needed.",
        "",
        "The level numbering is the source's own and does not follow the usual",
        "ADM0/1/2 convention — admin1 is the six *grandes régions*, not the",
        "gouvernorats. The shape counts above are what confirm it.",
        "",
        "## Sources tried and rejected",
        "",
        "**geoBoundaries (gbOpen)** — ODbL, and the obvious choice, but every",
        "file is served from GitHub through Git LFS. The pointers download and",
        "the objects do not: resolving them needs the LFS batch API on",
        "github.com, which this environment's git proxy refuses for repositories",
        "outside the session's own. What arrives is a 132-byte pointer that an",
        "unchecked script would write out as a shapefile, so `fetch()` rejects",
        "anything beginning with the LFS pointer header.",
        "",
        "**GADM** — reachable, but its licence discourages redistribution.",
        "",
        "## What a join to these units means",
        "",
        "These are contemporary boundaries. The sheets record fieldwork from the",
        "1880s to the 1930s, when the units were French civil and military",
        "circumscriptions that do not map onto today's gouvernorats. Aggregating",
        "historical objects into modern units is a way of indexing them and",
        "comparing with modern statistics — not a claim that the unit existed at",
        "the time. The historical boundaries the sheets themselves draw are a",
        "separate extraction, still to be done.",
    ]
    (args.out / "SOURCE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n-> {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

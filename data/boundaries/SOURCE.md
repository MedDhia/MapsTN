# Contemporary boundary source

Downloaded by `scripts/fetch_boundaries.py`. Not edited by hand.

**Tunisia - Subnational Administrative Boundaries** — OCHA Common Operational Dataset, via the
Humanitarian Data Exchange.

- Licence: **Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO)** — attribution required.
- HDX dataset: `cod-ab-tun`
- Resource: `tun_admin_boundaries.shp.zip`
- Metadata last modified: 2026-08-14T06:40:28.498347

| Level | Tunisian unit | Files kept |
| --- | --- | --- |
| admin0 | state | 5 |
| admin1 | grandes régions | 5 |
| admin2 | gouvernorats | 5 |
| admin3 | délégations | 5 |

Level 4 exists in the source and is not kept: 15 MB of geometry.
`--levels 0 1 2 3 4` fetches it if needed.

The level numbering is the source's own and does not follow the usual
ADM0/1/2 convention — admin1 is the six *grandes régions*, not the
gouvernorats. The shape counts above are what confirm it.

## Sources tried and rejected

**geoBoundaries (gbOpen)** — ODbL, and the obvious choice, but every
file is served from GitHub through Git LFS. The pointers download and
the objects do not: resolving them needs the LFS batch API on
github.com, which this environment's git proxy refuses for repositories
outside the session's own. What arrives is a 132-byte pointer that an
unchecked script would write out as a shapefile, so `fetch()` rejects
anything beginning with the LFS pointer header.

**GADM** — reachable, but its licence discourages redistribution.

## What a join to these units means

These are contemporary boundaries. The sheets record fieldwork from the
1880s to the 1930s, when the units were French civil and military
circumscriptions that do not map onto today's gouvernorats. Aggregating
historical objects into modern units is a way of indexing them and
comparing with modern statistics — not a claim that the unit existed at
the time. The historical boundaries the sheets themselves draw are a
separate extraction, still to be done.

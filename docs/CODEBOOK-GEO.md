# Codebook — georeferencing and thematic coding

Variables in
[`data/gallica_tunisia_maps_geospatial.csv`](../data/gallica_tunisia_maps_geospatial.csv),
one row per record, keyed by `record_id`. Produced by
`scripts/code_geospatial.py`. Results are summarised in
[GEOREFERENCING.md](GEOREFERENCING.md).

This coding answers four questions. Each has its own variable block, and they
are deliberately independent — a sheet can be perfectly placeable and carry
nothing worth extracting, or be thematically rich and impossible to place.

---

## Q1 — Coordinates

### Where the coordinates come from

Gallica's SRU exposes Dublin Core only, which has **no coordinate element at
all**. Cartographic coordinates live in the BnF catalogue général's UNIMARC
records, field **123 `$d $e $f $g`** (westernmost, easternmost, northernmost,
southernmost), encoded as `[NSEW]DDDMMSS` — `E0133000` is 13°30′00″ E.
`scripts/fetch_catalogue_records.py` retrieves these over the catalogue's own
SRU endpoint for the records that carry a notice link.

| Variable | Description |
| --- | --- |
| `bbox_west`, `bbox_east`, `bbox_north`, `bbox_south` | Decimal degrees; west and south are negative |
| `bbox_source` | `unimarc_123` (coded subfields), `math_data_text` (parsed from the field 206 statement), or `none` |
| `tunisia_extent_share` | Share of the sheet's extent occupied by Tunisia's bounding box |

`tunisia_extent_share` is the useful one. Near 1.0 the sheet *is* a map of
Tunisia; near 0.0 Tunisia is a sliver at the edge of a Mediterranean, African or
world sheet. An 18th-century English chart in this corpus labels Tunisia simply
"PART OF BARBARY" in its bottom-left corner — geometrically fine, substantively
useless for Tunisia.

Tunisia's reference box is taken as 7.49°–11.60° E, 30.23°–37.55° N.

### Limits

Coordinates are the exception, not the rule. Most records have none, and their
absence carries no information about the map — it reflects cataloguing practice.
For everything else, coordinates have to be established by georeferencing against
control points, which is what Q2 codes.

---

## Q1 — Orientation

**`orientation` is a presumption, not a measurement.** Orientation is essentially
never catalogued: only 2 records in the corpus mention it in their text.

| Value | Assigned when |
| --- | --- |
| `stated_in_record` | The catalogue text mentions orientation, a compass rose or a wind rose |
| `presumed_north` | Dated 1700 or later and not a perspective view — European printed cartography is north-up by convention |
| `uncertain` | Dated before 1700, undated, or coded as a view |

`orientation_basis` records which rule fired.

Pre-1700 material is coded `uncertain` because portolan charts have no
consistent north, and 16th-century siege pieces and city views are oriented to
the viewer. `genre == view` is coded `uncertain` for the same reason at any date.

This presumption was checked by eye against four sheets (documented in
[GEOREFERENCING.md](GEOREFERENCING.md)). It held for post-1700 printed maps and
failed exactly where the coding already says `uncertain`. **Verify against the
image before relying on it for any individual sheet.**

---

## Q2 — Georeferenceability

### `geometric_class`

How the map was constructed, which governs how well it can be fitted.

| Value | Meaning |
| --- | --- |
| `survey` | Instrument survey by a state body from 1830 on — carries a projection and graticule |
| `chart` | Sea chart on a plane graticule with rhumb lines |
| `early_modern` | Printed map, 1700 onward, compiled rather than surveyed |
| `sketch` | Pre-1700 material, portolans, undated compilations |
| `atlas_volume` | A bound volume, not a single sheet |
| `sketch_view` | Perspective view rather than a plan |

### `georef_tier`

| Value | Meaning | Method |
| --- | --- | --- |
| `1_direct` | Projection and graticule present, stated scale, good scan | Affine or low-order polynomial transform |
| `2_control_points` | Internally consistent geometry, no usable graticule | Identify control points (ports, river mouths, known sites) and fit |
| `3_warp_only` | Geometry loose or distorted; also anything partner-hosted, where no IIIF image is available | Thin-plate spline warp; expect large residuals |
| `4_not_georeferenceable` | Atlas volume or perspective view | Georeference individual plates instead, or not at all |

Two demotions are applied after the initial class:

- A `survey` sheet drops to `2_control_points` if its scan is low or unknown
  resolution, or if no scale is catalogued — a tier-1 claim needs an image you
  can actually place control points on.
- Anything partner-hosted drops to `3_warp_only`, because the image is not
  served through IIIF and cannot be pulled into a georeferencing tool.

`georef_blockers` lists what stood in the way, so a demotion can be audited.

---

## Q3 — Transferable content

### `thematic_layers`

Feature classes that could be digitised as GIS layers, detected from title,
subject headings, description, coverage and document type. A record can carry
several.

`settlements`, `coastline_bathymetry`, `relief`, `hydrology`, `roads`,
`railways`, `admin_boundaries`, `fortifications`, `archaeology`,
`geology_mines`, `land_use`, `urban_fabric`, `population`, `economy`.

Two deliberate exclusions in `admin_boundaries`: the words *province* and
*département*. "Tunis, Province de -- Côtes" is a standing subject heading on 58
coastal charts that carry no administrative content whatsoever; including those
terms inflated the layer roughly threefold.

**This is a detection of what the catalogue says, not of what is drawn on the
sheet.** It under-counts: a topographic sheet shows roads and settlements whether
or not its record says so. It is a floor, not a census.

### `n_thematic_layers`, `content_mappable`

| Value | Meaning |
| --- | --- |
| `yes` | At least one layer and georeferencing tier 1 or 2 |
| `partial` | At least one layer but tier 3 — content is there, placement is rough |
| `no` | No detected layer, or tier 4 |

---

## Q4 — Spatial inequality

### `inequality_layers`

The subset of thematic layers bearing on how people, infrastructure, land or
activity are **distributed** across space:

`roads`, `railways`, `admin_boundaries`, `land_use`, `urban_fabric`,
`population`, `economy`, `geology_mines`.

`settlements` is recorded but never decisive. Almost every map names towns;
knowing where towns are is context, not evidence about inequality. Coastline
soundings, relief and fortifications are excluded entirely.

### `inequality_use`

| Value | Rule |
| --- | --- |
| `direct` | Carries at least one distributional layer **and** `confidence == high` (Tunisia is the subject, not incidental) **and** georeferencing tier 1 or 2 |
| `indirect` | Has a relevant layer but fails one of the other two conditions — usable as context or corroboration |
| `none` | No inequality-bearing layer |

All three conditions are needed. A distribution you cannot place on the ground
cannot be compared with anything; a distribution on a map where Tunisia is a
corner detail is not about Tunisia.

### `coverage_group`

Scale band, as a rough key for finding repeat coverage of comparable ground at
different dates — the minimum requirement for studying *evolution* rather than a
single cross-section. It is a coarse instrument: it groups by scale only, not by
extent, so candidate pairs still need checking by eye.

---

## Reproducing

```bash
python3 scripts/harvest_gallica_maps.py       # catalogue records
python3 scripts/fetch_scan_dimensions.py      # IIIF pixel dimensions
python3 scripts/fetch_catalogue_records.py    # UNIMARC, including coordinates
python3 scripts/code_quality.py               # quality coding (prerequisite)
python3 scripts/code_geospatial.py            # this coding
```

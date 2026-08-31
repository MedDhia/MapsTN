# Extracting objects with coordinates you can trust

Two steps, in this order, because the second is worthless without the first:
give every sheet an exact pixel-to-ground transform, then find the legend's
symbols in the pixels and push them through it.

| Step | Script | Output |
| --- | --- | --- |
| Georeference | [`scripts/georeference_sheets.py`](../scripts/georeference_sheets.py) | `data/sheet_georef.{json,csv}`, `data/georef/*.{wld,points}` |
| Extract symbols | [`scripts/extract_symbols.py`](../scripts/extract_symbols.py) | `data/symbols/<record_id>.geojson`, `data/symbols_summary.csv` |

---

## 1. The transform

### Why neither obvious anchor works alone

The **catalogue bounding box** gives absolute position but its corners are
rounded — to whole arcminutes on 29 of 93 sheets — so it is good to about
±800 m. The **printed kilometric grid** gives scale and rotation to a tenth of a
percent and sits at exact integer kilometres in Lambert, but the detector finds
*where* the lines are, not *which* kilometre each one is.

So the linear part of the transform comes from the grid and the absolute
kilometre comes from the **grid labels printed in the margin**, read by OCR with
their positions and matched back to the detected lines. The catalogue box is
demoted to two jobs: a window that tells the label reader which three-digit
numbers could possibly be Lambert values, and an independent check afterwards.

### What the numbers say

Measured on four sheets read closely (Kairouan, Kasserine, Toujane, Médenine):

| | |
| --- | --- |
| Grid fit residual, RMS | **8–25 m** (median 16 m) |
| Ground metres per pixel | 4.26 m |
| Control points per sheet | ~600 grid intersections |

The residual is the number that matters for relative geometry. A printed grid is
rigid, so a single affine fitting 600 intersections to 16 m RMS means the scale,
rotation and skew are right and the paper is flat. **Distances and shapes within
a sheet are good to about 20 m.**

Absolute position is a separate question and is reported per sheet as
`anchor_vs_catalogue_e_m` / `_n_m` — how far the label-derived anchor sits from
where the catalogue would have put it. On Kasserine that is 231 m and 332 m,
comfortably inside the catalogue's own rounding. Sheets where the labels do not
agree well enough among themselves, or where the result is more than a kilometre
from the catalogue, are marked `anchor_confident = 0` and should not be used for
absolute work until checked by hand.

### Four wrong turns, each recorded in the code

These cost most of the work and each one produced a plausible-looking wrong
answer, which is why they are written down rather than quietly fixed.

1. **The snap statistic measured the wrong thing.** Estimating the absolute
   offset at every grid intersection and rounding to the nearest kilometre
   reported a ~500 m snap distance on every sheet regardless of quality — it was
   measuring the catalogue's *scale* error accumulating over 30 km, not its
   offset. The offset has to be estimated once, at one point.
2. **The neatline is three lines, not one.** Each side of the frame is an inner
   neatline against the map, then the graticule's graduated band, then a heavy
   outer rule. Searching inward from the paper edge finds the outer rule, 130 px
   beyond the neatline, and every sheet measured about 5% too tall; searching
   outward from the map centre overshoots the other way by 2%. Either error is
   ±400 m in the anchor, which is why the anchor was moved off the frame
   entirely and onto the labels.
3. **The detected grid lines are not always consecutive.** A spurious or missed
   line shifts every index after it. On the Kairouan sheet that made one affine
   fit the intersections to 239 m RMS, an order of magnitude worse than the
   grid deserves. Deriving each line's kilometre from its measured position
   instead of its position in a list fixed it — 239 m to 25 m.
4. **A label's value is useless without its position.** The top and bottom
   margins disagree about where a given kilometre is by over a kilometre,
   because the grid is tilted about four degrees and the sheet is 5000 px tall.
   Each label has to be reduced to the line constant it lies on before it can
   vote.

### Sidecars

Each georeferenced sheet gets a `.wld` world file in its own Lambert zone
(EPSG:22391 Nord Tunisie or 22392 Sud Tunisie, Clarke 1880 IGN — the ellipsoid
the sheets' own records name) and a `.points` file in QGIS georeferencer format.
Both are directly loadable; nothing needs to be re-derived to open a sheet in
GIS.

---

## 2. The symbols

### What is extracted

| Class | Legend row | Symbol | Status |
| --- | --- | --- | --- |
| `building` | *Maisons* | individual solid red marks | extracted by default |
| `well` | *Puits et fontaine* | thin blue open ring | **provisional**, opt-in |
| `vegetation` | *Bois / Oliviers / Palmiers* | teal stipple ring | **provisional**, opt-in |

Both editions of the legend define these identically, so no per-edition
crosswalk is needed — see
[`config/legend_vocabulary.json`](../config/legend_vocabulary.json).

On the Kasserine sheet: **1164 buildings and 514 wells**, every one carrying a
pixel position, a Lambert easting and northing, and a WGS84 longitude and
latitude. Their extent runs lon 8.663–9.022, lat 35.109–35.290 against a
catalogued sheet extent of 8.660–9.020 by 35.100–35.289 — agreement to about
180 m, which is the anchor's stated offset and not a separate error.

Across ten sheets whose transforms all fit to 12–14 m, building counts run
454–1611, which is the kind of spread settlement density should show. Well
counts run **4 to 2158**. Part of that is real — Djebel Semmama is a dry massif
and Oued-Zarga is the Medjerda valley — but a factor of 500 is not, and the
overlays show the well detector firing on blue hatching in marshy ground. So
wells are shipped where already extracted, and labelled provisional, but they
are no longer extracted by default and should not be counted or compared across
sheets until the detector is validated sheet by sheet.

### A ring is not a blob

Connected-component labelling finds about a tenth of the rings. The stroke is
one or two pixels wide and breaks wherever it crosses another feature, so each
ring falls apart into arcs that no size filter recognises. Matching an annulus
template scores the whole shape at once, and demanding an *empty middle* as well
as an inked rim is what separates a ring from a filled dot.

### Three false-positive sources, and what each needed

- **The grid is printed in the same red as the houses.** At a crossing the two
  lines make a compact blob no size or aspect filter can distinguish, and the
  first run returned grid crossings as buildings. Fixed geometrically: the grid's
  line equations are already known exactly from the georeferencing, so the grid
  is cut out of the red channel before blob-finding.
- **Red numerals — spot heights and grid labels — are the same colour and size
  as a house.** They are strokes rather than fills, so a minimum fill ratio of
  0.55 removes them.
- **A watercourse is a chain of blue rings.** The first well detector traced the
  oued down the middle of the sheet and called every bend a well. Requiring the
  neighbourhood beyond the ring to be mostly empty keeps the isolated symbol and
  drops the chain.

Detections are also clipped a little inside the neatline. Without that, the
legend's own specimen symbols and the red margin labels are extracted as map
content — the Kasserine sheet returned features up to 1.3 km outside its own
frame.

### What is deliberately not shipped by default

**Vegetation stipple** (*Bois / Broussailles / Oliviers / Palmiers*) is
implemented but off by default. The stipple is dense and saturated on the Sahel
sheets and faint on the steppe ones: a threshold finding 268 rings in one
Kasserine window finds 3 when tightened enough to stop it tracing the black
lettering. Counts that swing by two orders of magnitude on a threshold nudge are
not data. It needs per-sheet calibration first, and until then
`--classes building,well,vegetation` is opt-in.

Still unbuilt, in the order worth doing: **trig points** (a triangle with a
printed height, and they double as survey control), **shrines and cemeteries**
(the confessional cemetery glyphs are the highest-value class in the legend),
**parcel boundaries** (dashed polygons named by holding lineage), and **toponym
OCR**, which remains the long pole.

---

## 3. How to check it rather than believe it

Every claim above is a number in
[`data/sheet_georef.csv`](../data/sheet_georef.csv) or reproducible:

```bash
# transform, with residuals and the anchor cross-check
python3 scripts/georeference_sheets.py --images <dir of record_id.jpg>

# re-apply the confidence rule to cached results, no scans re-read
python3 scripts/georeference_sheets.py --images <dir> --csv-only

# symbols, with the detections drawn on the image for inspection by eye
python3 scripts/extract_symbols.py --images <dir> --overlay data/overlays \
    --window 4200 3400 5400 4600
```

The `--overlay` output is the honest test and the one that caught every mistake
listed above: a count tells you nothing about whether the detector found houses
or grid crossings, and looking at 1200 px of sheet with the detections circled
tells you immediately.

---

## 4. On contemporary Tunisia

`scripts/fetch_boundaries.py` downloads the boundaries and `scripts/map_objects.py`
does the join and draws the map.

![Extracted objects on contemporary Tunisian boundaries](img/objects_on_modern_tunisia.png)

### The boundaries

**OCHA Common Operational Dataset for Tunisia**, via the Humanitarian Data
Exchange, CC BY-IGO — see [`data/boundaries/SOURCE.md`](../data/boundaries/SOURCE.md).
Its level numbering is its own and does not follow the ADM0/1/2 convention;
assuming it does puts every label one step out, and the shape counts are what
settle it:

| Level | Unit | Count |
| --- | --- | --- |
| admin0 | state | 1 |
| admin1 | grandes régions | 6 |
| admin2 | **gouvernorats** | 24 |
| admin3 | **délégations** | 264 |

Two other sources were tried. **geoBoundaries** is the obvious choice and is
ODbL, but serves every file from GitHub through Git LFS: the pointers download
and the objects do not, because resolving them needs the LFS batch API on
github.com, which this environment's git proxy refuses for repositories outside
the session's own. What arrives is a 132-byte pointer that an unchecked script
would write out as a shapefile, so the fetcher rejects anything starting with the
LFS header. **GADM** is reachable but its licence discourages redistribution.

### The join

8368 of the 8373 extracted houses fall inside a gouvernorat — the five strays are
on the coastline, where the sheet edge sits just outside the modern polygon.

| Gouvernorat | Houses | km² read | Houses / km² |
| --- | --- | --- | --- |
| Béja | 1725 | 1076 | **1.60** |
| Manubah | 176 | 119 | 1.48 |
| Kassérine | 1764 | 1240 | 1.42 |
| Le Kef | 525 | 423 | 1.24 |
| Sousse | 1032 | 962 | 1.07 |
| Siliana | 686 | 705 | 0.97 |
| Mahdia | 336 | 468 | 0.72 |
| Zaghouan | 1120 | 1796 | 0.62 |
| Kairouan | 514 | 920 | 0.56 |
| Sfax | 32 | 74 | 0.43 |
| Ben Arous | 458 | 126 | **3.63** |

Ben Arous is the outlier and for a reason worth stating: only 126 km² of it has
been read, all of it the peri-urban fringe south of Tunis, so its density is a
statement about that fringe and not about the gouvernorat. Small denominators
are where a density measure misleads, and the `extracted_km2` column is in the
table so that can be seen rather than guessed.

At délégation level, 44 of 264 units have extracted houses. The densest are
Bir Mchergua (2.86/km²), Testour (2.10) and Kasserine Sud (2.06).

### Two things the map deliberately refuses to do

**It does not present extraction coverage as geography.** Ten sheets are
extracted, so a raw count per gouvernorat would mostly report which sheets happen
to be done. The denominator is therefore the *extracted* area inside each unit —
the convex hull of that unit's own symbols, clipped to the unit — so the number
means houses per km² of ground actually read.

**It does not draw no data as zero.** Units with no extracted sheet are hatched.
The lightest step of a sequential ramp means "near zero", and near zero is a
claim; thirteen gouvernorats have no sheet extracted and must not read as
"no houses here".

### What the map is also evidence for

The 73 sheet footprints tile the northern half of the country as a regular
lattice, abutting without overlaps or gaps, and every extracted house falls
inside its own sheet. Nothing in the pipeline enforces that: the footprints come
from each sheet's own printed grid and margin labels, fitted independently. Had
the anchor been wrong on any sheet, that sheet would sit a kilometre off the
lattice. It is the cheapest check available on the georeferencing, and it passes
by eye.

### The joined outputs

| Path | |
| --- | --- |
| [`data/symbols_by_unit.csv`](../data/symbols_by_unit.csv) | 288 rows: every gouvernorat and délégation, with counts, area read and density |
| [`data/symbols_joined.geojson`](../data/symbols_joined.geojson) | every symbol with its modern gouvernorat and délégation attached |
| [`data/boundaries/`](../data/boundaries/) | the shapefiles themselves, levels 0–3 |

### A caution on the units

These are contemporary boundaries. The sheets record fieldwork from the 1880s to
the 1930s, when the units were French civil and military circumscriptions that do
not map onto today's gouvernorats. Aggregating to modern units is a way of
indexing the objects and comparing them against modern statistics — not a claim
that the unit existed. The historical boundaries the sheets themselves draw,
*limite de commune de plein exercice* among them, are a separate extraction and
still to be done.

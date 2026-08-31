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

### The sheet states its own coordinates, and that changes everything

The **printed kilometric grid** gives scale and rotation to a tenth of a percent
and sits at exact integer kilometres in Lambert, but the detector finds *where*
the lines are, not *which* kilometre each one is. So the linear part of the
transform comes from the grid, and the absolute placement — which kilometre line
zero is — has to come from somewhere else.

It comes from the sheet. **Every sheet prints the exact Lambert easting and
northing of each of its four neatline corners, to the metre, in red in the
margin**, with a leader line pointing at the corner. Kasserine says:

| | easting | northing |
| --- | --- | --- |
| NW | 388.498 m | 222.548 m |
| NE | 420.395 m | 220.122 m |
| SW | 386.972 m | 202.612 m |
| SE | 418.870 m | 200.185 m |

Eight numbers, and they close as a parallelogram to **1 m** — width 31 897 against
31 898, height 19 936 against 19 937. This is primary, exact, and owes nothing to
any catalogue. It settles 57 of the 73 georeferenced sheets on both axes.

Where the annotation can be read at only one corner, a second source finishes the
job, and it was not designed: **adjacent sheets print identical corner
coordinates.** Djebel Mrhila gives its south-west corner as 420.395 m /
220.122 m, which is exactly Kasserine's north-east. Across the series **237
corner pairs from different sheets coincide, median 67 m apart, worst 184 m, on
69 of the 73 sheets** — and since an anchor error is a whole kilometre by
construction, agreement at 67 m rules one out. That rescues 9 more sheets and, as
a by-product, validates the whole set of transforms against each other.

The **margin kilometre labels** — a vote among the red three-digit numbers along
the edges — remain as the third source, and the **catalogue bounding box** is now
only a coarse sanity check. One sheet of the 73 rests on the labels alone.

### The catalogue was the wrong arbiter, and the evidence that says so

For most of this work a sheet was trusted when its label-voted anchor agreed with
the catalogue box to better than a kilometre. That test rejected 34 of 73 sheets.
It was measuring the wrong thing, and three independent facts say so.

**An anchor error must be a whole kilometre.** The anchor is an integer; it enters
the transform as `origin_km × 1000`. So if `anchor_vs_catalogue` were measuring
anchor error, its values would cluster near whole kilometres. They do not: across
the sheets it rejected, the residual to the nearest whole kilometre averages
**253 m against 250 m expected from pure chance** (Rayleigh test on the phase,
p = 0.45). Almost all of what the test reported was frame-detection error and
catalogue error.

**The sheets it rejected were right.** Read against their own printed corners:

| sheet | catalogue said the anchor was out by | the sheet's own printing says |
| --- | --- | --- |
| La Marsa | 1 542 m | **17 m** |
| Djemmal | 14 359 m | **12 m** |
| Djebel Ichkeul | 1 682 m | **49 m** |
| Kasserine | 231 m | **64 m** |

**The test was never independent.** The window of three-digit values the label
reader will accept is derived from the catalogue box. A sheet with a bad box has
its anchor pushed into the wrong window, and then the "independent check" agrees
with the error it caused. That is what put Djebel Mrhila 36 km east of where it
prints its own corner — and the catalogue box agreed, because the box was the
source of the error.

Correcting the arbiter took the sheets with an anchor resting on nothing from
**34 to 1**.

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

Absolute position is a separate question, and `anchor_basis_e` / `_n` records
which of the three sources established each axis of each sheet:

| basis | sheets (of 73) |
| --- | --- |
| printed corners on both axes | 57 |
| printed corners on one axis, another source on the other | 10 |
| a corner shared with a confirmed neighbour, both axes | 2 |
| margin labels on both axes | 3 |
| nothing that settles it | **1** |

A useful by-product: because the printed corner is exact, the difference between
it and the *detected* frame measures the frame detector. It comes out at a median
**15 m** in easting and **32 m** in northing, worst 258 m and 466 m — far better
than the ±550 m worst case the three-rules problem suggested, and it is reported
per sheet as `neatline_error_m_e` / `_n` rather than folded into the anchor.

### Five wrong turns, each recorded in the code

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
5. **Corroboration between four corners of one sheet is not independent.** The
   four corner annotations are the same typeface in the same scan, so a digit
   misread at one corner is liable to be misread the same way at another — and
   then two wrong readings confirm each other and look exactly like two right
   ones. Grombalia reads 628 at its north-west corner and 660 at its north-east,
   both a 5 read as a 6, against a correct 526.895 at the south-west and a
   correct 560 at the north-east. Two against two, and the wrong pair would have
   moved a correctly anchored sheet 100 km. Ties now go to the margin labels,
   which are separate printing read separately; a reading that would *move* a
   sheet needs three corners where one that confirms it needs two; and the result
   still has to land on Tunisia.

Three preprocessing attempts on the corner annotation are also worth recording,
because the glyphs are only about 22 px tall and the choice mattered more than
any parameter. A **binary red mask** eroded them until `222.548` read as `2.6.`.
A **stretched red-dominance measure** saturated and merged them into blobs. What
works is the plain **green channel** — red ink absorbs green, cream paper does
not, so the green channel already *is* the grayscale wanted — with black ink
whitened out and Tesseract left to binarise. That one change took the reading
from 1–2 corners per sheet to 8 of 10 exact.

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

**All 73 georeferenced sheets are extracted: 74 847 houses**, every one carrying
a pixel position, a Lambert easting and northing, and a WGS84 longitude and
latitude. 74 136 of them are on the 72 sheets whose absolute anchor is
confirmed.

Across all 73 georeferenced sheets, building counts run **29 to 3515** per
sheet, median 929 — the kind of spread settlement density should show. Well
counts, on the ten sheets where they were extracted, ran **4 to 2158**. Part of
that spread is real — Djebel Semmama is a dry massif and Oued-Zarga the Medjerda
valley — but a factor of 500 is not, and the overlays show the well detector
firing on blue hatching in marshy ground. Wells are therefore not extracted by
default, are labelled provisional where they exist, and should not be counted or
compared across sheets until the detector is validated sheet by sheet.

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

### The clip: catalogued *size*, measured *position*

Without any clip the legend's own specimen symbols and the red margin labels come
through as map content. The clip box takes its **size** from the sheet's
catalogued extent — which is exactly what a sheet's *"Coordonnées (E … / N …)"*
statement describes, its neatline — and its **position** from the sheet's own
transform. Each source is used only for what it is reliable for.

- **Not the detected neatline, for size.** Its box comes out a median 6% smaller
  than the catalogued one but ranges from 40% smaller to larger, because each
  side of the frame is three rules and the detector picks a different one on
  different sheets. The catalogued size does not vary with how a scan came out.
- **Not the catalogue, for position.** On Djebel Mrhila the box sits 36 km east
  of where the sheet prints its own corner coordinates. Once that sheet's anchor
  was corrected, clipping on the catalogue box threw away four fifths of its
  houses — 735 down to 152. Re-centring on the transform brought it to 818.

Where the catalogue box was already right the change is a no-op, which is the
check that it is doing what it claims: Kasserine moved 1196 → 1195.

Across the series the clip removes **32% of raw detections**, all of it margin
and legend.

### Speed, because it decided what was possible

The first full-sheet pass took 3 min 27 s per sheet, of which two minutes was
system time: `np.mgrid` over a 66-megapixel scan is two int64 arrays of half a
gigabyte, and then each of the ~55 grid lines makes another full-size temporary.
Masking the grid out in 512-row blocks, finding the nearest line by
`searchsorted` instead of one comparison per line, and building only the colour
masks actually requested took it to **30 s per sheet** — same output, 7× faster,
which is the difference between extracting ten sheets and extracting all 73.

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
# 1. transform from the grid, anchored on the margin labels
python3 scripts/georeference_sheets.py --images <dir of record_id.jpg>

# 2. read each sheet's own printed corner coordinates (needs step 1's neatline)
python3 scripts/read_corner_coordinates.py --images <dir>

# 3. re-anchor on them, corroborate from neighbours, re-apply the confidence
#    rule. Arithmetic on the cached transforms - no scan is re-read.
python3 scripts/georeference_sheets.py --images <dir> --csv-only

# symbols, with the detections drawn on the image for inspection by eye
python3 scripts/extract_symbols.py --images <dir> --overlay data/overlays \
    --window 4200 3400 5400 4600
```

The two-pass shape is not an accident of implementation: the corner reader needs
the detected neatline to know where to look, and the anchor needs the corner
reader. Step 3 is cheap and idempotent, because changing an anchor is a whole
number of kilometres of translation and nothing else.

Two checks are worth more than the rest.

The **`--overlay`** output is the honest test for the symbols, and the one that
caught every detector mistake listed above: a count tells you nothing about
whether the detector found houses or grid crossings, and looking at 1200 px of
sheet with the detections circled tells you immediately.

The **shared corners** are the honest test for the transforms, and nothing in the
pipeline is fitted to them. Each sheet's position comes from its own printing;
that 237 corner pairs across 69 sheets then land within 67 m of each other is an
outside verdict on the whole set:

```bash
python3 - <<'EOF'
import json, itertools, statistics as st
geo = json.load(open('data/sheet_georef.json'))
pts = [(s['lambert_zone'], c['easting'], c['northing'], rid)
       for rid, s in geo.items() if 'corners' in s
       for c in s['corners'].values()]
near = [((a[1]-b[1])**2 + (a[2]-b[2])**2) ** 0.5
        for a, b in itertools.combinations(pts, 2)
        if a[3] != b[3] and a[0] == b[0]]
near = [d for d in near if d < 250]
print(len(near), 'coinciding pairs; median', round(st.median(near)), 'm')
EOF
```

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
the session's own. The 132-byte "shapefile" that arrives is an LFS pointer, and a
script that does not check would write it out as if it were data. **GADM** is
reachable but its licence discourages redistribution.

### The join

**20 of 24 gouvernorats and 188 of 264 délégations** hold extracted houses. Only
Gafsa, Kebili, Tataouine and Tozeur — the deep south and the Djerid — have no
sheet extracted at all.

Aggregation uses the **72 anchor-confirmed sheets**, which after the
printed-corner anchoring is all but one of the 73. That is 71 190 houses joined
into gouvernorats over 43 646 km² of ground read. The one sheet left out is an
untitled 1930s sheet whose anchor rests on its margin labels alone.

| Gouvernorat | Houses | km² read | Houses / km² |
| --- | --- | --- | --- |
| Tunis | 2406 | 252 | **9.54** |
| Manubah | 3355 | 1117 | 3.00 |
| Ariana | 1071 | 382 | 2.81 |
| Ben Arous | 1380 | 517 | 2.67 |
| Nabeul | 5831 | 2592 | 2.25 |
| Zaghouan | 6245 | 2802 | 2.23 |
| Siliana | 8668 | 4626 | 1.87 |
| Béja | 6344 | 3473 | 1.83 |
| Bizerte | 6292 | 3568 | 1.76 |
| Monastir | 1694 | 982 | 1.73 |
| Médenine | 592 | 350 | 1.69 |
| Sidi Bou Zid | 1119 | 686 | 1.63 |
| Sousse | 3112 | 2142 | 1.45 |
| Gabès | 1491 | 1119 | 1.33 |
| Jendouba | 1239 | 965 | 1.28 |
| Kairouan | 7673 | 6044 | 1.27 |
| Le Kef | 5586 | 4587 | 1.22 |
| Kassérine | 4828 | 4693 | 1.03 |
| Sfax | 153 | 177 | 0.86 |
| Mahdia | 2111 | 2573 | 0.82 |

Four gouvernorats have a sheet but no reportable density, their read area falling
under the 25 km² floor.

The densest délégations are peri-urban Tunis and its coast — **Sidi Hassine**
(Tunis, 8.65/km² on 60 km²), Soukra (Ariana, 8.37), Cité El Khadra (Tunis, 6.47),
La Marsa (Tunis, 6.38), Fouchana (Ben Arous, 5.99) — with **Bou Argoub** (Nabeul,
5.24 on 48 km²) and **Bekalta** (Monastir, 4.93) the densest that are neither.

### Three things the map deliberately refuses to do

**It does not present extraction coverage as geography.** The denominator is the
*extracted* area inside each unit — the convex hull of that unit's own symbols,
clipped to the unit — so the number means houses per km² of ground actually read.

**It does not draw no data as zero.** Units with no extracted sheet are hatched.
The lightest step of a sequential ramp means "near zero", and near zero is a
claim.

**It does not report a density from a denominator too small to carry one.** A
density needs at least 25 km² read; below that the unit is drawn in flat grey,
distinct from both a value and from "no sheet". Without that floor the délégation
table led with *Menzel Chaker, 353 houses per km²* — six houses on 0.02 km² — and
*Saouaf, 98/km²* from four houses. A ratio with a denominator that small is
arithmetic rather than measurement, and it sorts straight to the top of any
ranking. 41 délégations and one gouvernorat are suppressed on this rule.

### The coastline check was measuring coastality, not anchors — a correction

An earlier version of this document, and the pull request that introduced the
map, claimed the following as an independent verdict on the anchor test: 1.9% of
houses on anchor-confirmed sheets fell outside any gouvernorat against 7.7% on
unconfirmed ones, four times the rate. **That comparison was confounded and the
conclusion drawn from it was wrong.**

What settles it is splitting the sheets by how much of their own footprint is
sea, and comparing within each band:

| sheet footprint | previously confirmed | previously unconfirmed |
| --- | --- | --- |
| wholly inland (<2% water) | 30 069 houses, **0.00%** outside | 17 623 houses, **0.00%** outside |
| coastal edge (2–20%) | 11 102 houses, 2.29% | 4 899 houses, 6.45% |
| substantially sea (>20%) | 3 205 houses, 20.3% | 7 949 houses, 21.7% |

On the 17 previously-unconfirmed sheets that are wholly inland, **not one of
17 623 houses falls outside the country**. On the sheets that are mostly sea the
two groups are indistinguishable, at 20% and 22%. The whole of the original gap
was composition: the group the old test rejected happened to contain 11 mostly-sea
sheets against the confirmed group's 4, because the northern and Cap Bon coastal
sheets are exactly the ones whose catalogue boxes were worst.

Kef Abbed makes the point concretely. It does place houses at 37.43°N, north of
Cap Angela, and 130 of its 143 detections fall outside any gouvernorat — but its
anchor is now confirmed by its own printed corners at three corners in easting and
two in northing, and its transform is byte-for-byte unchanged. Over half its
footprint is water. Those detections are **detector false positives over the sea,
not evidence of a displaced sheet.**

So the honest reading is narrower and still worth having: houses landing outside
the country measure **false positives on the sea-facing part of coastal sheets**,
at roughly a fifth of detections on sheets more than 20% water. They do not enter
any density, since a point outside every unit joins to nothing. The test that
does bear on anchors is the shared-corner agreement in §1, which no part of the
pipeline is fitted to.

### What the map is also evidence for

The 73 sheet footprints tile the northern half of the country as a regular
lattice, abutting without overlaps or gaps, and every extracted house falls
inside its own sheet. Nothing in the pipeline enforces that: the footprints come
from each sheet's own printing, fitted independently. The shared-corner
measurement in §1 puts a number on what this shows by eye — 237 corner pairs from
different sheets agreeing to a median 67 m.

What it does *not* test is content alignment across a shared edge. A sheet whose
anchor were wrong would still be clipped to a box centred on its own transform,
so its footprint would stay on the lattice while its content came from the wrong
part of the image. Detecting that needs feature matching across sheet edges, and
is not done.

### Where confidence lives

Whether a sheet's anchor was confirmed is recorded once, in
[`data/sheet_georef.csv`](../data/sheet_georef.csv), and joined on `record_id`.
It used to be stamped onto every extracted symbol as well, and the two copies
drifted — 44 sheets by one rule against 39 by another, with each consumer
believing whichever it happened to read. A derived fact about a sheet does not
belong on ten thousand of its symbols.

### The joined outputs

| Path | |
| --- | --- |
| [`data/symbols_by_unit.csv`](../data/symbols_by_unit.csv) | 288 rows: every gouvernorat and délégation, with counts, area read, density and the basis for it |
| [`data/symbols_joined.csv`](../data/symbols_joined.csv) | every symbol with its modern gouvernorat and délégation attached |
| [`data/boundaries/`](../data/boundaries/) | the shapefiles themselves, levels 0–3 |

### A caution on the units

These are contemporary boundaries. The sheets record fieldwork from the 1880s to
the 1930s, when the units were French civil and military circumscriptions that do
not map onto today's gouvernorats. Aggregating to modern units is a way of
indexing the objects and comparing them against modern statistics — not a claim
that the unit existed. The historical boundaries the sheets themselves draw,
*limite de commune de plein exercice* among them, are a separate extraction and
still to be done.

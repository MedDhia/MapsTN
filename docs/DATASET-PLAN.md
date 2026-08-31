# Building a dataset from the Bonne / Clarke 1880 sheets

This is the working plan for turning the Tunisia 1:50 000 series into research
data, and the record of what has been established so far by reading the sheets
rather than their catalogue records.

Everything here rests on 96 scans, all of them downloaded and analysed. The
earlier work in [`OBJECT-EXTRACTION.md`](OBJECT-EXTRACTION.md) rested on one.

---

## 1. Which sheets are "the Bonne / Clarke 1880 maps"?

The prompt for this work was a catalogue record stating `proj. Bonne, ellipsoïde
de Clarke 1880`. The obvious way to define the population is to select on that
string. It gives the wrong answer.

| | sheets |
| --- | --- |
| In the 1:50 000 series | 103 |
| Whose catalogue record states the projection | **20** |
| Whose catalogue record states nothing about projection | 83 |

Refetching six of the silent records confirms the parser is not at fault — the
`Coordonnées` line really does stop after the bounding box. Across all 96 cached
partner pages, the words *carroyage*, *Lambert*, *quadrillage*, *méridien* and
*grade* appear **zero** times. The projection is not a property the catalogue
records; the twenty that have it are the twenty someone happened to type it for.

So the population is defined from the sheets. Reading them gives a cleaner
criterion than the catalogue ever could:

| Evidence read off the scan | sheets |
| --- | --- |
| A printed kilometric grid detected | **85 of 96** |
| Header states `CARROYAGE`/`QUADRILLAGE KILOMÉTRIQUE LAMBERT` | 67 |
| — of those, `(NORD TUNISIE)` | 63 |
| — of those, `(SUD TUNISIE)` | 4 |
| Zone assigned, header text or unambiguous latitude | 95 |
| No grid | 11 |

Bonne and Lambert are not alternatives here, and it is worth being explicit
because the two words invite confusion. **Bonne is the projection the sheet is
drawn on. The Lambert carroyage is a military grid overprinted on top of it**,
in red, from the 1920s. A sheet can have the first without the second, and the
eleven sheets with no grid are exactly the early ones: the 1902 editions of
Tunis, La Marsa, El Ariana and Porto-Farina, plus seven undated sheets that
their layout places in the same generation.

That is the real division in the corpus, and it is a division the catalogue
cannot see:

- **85 sheets with the Lambert overprint.** Georeferenceable automatically, to
  about ±9 m, with no human picking control points.
- **11 sheets without it.** Bonne graticule and a sheet-local kilometre
  graduation only. Still georeferenceable, but from the graticule corners, and
  worth less.

Two Lambert zones are in play, and they are not interchangeable — Lambert Nord
Tunisie and Lambert Sud Tunisie have different origins. The four SUD sheets are
the four southernmost in the corpus (33.2°–33.8°N), which is the consistency
check one would want. The conventional limit at 34°39′N falls in the observed
gap between the southernmost NORD sheet (34.97°N) and the northernmost SUD one
(33.77°N). One sheet, *Environs de Sfax*, begins at exactly 34.65°N and is left
unassigned rather than guessed.

---

## 2. What is now in hand

| Artefact | What it is |
| --- | --- |
| [`data/sheet_images.json`](../data/sheet_images.json) | full-resolution scan URL for all 96 partner sheets (0.71 GB total) |
| [`data/partner_pages.json`](../data/partner_pages.json) | the rendered catalogue page text, cached, so metadata claims are checkable offline |
| [`data/sheet_grid.csv`](../data/sheet_grid.csv) | per sheet: grid present, spacing, rotation, scan resolution, Lambert zone, grid label range |
| [`data/sheet_margins.csv`](../data/sheet_margins.csv) | per sheet: fieldwork years, revision, print run, publisher, contour interval, magnetic epoch |
| [`config/legend_vocabulary.json`](../config/legend_vocabulary.json) | the object taxonomy, transcribed from the legend the sheets print |

The scans themselves are not committed: 0.71 GB of public JPEGs belongs in a
cache, not in git. `scripts/fetch_sheet_images.py` finds them and a short loop
downloads them.

### Scan resolution, measured on 85 sheets

| | |
| --- | --- |
| Median | **298 dpi** |
| Range | 297–302 dpi |
| Grid spacing | 234–238 px/km, standard deviation 1.25 px |

This corrects the earlier figure. `OBJECT-EXTRACTION.md` used 311 dpi, inferred
from La Marsa's catalogued paper size of 56 × 76 cm. The catalogued size is
rounded to the centimetre and describes the sheet, not the printed image; the
grid is a known kilometre measured over thirty repeats. **1 px = 4.26 m**, and
`scripts/coordinate_precision.py` now reads the per-sheet measurement rather
than assuming a constant (83 of its 93 rows measured, 10 on the series median).

The tightness of that range — 96 sheets, printed between 1902 and 1941, all
scanning within 2% of each other — says the whole collection went through one
scanning rig at one setting. Which is convenient: a pipeline tuned on one sheet
will not need retuning per sheet.

---

## 3. The georeferencing pipeline

The step that was previously described as intractable is done.
`OBJECT-EXTRACTION.md` §4 said grid detection had been attempted by colour
thresholding and abandoned, because the red of the grid is the red of the roads.
That diagnosis was right and the conclusion was wrong: the question "is this
pixel grid-red" is unanswerable, but "is there a direction in which the red
pixels pile up into a regular comb" is not. Roads are crooked and unrepeating
and contribute a smooth background; the grid contributes sharp peaks at a fixed
period.

`scripts/detect_sheet_grid.py` does three things per sheet:

1. **Shear-and-project** the red mask over a range of angles — a Radon transform
   without the library — and keep the angle whose projection is most peaked.
   The grid sits about 4.25° off the scan raster on most sheets.
2. **Peak spacing** gives the grid lines and hence the resolution.
3. **OCR the red margin type**, which yields both the zone statement and the
   absolute grid labels (`389 390 391 …`).

Absolute labels plus detected pixel positions is a full georeference with no
human in the loop. Roughly 30 easting and 20 northing lines per sheet give about
600 control-point intersections, which is far more than a projective or
polynomial fit needs.

There turned out to be something better still on the sheet, and it was in plain
sight for most of this work: **every sheet prints the exact Lambert coordinates
of its own four neatline corners, to the metre**, in red in the margin with a
leader line to the corner. That is a primary, exact statement of absolute
position owing nothing to any catalogue, and adjacent sheets print identical
values at the corners they share. `scripts/read_corner_coordinates.py` reads
them; see [`OBJECT-DATASET.md`](OBJECT-DATASET.md) §1 for what it changed, which
was to take the sheets whose absolute position rested on nothing checkable from
34 of 73 down to 1.

### What this buys, against the alternative

| Control | Uncertainty |
| --- | --- |
| Printed corner coordinates | **to the metre, as stated** |
| Printed kilometric grid | **±9 m** relative, no absolute placement |
| Catalogue bounding box | up to ±775 m longitude, ±926 m latitude — and 36 km on one sheet |

The bounding box is fine for indexing and useless for placing a well. The 36 km
is the Djebel Mrhila sheet, whose box is wrong by more than a sheet width; the
sheet's own printing put it right.

### Precision floor

Below about 25 m the limit stops being the georeferencing and becomes the map.
A marabout drawn 0.5 mm across occupies 25 m of ground; the original survey
carries its own error of 10–50 m. "The coordinate of this well to ±5 m" is not a
meaningful object.

---

## 4. Dates: the sheets disagree with the catalogue, by decades

Each sheet carries a survey credits block — an index diagram cutting the sheet
into lettered zones with an officer and a fieldwork year against each letter.
The catalogue gives one date. The sheet gives three or more.

| Sheet | Catalogue | Fieldwork, from the sheet | Print run |
| --- | --- | --- | --- |
| Kairouan | 1927 | **1898** | Sept 1936 |
| Environs de Médenine | 1933 | **1900–1907** | May 1940 |
| Environs de Sfax | — | **1896** (revised 1934) | April 1940 |
| Djebel Ichkeul | 1936 | **1890–1932** (five field seasons) | — |
| Toujane / Mareth | 1941 | **1907–1937** | Sept 1941 |
| Kasserine | 1936 | **1935** | Feb 1941 |

Read across the 65 sheets where the block is legible, the pattern holds:

| | |
| --- | --- |
| Catalogue year later than fieldwork by | **median 23 years**, max 46 |
| Sheets whose fieldwork is 1880s–1900s | **41 of 65** |
| Sheets whose catalogue year is 1920s–1940s | 88 of 103 |

So the corpus is, in substance, a survey of the 1890s and 1900s printed and
reprinted for forty years afterwards. A sheet "of 1927" showing 1898 fieldwork
is evidence about the 1890s, and treating the catalogue date as the observation
date would misdate a quarter-century of Tunisian rural geography. Some sheets
are not evidence about a single year at all: Djebel Ichkeul is a composite of
five field seasons spanning 1890–1932, and its credits diagram says which part
of the sheet belongs to which.

`scripts/read_sheet_margins.py` reads this automatically. It is honest about how
well: OCR on engraved copperplate script is poor, so each row records
`survey_years_basis` as `anchored` (54 sheets — the block's own phrase *"Les
Travaux sur le Terrain ont été exécutés…"* was legible) or `unanchored` (11
sheets — years found in the right place but the phrase was not). Two filters
guard against OCR damage: years outside 1880–1949 are rejected, and a year later
than the sheet's own catalogue date is dropped, since fieldwork cannot postdate
the sheet reporting it. Both were needed — before them the table claimed
fieldwork of 1854 on Cap Bon and 1952 on a sheet catalogued 1934. The 1902
sheets set the block in a different position and remain the hardest case; 31
sheets yield no fieldwork year and would need a human eye.

The contour interval (10 m wherever it reads), price, magnetic declination epoch
and publisher come from the same pass. The publisher dates a print on its own:
the Service géographique de l'Armée (64 sheets) became the Institut géographique
national (18 sheets) in 1940.

---

## 5. What the sheets actually contain

The legend is now transcribed in full, row by row, in
[`config/legend_vocabulary.json`](../config/legend_vocabulary.json): **45 rows in
each of two editions**, arranged in the nine printed blocks, each row with its
label as printed and a description of its symbol. Read by eye at full scan
resolution in overlapping panels across the whole legend band, because OCR is
not adequate to it — Tesseract returns *"Chemin d'erploitation et sentier
mulclier"* for *"Chemin d'exploitation et sentier muletier"*.

### There are three legend regimes, not two

| | sheets | catalogue years |
| --- | --- | --- |
| 1936 functional edition | **78** | 1922–1940 |
| 1902 administrative edition | **9** | 1902 |
| **No symbol legend at all** | **4** | 1940s |
| Legend present, edition not read | 4 | — |
| Nothing read | 1 | — |

The third regime is easy to miss and matters: the *coupures spéciales* and some
southern sheets print **no legend whatever** — only an imprint line, the scale
statement and bar, the contour interval, the print run and the price. Their
symbols follow the series convention and have to be read from an edition that
publishes it. Assuming a legend for those four sheets would be inventing one.

The split between the two full editions is clean: no sheet dated 1902 carries
the later legend and none dated 1922–1940 carries the earlier one.
`scripts/read_sheet_legends.py` assigns each sheet by fuzzy-matching the road
ladder, which is where the editions differ and where OCR survives best.

### The editions differ in exactly two places

An earlier version of this document claimed more drift than exists. Reading both
legends at full resolution, the differences are:

1. **The road ladder has four maintained rungs in 1902 and three in 1936.**
   1902: *Route nationale · Route départementale · Chemin de grande
   communication et d'intérêt commun · Chemin vicinal ou autre chemin
   carrossable* — a legal classification. 1936: *Route de grand parcours · Route
   de moyenne communication · Chemin vicinal* — a traffic one. These are not the
   same scale relabelled; one has four rungs and the other three, so pooling
   them needs a crosswalk. The four *unmaintained* classes below the brace are
   identical in both.
2. **The shrine row reads *"Église, chapelle et marabout"* in 1902 and
   *"Église, chapelle, koubba"* in 1936** — same three glyphs, different word.

Everything else is word-for-word identical, including the confessional cemetery
row, the four-level boundary hierarchy, the *Bois* inset naming *Broussailles*,
*Oliviers* and *Palmiers*, *Ravine sans eau en été*, and the typographic *Nota*.
Three differences I had previously recorded — over the olive texture, the
boundary wording and the ravine wording — were artefacts of reading from
low-resolution crops and do not exist. The one further difference that is real
is minor: 1936 prints the contour interval in the legend band and 1902 does not,
which is why that field is recoverable by script only on the later edition.

### Classes that carry real research weight

**Cemeteries are typed by confession** — *chrétien*, *musulman*, *israélite*,
each with its own glyph, on both the 1902 and the 1936 legend. A mapped,
pre-independence indicator of the confessional composition of a locality, with
no counterpart in OSM or in any contemporary Tunisian dataset.

**Land parcels are drawn and named by holding lineage.** On the Sfax hinterland
the ground is divided into fine dashed polygons labelled *Dj.ane Kouidene Oulad
Nedjem*, *Oulad Youssef*, *Oulad Trab*, *Henchir ech Cherfi*. That is cadastral
information printed on a topographic map: a *djenane* is an irrigated garden
estate, a *henchir* a large estate, and the *Oulad X* is who holds it. Parcel
area is a distributional variable, so the boundaries are worth extracting as
geometry rather than as labels.

**Tribal territory is named in spaced capitals** across open country — *BLED EL
ARSAMA*, *ECH CHERF*, *EN NEZILA*, *ET TEMARA* — and *Melk Oulad Kralfa* names
private title. *Bled* against *melk* is the *arch*/*melk* tenure distinction that
structures rural inequality in Tunisia. The legend does not admit this class
exists; it is printed as ordinary toponymy.

**Olive trees are drawn individually**, with their own glyph distinct from the
stipple used for scrub, so planting *density* is recoverable and not just
extent. Likewise houses outside built-up areas are drawn one by one in red, so
settlement density is countable without classifying anything.

**The settler/indigenous distinction is drawn, not inferred**: *Village
Français* and *Ferme École* are labelled separately from the adjacent indigenous
centre.

**The typographic rule is a free feature.** Both editions print: upright type is
an inhabited place, sloped type is physical geography. The map encodes the
settlement/non-settlement distinction in the typeface, which is both usable for
OCR-based extraction and a check on any glyph classifier.

---

## 6. What remains to be built

In the order that gets a usable dataset soonest.

1. **Emit the control points and warp.** The grid intersections are detected and
   the labels are read; nothing yet writes GCPs to a file or produces a GeoTIFF.
   This is plumbing over work already done, and it unblocks everything else.
2. **Symbol extraction by template matching.** Wells (blue circle), houses (red
   rectangle), olive glyphs, trig triangles. Near-uniform marks on a noisy
   background — the easiest class of the four, and the one with the most
   immediate research payoff.
3. **Parcel boundary vectorisation.** Fine black dashed polygons. Harder than
   symbols, more valuable than any of them.
4. **Toponym OCR.** French with heavy superscript abbreviation (`Sᵈⁱ`, `Mᵛᵉᵗ`,
   `Kᵃᵗ`, `Hʳ`) at every angle, which general OCR handles badly. Needed for the
   tenure and tribal classes, and for matching anything to a modern gazetteer.
   This is the long pole and should not gate the rest.

Two things to decide before step 1, because they are choices about the dataset
rather than about the code:

- **The eleven pre-carroyage sheets.** Georeference them from the graticule
  corners and accept worse precision, or exclude them and lose the earliest
  observations — which are also the ones closest to the pre-colonial baseline.
- **How to handle composite survey dates.** The Bizerte sheet spans 1890–1932.
  Either attach a date range to the whole sheet, or digitise the credits index
  diagram and attach a date to each lettered zone. The second is more work and
  is the only one that supports a change-over-time design.

---

## 7. Known limits

- **Coverage is not national.** The series as held here runs from about 37.2°N
  to 35.1°N — the north and the Sahel — plus seven scattered southern sheets.
  The centre-south and the Djerid are largely absent. See
  [`SERIES-50K.md`](SERIES-50K.md).
- **One catalogue extent is impossible.** `B8-C38 Djemmal` is recorded as
  1.62′ × 10′, a sheet 2.4 km wide. The east bound is a typo in the source
  record; flagged as `extent_plausible = 0`.
- **Grid rotation is not meridian convergence.** It clusters near 4.25° across
  the whole corpus, where convergence for Tunisia is under 1° and would vary
  with longitude. It is how the sheets sat on the scanner. Harmless — the fit
  absorbs it — but it should not be read as a cartographic quantity.
- **Margin OCR is partial.** Fieldwork years read on some sheets and not others,
  and the basis is recorded per row. The 1902 layout is the weakest case.

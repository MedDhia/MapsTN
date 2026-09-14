# Codebook — tribal annotation

Variables in [`data/gallica_tunisia_maps_tribes.csv`](../data/gallica_tunisia_maps_tribes.csv)
(one row per catalogue record, 663 rows) and in
[`data/tribal_territories.csv`](../data/tribal_territories.csv) (one row per
label read off a map face). Results and the argument are in
[`docs/TRIBES.md`](TRIBES.md); the scripts are
[`code_tribal_annotation.py`](../scripts/code_tribal_annotation.py) and
[`place_tribal_labels.py`](../scripts/place_tribal_labels.py).

## The one thing to know before using either file

**`tribal_annotation` is not a yes/no.** Three of its four values mean "we
looked"; the fourth, `unknown`, holds 645 of the 663 records and means nobody has
opened the scan. Filtering `tribal_annotation == "observed"` gives the maps known
to annotate tribes — it does not give the maps that do.

The reason is in the data: the catalogue text for the whole collection contains
the word *tribu* zero times. This coding therefore cannot be automated over the
corpus, and its inspected set was chosen for the highest prior rather than at
random.

## A. Record-level coding

| Variable | Values | Definition |
| --- | --- | --- |
| `record_id` | string | Joins to every other table in this repository. |
| `title`, `year`, `century`, `provenance`, `confidence` | | Copied from [`data/gallica_tunisia_maps.csv`](../data/gallica_tunisia_maps.csv), truncated to 160 characters for the title. |
| `scale_denominator` | integer or empty | Parsed from the record's scale statement. Empty for the 340 records that state none. |
| `scale_band` | `topographic` (≤1:100 000), `regional` (≤1:500 000), `synoptic` (≤1:2 000 000), `overview`, `unknown` | Same bands as [`CODEBOOK-FEATURES.md`](CODEBOOK-FEATURES.md), so the two codings can be read side by side. |
| `period` | `pre_protectorate` (< 1881), `protectorate` (≥ 1881), `unknown` | 1881 is the invasion and the Bardo treaty. The cut is at the year the answer to "who holds this ground" stopped being a question and became an administration. |
| `tribal_annotation` | `observed`, `catalogued`, `none_seen`, `unknown` | See below. |
| `annotation_forms` | pipe-separated, from the form vocabulary | Only ever populated for `observed` rows. What was actually seen. |
| `evidence_basis` | `inspected`, `catalogue`, `none` | Which route the row rests on. |
| `metadata_terms` | pipe-separated term families | Which families of the vocabulary in [`config/tribal_gazetteer.json`](../config/tribal_gazetteer.json) matched the record's own text, the BnF notice and the partner page. |
| `metadata_terms_strong` | pipe-separated | The same, excluding `colonial_person_terms`. One record in the collection has a value here. |
| `metadata_tribes` | pipe-separated tribe names | Gazetteer names found in the text. Three records; two are 1:50 000 sheets titled after a district. |
| `tribes_seen_n` | integer or empty | How many tribes the inspection record lists for this map. |
| `labels_placed_n` | integer or empty | How many labels from this map are in `tribal_territories.csv`. |
| `expected_form` | pipe-separated forms | **Inference, not observation.** What a map of this band and period would be expected to carry, calibrated on the sixteen inspected maps. |
| `url` | | The item page. |

### `tribal_annotation`

| Value | n | What it rests on | What it licenses |
| --- | --- | --- | --- |
| `observed` | 14 | The scan was read; `annotation_forms` records what was on it. | Cite it. |
| `catalogued` | 2 | The record's text matched the gazetteer and the face has not been read. Both are 1:50 000 sheets whose *titles* carry a district name that is also a tribe name. | Treat as a lead, not a finding. |
| `none_seen` | 2 | The scan was read in the windows recorded in [`config/inspected_tribal_maps.json`](../config/inspected_tribal_maps.json) and carried none. | Weaker than `observed` — a large sheet read in one window can hide a label elsewhere. `windows_read` says how weak. |
| `unknown` | 645 | Nobody has looked. | Nothing. |

### `annotation_forms` vocabulary

| Form | What it is on the sheet | Seen on |
| --- | --- | --- |
| `territory_label` | The tribe's name in letterspaced capitals across the country it holds, no boundary drawn | 1842, 1853, 1857, 1881 ×3, 1900, 1911, 1920 |
| `marked_tribe` | A territory label carrying an explicit `(Tribu)`, `(Tribu des)`, `(Tribus)`, `TERRITOIRE DES` | 1881 Lasailly only |
| `douar_toponym` | A settlement printed `Dr` / `Douar` + a lineage name | 1857, 1881 Garnier, and both 1:50 000 sheets read |
| `lineage_toponym` | Any place name carrying Ouled / Oulad / Beni / ben | Almost everything |
| `smala` | A settlement named as a tribe's smala | 1900, 1920 |
| `glossary` | A legend panel translating the tribal and settlement vocabulary the map uses | 1881 *Voltaire* |
| `thematic_distribution` | The map's subject is the distribution of a mode of habitation, mapped as areas | 1930 *Habitation rurale des indigènes* |
| `caidat_label` | The caïdat — the administrative unit built on the tribe — named across its ground, abbreviated `Kt des X` on the 1889 sheet and written out by 1943 | 1889, 1943 |
| `admin_limit` | Drawn limits of caïdats, contrôles civils, annexes, the territoire militaire. The only boundaries in this collection that enclose a named native unit — no sheet bounds a tribe | 1889, 1900, 1930, 1943 |

A form is recorded when it was seen in the windows read, so the absence of a form
from a row is absence of evidence at that grain. `lineage_toponym` in particular
is under-recorded: it is on nearly every sheet in the collection and was only
noted where it was looked for.

## B. Label-level coding

One row per label read off a map face, in
[`data/tribal_territories.csv`](../data/tribal_territories.csv) and
[`.geojson`](../data/tribal_territories.geojson). 114 rows: 69 from the 1881
Lasailly sheet, whose face was read whole, and 45 from the 1853 Pellissier, read
over the Tell, the steppe and the Sahel down to about 34°N. **The two do not
cover the same ground**, so the label counts are not a measure of how much each
sheet annotates.

| Variable | Definition |
| --- | --- |
| `record_id`, `year` | The map the label was read from. |
| `label_as_printed` | The text as engraved, transliteration and abbreviation intact: `O. Riah`, `M'Talith`, `Ouchtata Khezara`. |
| `tribe` | The gazetteer's canonical name for it. `O. Riah`, `Ouled Riah` and `Riah` all resolve to `Riah`. |
| `in_gazetteer` | 1 if the printed text resolved to a gazetteer entry, 0 if it is carried through unresolved. |
| `marker` | The marker as printed: `Tribu`, `Tribu des`, `Tribus`, `Territoire des`, or empty. |
| `marked_tribe` | 1 if any marker is present. 40 of 114 — all of them on the 1881 sheet, since the 1853 one marks nothing. |
| `x_px`, `y_px` | Where the label centre sits on the full-resolution scan. Kept so that any reading can be checked against the image. |
| `lon`, `lat` | WGS84, three decimals. **Not a territory centroid** — see below. |
| `gouvernorat` | The modern gouvernorat the point falls in, or empty for the 31 labels west of the frontier. |
| `inside_tunisia` | 1 if the point falls inside the modern border. |
| `read_confidence` | `high` — read without hesitation at full resolution. `medium` — the letters are broken, the name is unfamiliar, or the label could be a village rather than a tribe. 31 of 114 are `medium`, and 16 of those are on the 1853 sheet, which marks nothing and so leaves the class to judgement. |

### What `lon`/`lat` mean, and what they do not

They are **where the engraver centred the tribe's name**, not where the tribe's
territory is centred and certainly not where its boundary runs. No sheet in this
collection draws a tribal boundary.

Two error terms, both in [`data/tribal_fit.json`](../data/tribal_fit.json):

* **Transform.** An affine per sheet, fitted to towns with known modern
  coordinates — seven on the 1881 sheet, ten on the 1853. Leave-one-out RMS, which
  is the figure that applies to a label the fit never saw, is **6.17 km** for 1881
  and **8.17 km** for 1853. Each contains the compilation's own error and the error
  in reading a printed dot, and does not separate them.
* **Annotation.** The printed names have been measured end to end for the 1881
  sheet: 62 of 69 run **5.7 to 48.1 km, median 16**, in
  [`data/tribal_spread.csv`](../data/tribal_spread.csv). This is the
  larger term, it is irreducible, and it is a property of the map rather than of
  the method.
* **Reading, on an unmarked sheet.** On the 1881 sheet, where `(Tribu)` fixes where
  a label ends, the same label read twice from two tiles agreed to 3–5 px. On the
  1853 sheet the same check gives 80 px for HAMEMA, and MADJER runs along an arc of
  some 1500 px whose centre is a judgement call. Its anchor carries a note in
  [`config/tribal_labels_read.json`](../config/tribal_labels_read.json).

So: a label anchor is good to roughly 6 km of where the name is printed, and the
name covers a median 16 km of ground and up to 48. Do not join these points to
modern boundaries and
report the result as a tribe's extent. The `gouvernorat` column is there to make
the points findable, not to assign a tribe to a governorate.

## C. Files

| File | What it holds |
| --- | --- |
| [`config/tribal_gazetteer.json`](../config/tribal_gazetteer.json) | The marker vocabulary as regexes, and 86 tribe names with their observed spellings. Built bottom-up from the sheets; not an ethnography of Tunisia. Six entries are fractions — five of the M'Talith and one of the Hammama — which only the 1853 sheet maps separately. |
| [`config/inspected_tribal_maps.json`](../config/inspected_tribal_maps.json) | What each of the sixteen inspected maps carries, which windows were read, and which tribes were seen. |
| [`config/tribal_labels_read.json`](../config/tribal_labels_read.json) | Every transcribed label with its scan pixel, and the control points used to place them. |
| [`data/tribal_fit.json`](../data/tribal_fit.json) | Per-map transform coefficients, px per degree, RMS and leave-one-out RMS, and the residual at each control town. |
| [`data/tribal_annotation_summary.json`](../data/tribal_annotation_summary.json) | Distributions of every coded variable, and the forms by decade. |
| [`data/tribal_map_agreement.csv`](../data/tribal_map_agreement.csv) | The 30 tribes named on both transcribed sheets, and how far apart the two sheets put each one. Median 23 km, which is about one label length. The 197 km outlier, Ouled Khiar, is two different groups sharing a name. |
| [`data/tribal_spread.csv`](../data/tribal_spread.csv) | One row per tribe: how many names carry it, how far apart they stand, how much ground its field covers. See section D. |
| [`data/tribal_spread_summary.json`](../data/tribal_spread_summary.json) | The counts behind the figure, the bandwidth and why it is that. |
| [`data/tribal_imada_assignment.csv`](../data/tribal_imada_assignment.csv) | One row per contemporary imada, all 2,084. See section D2. |
| [`data/boundaries/neighbours_ne50m.geojson`](../data/boundaries/neighbours_ne50m.geojson) | Algeria, Libya and Sicily clipped to the map window, Natural Earth 1:50m, so the names printed west of the frontier sit on land. |
| [`config/martel_1965_tribes.json`](../config/martel_1965_tribes.json), [`data/martel_1965_tribes.csv`](../data/martel_1965_tribes.csv), [`data/martel_1965_fit.json`](../data/martel_1965_fit.json) | The third sheet, read and placed. See section E. |

## D. How much ground a name covers

[`data/tribal_spread.csv`](../data/tribal_spread.csv), one row per label on the
1881 Lasailly sheet, 69 rows. Built by
[`map_tribal_spread.py`](../scripts/map_tribal_spread.py), which also draws
[`docs/img/tribal_spread.png`](img/tribal_spread.png).

| Variable | Definition |
| --- | --- |
| `sheet` | `1881 Lasailly`. The only sheet measured so far. |
| `label_as_printed`, `tribe` | The name as engraved, and the gazetteer name it resolves to. |
| `lon`, `lat` | The middle of the printed name, from the sheet's affine. |
| `extent_px` | **The measurement.** The length of the name on the scan, end to end, first letter to last. |
| `extent_km` | The same at 0.0798 km per scan pixel, the fitted scale of this sheet. |
| `extent_basis` | `measured`, `measured_clipped` (one end ran off the crop, so the figure is a lower bound), or `not_measured`. |
| `inside_tunisia` | 1 if the label's centre falls inside the modern border. 29 of these labels do not. |

**How it was read.** Each label was cropped from the full 5880 × 8853 scan into
a horizontal strip with a pixel ruler drawn beneath it and the anchor marked,
several strips to a contact sheet, and read by eye. An earlier attempt to chain
glyph blobs automatically is recorded in the script as a failure: it worked on a
clean label and ran away across the sheet on a crowded one.

**What the number is.** The engraver letterspaced a tribe's name across the
country it holds, so the length of the name is the map's own statement of the
tribe's reach. It is not an error bar and not a boundary. Two tribes of the same
importance get names of the same size only if the compiler thought their ground
was the same size, which is exactly the signal.

**Why the figure draws a circle.** The sheet gives one number, the length along
the baseline. The across-name dimension is stated nowhere, so an ellipse would
have to invent a second parameter and an orientation. The circle is centred on
the middle of the name with that length as its diameter, and nothing is clipped
to any boundary.

**What is not in the file.** The 1853 Pellissier and 1965 Martel sheets. Their
names run on long arcs and verticals, not horizontal baselines, so the endpoints
need a different reading. Their labels stay points on the figure.

## D2. The imada index

[`data/tribal_imada_assignment.csv`](../data/tribal_imada_assignment.csv), one
row per contemporary imada, all 2,084, from the OCHA Common Operational Dataset
2022. Kept as a table and no longer drawn. The rule: an imada takes the tribe
whose nearest read label lies closest to its representative point, out to a
60 km cutoff, applied once per cartographer and once pooled.

| Variable | Definition |
| --- | --- |
| `adm4_pcode`, `imada`, `delegation`, `gouvernorat`, `area_sqkm` | The unit and its parents, verbatim from the COD. |
| `tribe_1853_pellissier`, `km_1853` | What the 1853 sheet alone would put here, and how far its nearest name is. Empty beyond the cutoff. |
| `tribe_1881_lasailly`, `km_1881` | The same for the 1881 Lasailly sheet. |
| `tribe_1881_martel`, `km_martel` | The same for Martel's 1965 sketch map, a secondary source. |
| `tribe_pooled`, `source_pooled`, `km_pooled` | The winner with all three competing, which sheet it came from, its distance. |
| `runner_up`, `runner_up_km` | The nearest label of a different tribe, pooled, and its distance. |
| `sources_naming`, `sources_agreeing` | How many of the three reach this imada, and how many name the same tribe as `tribe_pooled`. |

**This table answers a question about indexing, not about where a tribe was**,
and it carries its own warning: of the 1,845 imadas that two or three sheets
reach, only 232, **12.6%**, get the same tribe from all of them. Part is grain
rather than contradiction, since Pellissier names fractions where the others
name the parent. Do not dissolve the table by `tribe_pooled` and publish the
result as tribal territory. The 107 rows with an empty `tribe_pooled` are the
Grand Erg and the deep Dahar.

## E. Martel 1965, the third sheet

[`data/martel_1965_tribes.csv`](../data/martel_1965_tribes.csv), 27 rows, one
per tribe name on the sketch map *Villes et tribus tunisiennes 1881* in André
Martel, *Les Confins saharo-tripolitains de la Tunisie (1881-1911)* (Paris,
P.U.F., 1965). Read and placed by
[`place_martel_labels.py`](../scripts/place_martel_labels.py).

| Variable | Definition |
| --- | --- |
| `source`, `year` | `martel_1965`, and 1881, which is the date the map depicts rather than the date it was drawn. |
| `label_as_printed` | The name as set on the sketch map: `OLED AYAR`, `FRAICHICH`, `OUERGHAMMA`. |
| `tribe` | The gazetteer's canonical name where the label resolves to one, otherwise the printed name title-cased. |
| `in_gazetteer` | 1 for the 19 that resolve, 0 for the 8 that do not. |
| `x_px`, `y_px` | Where the name sits on the reproduction read, 1,200 px across. |
| `lon`, `lat` | WGS84, from a 20-town affine. RMS 10.9 km, leave-one-out 12.6 km, in [`data/martel_1965_fit.json`](../data/martel_1965_fit.json). |
| `note` | Why a label is unmatched, or how an arc-set name was anchored. |

**This is a secondary source and the file exists to keep it one.** Martel is a
historian writing in 1965 from French military and archival material, not an
1881 engraver. The two Gallica sheets are evidence of what a nineteenth-century
compiler put on paper; Martel is evidence of what a modern scholar concluded.
They are kept in separate files, given separate colours on the figure, and
counted separately in every summary. `source` in the assignment table says which
of the three won each imada.

The 8 unmatched names are all southern, and two of them are name collisions with
gazetteer entries that belong to different groups: the Nefzaoua Ouled Yacoub
against the north-western Ouled Yakoub, and the Djerid Troud against the Troud
of the lower Medjerda in Ganiage's annexe. Both are left unmatched rather than
merged.

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
* **Annotation.** Six labels measured run 175 to 400 px, 14 to 32 km. This is the
  larger term, it is irreducible, and it is a property of the map rather than of
  the method.
* **Reading, on an unmarked sheet.** On the 1881 sheet, where `(Tribu)` fixes where
  a label ends, the same label read twice from two tiles agreed to 3–5 px. On the
  1853 sheet the same check gives 80 px for HAMEMA, and MADJER runs along an arc of
  some 1500 px whose centre is a judgement call. Its anchor carries a note in
  [`config/tribal_labels_read.json`](../config/tribal_labels_read.json).

So: a label anchor is good to roughly 6 km of where the name is printed, and the
name covers 14–32 km of ground. Do not join these points to modern boundaries and
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
| [`data/tribal_imada_assignment.csv`](../data/tribal_imada_assignment.csv) | One row per contemporary imada, all 2,084, with the tribe it is assigned to. See section D. |
| [`data/tribal_imada_summary.json`](../data/tribal_imada_summary.json) | The counts behind that table, and the rule it rests on. |
| [`config/martel_1965_tribes.json`](../config/martel_1965_tribes.json), [`data/martel_1965_tribes.csv`](../data/martel_1965_tribes.csv), [`data/martel_1965_fit.json`](../data/martel_1965_fit.json) | The third sheet, read and placed. See section E. |

## D. The imada assignment

[`data/tribal_imada_assignment.csv`](../data/tribal_imada_assignment.csv) gives
every contemporary imada the tribe whose nearest read label lies closest to it,
out to a 60 km cutoff. Boundaries are the OCHA Common Operational Dataset, 2022,
2,084 units. Built by
[`map_tribes_on_imadas.py`](../scripts/map_tribes_on_imadas.py), which also
draws [`docs/img/tribal_distribution_imada.png`](img/tribal_distribution_imada.png).

| Variable | Definition |
| --- | --- |
| `adm4_pcode`, `imada`, `delegation`, `gouvernorat` | The unit and its parents, verbatim from the COD. `adm4_pcode` joins back to the shapefile. |
| `area_sqkm` | The COD's own area for the imada. |
| `tribe` | The tribe whose nearest label point is closest to the imada's representative point. Empty where the nearest is beyond 60 km. |
| `label_as_printed` | The engraved form of that winning name. |
| `source` | Which sheet the winning label was read from: `1853 Pellissier`, `1881 Lasailly`, `1881 Martel (1965)`. The third is a secondary source. |
| `distance_km` | How far the winning name is. The single most important column in the file. |
| `runner_up`, `runner_up_km` | The nearest label belonging to a different tribe, and its distance. |

**`tribe` is the output of a rule, not a reading off a map.** No sheet in this
collection draws a tribal boundary. Where two names sit 60 km apart the
assignment changes hands at 30 km, because that is what nearest means and for no
other reason. Two columns are there so that no row has to be taken on trust:
`distance_km` says how far the extrapolation ran, and `runner_up_km` says how
close the decision was. **64% of assigned rows have a rival name within 10 km of
the winner**, and the median assigned imada is 19.5 km from its name while the
printed names themselves run 14 to 32 km long.

Do not dissolve this table by `tribe` and publish the result as a map of tribal
territory. It is an index of which name was nearest, at a stated resolution,
under a stated rule.

The 107 rows with an empty `tribe` are the Grand Erg and the deep Dahar, where
none of the three sheets prints a name within 60 km.

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

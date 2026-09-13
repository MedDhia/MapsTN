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
| `tribal_ksour` | `Kt des X` — the tribe named through its fortified granaries | 1889 SGA 1:800 000 |
| `douar_toponym` | A settlement printed `Dr` / `Douar` + a lineage name | 1857, 1881 Garnier, and both 1:50 000 sheets read |
| `lineage_toponym` | Any place name carrying Ouled / Oulad / Beni / ben | Almost everything |
| `smala` | A settlement named as a tribe's smala | 1900, 1920 |
| `glossary` | A legend panel translating the tribal and settlement vocabulary the map uses | 1881 *Voltaire* |
| `thematic_distribution` | The map's subject is the distribution of a mode of habitation, mapped as areas | 1930 *Habitation rurale des indigènes* |
| `caidat_label` | The caïdat — the administrative unit built on the tribe — named across its ground | 1943 |
| `admin_limit` | Drawn limits of caïdats, contrôles civils, annexes, the territoire militaire | 1900, 1930, 1943 |

A form is recorded when it was seen in the windows read, so the absence of a form
from a row is absence of evidence at that grain. `lineage_toponym` in particular
is under-recorded: it is on nearly every sheet in the collection and was only
noted where it was looked for.

## B. Label-level coding

One row per label read off a map face, in
[`data/tribal_territories.csv`](../data/tribal_territories.csv) and
[`.geojson`](../data/tribal_territories.geojson). 69 rows, all from the 1881
Lasailly sheet.

| Variable | Definition |
| --- | --- |
| `record_id`, `year` | The map the label was read from. |
| `label_as_printed` | The text as engraved, transliteration and abbreviation intact: `O. Riah`, `M'Talith`, `Ouchtata Khezara`. |
| `tribe` | The gazetteer's canonical name for it. `O. Riah`, `Ouled Riah` and `Riah` all resolve to `Riah`. |
| `in_gazetteer` | 1 if the printed text resolved to a gazetteer entry, 0 if it is carried through unresolved. |
| `marker` | The marker as printed: `Tribu`, `Tribu des`, `Tribus`, `Territoire des`, or empty. |
| `marked_tribe` | 1 if any marker is present. 40 of 69. |
| `x_px`, `y_px` | Where the label centre sits on the full-resolution scan. Kept so that any reading can be checked against the image. |
| `lon`, `lat` | WGS84, three decimals. **Not a territory centroid** — see below. |
| `gouvernorat` | The modern gouvernorat the point falls in, or empty for the 29 labels west of the frontier. |
| `inside_tunisia` | 1 if the point falls inside the modern border. |
| `read_confidence` | `high` — read without hesitation at full resolution. `medium` — the letters are broken or the name unfamiliar, and the transcription could be wrong by a letter or two. 15 of 69 are `medium`. |

### What `lon`/`lat` mean, and what they do not

They are **where the engraver centred the tribe's name**, not where the tribe's
territory is centred and certainly not where its boundary runs. No sheet in this
collection draws a tribal boundary.

Two error terms, both in [`data/tribal_fit.json`](../data/tribal_fit.json):

* **Transform.** An affine fitted to seven towns with known modern coordinates.
  In-sample RMS 39.6 px (3.16 km); leave-one-out RMS 77.3 px (6.17 km). Use the
  leave-one-out figure — it is the one that applies to a label the fit never saw.
  It contains the 1881 compilation's own error and the error in reading a printed
  dot, and does not separate them.
* **Annotation.** Six labels measured run 175 to 400 px, 14 to 32 km. This is the
  larger term, it is irreducible, and it is a property of the map rather than of
  the method.

So: a label anchor is good to roughly 6 km of where the name is printed, and the
name covers 14–32 km of ground. Do not join these points to modern boundaries and
report the result as a tribe's extent. The `gouvernorat` column is there to make
the points findable, not to assign a tribe to a governorate.

## C. Files

| File | What it holds |
| --- | --- |
| [`config/tribal_gazetteer.json`](../config/tribal_gazetteer.json) | The marker vocabulary as regexes, and 75 tribe names with their observed spellings. Built bottom-up from the sheets; not an ethnography of Tunisia. |
| [`config/inspected_tribal_maps.json`](../config/inspected_tribal_maps.json) | What each of the sixteen inspected maps carries, which windows were read, and which tribes were seen. |
| [`config/tribal_labels_read.json`](../config/tribal_labels_read.json) | Every transcribed label with its scan pixel, and the control points used to place them. |
| [`data/tribal_fit.json`](../data/tribal_fit.json) | Per-map transform coefficients, px per degree, RMS and leave-one-out RMS, and the residual at each control town. |
| [`data/tribal_annotation_summary.json`](../data/tribal_annotation_summary.json) | Distributions of every coded variable, and the forms by decade. |

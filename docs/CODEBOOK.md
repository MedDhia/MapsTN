# Codebook — quality coding

Variables in [`data/gallica_tunisia_maps_coded.csv`](../data/gallica_tunisia_maps_coded.csv),
one row per record, keyed to the inventory by `record_id`.

"Quality" in a historical map corpus is not one property, so records are coded
on **three independent families**. Each stands on its own, and for most purposes
the component variables — not the summary constructs at the end — are the honest
unit of analysis.

| Family | Question it answers |
| --- | --- |
| A. Cartographic | How good is this as a *map*? |
| B. Record | How well is it *catalogued*? |
| C. Digital access | How usable is the *digitisation*? |

Everything is derived from catalogue metadata already in
`data/gallica_tunisia_maps.json`, except scan pixel dimensions, which come from
Gallica's IIIF Image API (`data/scan_dimensions.json`). No value is hand-coded,
so the whole coding is reproducible with `python3 scripts/code_quality.py`.

---

## Identifiers and carry-through

| Variable | Type | Description |
| --- | --- | --- |
| `record_id` | string | Gallica ARK id, or `oai:` id for partner records |
| `title` | string | Catalogue title |
| `year` | int / blank | Exact year; blank where the catalogue gives none |
| `century` | string | From the harvest, e.g. `18th c.` |
| `confidence` | high/medium/low | Tunisia-relevance, from the harvest (see METHODOLOGY.md) |
| `provenance` | string | Holding digital library |
| `url` | string | Viewer link |

---

## Family A — Cartographic quality

### `scale_denominator` (int, blank if uncatalogued)
The *d* in 1:*d*, parsed from the `Échelle(s)` field.

### `scale_class`
Conventional cartographic bands. A smaller denominator means more ground detail.

| Value | Range | Typical content |
| --- | --- | --- |
| `large` | ≤ 1:25 000 | Site plans, city and fortification plans |
| `medium` | 1:25 001 – 1:250 000 | Topographic sheets |
| `small` | 1:250 001 – 1:1 000 000 | Regional and whole-country sheets |
| `very_small` | > 1:1 000 000 | Mediterranean, Africa, world |
| `unknown` | — | No scale in the catalogue record |

**`unknown` is the modal value and is not missing at random.** Early modern maps
frequently carry no expressed scale at all, and the catalogue records what the
map states. Treat `unknown` as informative about the period, not as a gap to
impute.

### `production_mode`
`manuscript` | `printed` | `unknown`

`manuscript` where the Dublin Core type says *document cartographique manuscrit*,
or the physical description says `ms.`, *au lavis*, *à la plume*, *sur calque*.
`printed` where there is an engraving, lithography or printing signal, or a named
commercial publisher (which implies a printed edition). Otherwise `unknown`.

Manuscript is not "worse" than printed — for administrative and military maps it
often means a unique surveyed document rather than a commercial derivative. It is
a *type* indicator that bears on quality, not a rank.

### `colour`
`colour` | `monochrome` | `unknown`, from `en coul.` / `col.` versus `en noir` /
`n. et b`. **Caveat:** limited two-colour printing (`en noir et bleu`, `en noir et
rouge`) is coded `monochrome`, because the catalogue phrasing keys on *noir*.

### `authority_type`
Who stood behind the survey. Read from the publisher **and** the creator field,
because the issuing body is often a creator while the publisher is only the
printer — e.g. a sheet published by "imp. de Lemercier" whose creator is "France.
Dépôt de la guerre" is coded `military_survey`, which is the substantively right
answer.

| Value | Matches |
| --- | --- |
| `military_survey` | Service géographique de l'armée, Dépôt de la guerre, Ministère de la guerre, War Office, État-major |
| `hydrographic` | Dépôt des cartes et plans de la Marine, Service hydrographique |
| `civil_survey` | Institut géographique national, Service topographique, cadastre |
| `scholarly` | Société de Géographie, universities, académies, École française |
| `commercial` | A named publisher matching none of the above |
| `unknown` | No publisher, or `[s.n.]` / *éditeur inconnu* |

First match wins, in the order listed.

### `genre`
`map` | `plan` | `view` | `atlas` | `other`, from the Dublin Core type. `atlas`
means the record is a whole volume, so its scale and dimensions describe the book
rather than any single map.

### `sheet_count` (int, blank if unstated)
Leading count in the physical description (`3 flles ; …`). Multi-sheet maps are
generally larger-format survey products.

### `sheet_width_cm`, `sheet_height_cm`, `sheet_area_cm2`
Sheet size in centimetres, for the map itself. Where a record gives several
dimensions (`22 x 21,5 cm (carte), 29,5 x 37,5 cm (support)`), the first is taken
— later ones are the mount or frame.

The catalogue states dimensions in cm, in mm, in metres, or with **no unit at
all**. Unlabelled pairs are resolved by magnitude: below 10 is metres
(`0,49 x 0,35`), up to 250 is centimetres, above that millimetres
(`500 x 380` = a 50 × 38 cm sheet). Parses yielding an edge under 1 cm or over
10 m are discarded rather than recorded. Order is *not* reliably width-then-height.

---

## Family B — Record quality

Eight binary presence indicators, each `1`/`0`:

| Variable | True when |
| --- | --- |
| `has_creator` | Any author, cartographer, engraver or draughtsman named |
| `has_publisher` | A publisher that is not `[s.n.]` / *inconnu* |
| `has_scale` | A scale was catalogued |
| `has_dimensions` | A physical description exists |
| `has_subjects` | Dublin Core subject headings assigned |
| `has_language` | A language is stated |
| `has_catalogue_notice` | Links to a full BnF catalogue notice |
| `has_exact_date` | An exact year, not just a century |

### `metadata_completeness` (0–8)
Sum of the eight. An unweighted count: it says how much the cataloguer recorded,
not how important each field is.

### `metadata_grade`
`A` = 7–8, `B` = 5–6, `C` = 3–4, `D` = 0–2.

### `date_precision`
| Value | Meaning |
| --- | --- |
| `exact` | Catalogue gives a specific year |
| `decade` | Bounds span ≤ 10 years (`188.`) |
| `century` | Bounds span ≤ 100 years (`17..`) |
| `multi_century` | Bounds span more (`16..-17..`) |
| `none` | No usable date |

---

## Family C — Digital access quality

### `provenance_tier`
`bnf` (BnF-held, served from Gallica) or `partner` (aggregated into Gallica's
index over OAI-PMH but hosted elsewhere). **All Family C measurements below
exist only for `bnf` records** — partner images sit on the partner's own server,
so they are `unknown` throughout, not zero. This is the single largest source of
missingness in the coding and it is systematic, not random.

### `has_iiif` (0/1)
A IIIF Presentation manifest exists — the item can be pulled into a georeferencing
or annotation tool (Allmaps, Mirador, QGIS via IIIF).

### `views` (int)
Number of digitised images. `1` for a single sheet; large values mean an atlas.

### `rights_open` (0/1)
Catalogue states *domaine public*.

### `scan_width`, `scan_height` (pixels)
First digitised view, from IIIF `info.json`.

### `scan_megapixels` and `scan_resolution_class`
Total information content of the scan.

| Value | Range |
| --- | --- |
| `low` | < 20 MP |
| `medium` | 20–50 MP |
| `high` | ≥ 50 MP |
| `unknown` | Not a BnF item, or IIIF did not answer |

Bands are absolute rather than quantiles, so they stay comparable if the corpus
is re-harvested.

### `scan_dpi` and `scan_dpi_class`
Effective scan resolution, `longest_edge_px / (longest_edge_cm / 2.54)` — how
finely the sheet was digitised *relative to its physical size*, which raw
megapixels cannot express (a big sheet scanned coarsely can out-pixel a small
sheet scanned finely).

| Value | Range |
| --- | --- |
| `low` | < 300 dpi |
| `standard` | 300–450 dpi |
| `high` | ≥ 450 dpi |
| `unknown` | Sheet size or scan size missing, or multi-sheet |

Computed only where `sheet_count` is 1 or unstated: for a multi-sheet map the
IIIF view is one sheet while the catalogue measures the assembled whole, so the
ratio would be meaningless. Because catalogue width/height order is unreliable,
the longest edges are matched to each other.

**This variable has little variance and that is itself the finding**: BnF
digitisation is near-uniformly at or above the 300 dpi reproduction floor. It
discriminates between items far less than `scan_megapixels` does.

---

## Summary constructs

These two are **heuristics of my own construction**, not standards. They are
provided because a single sortable column is convenient, but any substantive
claim should rest on the component variables above, which are all retained in the
CSV precisely so the constructs can be decomposed or rebuilt.

### `quality_index` (0–100)
Unweighted mean of three equally-weighted subscores:

| Subscore | Points |
| --- | --- |
| Cartographic | scale known 40, sheet dimensions known 20, colour known 10, authority identified 30 |
| Record | `metadata_completeness` / 8 × 100 |
| Access | IIIF 30; resolution `high` 50 / `medium` 35 / `low` 15 / `unknown` 0; open rights 20 |

Note what this rewards: **the cartographic subscore is largely a measure of
whether a property was *recorded*, not of how good the map is.** Scale known
scores 40 whether the map is 1:5 000 or 1:20 000 000. So `quality_index`
correlates strongly with cataloguing effort and with BnF-versus-partner
provenance, and it structurally penalises early modern maps, which genuinely
carry no stated scale. Do not read it as a ranking of cartographic merit.

### `research_tier`
Fitness for use, which is usually what "quality" means in practice.

| Value | Rule | Use |
| --- | --- | --- |
| `1_analytic` | `scale_class` is large or medium **and** scan is high/medium MP | Georeferenceable; features extractable |
| `2_contextual` | Good scan **or** IIIF available | Readable as visual evidence |
| `3_reference` | Neither | Citable, but not examinable at depth |

`research_tier` is the more defensible of the two constructs, because its rule is
short and its cut points are tied to what you can actually do with the file. It
inherits the scale-missingness problem all the same: an unscaled but superbly
detailed 17th-century manuscript plan falls to `2_contextual`.

---

## Reproducing

```bash
python3 scripts/harvest_gallica_maps.py      # catalogue records
python3 scripts/fetch_scan_dimensions.py     # IIIF pixel dimensions (cached)
python3 scripts/code_quality.py              # this coding
```

To change a coding rule, edit the relevant `code_*` function in
`scripts/code_quality.py`; each family is independent of the others.

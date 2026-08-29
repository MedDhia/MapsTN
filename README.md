# MapsTN

An inventory of Tunisia-related maps held in or indexed by
[Gallica](https://gallica.bnf.fr), the digital library of the Bibliothèque
nationale de France.

**663 distinct cartographic records, spanning 1318–2013**, harvested from
Gallica's public SRU API and enriched with parsed dates, scales, provenance and
a relevance score.

| | |
| --- | --- |
| Browsable inventory | [`docs/INVENTORY.md`](docs/INVENTORY.md) |
| Full dataset (CSV) | [`data/gallica_tunisia_maps.csv`](data/gallica_tunisia_maps.csv) |
| Full dataset (JSON) | [`data/gallica_tunisia_maps.json`](data/gallica_tunisia_maps.json) |
| **Quality coding (CSV)** | [`data/gallica_tunisia_maps_coded.csv`](data/gallica_tunisia_maps_coded.csv) |
| **Quality profile** | [`docs/QUALITY.md`](docs/QUALITY.md) |
| **Variable definitions** | [`docs/CODEBOOK.md`](docs/CODEBOOK.md) |
| Run statistics | [`data/summary.json`](data/summary.json) |
| How it was built, and its limits | [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) |

## What's in the collection

**By century**

| | 14th | 16th | 17th | 18th | 19th | 20th | 21st | undated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Records | 1 | 39 | 61 | 170 | 159 | 181 | 7 | 45 |

The single 14th-century item is a Visconti portolan chart of the western
Mediterranean dated 1318. The 16th century is dominated by Italian siege and
island views — *Il vero sito de La Goletta*, several *Disegno dell'isola de
Gerbi* of Djerba, *Carthaginis celeberrimi sinus typus* (1535) — reflecting the
Habsburg–Ottoman contest over the Tunisian coast. The 18th- and 19th-century
material is largely French and Dutch commercial cartography of the Regency of
Tunis, and the 20th century is dominated by survey mapping: 80 records name the
Service géographique de l'armée as publisher and 45 the Institut géographique
national, including 1:50 000 series sheets.

**By language** (records whose sole catalogued language is): French 433,
Italian 42, Latin 29, English 7, Spanish 4, Dutch 3; 130 records state none, and
a further 11 list more than one.

**Rights:** 523 of 663 records are explicitly marked public domain.

**Scale** is catalogued for 203 records, most commonly 1:800 000, 1:2 925 000
and 1:1 000 000.

## Two things to know before using the data

**Not everything here is held by the BnF.** Gallica's search index aggregates
partner libraries, so 157 records resolve to another institution's site — 127 of
them to the Université Bordeaux Montaigne "1886" collection. The `provenance`
column marks these; filter on `provenance == "Gallica"` for a strictly
BnF-held set of 506.

**Relevance is scored, not assumed.** Full-text search over historical
toponyms produces false positives, because Monastir is also a Balkan vilayet and
Béja is also a Portuguese district. Every record carries a `confidence` value —
`high` (551), `medium` (106), `low` (6) — and the six `low` records are visibly
wrong rather than hidden. `medium` mostly means "a map of North Africa or the
Mediterranean on which Tunisia appears", which may or may not be what you want.
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) explains the scoring.

## Quality coding

Every record is coded on quality indicators in
[`data/gallica_tunisia_maps_coded.csv`](data/gallica_tunisia_maps_coded.csv).
"Quality" here is three separate things, coded independently — see
[`docs/CODEBOOK.md`](docs/CODEBOOK.md) for every variable and
[`docs/QUALITY.md`](docs/QUALITY.md) for the distributions.

| Family | Variables | Headline |
| --- | --- | --- |
| **A. Cartographic** | scale class, production mode, issuing authority, colour, genre, sheet size | 56% printed, 29% manuscript; 96 records issued by a military survey |
| **B. Record** | 8 presence indicators, completeness 0–8, grade A–D | 219 grade A, 14 grade D; 525 carry an exact year |
| **C. Digital access** | IIIF, scan megapixels, scan dpi, rights | Median scan 52 MP at 391 dpi; 266 records above 50 MP |

Two summary constructs sit on top: `research_tier` (fitness for use) and
`quality_index` (0–100). **Prefer the components.** Both constructs are my own
heuristics, and `quality_index` in particular rewards *how fully an item was
catalogued and scanned*, not how good the map is — its three top-scoring records
are small-scale commercial maps of the whole Barbary coast.

**`research_tier`** is the more defensible summary:

| Tier | n | Meaning |
| --- | --- | --- |
| `1_analytic` | 50 | Medium/large scale with a good scan — georeferenceable, features readable |
| `2_contextual` | 456 | Usable as visual evidence |
| `3_reference` | 157 | Citable, not examinable at depth |

### The catch that matters most

**Scale is absent for 460 of 663 records, and its absence is not random.**
Partner-library records essentially never carry a scale (151 of 157) versus 61%
of BnF records. So the 20th century looks unscaled (132 records) almost entirely
because 116 of those are partner items — not because 20th-century survey maps
lack scales. Independently, early modern maps often state no scale at all.
Filtering on `scale_class` selects on cataloguing source and period. The same
applies to every Family C measure: all 163 `unknown` resolutions are the 157
partner records plus 6 IIIF failures.

## Data dictionary

| Column | Description |
| --- | --- |
| `record_id` | Gallica ARK identifier, or an `oai:` id for partner records |
| `title`, `alt_titles` | Catalogue title(s) |
| `year` | Exact publication year, empty when the record does not state one |
| `year_earliest`, `year_latest` | Bounds, expanded from truncated dates like `17..` |
| `century` | Assigned when both bounds fall in the same century |
| `date` | Raw Dublin Core date string |
| `creators` | Author, cartographer, engraver, draughtsman |
| `publisher`, `language` | As catalogued |
| `scale` | Parsed from the `Échelle(s)` description field |
| `physical_description`, `views` | Sheet count and dimensions; number of digitised images |
| `subjects`, `coverage`, `description` | Dublin Core subject/coverage/description |
| `holding` | Holding institution and shelfmark |
| `rights` | Rights statement (`domaine public` where applicable) |
| `confidence`, `matched_signal` | Tunisia-relevance score and the term that triggered it |
| `matched_labels`, `matched_queries` | Which query families and terms retrieved the record |
| `url` | Viewer link (Gallica ARK, or the partner's own link) |
| `iiif_manifest` | IIIF Presentation manifest; empty for partner records |
| `provenance` | Holding digital library |
| `thumbnail`, `catalogue_notice`, `internal_id` | Thumbnail, BnF catalogue notice, IFN id |

## Reproducing or extending

```bash
python3 scripts/harvest_gallica_maps.py    # re-query Gallica, rewrite data/
python3 scripts/fetch_scan_dimensions.py   # IIIF pixel dimensions (cached)
python3 scripts/build_inventory.py         # regenerate docs/INVENTORY.md
python3 scripts/code_quality.py            # regenerate the quality coding
```

All scripts are Python 3 standard library only — no dependencies. To widen
coverage, add toponyms or spelling variants to
[`config/queries.json`](config/queries.json) and re-run; the harvester
deduplicates across queries.

## Licence

Code in this repository is under the terms in [`LICENSE`](LICENSE). The
catalogue metadata originates from the Bibliothèque nationale de France and its
partner libraries; the digitised maps themselves are subject to each holding
institution's own reuse terms.

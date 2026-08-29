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
| **Georeferencing / thematic coding (CSV)** | [`data/gallica_tunisia_maps_geospatial.csv`](data/gallica_tunisia_maps_geospatial.csv) |
| **Georeferencing report** | [`docs/GEOREFERENCING.md`](docs/GEOREFERENCING.md) |
| **Geo variable definitions** | [`docs/CODEBOOK-GEO.md`](docs/CODEBOOK-GEO.md) |
| **Feature / region coding (CSV)** | [`data/gallica_tunisia_maps_features.csv`](data/gallica_tunisia_maps_features.csv) |
| **Feature / region report** | [`docs/FEATURES-REGIONS.md`](docs/FEATURES-REGIONS.md) |
| **Feature variable definitions** | [`docs/CODEBOOK-FEATURES.md`](docs/CODEBOOK-FEATURES.md) |
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

**Scale** is known for 323 records — 203 from the Gallica record, 120 recovered
from partner libraries' own pages (see below).

## Two things to know before using the data

**Not everything here is held by the BnF.** Gallica's search index aggregates
partner libraries, so 157 records resolve to another institution's site — 127 of
them to the Université Bordeaux Montaigne "1886" collection. The `provenance`
column marks these; filter on `provenance == "Gallica"` for a strictly
BnF-held set of 506.

**Relevance is scored, not assumed.** Full-text search over historical
toponyms produces false positives, because Monastir is also a Balkan vilayet and
Béja is also a Portuguese district — and because Gallica's index normalises
`medenine` into `médecine`, which imported 35 Paris medical-school plans. Every
record carries a `confidence` value — `high` (551), `unverified` (55),
`medium` (51), `low` (6). `unverified` means a query returned the record but its
own metadata contains no Tunisian term at all: that bucket holds both genuine
16th-century atlases whose Tunis plates are unstated, and outright false
positives. **Filter to `high` to avoid the question.**
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
| **C. Digital access** | IIIF, scan megapixels, scan dpi, rights | Median scan 52 MP at 391 dpi; 269 records above 50 MP |

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

**Scale is still absent for 340 of 663 records, and its absence is not random.**
It used to be 460. Gallica's aggregated records stripped the scale from almost
every partner item (151 of 157), which made the 20th century look unscaled and
made the partner block look like poor-quality material. It was a metadata
artefact: those libraries publish the scale on their own item pages, and
recovering it left only 31 of 157 partner records unscaled against 309 of 506
BnF ones. `scale_source` records which route each value came by.

What remains is genuine: early modern maps frequently state no scale at all, so
filtering on `scale_class` still selects on period. And every Family C measure
is BnF-only by construction — all 157 `unknown` resolutions are partner records,
whose images are not served through IIIF.

## Georeferencing and thematic potential

A second coding, in
[`data/gallica_tunisia_maps_geospatial.csv`](data/gallica_tunisia_maps_geospatial.csv),
answers four questions about what the collection can actually be used for.
Variables are defined in [`docs/CODEBOOK-GEO.md`](docs/CODEBOOK-GEO.md); full
results with record lists are in
[`docs/GEOREFERENCING.md`](docs/GEOREFERENCING.md).

**Coordinates: 151 records, 112 of them centred on Tunisia.** Gallica's Dublin
Core has no coordinate element at all. Coordinates come from two places: full
UNIMARC in the BnF catalogue général (field 123 `$d–$g`), which yields 34; and
the partner libraries' own item pages, which yield a further 117 that Gallica's
aggregated records drop entirely. The `tunisia_extent_share` column separates
sheets centred on the country from Mediterranean and Algerian maps that merely
catch it at the edge.

**Orientation: not catalogued.** Only 2 records mention it. The `orientation`
column is a presumption from period and genre (post-1700 printed cartography is
north-up), validated by eye on four sheets and flagged `uncertain` for the
pre-1700 and perspective-view material where the convention fails.

| Georeferencing tier | n | Method |
| --- | --- | --- |
| `1_direct` | 135 | Published corner coordinates or a graticule — affine or polynomial transform |
| `2_control_points` | 338 | Fit on ports, river mouths, known sites |
| `3_warp_only` | 142 | Thin-plate spline; expect large residuals |
| `4_not_georeferenceable` | 48 | Atlas volumes and perspective views |

**Content transfer is a separate question from geometry**, so it is coded
separately: 269 records are `content_mappable = yes`, 95 `partial`, 299 `no`.

### What this corpus will and won't support

**It is a maritime and military collection, not a socio-economic one.** The
extractable-layer counts make that plain: coastline and bathymetry dominate,
then fortifications. Land-use, population and economic layers are rare.

So for **spatial inequality**, only **61 records** qualify as `direct` — meaning
they show a *distribution* (roads, railways, administrative limits, land use,
urban fabric, mining), Tunisia is their subject rather than incidental, and they
can be placed on the ground. Knowing where towns are is treated as context, not
evidence, or the count would inflate to 123.

For **evolution** specifically, the usable spine is the itinerary and road
network series (1842, 1880, 1882, 1885–87), the national coverages of 1881,
1889, 1895 and 1920, the railway maps, the Algeria–Tunisia frontier
delimitations of 1843 and 1881, and a 1950 mining-and-energy map. That is a real
but thin time series, and it is about **infrastructure and administration** —
not about population, land tenure or income, which this corpus does not carry.

## Depicted features and regional coverage

A third coding, in
[`data/gallica_tunisia_maps_features.csv`](data/gallica_tunisia_maps_features.csv),
records what is drawn on each sheet and which part of Tunisia it covers. See
[`docs/CODEBOOK-FEATURES.md`](docs/CODEBOOK-FEATURES.md) and
[`docs/FEATURES-REGIONS.md`](docs/FEATURES-REGIONS.md).

**Features cannot be read from metadata.** Across all 663 records the catalogue
names mosques in 0, tribes in 0, oases in 0, cemeteries in 0 and wells in 5.
These things are drawn on maps, not catalogued. So the coding is a
scale-and-series model calibrated against **seven sheets read directly through
IIIF**, recorded in
[`config/inspected_sheets.json`](config/inspected_sheets.json).

What those sheets actually show, at 1:50 000: wells as dense blue circles,
marabouts as red dome symbols beside `Sdi` names, `Mvet` for marabout, `Za` for
zaouia, `Ae` for aïn, `Kat` for kalâa, `Hr` for henchir, *Puits* written out,
ksour and guerar granary clusters — and on the Medenine sheet a separately
labelled **"Village Français"** beside the indigenous centre, which is the
settler/indigenous split drawn straight onto the map. The 1920 Taride sheet
carries its own *"Explication des principaux termes arabes"*, so the map
documents the vocabulary: *Bir/Aïn* = well, *Bordj* = fortified post,
*Kalâa/Ksar* = fort, *Koubba* and *Zaouia* = chapel, *Sidi* = saint, *Souk* =
market. It also marks the **Limite nord du Territoire Militaire**.

| Scale band | n | Carries |
| --- | --- | --- |
| `topographic` (≤1:100 000) | 135 | Wells, shrines, ksour, ruins, farms, tracks, vegetation |
| `regional` | 47 | Ranked settlements, roads, railways, relief, admin limits |
| `synoptic` | 66 | Principal towns, railways, roads, chotts |
| `overview` | 75 | Coastline and major towns |
| `unknown` | 340 | No scale recorded |

### The 1:50 000 series

**89 records are numbered sheets of the Tunisia 1:50 000 topographic series** —
Tunis, La Goulette, Sousse, Nabeul, Le Kef, Porto-Farina, Metline, Sebkra
Kelbia. Gallica's aggregated records give them no scale, no coordinates and no
catalogue notice, so they were previously invisible in every coding here. Their
own item pages at the Bordeaux Montaigne "1886" collection state both, and
[`scripts/fetch_partner_records.py`](scripts/fetch_partner_records.py) recovers
them. That single fix moved 120 records from "no scale" to scaled, added 117
bounding boxes, and quadrupled the directly-georeferenceable set from 34 to 135.
This is the richest material in the collection for anything at village scale.

### Regional coverage

| Region | n | | Region | n |
| --- | ---: | --- | --- | ---: |
| `tunis_capital` | 213 | | `sud_est_djeffara` | 75 |
| `nord_ouest` | 113 | | `centre` | 72 |
| `bizerte_nord` | 107 | | `sfax_kerkennah` | 60 |
| `sahel` | 96 | | `sud_ouest_jerid` | 37 |
| `cap_bon` | 76 | | `national_extent` | 87 |

Regions are assigned from published coordinates where available (133 records)
and from a toponym gazetteer otherwise. The spatial method matters: the series
names its sheets after villages no gazetteer would carry, and using coordinates
raised the interior from 9 records to 72 for `centre` and 2 to 37 for the Jerid.

### Which are complete maps of Tunisia

**Only 2 are confirmed complete, and only because the images were checked.**
Titles mislead: *Carte de la Régence de Tunis* (1881, 1:500 000) sounds like the
whole Regency and stops before the Jerid and the south; *Carte de la Tunisie*
(1895, 1:800 000) is captioned "1re feuille Nord" in its top margin, which its
catalogue record never mentions.

| `coverage_complete` | n |
| --- | ---: |
| `yes` — verified complete | 2 |
| `partial` — verified incomplete, or names a sheet of a set | 2 |
| `unverified` — national in title, image not checked | 114 |
| `no` — not national in scope | 545 |

Confirmed complete: **Nouvelle carte de la Tunisie** (Taride, 1920, 1:900 000)
and **Carte de la Tunisie** (Service géographique de l'armée, 1889, 1:800 000).
The other 114 remain open — resolving them means opening each image, and each
one settled should be appended to `config/inspected_sheets.json`.

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
python3 scripts/harvest_gallica_maps.py      # re-query Gallica, rewrite data/
python3 scripts/fetch_scan_dimensions.py     # IIIF pixel dimensions (cached)
python3 scripts/fetch_catalogue_records.py   # UNIMARC incl. coordinates (cached)
python3 scripts/fetch_partner_records.py     # partner scale + coordinates (cached)
python3 scripts/build_inventory.py           # regenerate docs/INVENTORY.md
python3 scripts/code_quality.py              # regenerate the quality coding
python3 scripts/code_geospatial.py           # regenerate the geo/thematic coding
python3 scripts/code_features_regions.py     # regenerate the feature/region coding
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

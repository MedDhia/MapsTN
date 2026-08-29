# Methodology

How `data/gallica_tunisia_maps.csv` was built, and what its limits are.

## Source

[Gallica](https://gallica.bnf.fr), the digital library of the Bibliothèque
nationale de France, exposes a public [SRU 1.2 search
API](https://api.bnf.fr/api-gallica-de-recherche) at
`https://gallica.bnf.fr/SRU`. No key or registration is needed.

Two practical notes about the endpoint:

- **A browser `User-Agent` is required.** Gallica answers `403 Accès Interdit`
  to the default `curl`/`urllib` agent. The harvester sends a Chrome UA string.
- **`maximumRecords` is capped at 50**, so results are paged with `startRecord`.

## Query design

Every query is ANDed with a document-type filter:

```
(dc.type all "carte") and (<index> <operator> "<term>")
```

The type filter is what makes this an inventory of *maps* rather than of every
document mentioning Tunisia. All 663 records come back with Gallica's internal
`typedoc` of `cartes`.

**Operator choice matters.** Gallica's `all` operator ANDs the words anywhere in
the record, which is far too loose for multi-word toponyms — `gallica all "cap
bon"` returned 398 records that merely contained both "cap" and "bon" somewhere.
`adj`, the phrase operator, returned 60. The harvester therefore uses `adj` for
any term containing a space and `all` for single words.

The 59 queries in `config/queries.json` cover five families:

| Family | Examples |
| --- | --- |
| Country / polity | tunisie, tunisia, régence de tunis, royaume de tunis, ifriqiya |
| Cities and ports | tunis, carthage, bizerte, sfax, sousse, kairouan, la goulette, gabès… |
| Islands | djerba, kerkennah |
| Regions | cap bon, khroumirie, golfe de gabès, matmata, chott el jerid |
| Antiquity & historic exonyms | utique, dougga, sbeitla, byzacène, biserta, goletta, africa propria |

Historic exonyms are included deliberately: early modern maps label the country
*Biserta*, *Goletta* or *Africa propria* rather than *Tunisie*, and searching
only the modern French forms silently drops the 16th–17th century material.

Records are deduplicated by identifier, and each row keeps the full list of
queries that matched it in `matched_queries` / `matched_labels`.

## Relevance scoring

Full-text search over an aggregated catalogue produces false positives, and some
Tunisian toponyms exist elsewhere: **Monastir** is also a Balkan vilayet,
**Béja** is also a Portuguese district, **Mahdia** also appears in South Asian
contexts. Rather than dropping matches silently, every record carries a
`confidence` value:

| Value | Meaning | Count |
| --- | --- | --- |
| `high` | A Tunisia-specific toponym appears in the title, subject or coverage fields | 551 |
| `medium` | The toponym appears only in secondary fields, **or** the map covers a wider region that contains Tunisia (North Africa, Barbary, the Mediterranean) | 106 |
| `low` | Matched only by an ambiguous toponym, with no corroborating Tunisian signal anywhere in the metadata | 6 |

The `low` bucket is small and inspectably wrong — it contains a Salonika–Monastir
railway map, a Macedonian prehistoric-sites map, a Portuguese cadastral plan and
a map of the Ganges. Those six are kept in the dataset, flagged, and sorted to
the bottom of each century in the inventory rather than deleted, so the
filtering decision stays auditable.

`medium` is the bucket that needs judgement. It is mostly two things: general
maps of North Africa or the Mediterranean on which Tunisia is one region among
several, and 16th-century atlases (Braun & Hogenberg's *Théâtre des cités du
monde*, Münster's *Cosmographie universelle*) that contain Tunis, Carthage or La
Goulette as individual plates. Both are genuinely useful, but neither is a map
*of Tunisia*.

## Date parsing

Gallica records imprecise dates as truncated numerals — `17..` for the 18th
century, `188.` for the 1880s, `16..-17..` for a range spanning two centuries.
Reading only exact four-digit years left 138 records undated. The harvester
expands these into `year_earliest` / `year_latest` bounds and assigns a
`century` when both bounds fall in the same one, which reduces the undated set
to 19. `year` still holds the exact year and is left empty when the record does
not state one, so the two can be distinguished.

ISO-style dates (`1801-01-01`) are matched before range-splitting; without that,
splitting on `-` turned the `01` month component into a year.

## Provenance caveat

**157 of the 663 records are not hosted by the BnF.** Gallica's search index
aggregates partner libraries harvested over OAI-PMH, and those records resolve
to the partner's own site rather than to a `gallica.bnf.fr` ARK:

| Provenance | Records |
| --- | --- |
| Gallica (BnF) | 506 |
| Collections patrimoniales numérisées de Bordeaux 3 ("1886") | 127 |
| Bibliothèques spécialisées de la Ville de Paris | 21 |
| Bibliothèque interuniversitaire de la Sorbonne | 5 |
| Institut catholique de Paris | 3 |
| Bibliothèque numérique de Valenciennes | 1 |

The `provenance` column records this. For partner records the `url` column uses
the link supplied by the record itself, and `iiif_manifest` is empty, because
`gallica.bnf.fr/iiif/...` manifests exist only for BnF-held items. Filter on
`provenance == "Gallica"` for a strictly BnF-held set.

## Known limitations

- **Maps inside books are out of scope.** The `dc.type all "carte"` filter
  returns catalogued cartographic documents. A map plate bound into a
  19th-century travel narrative catalogued as a *monographie* will not appear.
- **Recall depends on the toponym list.** Four queries returned zero records
  (`ghar el melh`, `jendouba`, `sidi bouzid`, `thysdrus`, `tunetum`,
  `afrique proconsulaire`, `golfe de hammamet`, `chott el djerid`,
  `sahel tunisien`); some of those places are certainly mapped, under other
  spellings the list does not yet carry. Adding terms to
  `config/queries.json` and re-running is the intended way to extend coverage.
- **Metadata is only as good as the catalogue.** Scale is present for 206 of 663
  records; creator, publisher and language are frequently absent for early
  material.
- **Counts are a snapshot.** Gallica adds digitisations continuously. The
  `harvested_at` timestamp in `data/summary.json` records when this run was made.

## Reproducing

```bash
python3 scripts/harvest_gallica_maps.py   # re-query Gallica, rewrite data/
python3 scripts/build_inventory.py        # regenerate docs/INVENTORY.md
```

The harvester is standard-library-only and takes a few minutes at the default
0.3 s inter-request pause. Use `--limit N` to cap records per query for a quick
test run.

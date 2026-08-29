# Codebook — depicted features and regional coverage

Variables in
[`data/gallica_tunisia_maps_features.csv`](../data/gallica_tunisia_maps_features.csv),
one row per record, keyed by `record_id`. Produced by
`scripts/code_features_regions.py`; results in
[FEATURES-REGIONS.md](FEATURES-REGIONS.md).

---

## The problem this coding has to work around

**Catalogue metadata does not record what is drawn on a map.** Across all 663
records the Dublin Core names mosques in **0**, tribes in **0**, oases in **0**,
cemeteries in **0** and wells in **5**. A coding built only on catalogue text
would conclude that this collection depicts none of these things. It depicts
them constantly — they are simply not what a cataloguer records.

So feature coding here is a **scale-and-series model, calibrated against sheets
read directly through IIIF**. Seven sheets were examined and are recorded in
[`config/inspected_sheets.json`](../config/inspected_sheets.json) with what they
actually show. Every row states its basis in `features_basis`.

---

## A. Feature depiction

### `feature_band`

What a sheet can physically carry is set by its scale.

| Value | Scale | What sheets in this band were observed to show |
| --- | --- | --- |
| `topographic` | ≤ 1:100 000 | Wells, springs, marabouts, zaouias, ksour and kalâas, henchirs and ruins, individual farms, tracks, vegetation, contours, wadis |
| `regional` | 1:100 001 – 1:500 000 | Ranked settlements, roads, railways, relief, hydrography, administrative limits |
| `synoptic` | 1:500 001 – 1:2 000 000 | Principal towns, railways, roads, relief, chotts |
| `overview` | > 1:2 000 000 | Coastline and major towns only |
| `unknown` | — | No scale recorded anywhere |

### `expected_features`, `features_observed`, `features_basis`

- `expected_features` — the band list above. An inference.
- `features_observed` — what was actually seen on the sheet. Populated only for
  the seven inspected sheets.
- `features_basis` — `image` where a sheet was examined, `scale_model` where the
  band inference applies, `none` where no scale is known.

### `features_in_metadata`

The minority of records whose catalogue text does happen to name a feature
class, using the generics as they appear in French and transliterated Arabic:
*puits, bir, biar, aïn, aïoun, hassi, oglat* (wells and springs); *marabout,
koubba, zaouia, sidi* (shrines); *mosquée, djamaa, medersa*; *bordj, ksar,
kalâa, kasbah* (forts); *henchir, ruines* (ruins); *douar, mechta, gourbi*
(rural settlement); *oued, chott, sebkha*; *oasis, palmeraie*.

**This is a floor, not a census.** A 1:50 000 sheet shows hundreds of wells
whether or not its record says so.

### `settlement_focus`

| Value | Meaning |
| --- | --- |
| `urban_plan` | A city plan |
| `town_and_hinterland` | "Environs de …" — a town with its surrounding countryside |
| `rural_regional` | Topographic or regional sheet, countryside dominant |
| `small_scale_no_settlement_detail` | Too small a scale to distinguish urban from rural fabric |
| `undetermined` | No scale to judge from |

---

## B. Regional coverage

### Regions

Nine historic/geographic regions: `tunis_capital`, `cap_bon`, `bizerte_nord`,
`nord_ouest`, `sahel`, `centre`, `sfax_kerkennah`, `sud_ouest_jerid`,
`sud_est_djeffara`.

### `regions_covered`, `regions_basis`

Two methods, best first:

| `regions_basis` | Method |
| --- | --- |
| `bbox` | The sheet's published coordinates are intersected with region boxes. A region counts when the overlap covers ≥15% of whichever box is smaller. |
| `gazetteer` | Toponyms matched in title, subjects, coverage and geographic headings. |
| `scope` | National sheets, recorded as `national_extent` |
| `none` | Neither available |

The spatial method matters because the 1:50 000 series names its sheets after
villages — *Halk el Menzel*, *Metline*, *Sidi Bou Ali*, *Nefza* — that no
reasonable gazetteer would list. Using coordinates raised coverage of the
interior sharply: `centre` from 9 records to 72, `sud_ouest_jerid` from 2 to 37.

Two traps the gazetteer has to handle. **"Tunis" is both the capital and the
country**: *Tunis, Régence de* is a standing subject heading on scores of
coastal charts, and matching it naively filed 589 of 663 records under the
capital region. Those phrasings are masked before matching. And **word
boundaries are required** — without them `tunis` matches inside `tunisie`.

### `coverage_scope`

| Value | Meaning |
| --- | --- |
| `national` | The country is the subject, judged from the **title** (a subject heading is not enough) |
| `coastal_strip` | A hydrographic chart of the coast — spans the country lengthwise but maps a strip, not the territory |
| `supranational` | Extends well beyond Tunisia: Barbary, Africa, the Mediterranean, the world |
| `multi_region` / `single_region` | Two or more, or exactly one, Tunisian region |
| `locality` | A town plan, a topographic sheet, or a numbered sheet of a national series |
| `undetermined` | Nothing matched |

### `sheet_partition`

The record's text indicates one sheet of a larger set. This catches both
`1re feuille Nord` and the series form `Flle. N° XXXVI-B4-C37`. **89 records are
numbered sheets of the Tunisia 1:50 000 series** — they carry the country's name
in their title and would otherwise all read as maps of the whole country.

---

## C. Completeness

### `coverage_complete`

| Value | Meaning |
| --- | --- |
| `yes` | Verified against the image as covering the whole country |
| `partial` | Verified as covering only part, or the text names a sheet of a set |
| `unverified` | National in title, never checked against the image |
| `no` | Not national in scope |

**`yes` requires that someone has looked.** This is not caution for its own
sake — titles are actively misleading here:

- *Carte de la Régence de Tunis* (1881, Garnier, 1:500 000) sounds like the
  whole Regency and covers only the north and centre; it stops before the Jerid,
  Djerba and the south.
- *Carte de la Tunisie* (1895, Service géographique de l'armée, 1:800 000) is
  captioned **"Tunisie 800 000, 1re feuille Nord"** in its top margin. The
  catalogue record does not mention the partition anywhere.

Both were caught only by opening the image. `coverage_note` carries what was
seen, and `coverage_basis` is `image` or `title_and_gazetteer`.

---

## Reproducing

```bash
python3 scripts/fetch_partner_records.py    # partner scale + coordinates
python3 scripts/code_quality.py             # prerequisite
python3 scripts/code_geospatial.py          # prerequisite
python3 scripts/code_features_regions.py    # this coding
```

To add an inspected sheet, append it to
[`config/inspected_sheets.json`](../config/inspected_sheets.json) with what the
image shows; it overrides the inferred coding for that record.

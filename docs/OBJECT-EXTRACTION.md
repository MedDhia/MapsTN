# Objects on the sheets, and how precisely they can be located

Two questions: **what is drawn**, and **how well can each thing be placed on the
ground**. The short answers are that the object vocabulary is rich and legible,
and that precise coordinates are obtainable — but not from the catalogue
bounding box, which is off by hundreds of metres on a third of the sheets.

Everything below is measured on the **La Marsa sheet** (XIV-B1-C37, 1932
revision, 9312 × 6952 px), read at full resolution. Per-sheet figures are in
[`data/tunisia_50k_precision.csv`](../data/tunisia_50k_precision.csv).

---

## 1. What is drawn

Read directly off the sheets, using the abbreviation vocabulary the maps
themselves publish (the 1920 Taride sheet carries an *Explication des principaux
termes arabes*; the 1881 Garnier sheet has Arabic and Kabyle glossaries).

### Point objects

| Class | How it appears | Seen on |
| --- | --- | --- |
| Wells | Dense blue circles; `Bir`, `Biar`, `Puits` written out | Medenine, Kef, La Marsa |
| Springs | `Aᵉ` = Aïn — e.g. `Aᵉ ech Chefa` | La Marsa, Kef |
| Cisterns | `Citernes` | La Marsa |
| Marabouts / shrines | Red dome symbol beside `Sᵈⁱ` names; `Mᵛᵉᵗ` = marabout | Medenine, Kef, La Marsa (`Sᵈⁱ Salah`, `Sᵈⁱ Drif`) |
| Zaouias | `Zᵃ` | Kef |
| Koubbas | `Kᵇᵃ` — e.g. `Kᵇᵃ Sᵈⁱ ben Bekr` | Medenine |
| Kalâas / forts | `Kᵃᵗ` — e.g. `Kᵃᵗ el Maza` | Kef, La Marsa |
| Bordjs | `Bordj` — e.g. `Bordj el Djedid` | La Marsa |
| Ksour, guerar granaries | Clustered symbols, named `Ksar`/`Guerar` | Medenine |
| Roman ruins | `R.R.` | La Marsa, Medenine |
| Henchirs (ruined estates) | `Hʳ` | Kef |
| Houses and palaces | `Dar` — `Dar Mimoun Bey`, `Dar Salah Bey`; `Palais du Bey` | La Marsa |
| Lighthouses | `Phare` | La Marsa |
| Optical telegraph | `Poste optique` | La Marsa |
| Post and telegraph offices | `T.P.` in an oval | La Marsa |
| Railway stations | `Gare`, `Stᵒⁿ` | La Marsa |
| Roadmen's houses | `Mᵒⁿ cantʳᵉ` | La Marsa |
| Cemeteries | `Cimᵗʳᵉ` | La Marsa |
| Spot heights | Bare numbers in metres | all |
| **European settlement** | Separately labelled `Village Français` beside the indigenous centre | Medenine |

### Linear and area objects

Roads by class (carriageable, track, path), railways, contours, coastline,
oueds, built-up areas (red hatching), cultivation and orchards, vegetation,
sebkhas and chotts.

### The point that matters for research

The settler/indigenous distinction is **drawn on the map** — Medenine's *Village
Français* is a separate labelled entity from Medenine itself. So is the
administrative divide: the 1900 Touring Club sheet marks the *limite
septentrionale des Territoires du Sud*, and the 1920 Taride sheet the *Limite
nord du Territoire Militaire*. None of this exists in OSM.

---

## 2. Three coordinate systems, printed on every sheet

This is the finding that changes the answer. The sheets are not bare images with
a catalogue bounding box — they carry their own control.

**1. A labelled Lambert kilometric grid.** The La Marsa header reads *"Carroyage
kilométrique Lambert (Nord Tunisie)"*. Red grid lines cross the map at one
kilometre spacing, labelled in the margin (533, 534, 535 … easting; 411, 412 …
northing), and the neatline's own Lambert coordinate is printed **to the metre**:
`531.624 m`. Lambert Nord Tunisie is a defined projected system, so these are
usable control points, roughly 30 per sheet at grid intersections.

**2. A centesimal graticule from the Paris meridian.** Marked in grades
(`8ᵍ80'`, `90'`) and subdivided into numbered minutes along the neatline —
French military convention, 400 grades to the circle, longitudes reckoned from
Paris rather than Greenwich.

**3. The catalogue's sexagesimal latitude and longitude**, which is what
`data/tunisia_50k_index.geojson` uses. Good for indexing. Not good for
georeferencing, as follows.

---

## 3. How precisely an object can be placed

### Scan resolution, measured two ways

| Method | Result |
| --- | --- |
| 9312 × 6952 px for a catalogued 56 × 76 cm sheet | **311 dpi** |
| Labelled kilometre grid measured at 234.7 px/km | **298 dpi** |

The two agree within 4.2%, so **1 pixel ≈ 4.1–4.3 m on the ground**.

### Error budget

| Source | Magnitude | Notes |
| --- | --- | --- |
| Scan resolution | 4.1 m | one pixel |
| Locating a grid intersection | ±8 m | about two pixels |
| Locating a symbol centre | ±16 m | about four pixels |
| What a symbol *means* on the ground | 25–75 m | a 0.5–1.5 mm symbol at 1:50 000 |
| Paper distortion, folds, shrinkage | 25–100 m raw | mostly absorbed by fitting many grid points |
| Original survey error | 10–50 m | the La Marsa sheet records fieldwork by Capitaine Sauret, 1891 |
| **Catalogue bbox rounding** | **up to ±775 m** | **on the 29 sheets whose corners are whole arcminutes** |

### The conclusion

**Georeferencing from the printed kilometric grid: about ±10–25 m.** At that
point the limit is not the georeferencing but the symbol itself — a marabout
drawn 1 mm across occupies 50 m of ground, so "the coordinate of this marabout"
is not meaningful below that.

**Georeferencing from the catalogue bounding box alone: up to ±775 m in
longitude and ±926 m in latitude** on 29 of 93 sheets, whose corners are stated
only to whole arcminutes. That is thirty to seventy times worse, and it is the
difference between placing a well in the right field and placing it in the wrong
village.

So: *yes*, objects can be located precisely enough to reproduce the sheet
faithfully — **but the control has to come from the printed grid, not from the
metadata this repository has so far collected.**

### One sheet is simply wrong

`B8-C38 Djemmal` is catalogued as **1.62′ × 10′** — a sheet 2.4 km wide, which
is impossible at this scale and format. The source record says
`E 10°47ʹ36" - E 10°49ʹ13"`; the east bound is a typo. The parse is faithful,
the record is not. It is flagged in
[`data/tunisia_50k_precision.csv`](../data/tunisia_50k_precision.csv) via
`extent_plausible = 0`.

---

## 4. What would be needed to do this for all 103 sheets

Everything above was done by reading one sheet. Doing it across the series is a
pipeline, and step 1 below has since been built — see
[`DATASET-PLAN.md`](DATASET-PLAN.md), which supersedes this section and covers
all 96 sheets.

1. **Grid detection** — ~~attempted by colour thresholding and abandoned~~
   **done**, by `scripts/detect_sheet_grid.py`, on 85 of 96 sheets. The colour
   threshold failed for the reason given below, but the conclusion drawn from it
   was wrong: "is this pixel grid-red" is unanswerable, while "is there a
   direction in which the red pixels pile up into a regular comb" is not. Roads
   contribute a smooth background to such a projection and the grid contributes
   sharp peaks at a fixed period, so the grid is recoverable from the same mask
   that defeats a per-pixel classifier. The eleven sheets with no detection are
   the pre-1920s editions, which carry no Lambert overprint to find.
2. **Neatline detection** — still open, but no longer on the critical path: the
   grid labels give absolute coordinates directly, so the corner values the
   neatline carries are not needed to georeference.
3. **Symbol classification** — a small set of well-defined marks (well circle,
   marabout dome, station, ruin) on a noisy coloured background. Still open.
4. **Toponym OCR** — French with heavy superscript abbreviation (`Sᵈⁱ`, `Mᵛᵉᵗ`,
   `Kᵃᵗ`, `Hʳ`), which general OCR handles badly, plus the transliteration
   variants needed to match anything in OSM. Still open, and the long pole.

### One number here has been corrected

The 311 dpi above came from La Marsa's catalogued paper size. Measuring the
printed kilometre grid on 85 sheets gives a median of **298 dpi** (range
297–302), so **1 px = 4.24 m** rather than 4.08 m. The catalogued size is
rounded to the centimetre and describes the sheet rather than the printed image;
the grid is a known kilometre measured over thirty repeats. The error budget
above shifts by about 4%, which changes none of its conclusions.

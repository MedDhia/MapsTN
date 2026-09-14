# How many people a tribe had, and who counted them

The maps in [`docs/TRIBES.md`](TRIBES.md) say where a tribe was. They say nothing
at all about how many people it held — no sheet in this collection carries a
population figure. This is a review of the sources that do, what each of them
actually counts, and which of the 86 tribes in
[`config/tribal_gazetteer.json`](../config/tribal_gazetteer.json) each one
reaches.

Figures collected so far are in
[`data/tribal_population_sources.csv`](../data/tribal_population_sources.csv),
one row per tribe per source, each with the sentence or table row it came from.
**40 of the 60 Tunisian-side tribes in the gazetteer have at least one figure;
20 have none.** Twelve have two sources, six have three and six have four, which
is what makes the disagreements below legible.

## The sources, and what they count

| Source | Date | Counts | Unit | Granularity | Access |
| --- | --- | --- | --- | --- | --- |
| [Pellissier de Reynaud, *Description de la Régence de Tunis*](https://archive.org/details/descriptiondela00rayngoog) | 1853 | Population, by region and by tribe | souls; some tribes only in horsemen | Tribe | Full text, free |
| [*Dénombrement de la population civile indigène*, 22 mars 1931](https://gallica.bnf.fr/ark:/12148/bpt6k994559s) | 1931 | Census, Tableau II by caïdat, Tableau III by cheikhat | souls, split Muslim/Jewish and by nationality | Caïdat, then cheikhat | Page images on Gallica, free |
| [*Nomenclature et répartition des tribus de Tunisie*](https://gallica.bnf.fr/ark:/12148/bpt6k6212793n) | 1900 | **Nothing.** Structure only | — | Caïdat → cheikhat → fraction → sous-fraction → campsite | Page images on Gallica, free |
| [Ganiage, *La population de la Tunisie vers 1860*](https://www.persee.fr/doc/pop_0032-4663_1966_num_21_5_13406) | 1966, on c. 1858–61 data | Reconstruction from the *mejba* poll-tax registers in Dar el Bey | taxpayers, converted to individuals | Tribe, and fraction in the annexe | Full text free, page by page |
| André Martel, *Les Confins saharo-tripolitains de la Tunisie (1881-1911)*, Paris, P.U.F., 1965 | 1965, on 1881 | **No population figures.** A sketch map of where the tribes were | — | Tribe | Its map is read in [`docs/TRIBES.md`](TRIBES.md). It is listed here because it settles which tribe a figure belongs to, which is not a small thing: it caught two names held by two groups each |
| [FR MAE 1TU/600, *Notices de tribus*](https://archivesdiplomatiques.diplomatie.gouv.fr/media/20150bd1-ac87-4f49-bc76-af37a54b2dd8.pdf) | 1881–1956 | Officer monographs, one per tribe | whatever the officer counted | Tribe and fraction | Nantes, on site; finding aid online |
| [Guérin, *Voyage archéologique dans la Régence de Tunis*](https://archive.org/details/voyagearchologiq00guri) | 1862 | Camps he slept in | tents | One douar at a time | Full text, free |
| Monchicourt, *La région du Haut Tell en Tunisie* (Paris, A. Colin, 487 p.) — [review by A. Bernard, 1914](https://www.persee.fr/doc/geo_0003-4010_1914_num_23_128_8148) | 1913 | Regional monograph, Kef–Téboursouk–Maktar–Thala | not checked | Tribe, in that region only | Book not consulted here; the review is open |

Persée serves neither the PDF nor a full-text view to a script, but it does
serve one page at a time at `/doc/page/<article-id>/<page-id>`, and the thirty
pages of Ganiage fetched that way are what the prose figures below are read from.
That endpoint linearises the page, so on the two-column table of *Annexe I* it
interleaves the columns and the name-to-number pairing it returns is wrong. The
annexe was therefore read off the page image instead, at
`/renderPage/<article-id>/<page-id>_1400.jpg`.

**The unit is the first thing to check and the easiest thing to get wrong.**
Souls, tents, horsemen and taxpayers are four different quantities, and the
conversion between them is an assumption, not an arithmetic. Pellissier gives the
Zlass as 3,000 horsemen and the M'Talith as 15,000 souls on facing pages; those
numbers cannot be compared, and `data/tribal_population_sources.csv` keeps `unit`
next to `figure` so that they are not.

## Pellissier, 1853 — the one paired with a map in this repository

This matters more than its age suggests: the
[1853 map transcribed here](../data/tribal_territories.csv) *is the plate of this
book*. The names read off the sheet and the figures printed in the text are the
same survey, by the same man, in the same year.

He gives population by region, tribe by tribe, in four tables — the upper
Medjerda (total 14,500), the country north of the Medjerda (51,500), the Kef
(33,500) and the Arad (68,800) — plus figures for individual tribes in the
running text. Each table's parts sum to its own printed total, which is how the
transcription in the CSV was checked.

| Tribe | As printed | Figure | Unit | Page |
| --- | --- | --- | --- | --- |
| Mogod | Le Mogod | 10,000 | souls | 52 |
| Kroumirs | Khoumir | 8,000 | souls | 52 |
| Ouchtata | Ouchtata | 2,000 | souls | 52 |
| Ouled bou Salem | Oulad-Bou-Selem | 4,000 | souls | 29 |
| Djendouba | Djendouba | 2,000 | souls | 29 |
| Hakim | Hakim | 2,500 | souls | 29 |
| Ouled Sdira | Oulad-Sedira | 3,000 | souls | 29 |
| Ouargha | Ouarka | 4,000 | souls | 184 |
| Charen | Charen | 3,000 | souls | 184 |
| Ouled bou Ghanem | Oulad-Bou-Ghanem | 4,000 | souls | 185 |
| Ouartan | Ouartan | 7,000 | souls | 185 |
| Doufan | Doufan | 3,000 | souls | 185 |
| Zeghalma | Zeralma | 3,000 | souls | 185 |
| Ouerghemma | Ourghema | 15,000 | souls | 172 |
| Accara | Akara | 4,000 | souls | 172 |
| Matmata | Matmata | 5,000 | souls | 172 |
| Hamarna | Hamerna | 4,000 | souls | 172 |
| M'Talith | Methelith | 15,000 | souls | 133 |
| Souassi | Souassi | 4,000–5,000 | souls | 132 |
| Neffat | Nefat | 4,000 | souls | 136 |
| Ouled Ayar | Oulad-Ayar | 4,000 | souls | 192 |
| Zlass | Djelas | 3,000 | **horsemen** | 126 |
| Mejers | Madjer | 2,000 | **horsemen** | 127 |
| Frechiche | Frachich | 1,000 | **horsemen** | 127 |
| Hammama | Hamema | 4,000 | **horsemen** | 128 |
| Drid | Drid | 1,500 | **tents**, at one assembly | ~160 |

Four entries in the CSV cover more than one group on a single printed line —
*Les Adli, Djeladjela et Nefsa 1,500*, *Les Grezouan et les Grezara 1,500*, and
so on. They are recorded as such and must not be split.

Pellissier states his own error bar, and it is the right note to end on: *« il ne
faut pas demander à ces chiffres le degré d'exactitude qu'on serait en droit
d'exiger en Europe; mais je les crois très-voisins de la vérité. »*

## The 1931 census — the tribe as a caïdat, counted properly

By 1931 the administration counts the unit it had built on the tribe. Tableau II,
*État de la population indigène par Caïdats*, gives all 37 caïdats; nine of them
carry a tribe name from the gazetteer. The full table is transcribed in
[`data/census_1931_caidats.csv`](../data/census_1931_caidats.csv), and it
reproduces the volume's own printed subtotal (1,294,709 after 22 caïdats) and
grand total (2,215,399) in all three columns, which is the check on the reading.

| Caïdat | Tribe | Muslims | Total population |
| --- | --- | --- | --- |
| Djelass | Zlass | 93,017 | 93,157 |
| Ouerghemma | Ouerghemma | 70,069 | 71,923 |
| Madjeurs | Mejers | 68,503 | 68,734 |
| Hammama | Hammama | 58,953 | 59,010 |
| Souassi | Souassi | 42,399 | 42,407 |
| Fraïchiches | Frechiche | 39,043 | 39,085 |
| Oulad-Ayar | Ouled Ayar | 34,278 | 34,289 |
| Oulad-Aoun | Ouled Aoun | 30,827 | 30,923 |
| Matmata | Matmata | 19,573 | 19,805 |

Four more caïdats are the tribal countries under a regional name rather than a
tribal one: Aradh (66,153 — Pellissier's Arad, which he put at 68,800 in 1853),
Aïn-Draham (37,961 — the Kroumirie), Tatahouine (45,680 — the southern
Ouerghemma), Nefzaoua (35,112).

**Do not read these against the 1853 figures as growth.** A caïdat is an
administrative area with a drawn boundary; a tribe in 1853 was a name with no
boundary at all, and Pellissier was estimating by eye where the census was
enumerating households. The Arad pair — 68,800 in 1853 against 66,153 in 1931 —
looks like eighty years of stagnation and is much more likely to be two different
areas being measured two different ways.

Tableau III goes finer, to the cheikhat, and is where the smaller tribes are. It
is not safely usable by name alone: *Akara*, *Trabelsia* and *Neffat* all appear
as cheikhats of the **Caïdat de Bizerte**, hundreds of kilometres from the
Accara of the Ouerghemma, the Trabelsi of the Tell and the Neffat of Sfax. The
1900 *Nomenclature* is the key that resolves which cheikhat belongs to which
tribe, and until that join is done no cheikhat figure is entered here.

## Ganiage, c. 1860 — the tribes counted through their tax

Jean Ganiage read the *mejba* poll-tax registers kept at Dar el Bey and turned
taxpayer counts into population. This is the only source of the three that was
*built* to count tribes: the beylical fiscal unit was the tribe and its
fractions, so the registers are a tribal census in everything but name. It is
also the source closest in date to the 1881 map transcribed here.

| Tribe | As printed | Figure | Unit | Page |
| --- | --- | --- | --- | --- |
| Zlass | Zlass | more than 60,000 | individuals | 878 |
| Hammama | Hammama | 50,000 | individuals | 878 |
| Drid | Drid | about 50,000 | individuals | 877 |
| Frechiche | Frèchich | 46,000–47,000 (1857) | individuals | 877–878 |
| Mejers | Majeur | about 40,000 | individuals | 877 |
| M'Talith | Methellith | a little over 25,000 | individuals | 878 |
| Ouled Ayar | Ouled Ayar | about 24,000 | individuals | 877 |
| Ouerghemma | Ouerghamma | 20,000–25,000 | individuals | 881 |
| Souassi | Souassi | 20,000 | individuals | 878 |
| Ouled Aoun | Ouled Aoun | about 12,000 | individuals | 877 |
| Matmata | Matmata | 10,000–11,000 | individuals | 880 |
| Hamarna | Hamerna | 5,000–6,000 | individuals | 881 |
| Ouled Saïd, Neffat | Ouled Saïd, Neffat | 5,000–6,000 | individuals | 878 |
| Ouled Yakoub | Ouled Yacoub | 4,000–5,000 | individuals | 881 |
| Accara | Accara | 595 | **mejba taxpayers** | 881 |
| Riah | Riah | **unknown, and he says so** | — | 878 |

Two of those rows are worth reading twice. The **Zlass** are *« la plus
importante de la Régence »* on his count, and seventy years later the caïdat of
Djelass is still the largest of the tribal caïdats in the 1931 census, behind
only the three urban ones of Sfax, Tunis and Sousse. And the **Riah** are an
explicit blank: *« Nous ne savons combien étaient les Riah »*, because the
fiscal circumscription lumped them with Testour, Medjez el Bab and Zaghouan. A
named absence is a finding, and it is in the CSV as one.

Ganiage's own caution is on the Ouerghemma, where he converts 5,000 taxpayers
into a population: *« On sent trop le caractère aventureux de telles déductions
dans une région où la frontière était bien proche et bien précaire l'autorité du
gouvernement. »*

### Annexe I, read off the page

His article ends with the table the prose is built on. *Annexe I*, p. 882, is
the general schedule of *mejba* assessments in the first regular budget of the
Regency, the fiscal year 1277 of the Hegira, July 1860 to July 1861: every
fiscal circumscription of the country with the number of men assessed against
it, in two columns, 78 lines and a printed TOTAL of 221,664. It is transcribed
in [`data/ganiage_mejba_1277.csv`](../data/ganiage_mejba_1277.csv), one row per
line, with the footnote that ties each line to a tribe.

It was read by eye. The page image was fetched at 1148 px wide, read left column
then right, then read a second time in four crops enlarged 2.6×; the TOTAL row
was read a third time at 4×. The reading and its provenance are in
[`config/ganiage_annexe1_read.json`](../config/ganiage_annexe1_read.json).

**The printed lines do not add to the printed total.** They sum to 215,607
against a TOTAL of 221,664, a gap of 6,057 or 2.7%. Every line was verified twice
and the total three times, so the gap is in the source. Tunis is not on the list,
which is one candidate for what the total counts and the lines do not. The
annexe does not say, and this is reported rather than reconciled.

Two of Ganiage's own footnotes quote figures from this table, and both come back
exactly: p. 877 gives 11,131 taxpayers among the Drid and 1,944 among the Arab
Majour, and the same page gives 9,240 Majeur in July 1861, which is the sum of
the three Majeur lines here: Ouled Mehanna 4,780, Fouad 2,616, Chaktma 1,844.
That is an external check on the reading, not a restatement of it.

**Not every line is a tribe.** The list runs towns (Sousse, Sfax, Monastir,
Bizerte), districts under their old names (*Outhan el Kabli*, the Cap Bon),
oasis groups (*El Oudiane*, Tamerza and Chebika), two corps of *arouch* of
service at Kairouan, and one line, *Algériens* at 247, that is a nationality.
The largest single line, *Aradh* at 21,938, is the whole south-east. The
smallest, *Beit ech-Chéria* at 51, is one tribe settled around Gafsa.

The tribal work is done by the fourteen footnotes, which say which fiscal units
belong to which tribe: footnote 2 gathers four lines into the Zlass, footnote 5
three into the Hammama, footnote 9 three into the Frèchich, footnote 10 three
into the Majeur, footnote 12 five into the Ounifa league of the north-west. On
that authority the 78 lines reach 22 gazetteer tribes, in
[`data/ganiage_mejba_groups.csv`](../data/ganiage_mejba_groups.csv):

| Tribe | Taxpayers, 1277 | Lines | Ganiage's own figure, individuals | Individuals per taxpayer |
| --- | --- | --- | --- | --- |
| Zlass | 15,706 | 4 | more than 60,000 | 3.82 |
| Drid | 13,075 | 2 | about 50,000 | 3.82 |
| Hammama | 12,313 | 3 | 50,000 | 4.06 |
| Frechiche | 11,057 | 4 | about 46,500 | 4.21 |
| Mejers | 9,240 | 3 | about 40,000 | 4.33 |
| M'Talith | 6,411 | 1 | more than 25,000 | 3.90 |
| Ouled Ayar | 5,797 | 1 | about 24,000 | 4.14 |
| Souassi | 4,955 | 1 | 20,000 | 4.04 |
| Ouartan | 3,953 | 1 | not stated | |
| Trabelsi | 3,883 | 1 | not stated | |
| Ouled bou Ghanem | 2,930 | 1 | not stated | |
| Ouled Aoun | 2,769 | 1 | about 12,000 | 4.33 |
| Djendouba | 2,674 | 1 | not stated | |
| Charen | 2,164 | 1 | not stated | |
| Ouled Sidi Abid | 1,500 | 1 | not stated | |
| Ouargha | 1,480 | 1 | not stated | |
| Zeghalma | 1,393 | 1 | not stated | |
| Neffat | 1,287 | 1 | not stated | |
| Ouled Saïd | 1,185 | 1 | not stated | |
| Ouled bou Salem | 1,040 | 1 | not stated | |
| Ouled Yakoub | 863 | 1 | not stated | |
| Ouled Khiar | 266 | 1 | not stated | |

Four lines name a gazetteer entry finer than the tribe above them and so get
their own row in the sources file: Ouled Khalifa 3,618 and Ouled Aziz 3,847,
Ouled Redouane 5,132, and the joint line *Khamemsa et Doufane* 2,200, whose
figure belongs to the pair and which the annexe does not split. Five tribes that
had no figure at all before now have one: Trabelsi, Khememsa, Oulad Khalifa,
Ouled Redouan and the Oulad Aziz fraction of the Hammama. So do two frontier
tribes, the Ouled Khiar and the Ouled Sidi Abid.

Those 33 attributable lines carry 105,941 of the 215,607 taxpayers on the page.
A little under half the assessed men of the Regency sit in a line this repository
can put a tribe's name to; the rest are in towns, districts and composite
circumscriptions, which is the shape of the country's fiscal geography and not a
defect of the reading.

**The last column is the whole argument of the article, exposed.** Ganiage
states his rate on p. 864, note 4: *« En règle générale, nous avons retenu le
taux de quatre habitants pour un imposé à la mejba, toutes dispenses
comprises. »* Setting his published tribe totals against the taxpayer counts
recovers what he actually used, tribe by tribe: 3.82 to 4.33, median 4.06,
across the nine tribes where he publishes both. The convention is visible, it is
his stated four to within a fifth of a person, and it is a convention: the same
kind of multiplier as Pellissier's ×5 on warriors, applied to a better base.

That range used to read 3.82 to 5.21. The 5.21 was the Ouled Yakoub, and it was
an artefact of two groups sharing a name. Ganiage's 4 or 5,000 on p. 881 is
argued alongside the Ouerghamma and the Hamerna of the Aradh, so it is the
southern Ouled Yacoub, whom Martel's 1881 sketch map prints in the Nefzaoua; the
863 taxpayers on the annexe line carry footnote 12, which puts that
circumscription in the Ounifa league of the north-west. Dividing one by the
other compared two different tribes. No ratio is taken for that name now, both
rows carry the warning, and the correction tightened the result rather than
loosening it: the outlier was the only figure that sat outside Ganiage's own
rate.

**The annexe is a tax roll, not a census, and Ganiage says so.** On p. 864 he
calls the 1277 table *« en définitive peu utilisable »*: it mixes figures that
are hard to compare, it leaves out the mass of exemptions, and, being the fifth
year of collection, its lists are already thinned against the first
enumerations. His documents tell him nothing about the Kroumirs, nor about
Tunis, Kairouan and Sfax, to which he allots 110,000 between them. 221,664 at
his own rate of four gives 886,656, against the 1,100,000 he puts on the
Regency. The gap is the exempt, the uncounted and the three great towns.

The citation: Jean Ganiage, « La population de la Tunisie vers 1860. Essai
d'évaluation d'après les registres fiscaux », *Population*, 21ᵉ année, n° 5,
1966, pp. 857–886, DOI [10.2307/1528138](https://doi.org/10.2307/1528138).

## The two nineteenth-century sources disagree by a factor of four

Pellissier and Ganiage are describing the same decade, and on the steppe tribes
they are not close.

| Tribe | Pellissier 1853 | Pellissier's own conversion, ×5 | Ganiage, c. 1860 |
| --- | --- | --- | --- |
| Zlass | 3,000 horsemen | 15,000 | more than 60,000 |
| Hammama | 4,000 horsemen | 20,000 | 50,000 |
| Mejers | 2,000 horsemen | 10,000 | about 40,000 |
| Frechiche | 1,000 horsemen | 5,000 | 46,000–47,000 |
| **Four tribes together** | 10,000 horsemen | **50,000** | **about 196,000** |

The ×5 is not an invention of this page. Pellissier states it himself (p. 128):
*« J'ai noté le chiffre des guerriers des tribus sur les renseignements qui m'ont
été fournis par les kaïds. En les additionnant, on aura, pour les quatre tribus,
un total de dix mille cavaliers, ce qui répond à une population de cinquante
mille âmes, en comptant cinq individus pour un guerrier, proportion généralement
adoptée et que j'ai toujours trouvée exacte. »*

Ganiage quotes that same passage to reject it (p. 878, note 4): *« Nous sommes
loin des chiffres de Pellissier … En dehors des régions peuplées de sédentaires
qu'il connaissait fort bien, les estimations du vice-consul à Sousse
apparaissent dénuées de fondement, en particulier pour le centre et le sud du
pays. »*

Which is right matters for anything built on these numbers, and the honest
answer is that they fail differently. Pellissier is counting warriors reported
by kaïds, then multiplying; the kaïds had every reason to understate, and his
multiplier is a convention. Ganiage is counting taxpayers, then multiplying;
the same kaïds had the same reason to understate, and *his* multiplier is also a
convention. What tilts it is that Ganiage's tribes, multiplied out, are the
order of magnitude the 1931 census finds in the same places, and Pellissier's
are not.

| Tribe | Pellissier 1853 (×5 where horsemen) | Ganiage c. 1860 | Census 1931 |
| --- | --- | --- | --- |
| Zlass | 15,000 | >60,000 | 93,157 |
| Mejers | 10,000 | ~40,000 | 68,734 |
| Hammama | 20,000 | 50,000 | 59,010 |
| Ouerghemma | 15,000 | 20,000–25,000 | 71,923 |
| Frechiche | 5,000 | 46,000–47,000 | 39,085 |
| Souassi | 4,000–5,000 | 20,000 | 42,407 |
| Ouled Ayar | 4,000 | ~24,000 | 34,289 |
| Matmata | 5,000 | 10,000–11,000 | 19,805 |

Read the columns, not the rows: the 1931 figures are caïdats and the others are
tribes, so no row is a growth series. What the table shows is that Pellissier's
steppe estimates sit four to eight times below both later counts, while his
figures for the settled north — the ones Ganiage exempts from his criticism —
are not out of line at all.

## What has not been retrieved

**Ganiage's *Annexe II*, p. 883,** was not transcribed. It is a *Recensement des
hommes du cap Bon*, the men of each Cap Bon locality by five-year age group,
which is a register of a district's towns and villages and resolves to no tribe
at all. It is the better table for anyone working on age structure, and the
wrong one for this repository. *Annexe I*, which ends on p. 882, is read in full
above.

**FR MAE 1TU/600** is the richest unexploited seam: 253 files of tribal notices
written by intelligence officers from 1884, held at the Centre des archives
diplomatiques de Nantes. The service's own 1885 remit was to collect *« origine
des tribus, populations, contingents pouvant être levés pour ou contre nous,
recensements des bêtes de somme, bestiaux et approvisionnements »* — so these
notices should carry exactly the numbers this page is short of. 23 gazetteer
tribes have a dedicated notice, among them:

| Tribe | File | Author and date |
| --- | --- | --- |
| Frechiche | 1TU/600/94, /96 | *Caïdat des Fraichiches*; Lt Aubert, *Notices sur les Fraichiches* |
| Hammama | 1TU/600/102, /104 | Capt. d'Assailly; Lt Le Bonniec on the Ouled Aziz fraction |
| Ouled Ayar | 1TU/600/52, /53 | Anon., *Tribu des Ouled Ayar (Dahra et Guebala)*, 187 f. [1884] |
| Mogod | 1TU/600/9, /198 | Anon. 1886, corrected 1891 by Capt. Brünck |
| Charen | 1TU/600/8, /36 | Lt Bailly, 1885 |
| Ouargha | 1TU/600/34, /213 | Lt Bailly |
| Ouartan | 1TU/600/35, /214 | Lt Arbez, 1884, corrected 1890 |
| Djendouba | 1TU/600/42 | Capt. Vincent, [1886] |
| Souassi | 1TU/600/67, /252 | Sous-lt Fonssagrives |
| Accara | — | Lt Bailly, *Notice sur les Accara*, [1897] |
| Aguerba | 1TU/600/80, /231 | Lt Lamy |
| Iddir | 1TU/600/73 | Lt Simon, three versions |

They are consultable on site, not digitised.

**Monchicourt 1913** covers the Kef–Téboursouk–Maktar–Thala quadrilateral, which
is where a third of the mapped tribes sit. The book itself was not consulted
here; what was read is Augustin Bernard's review of it in *Annales de
géographie* 23 (128), 1914, pp. 172–175, which describes a 487-page monograph
written by a contrôleur civil who had worked the region since 1898. Whether it
counts tribes is unverified.

## Tribes with no figure from any source yet

Of the 60 Tunisian-side gazetteer tribes, 20 have nothing: Aguerba, Chehida,
Hezil, Iddir, Makna, Mehabel, Mehadhba, Mekena, Meressen, Oulad Amer, Ouled
Soltan, Ouled el Goussem, Regab, Riah, Taïfa, and the five M'Talith fractions
that only the 1853 map names separately. The Riah are the interesting one: they
are missing not because nobody looked but because the tax circumscription that
held them held three towns as well, and Ganiage says so.

The fractions are the interesting gap, and the annexe has just shown what closes
it. Pellissier counts the M'Talith whole, at 15,000, and names its six *berada*
without counting them; his map draws five of them across their own strips of the
Sahel. The 1277 schedule assesses the M'Talith as a single circumscription of
6,411 men and splits none of them, which is why those five are still empty while
the Zlass and the Hammama fractions are not. Whoever wants those five numbers
will find them, if anywhere, in the registers behind the budget rather than in
the budget, or in a Nantes notice.

## Files

| File | What it holds |
| --- | --- |
| [`data/tribal_population_sources.csv`](../data/tribal_population_sources.csv) | One row per tribe per source, 85 rows. `figure` is a string because sources give ranges and bounds; `unit` says what is being counted and must be read before `figure`; `quote` carries the sentence or table row it came from, `page` and `url` say where. |
| [`data/ganiage_mejba_1277.csv`](../data/ganiage_mejba_1277.csv) | The 78 lines of Ganiage's *Annexe I*, in printed order. `name_as_printed` is the fiscal unit as engraved, `taxpayers` the men assessed, `footnote` and `footnote_text` his own note on the line, `tribe` the gazetteer name it belongs to and `attribution_basis` how that was decided: `footnote` on his authority, `name` on the printed name alone, `none` for the lines that are towns, districts or oasis groups. `also_gazetteer` names a finer entry the line matches, and `joint_line` marks the one line covering two tribes. |
| [`data/ganiage_mejba_groups.csv`](../data/ganiage_mejba_groups.csv) | The same lines gathered into the 22 tribes they reach, with Ganiage's own published figure for the tribe where he gives one and the individuals-per-taxpayer that implies. `at_ganiage_rate_of_4` applies his stated rate instead, for tribes where he publishes nothing. |
| [`data/ganiage_mejba_summary.json`](../data/ganiage_mejba_summary.json) | The arithmetic, including the 6,057 discrepancy and what the annexe does not cover. |
| [`config/ganiage_annexe1_read.json`](../config/ganiage_annexe1_read.json) | The reading itself, with how the page was read and how many times. |
| [`data/census_1931_caidats.csv`](../data/census_1931_caidats.csv) | Tableau II of the 1931 census, 37 caïdats. |
| [`scripts/read_ganiage_annexe.py`](../scripts/read_ganiage_annexe.py) | Builds the three Ganiage outputs from the reading and refreshes the annexe rows of the sources file. It reads nothing off the page; the reading is in the config. |

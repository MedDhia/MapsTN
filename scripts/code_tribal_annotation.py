#!/usr/bin/env python3
"""Find the maps that annotate tribes, and say how each one does it.

The question is where a map tells you which people hold which ground: a tribe's
name laid across its country, a caidat named across the same ground fifty years
later, a colour for the tents against a colour for the stone houses.

**The catalogue cannot answer it.** Across 663 records - their Dublin Core, the
BnF catalogue notices behind them and the partner libraries' own item pages - the
word tribu occurs exactly zero times. The gazetteer of tribe names matches three
records, and two of those are 1:50 000 sheets titled Nefza and Ouargha after the
districts they cover. That is not a failure of this scan. Tribal annotation lives
on the map face, and the map face is not catalogued; the same hole that hides
mosques, wells and oases in docs/FEATURES-REGIONS.md hides this.

So the coding has three routes, and every row says which one it rests on:

  inspected   somebody opened the scan and read it. config/inspected_tribal_maps.json
              records what was seen, in which window, at what resolution. This is
              the only route that can say no.
  catalogued  the record's own text names a tribe or uses the vocabulary of one.
              Three records, and two are false in the sense that matters.
  inferred    nothing but scale, date and series. `expected_form` carries this and
              `tribal_annotation` never does: an expectation is not an observation,
              and the 1886 itinerary sheet - 1:800 000, the right period, the
              right publisher, no tribes in the window read - is why.

What the inspected maps show, which is the finding docs/TRIBES.md is written
around: the annotation does not fade out, it changes grain. 1842-1881 prints the
tribe as a country. 1889 prints it as its ksour. 1900-1920 keeps the name but
sets it in type so spaced it is barely a name. 1943 prints the caidat instead.
And the 1:50 000 sheets, at every date, print neither - they print the douar,
the lineage, the henchir, the grain below the tribe.

Outputs:
    data/gallica_tunisia_maps_tribes.csv
    data/tribal_annotation_summary.json
    docs/TRIBES.md

Usage:
    python3 scripts/code_tribal_annotation.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Scale bands, matching docs/CODEBOOK-FEATURES.md so the two codings can be read
# together. The band decides what a sheet has room to say about a tribe: at
# 1:50 000 a tribe is larger than the sheet, so the sheet names its parts.
SCALE_BANDS = [
    (100_000, "topographic"),
    (500_000, "regional"),
    (2_000_000, "synoptic"),
    (float("inf"), "overview"),
]

# What the inspected maps in each band and period actually carry. Calibrated on
# the 16 maps in config/inspected_tribal_maps.json and on nothing else, which is
# why it is reported as an expectation and never as a coding.
EXPECTED = {
    ("topographic", "pre_protectorate"): ["douar_toponym", "lineage_toponym"],
    ("topographic", "protectorate"): ["douar_toponym", "lineage_toponym"],
    ("regional", "pre_protectorate"): ["territory_label", "lineage_toponym"],
    ("regional", "protectorate"): ["caidat_label", "admin_limit", "lineage_toponym"],
    ("synoptic", "pre_protectorate"): ["territory_label"],
    ("synoptic", "protectorate"): ["territory_label", "admin_limit"],
    ("overview", "pre_protectorate"): [],
    ("overview", "protectorate"): [],
}

# 1881 is the invasion and the Bardo treaty; 1956 is independence. Before the
# first, a French map of Tunisia is reconnaissance; between them, administration.
PROTECTORATE_FROM = 1881


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(text))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ",
                                      strip_accents(text).lower())).strip()


def scale_denominator(scale: str) -> int | None:
    match = re.search(r"1\s*[:/]\s*([\d\s.,]+)", str(scale))
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    return int(digits) if digits else None


def band_for(denominator: int | None) -> str:
    if denominator is None:
        return "unknown"
    for limit, name in SCALE_BANDS:
        if denominator <= limit:
            return name
    return "unknown"


def period_for(year: str) -> str:
    if not str(year).isdigit():
        return "unknown"
    return "protectorate" if int(year) >= PROTECTORATE_FROM else "pre_protectorate"


def record_text(record: dict) -> str:
    fields = ("title", "alt_titles", "subjects", "description", "coverage",
              "creators", "publisher", "physical_description")
    return normalise(" | ".join(str(record.get(f, "")) for f in fields))


def extra_text(record_id: str, partner: dict, catalogue: dict) -> str:
    chunks = []
    if record_id in partner:
        chunks.append(str(partner[record_id]))
    if record_id in catalogue:
        chunks.append(" ".join(str(v) for v in catalogue[record_id].values()))
    return normalise(" | ".join(chunks))


def scan_text(text: str, generic: dict, tribe_lookup: list) -> tuple[list, list]:
    families = [name for name, pattern in generic.items() if re.search(pattern, text)]
    tribes = sorted({entry["name"] for pattern, entry in tribe_lookup
                     if re.search(pattern, text)})
    return families, tribes


def build_tribe_patterns(gazetteer: dict) -> list:
    patterns = []
    for entry in gazetteer["tribes"]:
        spellings = {normalise(entry["name"])} | {normalise(v) for v in entry.get("variants", [])}
        for spelling in spellings:
            if len(spelling) < 5:
                # Two- and three-letter tribe names would fire on half the
                # gazetteer of Tunisia. None of the names here are that short
                # once normalised, but the guard is cheap and the failure is not.
                continue
            patterns.append((r"\b" + spelling.replace(" ", r"\s+") + r"\b", entry))
    return patterns


def code(records: list, partner: dict, catalogue: dict, gazetteer: dict,
         inspected: dict, inspected_sheets: dict, placed: dict) -> list[dict]:
    generic = gazetteer["generic_terms"]
    weak = set(gazetteer.get("weak_terms", []))
    tribe_patterns = build_tribe_patterns(gazetteer)
    rows = []
    for record in records:
        record_id = record["record_id"]
        denominator = scale_denominator(record.get("scale", ""))
        band = band_for(denominator)
        period = period_for(record.get("year", ""))

        families, tribes = scan_text(record_text(record), generic, tribe_patterns)
        families_extra, tribes_extra = scan_text(
            extra_text(record_id, partner, catalogue), generic, tribe_patterns)
        all_families = sorted(set(families) | set(families_extra))
        all_tribes = sorted(set(tribes) | set(tribes_extra))
        strong = [f for f in all_families if f not in weak]

        seen = inspected["maps"].get(record_id)
        legacy = inspected_sheets.get("sheets", {}).get(record_id, {})
        legacy_tribes = "tribes" in legacy.get("features_observed", [])

        if seen:
            forms = seen["annotation_forms"]
            annotation = "observed" if forms else "none_seen"
            basis = "inspected"
        elif legacy_tribes:
            forms = []
            annotation = "observed"
            basis = "inspected"
        elif strong or all_tribes:
            forms = []
            annotation = "catalogued"
            basis = "catalogue"
        else:
            forms = []
            annotation = "unknown"
            basis = "none"

        rows.append({
            "record_id": record_id,
            "title": record["title"][:160],
            "year": record.get("year", ""),
            "century": record.get("century", ""),
            "scale_denominator": denominator or "",
            "scale_band": band,
            "period": period,
            "provenance": record.get("provenance", ""),
            "confidence": record.get("confidence", ""),
            "tribal_annotation": annotation,
            "annotation_forms": " | ".join(forms),
            "evidence_basis": basis,
            "metadata_terms": " | ".join(all_families),
            "metadata_terms_strong": " | ".join(strong),
            "metadata_tribes": " | ".join(all_tribes),
            "tribes_seen_n": len(seen["tribes_seen"]) if seen and isinstance(
                seen.get("tribes_seen"), list) else "",
            "labels_placed_n": placed.get(record_id, 0) or "",
            "expected_form": " | ".join(EXPECTED.get((band, period), [])),
            "url": record.get("url", ""),
        })
    return rows


def summarise(rows: list[dict], inspected: dict) -> dict:
    forms = Counter()
    for row in rows:
        for form in filter(None, row["annotation_forms"].split(" | ")):
            forms[form] += 1
    by_period_form = defaultdict(Counter)
    for record_id, sheet in inspected["maps"].items():
        year = sheet.get("year", "")
        decade = f"{str(year)[:3]}0s" if str(year).isdigit() else "undated"
        for form in sheet["annotation_forms"] or ["none_seen"]:
            by_period_form[decade][form] += 1
    return {
        "records": len(rows),
        "tribal_annotation": dict(Counter(r["tribal_annotation"] for r in rows).most_common()),
        "evidence_basis": dict(Counter(r["evidence_basis"] for r in rows).most_common()),
        "annotation_forms": dict(forms.most_common()),
        "metadata_term_families": dict(Counter(
            f for r in rows for f in filter(None, r["metadata_terms"].split(" | "))).most_common()),
        "records_with_tribe_name_in_metadata": sum(1 for r in rows if r["metadata_tribes"]),
        "inspected_maps": len(inspected["maps"]),
        "inspected_with_annotation": sum(1 for s in inspected["maps"].values()
                                         if s["annotation_forms"]),
        "forms_by_decade": {k: dict(v) for k, v in sorted(by_period_form.items())},
    }


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_doc(rows: list[dict], summary: dict, inspected: dict, fits: dict,
              placed_rows: list[dict], path: Path) -> None:
    inspected_maps = inspected["maps"]
    order = sorted(inspected_maps.items(),
                   key=lambda kv: (str(kv[1].get("year") or "9999"), kv[0]))
    fit = next(iter(fits.values())) if fits else {}

    inside = [r for r in placed_rows if r["inside_tunisia"] == "1"]
    marked = [r for r in placed_rows if r["marked_tribe"] == "1"]
    by_gov = Counter(r["gouvernorat"] for r in inside)

    lines = []
    add = lines.append
    add("# Maps that annotate tribes")
    add("")
    add("Which maps in this collection say where a tribe is, how each one says it, "
        "and where the named tribes sit on the ground.")
    add("")
    add("| | |")
    add("| --- | --- |")
    add("| Coding, every record | [`data/gallica_tunisia_maps_tribes.csv`](../data/gallica_tunisia_maps_tribes.csv) |")
    add("| Variable definitions | [`docs/CODEBOOK-TRIBES.md`](CODEBOOK-TRIBES.md) |")
    add("| What was seen on each map | [`config/inspected_tribal_maps.json`](../config/inspected_tribal_maps.json) |")
    add("| Vocabulary and tribe gazetteer | [`config/tribal_gazetteer.json`](../config/tribal_gazetteer.json) |")
    add("| Labels transcribed, with pixels | [`config/tribal_labels_read.json`](../config/tribal_labels_read.json) |")
    add("| Labels placed on the ground | [`data/tribal_territories.csv`](../data/tribal_territories.csv), [`.geojson`](../data/tribal_territories.geojson) |")
    add("| Transform and residuals | [`data/tribal_fit.json`](../data/tribal_fit.json) |")
    add("")
    add("## The catalogue does not know")
    add("")
    tribe_named = summary["records_with_tribe_name_in_metadata"]
    gazetteer_size = len(json.loads(
        (REPO_ROOT / "config" / "tribal_gazetteer.json").read_text(encoding="utf-8"))["tribes"])
    add(f"Across {summary['records']} records — their Dublin Core, the BnF catalogue "
        f"notices behind them and the partner libraries' own item pages — the word "
        f"*tribu* occurs **zero** times. A gazetteer of {gazetteer_size} tribe names, "
        f"every one of them read off a map in this collection, matches "
        f"**{tribe_named}** records:")
    add("")
    add("| Record | Year | What matched | Is it a tribal map? |")
    add("| --- | --- | --- | --- |")
    for row in rows:
        if not row["metadata_tribes"]:
            continue
        title = row["title"][:58]
        verdict = {
            "oai:u-bordeaux-montaigne.fr:340374": "No — a 1:50 000 sheet titled after the Nefza district",
            "oai:u-bordeaux-montaigne.fr:340434": "No — a 1:50 000 sheet titled after the Ouargha district",
            "btv1b84446578": "Yes — the Kroumir expedition of 1881",
        }.get(row["record_id"], "—")
        add(f"| [{title}]({row['url']}) | {row['year'] or '—'} | {row['metadata_tribes']} | {verdict} |")
    add("")
    weak_only = sum(1 for r in rows if r["metadata_terms"] and not r["metadata_terms_strong"])
    strong_n = sum(1 for r in rows if r["metadata_terms_strong"])
    add(f"The generic vocabulary does no better. Tribe, fraction, nomade, douar, "
        f"caidat, ethnographique and the rest match {weak_only + strong_n} records "
        f"between them, and {weak_only} of those match only on the weak colonial "
        f"nouns — *indigènes*, *population*, *race* — which fire on a tuberculosis "
        f"dispensary map of Paris as readily as on anything Tunisian. One record "
        f"matches on strong terms: *Habitation rurale des indigènes*, which is "
        f"genuinely an ethnographic map, and which says so only because its title "
        f"is its subject.")
    add("")
    add("So the count of maps that annotate tribes cannot be got from the metadata "
        "at any threshold. It has to be got by looking, and looking does not scale: "
        f"**{summary['inspected_maps']} maps** have been read directly, of which "
        f"**{summary['inspected_with_annotation']}** carry tribal annotation of some "
        "kind. Everything else in the collection is coded `unknown`, and `unknown` "
        "here means unknown, not no.")
    add("")
    add("## What the annotation looks like, and how it changed")
    add("")
    add("A tribe is never drawn as a polygon. Not once, on any sheet read for this "
        "coding. What the maps print is a **name in letterspaced capitals laid "
        "across the country the tribe holds**, and where the name stops the "
        "annotation stops. Whoever engraved these knew roughly where a tribe was and "
        "did not pretend to know where it ended — which is a more honest map of a "
        "pastoral society than a boundary would have been, and a harder one to turn "
        "into data.")
    add("")
    add("Read in date order, the inspected maps show the grain of the annotation "
        "changing while the ground stays the same:")
    add("")
    add("| Year | Map | Form | What it prints |")
    add("| --- | --- | --- | --- |")
    for record_id, sheet in order:
        forms = ", ".join(f"`{f}`" for f in sheet["annotation_forms"]) or "*none seen*"
        example = ""
        seen = sheet.get("tribes_seen")
        if isinstance(seen, list) and seen:
            example = "; ".join(seen[:3])
        elif isinstance(seen, str):
            example = "69 labels, transcribed"
        add(f"| {sheet.get('year') or '—'} | {sheet['title'][:52]} | {forms} | {example} |")
    add("")
    add("Four stages, and the third is the one worth pausing on.")
    add("")
    add("**1842–1881, the tribe as a country.** Pellissier in 1853 and the Dépôt de "
        "la guerre in 1857 spread tribe names across the steppe in capitals — MADJER, "
        "HAMEMA, OULED TRABERSI — and the 1857 sheet goes further, printing DOUARS "
        "OULED ARFA as a label in its own right: the tribe located through its camps. "
        "These are reconnaissance maps of a country France did not yet hold, and on "
        "them the tribe is the unit that matters, because the tribe is who a column "
        "would meet.")
    add("")
    add("**1881, the tribe marked explicitly.** The invasion year produces the one "
        "sheet in the collection that tags its tribes: Lasailly's *Carte du théâtre "
        "de la guerre en Tunisie* prints `(Tribu)` under the name. It is transcribed "
        "in full below.")
    add("")
    add("**1889, the tribe as its granaries.** The Service géographique's 1:800 000 "
        "names the southern tribes not by their grazing but by their ksour — `Kt des "
        "Neffet`, `Kt des Aguerba`, `Kt des Mahedba`, `Kt des Acara`. Same tribes as "
        "the Taride map thirty years later; a different thing pointed at. A ksar is a "
        "building with coordinates. Grazing is not.")
    add("")
    add("**1900–1943, the tribe becomes the caidat.** The Touring Club sheet of 1900 "
        "still prints the names but sets them so widely that a letter can stand 8 km "
        "from its neighbour, while the administrative limits are inked more strongly "
        "than the names. By 1943 the Service géographique's 1:500 000 prints CAÏDAT DE "
        "TEBOURSOUK, CAÏDAT DE SOUK EL KHEMIS across the same Tell in the same "
        "letterspaced capitals — the annotation survives, the tribe is replaced by the "
        "unit the protectorate built on it, and most of those units are named for a "
        "market town rather than for a people.")
    add("")
    add("**And at 1:50 000, none of the above.** The large-scale series never names a "
        "tribe. It names the grain below: `Dr en Nouilia`, `Dr Krelifa b. Slimane` — "
        "the douar as a mapped settlement — and `Hr Ouled el Hadj`, `Bir Oulad Achour`. "
        "On the Chorbane sheet, which sits inside the country the 1881 and 1920 maps "
        "both label Souassi, the word Souassi does not appear. The tribe is present as "
        "its lineages and absent as itself, because at 1:50 000 a tribe is bigger than "
        "the sheet.")
    add("")
    add("One map does something else entirely. *Habitation rurale des indigènes* "
        "(1930), a plate from the Atlas d'Algérie et de Tunisie, maps six classes of "
        "dwelling as coloured areas — tentes, gourbis, maisons à terrasse, maisons à "
        "toit de tuiles, maisons à l'européenne, grottes et ghorfas. It is the only "
        "thematic ethnographic map in the collection, and the only one that treats "
        "the distribution itself as the subject rather than as annotation.")
    add("")
    add("## The 1881 sheet, transcribed")
    add("")
    add(f"{fit.get('labels', 0)} labels were read off the face of "
        f"[Lasailly's 1881 war-theatre map]({[r['url'] for r in rows if r['record_id'] == 'btv1b84389986'][0]}) "
        f"— the whole map face in {20} overlapping tiles at full scan resolution — and "
        f"each was given a coordinate. {len(marked)} of them carry an explicit "
        f"`(Tribu)`-family marker and {len(placed_rows) - len(marked)} do not; "
        f"{len(inside)} fall inside modern Tunisia and "
        f"{len(placed_rows) - len(inside)} west of the frontier, in what the sheet "
        f"labels the Province de Constantine. The two groups nearly coincide — the "
        f"engraver marked the tribes inside the Regency and left the Constantine "
        f"ones as bare capitals — but not quite: Mogod and Charen sit inside Tunisia "
        f"unmarked, and two marked tribes, the Beni Mtir and the Ouled bou Ghanem, "
        f"fall just west of a frontier that in 1881 was still being argued over, as "
        f"General Lewal's *Etude sur la frontière de la Tunisie* in this same "
        f"collection attests.")
    add("")
    add("![Where the 1881 sheet puts each tribe's name](img/tribal_territories.png)")
    add("")
    add("**How accurate is a point?** Two different questions, and both answers are "
        "small compared with a tribe.")
    add("")
    add(f"The transform is an affine fitted to {fit.get('control_points')} towns whose "
        f"modern coordinates are known — Tunis, Bizerte, Le Kef, Kairouan, Sousse, "
        f"Sfax, Gafsa — read off the sheet the same way the labels were. In-sample RMS "
        f"is **{fit.get('rms_px')} px ({fit.get('rms_km')} km)**; leave-one-out, which "
        f"is the honest number for a label the fit never saw, is "
        f"**{fit.get('loo_rms_px')} px ({fit.get('loo_rms_km')} km)**. That figure is "
        f"the 1881 compilation's own error plus mine, and it is not separable into the "
        f"two.")
    add("")
    add("The graticule was not used, though it is printed and legible, and the reason "
        "is worth recording: the sheet is scanned with a slight rotation and its frame "
        "is not square — the 8° tick on the top border and the 8° tick on the bottom "
        "border are 141 px apart in x. A transform fitted to the border inherits the "
        "frame's skew. Towns do not have that problem.")
    add("")
    add("**The larger error is not positional at all.** Six labels measured across the "
        "tiles run 175 to 400 px — ZLAAS the shortest, OUERGAMA the longest — which at "
        "this sheet's scale is **14 to 32 km of ground**. The point records where the "
        "name is *centred*, so it locates the tribe to within a tribe's width and no "
        "finer. Reading the same label twice from two overlapping tiles agreed to 3–5 "
        "px, and the two towns read twice agreed to 3 px, so transcription is not the "
        "limit. The annotation is.")
    add("")
    add("Where the named tribes fall, by modern gouvernorat:")
    add("")
    add("| Gouvernorat | Labels |")
    add("| --- | --- |")
    for name, count in by_gov.most_common():
        add(f"| {name} | {count} |")
    add(f"| *west of the frontier* | {len(placed_rows) - len(inside)} |")
    add("")
    north_west = sum(by_gov[name] for name in ("Jendouba", "Béja", "Le Kef"))
    add(f"The north-west carries the annotation and the south barely does. Jendouba, "
        f"Béja and Le Kef hold {north_west} of the {len(inside)} Tunisian labels "
        f"between them, while south of Sfax the entire country — the Jerid, the "
        f"Nefzaoua, the Dahar, the Matmata — carries exactly one, the Ouerghemma. "
        f"That is not a map of where tribes were. It is a map of where a French "
        f"compiler in 1881 had names for them, and 1881 is the year of the Kroumir "
        f"campaign in exactly that north-western corner.")
    add("")
    add("## Coding")
    add("")
    add("| `tribal_annotation` | n | Meaning |")
    add("| --- | --- | --- |")
    meanings = {
        "observed": "read on the scan; `annotation_forms` says what",
        "catalogued": "the record's own text uses tribal vocabulary; the face has not been read",
        "none_seen": "the scan was read in the recorded windows and carried none",
        "unknown": "nobody has looked",
    }
    for value, count in summary["tribal_annotation"].items():
        add(f"| `{value}` | {count} | {meanings.get(value, '')} |")
    add("")
    add("`expected_form` is the one inferred column, and it is deliberately kept out "
        "of `tribal_annotation`. It says what a map of that scale band and period "
        "*would* be expected to carry, calibrated on the inspected sixteen. The 1886 "
        "*Carte des itinéraires* is why it stays an expectation: 1:800 000, the right "
        "decade, the Service géographique's own press, and no tribal annotation in the "
        "window read — it prints wells instead, each graded for water quality, because "
        "an itinerary map answers a marching column's question and the column's "
        "question was water.")
    add("")
    add("## What this does not settle")
    add("")
    add("**Sixteen maps out of 663.** The inspected set was chosen for the highest "
        "prior — medium-scale French maps of the Regency between 1840 and 1950 — so the "
        "hit rate among them says nothing about the collection. The honest count is: "
        f"{summary['inspected_with_annotation']} maps in this collection are known to "
        "annotate tribes, and an unknown number of the rest do.")
    add("")
    add("**One map transcribed.** The 1853 Pellissier is denser in tribal names than "
        "the 1881 sheet and is not transcribed here, because it marks none of them and "
        "each would have to be classified by eye against a gazetteer rather than read "
        "off a tag. The comparison it would allow — the same country named twice, "
        "twenty-eight years and one conquest apart — is the obvious next piece of work.")
    add("")
    add("**A point is not a territory.** Nothing in `data/tribal_territories.csv` "
        "should be joined to a modern boundary and reported as a tribe's extent. The "
        "gouvernorat column exists to make the points findable, not to assign a tribe "
        "to a governorate.")
    add("")
    add("**The spellings are French.** Frechiche, Fraichiche, Frechich; Kroumir, "
        "Khroumir, Krumir; Ouled, Oulad, O., Od. The gazetteer normalises what it has "
        "seen, and a tribe printed in a spelling nobody has read yet will not match.")
    add("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config")
    parser.add_argument("--docs", type=Path, default=REPO_ROOT / "docs")
    args = parser.parse_args(argv)

    records = json.loads((args.data / "gallica_tunisia_maps.json").read_text(
        encoding="utf-8"))["records"]
    partner = json.loads((args.data / "partner_pages.json").read_text(encoding="utf-8"))
    catalogue = json.loads((args.data / "catalogue_records.json").read_text(encoding="utf-8"))
    gazetteer = json.loads((args.config / "tribal_gazetteer.json").read_text(encoding="utf-8"))
    inspected = json.loads((args.config / "inspected_tribal_maps.json").read_text(encoding="utf-8"))
    inspected_sheets = json.loads((args.config / "inspected_sheets.json").read_text(encoding="utf-8"))

    placed_rows: list[dict] = []
    placed_path = args.data / "tribal_territories.csv"
    if placed_path.exists():
        placed_rows = list(csv.DictReader(placed_path.open(encoding="utf-8")))
    placed = Counter(r["record_id"] for r in placed_rows)
    fits = {}
    fit_path = args.data / "tribal_fit.json"
    if fit_path.exists():
        fits = json.loads(fit_path.read_text(encoding="utf-8"))

    rows = code(records, partner, catalogue, gazetteer, inspected,
                inspected_sheets, placed)
    summary = summarise(rows, inspected)

    write_csv(rows, args.data / "gallica_tunisia_maps_tribes.csv")
    (args.data / "tribal_annotation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    write_doc(rows, summary, inspected, fits, placed_rows, args.docs / "TRIBES.md")

    print(f"{summary['records']} records coded")
    for key, value in summary["tribal_annotation"].items():
        print(f"  {key:12s} {value}")
    print(f"metadata tribe-name matches: {summary['records_with_tribe_name_in_metadata']}")
    print(f"inspected maps: {summary['inspected_maps']}, "
          f"with annotation: {summary['inspected_with_annotation']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

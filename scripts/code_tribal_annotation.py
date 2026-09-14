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
around: the annotation does not fade out, it changes what it names. 1842-1881
prints the tribe as a country, unbounded. By 1889, eight years into the
protectorate, the Service geographique prints the *caidat* instead - Kt des Riah,
Kt des Ouled Yahia - and draws its limits, which nobody ever drew for a tribe.
Commercial sheets keep the tribe names into the 1920s; by 1943 most caidats are
named for a market town rather than for a people. And the 1:50 000 sheets, at
every date, print none of it - they print the douar, the lineage, the henchir,
the grain below the tribe.

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
              placed_rows: list[dict], pairs_rows: list[dict], path: Path) -> None:
    inspected_maps = inspected["maps"]
    order = sorted(inspected_maps.items(),
                   key=lambda kv: (str(kv[1].get("year") or "9999"), kv[0]))
    fits_by_map = {k: v for k, v in fits.items() if not k.startswith("_")}
    summary_agree = fits.get("_agreement", {})

    inside = [r for r in placed_rows if r["inside_tunisia"] == "1"]
    # The gouvernorat table is the 1881 sheet alone: its whole face was read, so a
    # count per unit means something. Mixing in the 1853 labels would make the
    # north-west look denser still for no reason but that two maps cover it.
    by_gov = Counter(r["gouvernorat"] for r in inside
                     if r["record_id"] == "btv1b84389986")

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
    add("| Do two sheets agree? | [`data/tribal_map_agreement.csv`](../data/tribal_map_agreement.csv) |")
    add("| How much ground a name covers | [`data/tribal_spread.csv`](../data/tribal_spread.csv) |")
    add("| Tribes on today's imadas | [`data/tribal_imada_assignment.csv`](../data/tribal_imada_assignment.csv) |")
    add("| Martel's 1881 sketch map, read | [`data/martel_1965_tribes.csv`](../data/martel_1965_tribes.csv) |")
    add("| How many people was a tribe? | [`docs/POPULATION-SOURCES.md`](POPULATION-SOURCES.md) |")
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
    add("**A tribe is never drawn as a polygon.** Not once, on any sheet read for "
        "this coding. What the maps print is a *name in letterspaced capitals laid "
        "across the country the tribe holds*, and where the name stops the annotation "
        "stops. Whoever engraved these knew roughly where a tribe was and did not "
        "pretend to know where it ended — which is a more honest map of a pastoral "
        "society than a boundary would have been, and a harder one to turn into data.")
    add("")
    add("What does get a boundary is the caïdat. From 1889 the Service géographique "
        "draws dotted limits around units named for the tribes — and that is the "
        "whole administrative story in one typographic difference: a tribe is a name "
        "without edges, a caïdat is a name with them.")
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
    add("**1889, the tribe becomes the caïdat — and acquires an edge.** The Service "
        "géographique's 1:800 000, eight years into the protectorate, tiles the whole "
        "country with `Kt des X`: *caïdat des Riah*, *des Ouled Yahia*, *des Ouled "
        "Khalifa*, *des Neffet*, *des Aguerba*, *des Acara*, and — the label that "
        "settles what the abbreviation means — *Kt des Arrouch en Sendjac*, `arch` "
        "being the Arabic for tribe. Most caïdats are still named for the tribe they "
        "were built on, so the names survive; what changes is that they are now the "
        "names of administrative units, and the sheet draws their limits as dotted "
        "lines. Nobody ever drew a limit around a tribe.")
    add("")
    add("*(An earlier reading of this sheet took `Kt` for `Ksour` — the tribe named "
        "through its granaries. It is recorded because it was a tidy story and it was "
        "wrong. Three things break it: the labels tile the Tell as well as the south, "
        "one of them is `Kt de Sfax`, which has no ksour, and one is `Kt des "
        "Arrouch`.)*")
    add("")
    add("**1900–1943, the name detaches from the people.** Commercial sheets keep the "
        "tribes: the Touring Club map of 1900 and the Taride of 1920 both still print "
        "Souassi, Metellith, Neffet, though the Touring Club sets them so widely that "
        "a letter can stand 8 km from its neighbour while the administrative limits "
        "are inked more strongly than the names. The military sheets do not. By 1943 "
        "the Service géographique's 1:500 000 prints CAÏDAT DE TEBOURSOUK, CAÏDAT DE "
        "SOUK EL KHEMIS across the same Tell in the same letterspaced capitals — same "
        "unit as 1889, and now named for the market town rather than for the people. "
        "Fifty-four years to go from *caïdat des Riah* to *caïdat de Teboursouk*.")
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
    add("## Two sheets, transcribed")
    add("")
    add(f"Two of the inspected maps were read label by label and every tribe name "
        f"given a coordinate: the 1881 Lasailly war-theatre sheet, because it marks "
        f"its tribes with `(Tribu)` and so needs no judgement, and the 1853 "
        f"Pellissier, because it is the densest tribal annotation in the collection "
        f"and the earliest that is systematic. {len(placed_rows)} labels in total, "
        f"{len(inside)} of them inside modern Tunisia.")
    add("")
    add("**The two transcriptions do not cover the same ground.** The 1881 face was "
        "read whole, in 20 tiles. The 1853 was read over the Tell, the Kroumirie, the "
        "steppe and the Sahel down to about latitude 34 — the country the other sheet "
        "also labels — and the Jerid, the Nefzaoua and the Dahar were left unread, "
        "the Ouerghemma among them. So the label counts below are not a measure of "
        "how much each sheet annotates, and differencing them as coverage would be "
        "differencing my reading, not the maps.")
    add("")
    add("| Sheet | Labels | Marked `(Tribu)` | Control towns | In-sample RMS | Leave-one-out RMS |")
    add("| --- | --- | --- | --- | --- | --- |")
    for record_id, f in sorted(fits_by_map.items(), key=lambda kv: kv[1]["year"]):
        marked_here = sum(1 for r in placed_rows
                          if r["record_id"] == record_id and r["marked_tribe"] == "1")
        add(f"| {f['year']} {f['title'][:44]} | {f['labels']} | {marked_here} | "
            f"{f['control_points']} | {f['rms_px']} px ({f['rms_km']} km) | "
            f"{f['loo_rms_px']} px ({f['loo_rms_km']} km) |")
    add("")
    add("![Where two sheets put each tribe's name](img/tribal_territories.png)")
    add("")
    add("**How accurate is a point?** Two questions, and the smaller answer is the "
        "one people would misuse.")
    add("")
    add("Each transform is an affine fitted to towns whose modern coordinates are "
        "known, read off the sheet the same way the labels were. Leave-one-out RMS — "
        "the figure that applies to a label the fit never saw — is "
        f"{fits_by_map['btv1b84389986']['loo_rms_km']} km for 1881 and "
        f"{fits_by_map['btv1b53136235q']['loo_rms_km']} km for 1853. Each contains "
        "the compilation's own error and the error in reading a printed dot, and does "
        "not separate them. The 1853 sheet is drawn at 1:800 000 against the 1881 "
        "sheet's 1:1 200 000 and is nonetheless the less accurate of the two, which is "
        "what twenty-eight years of survey between them buys.")
    add("")
    add("Neither used the printed graticule, though both have one. On the 1881 sheet "
        "the scan carries a slight rotation and the frame is not square — the 8° tick "
        "on the top border and the 8° tick on the bottom border are 141 px apart in x "
        "— so a transform fitted to the border inherits the frame's skew. Towns do "
        "not have that problem.")
    add("")
    add("Where a town could *not* be found is a measurement too. On the 1853 sheet "
        "neither Gafsa nor Tozeur is within 300 px of where a fit on the other ten "
        "towns predicts it. The south-west is the part Pellissier had least survey "
        "for, and that is what the failure says.")
    add("")
    add("**The larger error is not positional at all.** Every name on the 1881 sheet "
        "has now been measured end to end: 62 of the 69 run **5.7 to 48.1 km of "
        "ground, median 16**, NEFZA the shortest and HANENCHAS the longest, in "
        "[`data/tribal_spread.csv`](../data/tribal_spread.csv). An earlier figure of "
        "14 to 32 km, quoted in this report and in the codebook, came from a sample "
        "of six and missed both ends. The point records where the name is *centred*, "
        "so it locates the tribe to within a tribe's width and no finer. On the 1881 "
        "sheet, reading the same label twice from two "
        "overlapping tiles agreed to 3–5 px and the two towns read twice agreed to 3 "
        "px. On the 1853 sheet the same check gives 80 px for HAMEMA, and MADJER — "
        "which runs along an arc of some 1500 px from Sbiba round to Djilma — had its "
        "letters read at three points 1000 px apart before they resolved into one "
        "name. A `(Tribu)` tag tells you where a label ends. Without one, nothing does.")
    add("")
    add("### Do the two sheets agree?")
    add("")
    add(f"This is the only external check available on either transcription. There is "
        f"no ground truth for where a tribe was, but two compilers working "
        f"twenty-eight years apart, one before the conquest and one during it, are "
        f"independent. **{summary_agree.get('tribes_on_two_sheets', 0)} tribes are "
        f"named on both sheets**, and the distance between the two placements has a "
        f"median of **{summary_agree.get('median_km', 0)} km** — about one label "
        f"length. {summary_agree.get('within_10_km', 0)} agree to within 10 km, "
        f"{summary_agree.get('within_20_km', 0)} to within 20 km. Full table in "
        f"[`data/tribal_map_agreement.csv`](../data/tribal_map_agreement.csv).")
    add("")
    add("| Tribe | 1853 prints | 1881 prints | Apart |")
    add("| --- | --- | --- | --- |")
    for pair in pairs_rows[:6]:
        add(f"| {pair['tribe']} | {pair['label_a']} | {pair['label_b']} | "
            f"{pair['distance_km']} km |")
    add("| … | | | |")
    for pair in pairs_rows[-3:]:
        add(f"| {pair['tribe']} | {pair['label_a']} | {pair['label_b']} | "
            f"{pair['distance_km']} km |")
    add("")
    add("The outlier is the finding. **Ouled Khiar sits 197 km apart** because the two "
        "sheets are not naming the same people: Pellissier's Oulad Khiar is east of "
        "Tunis below Zaghouan, and Lasailly's is in the Constantine province west of "
        "the frontier. Two groups, one name, and a gazetteer that matches on names "
        "merges them. It is left merged in the data, flagged here, because splitting "
        "it would be a claim about the tribes rather than about the maps. Riah, at 47 km, may be the "
        "same case: the 1853 sheet prints it in the Mogods behind Bizerte and the "
        "1881 sheet by Medjez el Bab. Mejers, at 44 km, is not — it is the MADJER arc, "
        "and the gap is the width of my uncertainty about where that label is centred, "
        "not a disagreement between the sheets.")
    add("")
    add("### Where the 1881 labels fall")
    add("")
    add("By modern gouvernorat, for the sheet whose face was read in full:")
    add("")
    add("| Gouvernorat | Labels |")
    add("| --- | --- |")
    for name, count in by_gov.most_common():
        add(f"| {name} | {count} |")
    outside_1881 = sum(1 for r in placed_rows
                       if r["record_id"] == "btv1b84389986" and r["inside_tunisia"] != "1")
    add(f"| *west of the frontier* | {outside_1881} |")
    add("")
    north_west = sum(by_gov[name] for name in ("Jendouba", "Béja", "Le Kef"))
    inside_1881 = sum(by_gov.values())
    add(f"The north-west carries the annotation and the south barely does. Jendouba, "
        f"Béja and Le Kef hold {north_west} of the {inside_1881} Tunisian labels "
        f"between them, while south of Sfax the entire country — the Jerid, the "
        f"Nefzaoua, the Dahar, the Matmata — carries exactly one, the Ouerghemma. "
        f"That is not a map of where tribes were. It is a map of where a French "
        f"compiler in 1881 had names for them, and 1881 is the year of the Kroumir "
        f"campaign in exactly that north-western corner. Over the same latitudes the "
        f"1853 sheet is less lopsided — its median label sits at 35.9°N against the "
        f"1881 sheet's 36.6°N, and seven of its labels fall south of 35°N against "
        f"four — though part of that is simply that Pellissier names the fractions "
        f"of the M'Talith and the Hamema where Lasailly names the parent.")
    add("")
    spread_path = REPO_ROOT / "data" / "tribal_spread_summary.json"
    if spread_path.exists():
        sp = json.loads(spread_path.read_text(encoding="utf-8"))
        add("## How much ground a name covers")
        add("")
        add("![How much ground a tribe's name covers, measured off the sheet]"
            "(img/tribal_spread.png)")
        add("")
        add("A tribe on these sheets is a name letterspaced across the country "
            "it holds. How far the engraver spread it is the only statement the "
            "map makes about extent, so that is the thing to measure, and three "
            "earlier attempts to draw a tribe's spread are recorded here because "
            "each supplied the number the map does not.")
        add("")
        add("| Drawn as | What went wrong |")
        add("| --- | --- |")
        add("| A dot per label | Exact, and silent about extent. |")
        add("| Administrative units, filled or sprinkled | Answers extent by "
            "inventing it, and confines a nineteenth-century tribe inside a 2022 "
            "mesh that stops at a frontier which did not exist. |")
        add("| A Gaussian blur of the labels | Looks measured and is not: the "
            "bandwidth was a choice, so every tribe came out the same size "
            "whatever the sheet said. |")
        add("")
        add("The third was the worst because it flattened the signal. OUERGAMA "
            "is letterspaced 1.7 times wider per letter than MEKENA, and that "
            "difference is the map speaking about two tribes of very different "
            "reach.")
        add("")
        add(f"**So the extents were measured.** Each label on the "
            f"{sp['sheet']} sheet was cropped from the full scan into a contact "
            f"strip with a pixel ruler under it and read end to end by eye. "
            f"**{sp['measured']} of {sp['labels']} labels** yielded a length; "
            f"{sp['unmeasured']} run into a sheet edge or into another name and "
            f"are left unmeasured. Every tribe is then drawn as a circle whose "
            f"diameter is that printed length.")
        add("")
        add(f"**Why a circle and not an ellipse.** The sheet states one number, "
            f"the length of the name along its baseline. The across-name "
            f"dimension appears nowhere on the map, so an ellipse would have to "
            f"invent it, which is the mistake the figure exists to stop making. "
            f"A circle adds no second parameter and no orientation. Nothing is "
            f"clipped either, so a circle crosses the modern frontier wherever "
            f"the name does.")
        add("")
        add("| | |")
        add("| --- | --- |")
        add(f"| Shortest name | {sp['narrowest']['tribe']} "
            f"(*{sp['narrowest']['printed']}*), {sp['narrowest']['km']} km |")
        add(f"| Longest | {sp['widest']['tribe']} "
            f"(*{sp['widest']['printed']}*), {sp['widest']['km']} km |")
        add(f"| Median | {sp['median_km']:.0f} km |")
        add(f"| Mean | {sp['mean_km']} km |")
        add("")
        add(f"**This corrects a figure quoted earlier in this repository.** A "
            f"sample of six labels had given 14 to 32 km, and that range was "
            f"repeated in the codebook and in two scripts. With "
            f"{sp['measured']} measured the true range is "
            f"{sp['min_km']:.0f} to {sp['max_km']:.0f} km and the median is "
            f"{sp['median_km']:.0f}, so the sample of six had missed the small "
            f"tribes at one end and the great frontier confederations at the "
            f"other. The Hanencha name runs 48 km of ground, the Nemencha 46, "
            f"the Ouled Sidi Abid 43; the Nefza name runs 6.")
        add("")
        add("Per-label results are in "
            "[`data/tribal_spread.csv`](../data/tribal_spread.csv).")
        add("")
        add("**What is not yet measured.** The 1853 Pellissier and 1965 Martel "
            "sheets. Both set their tribal names on long arcs and verticals "
            "rather than horizontal baselines, so the endpoints have to be read "
            "a different way; until that is done their labels appear on the "
            "figure as points and carry no circle. Saying so is cheaper than "
            "drawing them at a size nobody measured.")
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
    add("**Two maps transcribed, and one of them by judgement.** The 1853 Pellissier "
        "marks nothing: every label from it was classed as a tribe by eye, against a "
        "gazetteer built partly from that same reading, which is a shorter loop than "
        "anyone would like. Labels that could be villages — Oulad Amer, Oulad "
        "Khalifa, Taïfa — are held at medium confidence and flagged in the data. The "
        "1881 sheet needs none of that, and is why it is the reference.")
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
    pairs_rows: list[dict] = []
    pairs_path = args.data / "tribal_map_agreement.csv"
    if pairs_path.exists():
        pairs_rows = list(csv.DictReader(pairs_path.open(encoding="utf-8")))
    write_doc(rows, summary, inspected, fits, placed_rows, pairs_rows,
              args.docs / "TRIBES.md")

    print(f"{summary['records']} records coded")
    for key, value in summary["tribal_annotation"].items():
        print(f"  {key:12s} {value}")
    print(f"metadata tribe-name matches: {summary['records_with_tribe_name_in_metadata']}")
    print(f"inspected maps: {summary['inspected_maps']}, "
          f"with annotation: {summary['inspected_with_annotation']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

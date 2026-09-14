#!/usr/bin/env python3
"""Turn the reading of Ganiage's Annexe I into tables.

Input is config/ganiage_annexe1_read.json, which holds the 78 lines of the
mejba assessment table printed on p. 882 of Ganiage 1966, read off the page
image by eye.  This script does no reading of its own: it groups the lines by
the tribe Ganiage's footnotes assign them to, checks the group totals against
the figures he gives in the body of the article, and writes

    data/ganiage_mejba_1277.csv      one row per fiscal unit, 78 rows
    data/ganiage_mejba_groups.csv    one row per gazetteer tribe reached
    data/ganiage_mejba_summary.json  the arithmetic, including the discrepancy

and refreshes the Annexe I rows of data/tribal_population_sources.csv, leaving
every hand-entered row in that file alone.
"""

import csv
import json
import pathlib
import unicodedata
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "ganiage_annexe1_read.json"
GAZETTEER = ROOT / "config" / "tribal_gazetteer.json"
SOURCES = ROOT / "data" / "tribal_population_sources.csv"

SOURCE_LABEL = "Ganiage 1966, Annexe I (budget of 1277)"
URL = "https://www.persee.fr/doc/pop_0032-4663_1966_num_21_5_13406"

# What Ganiage says in the body of the article about the same groups, so that
# the taxpayer totals assembled here can be set against his own conversions.
# Figures are the midpoint he can be held to; the text is in the sources CSV.
STATED = {
    "Zlass": (60000, ">", "p. 878, more than 60.000"),
    "Hammama": (50000, "=", "p. 878, 50.000"),
    "Frechiche": (46500, "~", "p. 877-878, 46 or 47.000 in 1857, Ouled Sidi Tlil included"),
    "Mejers": (40000, "~", "p. 877, near 40.000"),
    "Drid": (50000, "~", "p. 877, near 50.000, Arab Majour included"),
    "M'Talith": (25000, ">", "p. 878, a little over 25.000"),
    "Ouled Ayar": (24000, "~", "p. 877, twice the Ouled Aoun"),
    "Souassi": (20000, "=", "p. 878, 20.000"),
    "Ouled Aoun": (12000, "~", "p. 877, a dozen thousand"),
}

# Ganiage's own rate, stated on p. 864 note 4.
GANIAGE_RATE = 4

# Ouled Yakoub is deliberately absent from STATED. Ganiage's 4 or 5.000 on
# p. 881 is the southern group, argued alongside the Ouerghamma and the Hamerna
# of the Aradh; the 863 taxpayers on the annexe line carry footnote 12, which
# puts that circumscription in the Ounifa league of the north-west. Two groups
# share the name. Dividing one by the other gave 5.21 individuals per taxpayer,
# the highest ratio in the table and the only one outside Ganiage's own rate of
# four; it was an artefact of the collision, and it is why the ratio is no
# longer computed for this tribe. Martel's 1881 sketch map, which prints OLED
# YACOUB in the Nefzaoua, is what made the collision visible.


def fold(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn"
    )


def gazetteer_names():
    tribes = json.loads(GAZETTEER.read_text())["tribes"]
    return {t["name"] for t in tribes}


def main():
    cfg = json.loads(CONFIG.read_text())
    lines = cfg["lines"]
    known = gazetteer_names()

    for line in lines:
        for name in [line["tribe"]] + line.get("also_gazetteer", []):
            if name and name not in known:
                raise SystemExit(f"attributed to a name the gazetteer does not hold: {name}")

    total = sum(line["taxpayers"] for line in lines)
    printed = cfg["_arithmetic"]["printed_total"]
    if total != cfg["_arithmetic"]["sum_of_printed_lines"]:
        raise SystemExit("config arithmetic block is stale")

    # One row per fiscal unit.
    out = ROOT / "data" / "ganiage_mejba_1277.csv"
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "order",
                "column",
                "name_as_printed",
                "taxpayers",
                "share_of_printed_total",
                "footnote",
                "footnote_text",
                "tribe",
                "attribution_basis",
                "also_gazetteer",
                "joint_line",
                "note",
            ]
        )
        for line in lines:
            fn = line["footnote"]
            w.writerow(
                [
                    line["order"],
                    line["column"],
                    line["name_as_printed"],
                    line["taxpayers"],
                    f"{line['taxpayers'] / printed:.4f}",
                    fn if fn else "",
                    cfg["footnotes"][str(fn)] if fn else "",
                    line["tribe"],
                    line["attribution_basis"],
                    " | ".join(line.get("also_gazetteer", [])),
                    1 if line.get("joint") else "",
                    line.get("note", ""),
                ]
            )

    # One row per gazetteer tribe the annexe reaches.
    groups = defaultdict(list)
    for line in lines:
        if line["tribe"]:
            groups[line["tribe"]].append(line)

    grows = []
    for tribe, members in sorted(groups.items(), key=lambda kv: -sum(m["taxpayers"] for m in kv[1])):
        tp = sum(m["taxpayers"] for m in members)
        stated, qual, where = STATED.get(tribe, ("", "", ""))
        grows.append(
            {
                "tribe": tribe,
                "taxpayers_1277": tp,
                "fiscal_units": len(members),
                "units": " | ".join(m["name_as_printed"] for m in members),
                "attribution_basis": members[0]["attribution_basis"],
                "ganiage_individuals": stated,
                "ganiage_qualifier": qual,
                "ganiage_where": where,
                "implied_per_taxpayer": f"{stated / tp:.2f}" if stated else "",
                "at_ganiage_rate_of_4": tp * GANIAGE_RATE,
            }
        )

    with (ROOT / "data" / "ganiage_mejba_groups.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(grows[0].keys()))
        w.writeheader()
        w.writerows(grows)

    ratios = [float(r["implied_per_taxpayer"]) for r in grows if r["implied_per_taxpayer"]]
    summary = {
        "_about": cfg["_about"],
        "lines": len(lines),
        "sum_of_printed_lines": total,
        "printed_total": printed,
        "difference": printed - total,
        "difference_pct": round(100 * (printed - total) / printed, 2),
        "_difference_comment": cfg["_arithmetic"]["_comment"],
        "lines_attributed_to_a_gazetteer_tribe": sum(1 for line in lines if line["tribe"]),
        "gazetteer_tribes_reached": len(groups),
        "gazetteer_fractions_reached": sum(
            len(line.get("also_gazetteer", [])) for line in lines
        ),
        "taxpayers_in_attributed_lines": sum(sum(m["taxpayers"] for m in v) for v in groups.values()),
        "largest_line": max(lines, key=lambda x: x["taxpayers"])["name_as_printed"],
        "smallest_line": min(lines, key=lambda x: x["taxpayers"])["name_as_printed"],
        "ganiage_stated_rate": GANIAGE_RATE,
        "implied_rate_from_his_own_tribe_figures": {
            "n": len(ratios),
            "min": min(ratios),
            "median": sorted(ratios)[len(ratios) // 2],
            "max": max(ratios),
        },
        "printed_total_at_his_rate": printed * GANIAGE_RATE,
        "his_estimate_for_the_regency": 1100000,
        "_coverage_comment": (
            "221.664 taxpayers at his own rate of four give 886.656, against the 1.100.000 he "
            "puts on the Regency. The gap is in the annexe, not in the arithmetic: he says on "
            "p. 864 that the 1277 table leaves out the mass of exemptions and that his documents "
            "tell him nothing about the Kroumirs nor about Tunis, Kairouan and Sfax, to which he "
            "allots 110.000 between them. The annexe is a tax roll, and a tax roll is a list of "
            "who paid."
        ),
    }
    (ROOT / "data" / "ganiage_mejba_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )

    # Refresh the Annexe I rows of the population sources file, in place.
    with SOURCES.open() as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        kept = [r for r in reader if r["source"] != SOURCE_LABEL]

    new = []
    for r in grows:
        members = groups[r["tribe"]]
        if len(members) == 1:
            quote = f"{members[0]['name_as_printed']} {members[0]['taxpayers']:,}".replace(",", ".")
        else:
            quote = "; ".join(
                f"{m['name_as_printed']} {m['taxpayers']:,}".replace(",", ".") for m in members
            )
        basis = (
            "Ganiage's footnote ties these fiscal units to the tribe."
            if r["attribution_basis"] == "footnote"
            else "The fiscal unit is printed under the tribe's own name."
        )
        note = basis
        if r["tribe"] == "Ouled Yakoub":
            note += (
                " Footnote 12 puts this circumscription in the Ounifa league of "
                "the north-west. It is not the Ouled Yacoub of p. 881, whom "
                "Ganiage argues alongside the Ouerghamma of the Aradh and whom "
                "Martel's 1881 map prints in the Nefzaoua: two groups, one name, "
                "and no ratio is taken between them."
            )
        if r["ganiage_individuals"]:
            stated = f"{r['ganiage_individuals']:,}".replace(",", ".")
            note += (
                f" He puts the tribe at {r['ganiage_qualifier']}{stated} individuals"
                f" ({r['ganiage_where']}), which is {r['implied_per_taxpayer']} per taxpayer."
            )
        new.append(
            {
                "tribe": r["tribe"],
                "label_in_source": members[0]["name_as_printed"] if len(members) == 1 else " + ".join(
                    m["name_as_printed"] for m in members
                ),
                "year": 1861,
                "source": SOURCE_LABEL,
                "figure": r["taxpayers_1277"],
                "unit": "mejba taxpayers",
                "page": 882,
                "quote": quote,
                "url": URL,
                "note": note,
                "in_gazetteer": 1,
            }
        )

    # Lines that name a gazetteer entry finer than the tribe get their own row,
    # so that a fraction with a number is not hidden inside its tribe's total.
    for line in lines:
        for name in line.get("also_gazetteer", []):
            joint = line.get("joint")
            figure = f"{line['taxpayers']} (the pair)" if joint else line["taxpayers"]
            note = "Assessed on its own line in the annexe."
            if joint:
                others = [n for n in line["also_gazetteer"] if n != name]
                note = (
                    f"Assessed on one line with {' and '.join(others)}. The figure is the pair's, "
                    "not this tribe's, and the annexe does not split it."
                )
            if line["tribe"]:
                note += f" The line sits under the {line['tribe']} in Ganiage's footnote."
            new.append(
                {
                    "tribe": name,
                    "label_in_source": line["name_as_printed"],
                    "year": 1861,
                    "source": SOURCE_LABEL,
                    "figure": figure,
                    "unit": "mejba taxpayers",
                    "page": 882,
                    "quote": f"{line['name_as_printed']} {line['taxpayers']:,}".replace(",", "."),
                    "url": URL,
                    "note": note,
                    "in_gazetteer": 1,
                }
            )

    with SOURCES.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(kept + new)

    print(f"{len(lines)} fiscal units, {total:,} taxpayers on the lines, {printed:,} printed")
    print(f"discrepancy {printed - total:,} ({summary['difference_pct']}%)")
    print(f"{len(groups)} gazetteer tribes reached, {len(new)} rows written to the sources file")
    print(
        "implied individuals per taxpayer: "
        f"{min(ratios):.2f} to {max(ratios):.2f}, median {sorted(ratios)[len(ratios)//2]:.2f}"
    )


if __name__ == "__main__":
    main()

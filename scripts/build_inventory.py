#!/usr/bin/env python3
"""Render the harvested Gallica records as a browsable Markdown inventory.

Reads data/gallica_tunisia_maps.json (produced by harvest_gallica_maps.py) and
writes docs/INVENTORY.md, grouped by century and sorted chronologically.

Usage:
    python3 scripts/build_inventory.py
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CONFIDENCE_RANK = {"high": 0, "medium": 1, "unverified": 2, "low": 3}


def century_key(century: str) -> int:
    if not century:
        return 99
    digits = "".join(c for c in century if c.isdigit())
    return int(digits) if digits else 99


def escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def date_label(record: dict) -> str:
    if record["year"]:
        return record["year"]
    earliest, latest = record["year_earliest"], record["year_latest"]
    if earliest and latest and earliest != latest:
        return f"{earliest}–{latest}"
    return earliest or "n.d."


def short(text: str, width: int) -> str:
    text = escape(text)
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def render(records: list[dict], summary: dict) -> str:
    by_century: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_century[record["century"] or "Undated / spanning centuries"].append(record)

    lines = [
        "# Tunisia maps in Gallica — inventory",
        "",
        f"{summary['unique_records']} distinct cartographic records "
        f"({summary['earliest_year']}–{summary['latest_year']}), harvested "
        f"{summary['harvested_at']} from the Gallica SRU API.",
        "",
        "Records are grouped by century and sorted chronologically. `Conf.` is the",
        "Tunisia-relevance confidence described in [METHODOLOGY.md](METHODOLOGY.md);",
        "`low` rows are probable false positives from toponyms that also exist",
        "outside Tunisia and are listed last for review.",
        "",
        "Source data: [`data/gallica_tunisia_maps.csv`](../data/gallica_tunisia_maps.csv)",
        "and [`data/gallica_tunisia_maps.json`](../data/gallica_tunisia_maps.json).",
        "",
        "## Contents",
        "",
    ]

    ordered = sorted(by_century.items(), key=lambda kv: century_key(kv[0]))
    for century, group in ordered:
        anchor = century.lower().replace(" ", "-").replace(".", "").replace("/", "")
        lines.append(f"- [{century}](#{anchor}) — {len(group)} records")
    lines.append("")

    for century, group in ordered:
        lines.append(f"## {century}")
        lines.append("")
        lines.append("| Date | Title | Author / engraver | Scale | Conf. | Link |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        # Likely false positives sink to the bottom of each century group.
        group.sort(key=lambda r: (CONFIDENCE_RANK[r["confidence"]],
                                  int(r["year_earliest"] or 9999),
                                  r["title"].lower()))
        for record in group:
            link = f"[view]({record['url']})" if record["url"] else "—"
            lines.append(
                f"| {date_label(record)} "
                f"| {short(record['title'], 95)} "
                f"| {short(record['creators'], 45) or '—'} "
                f"| {record['scale'] or '—'} "
                f"| {record['confidence']} "
                f"| {link} |"
            )
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=REPO_ROOT / "data" / "gallica_tunisia_maps.json")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "INVENTORY.md")
    args = parser.parse_args()

    payload = json.loads(args.data.read_text(encoding="utf-8"))
    records = payload["records"]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(records, payload["summary"]), encoding="utf-8")
    print(f"wrote {args.out} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

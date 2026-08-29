#!/usr/bin/env python3
"""Harvest Tunisia-related cartographic records from Gallica (BnF) via its SRU API.

The script runs every query in config/queries.json against the Gallica SRU
endpoint, ANDed with a document-type filter so only cartographic material comes
back, then deduplicates records by ARK identifier, scores how confidently each
record is about Tunisia, and writes a CSV + JSON inventory.

Usage:
    python3 scripts/harvest_gallica_maps.py
    python3 scripts/harvest_gallica_maps.py --limit 100 --out-dir data

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SRU_ENDPOINT = "https://gallica.bnf.fr/SRU"
PAGE_SIZE = 50  # Gallica caps maximumRecords at 50
# Gallica returns 403 to clients that do not present a browser-like user agent.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

NS = {
    "srw": "http://www.loc.gov/zing/srw/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}

REPO_ROOT = Path(__file__).resolve().parent.parent

# Toponyms that identify Tunisia on their own. Used to promote a record to
# "high" confidence even when the metadata never spells out "Tunisie".
TUNISIA_SIGNALS = (
    "tunis",  # covers tunis, tunisie, tunisia, tunisien, tunisiens
    "carthage",
    "ifriqiya",
    "kairouan",
    "bizerte",
    "ferryville",
    "sfax",
    "sousse",
    "djerba",
    "jerba",
    "kerkennah",
    "goulette",
    "ghar el melh",
    "zaghouan",
    "khroumirie",
    "kroumirie",
    "tabarka",
    "gafsa",
    "tozeur",
    "kebili",
    "medenine",
    "tataouine",
    "zarzis",
    "kasserine",
    "nabeul",
    "hammamet",
    "kelibia",
    "utique",
    "dougga",
    "sbeitla",
    "thysdrus",
    "byzacene",
    "proconsulaire",
    "matmata",
    "jendouba",
    "gabes",
)

# Weaker signals: the record covers a region that contains Tunisia, so it is
# plausibly relevant but not Tunisia-specific.
REGIONAL_SIGNALS = (
    "afrique du nord",
    "afrique septentrionale",
    "maghreb",
    "barbarie",
    "berberie",
    "mediterranee",
    "algerie",
    "tripolitaine",
    "libye",
    "numidie",
)

SCALE_RE = re.compile(r"1\s*[:/]\s*([\d\s .,]+)")
YEAR_RE = re.compile(r"(1[0-9]{3}|20[0-2][0-9])")
# Gallica expresses imprecise dates as truncated numerals: '17..' means the 18th
# century, '188.' the 1880s, '16..-17..' a range spanning two centuries.
PARTIAL_DATE_RE = re.compile(r"^(\d{1,4})[.\s]*$")


def ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def normalize(text: str) -> str:
    """Lowercase and strip diacritics so 'Régence' matches 'regence'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def fetch(url: str, retries: int = 4, timeout: int = 60) -> bytes:
    """GET a URL, retrying with exponential backoff on transient failures."""
    delay = 2.0
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt == retries:
                break
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def build_url(query: str, start_record: int, maximum_records: int) -> str:
    params = {
        "operation": "searchRetrieve",
        "version": "1.2",
        "query": query,
        "startRecord": start_record,
        "maximumRecords": maximum_records,
    }
    return f"{SRU_ENDPOINT}?{urllib.parse.urlencode(params)}"


def text_values(record: ET.Element, tag: str) -> list[str]:
    values = []
    for node in record.findall(f".//dc:{tag}", NS):
        if node.text and node.text.strip():
            values.append(node.text.strip())
    return values


def extra(record: ET.Element, tag: str) -> str:
    node = record.find(f"./srw:extraRecordData/{tag}", NS)
    if node is None:
        node = record.find(f".//{tag}")
    return (node.text or "").strip() if node is not None and node.text else ""


def parse_scale(descriptions: list[str]) -> str:
    """Pull the map scale out of the 'Échelle(s) : 1:100 000' description field."""
    for description in descriptions:
        match = SCALE_RE.search(description)
        if match:
            denominator = re.sub(r"[^\d]", "", match.group(1))
            if denominator:
                return f"1:{int(denominator):,}".replace(",", " ")
    return ""


def parse_year(dates: list[str]) -> str:
    """Exact publication year, when the record states one."""
    for date in dates:
        match = YEAR_RE.search(date)
        if match:
            return match.group(1)
    return ""


def _bounds(token: str) -> tuple[int, int] | None:
    """Lower and upper year bound for a single Gallica date token."""
    token = token.strip()
    match = YEAR_RE.fullmatch(token)
    if match:
        year = int(match.group(1))
        return year, year
    match = PARTIAL_DATE_RE.match(token)
    if match:
        digits = match.group(1)
        # A single leading digit ('1...') is too vague to place in a century, and
        # a token not starting with 1 or 2 is a month/day fragment, not a year.
        if len(digits) < 2 or digits[0] not in "12":
            return None
        span = 10 ** (4 - len(digits))
        low = int(digits) * span
        return low, low + span - 1
    return None


def parse_date_bounds(dates: list[str]) -> tuple[str, str, str]:
    """Return (year_earliest, year_latest, century) from Gallica's date strings.

    Handles exact years ('1888'), truncated ones ('17..', '188.') and ranges
    ('16..-17..'). Century is only assigned when both bounds sit in the same one.
    """
    for date in dates:
        date = date.strip().strip("[]")
        # An ISO timestamp is a single exact date, not a range of three numbers.
        iso = re.fullmatch(r"(\d{4})-\d{2}-\d{2}", date)
        if iso:
            year = int(iso.group(1))
            return str(year), str(year), ordinal(year // 100 + 1) + " c."
        tokens = [t for t in re.split(r"\s*[-/]\s*", date) if t]
        parsed = [b for b in (_bounds(t) for t in tokens) if b]
        if not parsed:
            continue
        low = min(b[0] for b in parsed)
        high = max(b[1] for b in parsed)
        low_century = low // 100 + 1
        high_century = high // 100 + 1
        century = ordinal(low_century) + " c." if low_century == high_century else ""
        return str(low), str(high), century
    return "", "", ""


def parse_views(formats: list[str]) -> str:
    for value in formats:
        match = re.search(r"Nombre total de vues\s*:\s*(\d+)", value)
        if match:
            return match.group(1)
    return ""


def parse_record(record: ET.Element) -> dict | None:
    record_id = extra(record, "uri")
    if not record_id:
        for identifier in text_values(record, "identifier"):
            if "ark:/12148/" in identifier:
                record_id = identifier.rsplit("/", 1)[-1]
                break
    if not record_id:
        return None

    titles = text_values(record, "title")
    dates = text_values(record, "date")
    formats = text_values(record, "format")
    descriptions = text_values(record, "description")
    identifiers = text_values(record, "identifier")
    relations = text_values(record, "relation")

    catalogue = next((r.split("Notice du catalogue : ")[-1] for r in relations
                      if "catalogue.bnf.fr" in r), "")
    date_bounds = parse_date_bounds(dates)

    # Gallica also indexes partner libraries harvested over OAI. Those records use
    # an 'oai:...' id and live on the partner's own site, so an ARK URL cannot be
    # reconstructed for them — use the link the record supplies instead.
    is_bnf_ark = not record_id.startswith("oai:")
    link = extra(record, "link")
    if not link:
        link = next((i for i in identifiers if i.startswith("http")), "")
    if not link and is_bnf_ark:
        link = f"https://gallica.bnf.fr/ark:/12148/{record_id}"

    thumbnail = extra(record, "thumbnail")
    if not thumbnail and is_bnf_ark:
        thumbnail = f"https://gallica.bnf.fr/ark:/12148/{record_id}.thumbnail"

    return {
        "record_id": record_id,
        "url": link,
        "iiif_manifest": (
            f"https://gallica.bnf.fr/iiif/ark:/12148/{record_id}/manifest.json"
            if is_bnf_ark else ""
        ),
        "provenance": extra(record, "provenance") or "Gallica",
        "title": titles[0] if titles else "",
        "alt_titles": " | ".join(titles[1:]),
        "creators": " | ".join(text_values(record, "creator")),
        "date": " | ".join(dates),
        "year": parse_year(dates),
        "year_earliest": date_bounds[0],
        "year_latest": date_bounds[1],
        "century": date_bounds[2],
        "scale": parse_scale(descriptions),
        "publisher": " | ".join(text_values(record, "publisher")),
        "language": " | ".join(text_values(record, "language")),
        "subjects": " | ".join(text_values(record, "subject")),
        "coverage": " | ".join(text_values(record, "coverage")),
        "description": " | ".join(descriptions),
        "physical_description": " | ".join(
            f for f in formats
            if not f.startswith("image/") and "Nombre total de vues" not in f
        ),
        "views": parse_views(formats),
        "holding": " | ".join(text_values(record, "source")),
        "rights": " | ".join(text_values(record, "rights")),
        "doc_type": " | ".join(text_values(record, "type")),
        "gallica_typedoc": extra(record, "typedoc"),
        "catalogue_notice": catalogue,
        "thumbnail": thumbnail,
        "internal_id": next((i for i in identifiers if i.startswith("IFN-")), ""),
    }


def score_confidence(record: dict, only_ambiguous_matches: bool) -> tuple[str, str]:
    """Return (confidence, matched_signal) for a harvested record.

    high   - a Tunisia-specific toponym appears in title/subject/coverage
    medium - the toponym appears only in secondary fields, or the record covers
             a wider region (North Africa, Barbary, the Mediterranean)
    low    - matched only by a toponym that also exists outside Tunisia, with no
             corroborating Tunisian signal anywhere in the metadata
    """
    primary = normalize(" ".join(
        (record["title"], record["alt_titles"], record["subjects"], record["coverage"])
    ))
    secondary = normalize(" ".join(
        (record["description"], record["publisher"], record["holding"], record["creators"])
    ))

    for signal in TUNISIA_SIGNALS:
        if signal in primary:
            return "high", signal
    for signal in TUNISIA_SIGNALS:
        if signal in secondary:
            return "medium", signal
    for signal in REGIONAL_SIGNALS:
        if signal in primary:
            return "medium", signal
    if only_ambiguous_matches:
        return "low", ""
    return "medium", ""


def harvest(config: dict, limit_per_query: int | None, pause: float) -> dict[str, dict]:
    type_filter = config["type_filter"]
    records: dict[str, dict] = {}

    for spec in config["queries"]:
        term, index = spec["term"], spec["index"]
        # 'all' ANDs the words anywhere in the record, which is far too loose for
        # multi-word toponyms ('cap bon' matched 398 records that merely contained
        # both words). 'adj' is Gallica's phrase operator; use it whenever the term
        # has more than one word.
        operator = spec.get("op") or ("adj" if " " in term.strip() else "all")
        query = f'({type_filter}) and ({index} {operator} "{term}")'
        start, total, seen = 1, None, 0

        while True:
            page_size = PAGE_SIZE
            if limit_per_query is not None:
                page_size = min(page_size, limit_per_query - seen)
                if page_size <= 0:
                    break
            payload = fetch(build_url(query, start, page_size))
            root = ET.fromstring(payload)

            diagnostic = root.find(".//{http://www.loc.gov/zing/srw/diagnostic/}message")
            if diagnostic is not None:
                print(f"  ! SRU diagnostic for {term!r}: {diagnostic.text}", file=sys.stderr)
                break

            if total is None:
                node = root.find("./srw:numberOfRecords", NS)
                total = int(node.text) if node is not None and node.text else 0
                print(f"  {term:<22} [{index:<10} {operator:<3}] {total:>5} records")

            page = root.findall(".//srw:record", NS)
            if not page:
                break

            for node in page:
                parsed = parse_record(node)
                if parsed is None:
                    continue
                existing = records.get(parsed["record_id"])
                if existing is None:
                    parsed["matched_queries"] = []
                    parsed["matched_labels"] = []
                    parsed["_ambiguous_only"] = True
                    records[parsed["record_id"]] = parsed
                    existing = parsed
                if term not in existing["matched_queries"]:
                    existing["matched_queries"].append(term)
                if spec["label"] not in existing["matched_labels"]:
                    existing["matched_labels"].append(spec["label"])
                if not spec["ambiguous"]:
                    existing["_ambiguous_only"] = False

            seen += len(page)
            start += len(page)
            if start > total or (limit_per_query is not None and seen >= limit_per_query):
                break
            time.sleep(pause)

        time.sleep(pause)

    return records


def finalize(records: dict[str, dict]) -> list[dict]:
    rows = []
    for record in records.values():
        ambiguous_only = record.pop("_ambiguous_only")
        confidence, signal = score_confidence(record, ambiguous_only)
        record["confidence"] = confidence
        record["matched_signal"] = signal
        record["matched_queries"] = " | ".join(sorted(record["matched_queries"]))
        record["matched_labels"] = " | ".join(sorted(record["matched_labels"]))
        rows.append(record)

    rows.sort(key=lambda r: (int(r["year_earliest"] or 9999), normalize(r["title"])))
    return rows


FIELDS = [
    "record_id", "title", "year", "year_earliest", "year_latest", "century",
    "date", "creators", "publisher", "scale",
    "physical_description", "views", "subjects", "coverage", "description",
    "language", "holding", "rights", "doc_type", "gallica_typedoc",
    "confidence", "matched_signal", "matched_labels", "matched_queries",
    "url", "iiif_manifest", "provenance", "thumbnail", "catalogue_notice",
    "alt_titles", "internal_id",
]


def write_outputs(rows: list[dict], out_dir: Path, config: dict) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "gallica_tunisia_maps.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    by_confidence = Counter(r["confidence"] for r in rows)
    by_century = Counter(r["century"] or "undated / spans centuries" for r in rows)
    by_typedoc = Counter(r["gallica_typedoc"] or "unknown" for r in rows)
    by_label = Counter(
        label for r in rows for label in r["matched_labels"].split(" | ") if label
    )
    century_order = {c: i for i, c in enumerate(
        [f"{ordinal(n)} c." for n in range(1, 22)] + ["undated / spans centuries"]
    )}

    summary = {
        "harvested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endpoint": SRU_ENDPOINT,
        "type_filter": config["type_filter"],
        "queries_run": len(config["queries"]),
        "unique_records": len(rows),
        "by_confidence": dict(by_confidence.most_common()),
        "by_century": dict(sorted(by_century.items(),
                                  key=lambda kv: century_order.get(kv[0], 99))),
        "by_theme": dict(by_label.most_common()),
        "by_typedoc": dict(by_typedoc.most_common()),
        "earliest_year": min((int(r["year_earliest"]) for r in rows if r["year_earliest"]),
                             default=None),
        "latest_year": max((int(r["year_latest"]) for r in rows if r["year_latest"]),
                           default=None),
        "undated": sum(1 for r in rows if not r["year_earliest"]),
        "with_scale": sum(1 for r in rows if r["scale"]),
        "public_domain": sum(1 for r in rows if "domaine public" in r["rights"]),
    }

    json_path = out_dir / "gallica_tunisia_maps.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "records": rows}, handle,
                  ensure_ascii=False, indent=2)

    summary_path = out_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "queries.json")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap records fetched per query (for quick test runs)")
    parser.add_argument("--pause", type=float, default=0.4,
                        help="seconds to wait between SRU calls")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    print(f"Harvesting {len(config['queries'])} queries from {SRU_ENDPOINT}")

    records = harvest(config, args.limit, args.pause)
    rows = finalize(records)
    summary = write_outputs(rows, args.out_dir, config)

    print(f"\n{summary['unique_records']} unique records -> {args.out_dir}")
    print(f"  confidence: {summary['by_confidence']}")
    print(f"  span:       {summary['earliest_year']}-{summary['latest_year']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

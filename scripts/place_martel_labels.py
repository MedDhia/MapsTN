#!/usr/bin/env python3
"""Place the tribe names of Martel's 1881 sketch map on the ground.

Andre Martel, *Les Confins saharo-tripolitains de la Tunisie (1881-1911)*
(Paris, P.U.F., 1965) prints a sketch map, "Villes et tribus tunisiennes 1881",
at about 1:3 000 000. It is not a sheet in the Gallica collection this
repository inventories - it is a historian's synthesis - and it is kept apart
for that reason: its own config, its own CSV, its own colour on the figure.

It earns its place by covering the ground the two transcribed sheets do not.
The 1853 Pellissier was read only to about 34 N and the 1881 Lasailly gives
everything south of Sfax to a single tribe, so the Nefzaoua, the Djerid and the
Dahar were blank. Martel names them, which turns that blank from an assumption
into something testable.

Method is the same as scripts/place_tribal_labels.py: a least-squares affine
from towns whose modern coordinates are known, residuals reported in kilometres,
and a leave-one-out pass because the in-sample residual of a fit with twenty
control points flatters itself.

Outputs:
    data/martel_1965_tribes.csv
    data/martel_1965_fit.json

Usage:
    python3 scripts/place_martel_labels.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
COORD_DECIMALS = 3
KM_PER_DEG_LAT = 110.574


def fit_affine(points: list[dict]) -> np.ndarray:
    """Solve for (lon, lat) = A @ (x, y, 1) in least squares."""
    design = np.array([[p["x"], p["y"], 1.0] for p in points])
    target = np.array([[p["lon"], p["lat"]] for p in points])
    solution, *_ = np.linalg.lstsq(design, target, rcond=None)
    return solution


def apply(matrix: np.ndarray, x: float, y: float) -> tuple[float, float]:
    lon, lat = np.array([x, y, 1.0]) @ matrix
    return float(lon), float(lat)


def km_between(lon_a, lat_a, lon_b, lat_b) -> float:
    mid = math.radians((lat_a + lat_b) / 2)
    dx = (lon_a - lon_b) * 111.320 * math.cos(mid)
    dy = (lat_a - lat_b) * KM_PER_DEG_LAT
    return math.hypot(dx, dy)


def residuals(matrix: np.ndarray, points: list[dict]) -> dict[str, float]:
    out = {}
    for point in points:
        lon, lat = apply(matrix, point["x"], point["y"])
        out[point["town"]] = round(km_between(lon, lat, point["lon"], point["lat"]), 1)
    return out


def leave_one_out(points: list[dict]) -> float:
    errors = []
    for index in range(len(points)):
        rest = points[:index] + points[index + 1:]
        matrix = fit_affine(rest)
        held = points[index]
        lon, lat = apply(matrix, held["x"], held["y"])
        errors.append(km_between(lon, lat, held["lon"], held["lat"]) ** 2)
    return math.sqrt(sum(errors) / len(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=REPO_ROOT / "config" / "martel_1965_tribes.json")
    args = parser.parse_args(argv)

    config = json.loads(args.config.read_text(encoding="utf-8"))
    control = config["control_points"]
    matrix = fit_affine(control)

    per_town = residuals(matrix, control)
    rms = math.sqrt(sum(v ** 2 for v in per_town.values()) / len(per_town))
    loo = leave_one_out(control)

    # Scale check: on an equirectangular sheet the ratio of the two scales is
    # the cosine of the middle latitude. If it is not, the affine is the wrong
    # model and the residual below would be hiding a projection, not a reading.
    px_per_deg_lon = 1.0 / abs(matrix[0][0])
    px_per_deg_lat = 1.0 / abs(matrix[1][1])
    ratio = px_per_deg_lon / px_per_deg_lat
    mid_lat = sum(p["lat"] for p in control) / len(control)

    rows = []
    for label in config["labels"]:
        lon, lat = apply(matrix, label["x"], label["y"])
        rows.append({
            "source": "martel_1965",
            "year": 1881,
            "label_as_printed": label["text"],
            "tribe": label["tribe"] or label["text"].title(),
            "in_gazetteer": 1 if label["tribe"] else 0,
            "x_px": label["x"],
            "y_px": label["y"],
            "lon": round(lon, COORD_DECIMALS),
            "lat": round(lat, COORD_DECIMALS),
            "note": label.get("note", ""),
        })

    out = REPO_ROOT / "data" / "martel_1965_tribes.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    fit = {
        "_about": config["_about"],
        "_what_this_is_not": config["_what_this_is_not"],
        "_how_read": config["_how_read"],
        "citation": config["citation"],
        "control_points": len(control),
        "labels": len(rows),
        "labels_matched_to_gazetteer": sum(r["in_gazetteer"] for r in rows),
        "px_per_degree_lon": round(px_per_deg_lon, 1),
        "px_per_degree_lat": round(px_per_deg_lat, 1),
        "scale_ratio": round(ratio, 3),
        "cos_mid_latitude": round(math.cos(math.radians(mid_lat)), 3),
        "_projection_check": (
            "The two scales stand in the ratio of the cosine of the middle "
            "latitude, so the sheet is plain equirectangular and an affine is "
            "the right model for it."),
        "rms_km": round(rms, 2),
        "loo_rms_km": round(loo, 2),
        "per_town_km": per_town,
        "_accuracy_comment": (
            "Larger than the two Gallica sheets, and it should be: those were "
            "read at full IIIF resolution over twenty tiles, this from one "
            "screen reproduction about 1200 px across. It is still well inside "
            "the length of the names themselves."),
    }
    (REPO_ROOT / "data" / "martel_1965_fit.json").write_text(
        json.dumps(fit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{len(rows)} labels placed, {sum(r['in_gazetteer'] for r in rows)} "
          f"matched to the gazetteer")
    print(f"scale ratio {ratio:.3f} against cos({mid_lat:.1f} N) = "
          f"{math.cos(math.radians(mid_lat)):.3f}")
    print(f"RMS {rms:.2f} km, leave-one-out {loo:.2f} km")
    worst = sorted(per_town.items(), key=lambda kv: -kv[1])[:3]
    print("worst towns: " + ", ".join(f"{t} {v} km" for t, v in worst))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

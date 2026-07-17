from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path


SKIN_COLUMNS = ("Head", "Chest", "Forearm", "Hand", "Thigh", "Calf", "Foot")


def mean_skin(row: dict[str, float]) -> float:
    return (
        0.07 * row["Head"] + 0.35 * row["Chest"] + 0.14 * row["Forearm"]
        + 0.05 * row["Hand"] + 0.19 * row["Thigh"] + 0.13 * row["Calf"]
        + 0.07 * row["Foot"]
    )


def read_experiment_csv(path: Path, start: datetime | None = None) -> list[dict]:
    start = start or datetime(2026, 7, 15, 10, 0, tzinfo=timezone(timedelta(hours=8)))
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = set(SKIN_COLUMNS) | {"HR"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}缺少列: {sorted(missing)}")
        for index, raw in enumerate(reader):
            row = {key: float(raw[key]) for key in SKIN_COLUMNS}
            row["HR"] = float(raw["HR"])
            row["MeanSkin"] = float(raw["MeanSkin"]) if raw.get("MeanSkin") else mean_skin(row)
            row["CoreTruth"] = float(raw["Core"]) if raw.get("Core") else None
            row["timestamp"] = start + timedelta(minutes=index)
            rows.append(row)
    return rows


def watch_payload(row: dict, include_skin: bool = False) -> dict:
    payload = {
        "heart_rate": round(row["HR"]),
        "timestamp": row["timestamp"].isoformat(),
    }
    if include_skin:
        payload.update({
            "skin_temperature": row["Hand"],
            "skin_temperatures": {key.lower(): row[key] for key in SKIN_COLUMNS},
        })
    return payload


def column_stats(directory: Path, columns: list[str]) -> tuple[list[float], list[float]]:
    sums = [0.0] * len(columns)
    squares = [0.0] * len(columns)
    count = 0
    files = sorted(directory.glob("*.csv"))
    if not files:
        raise ValueError(f"参考目录没有CSV: {directory}")
    for path in files:
        rows = read_experiment_csv(path)
        # Kalman_Result must follow the notebook, not an arbitrary saved column.
        from kalman import kalman_filter
        initial = rows[0]["CoreTruth"] if rows[0]["CoreTruth"] is not None else 37.0
        kalman = kalman_filter([row["HR"] for row in rows], initial)
        for row, estimate in zip(rows, kalman):
            row["Kalman_Result"] = estimate
            row["Core"] = row["CoreTruth"]
            values = [float(row[column]) for column in columns]
            if any(not math.isfinite(value) for value in values):
                continue
            count += 1
            for i, value in enumerate(values):
                sums[i] += value
                squares[i] += value * value
    means = [value / count for value in sums]
    stds = [math.sqrt(max(0.0, squares[i] / count - means[i] ** 2)) for i in range(len(columns))]
    return means, stds


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)

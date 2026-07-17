#!/usr/bin/env python3
"""Export the exact population mean/std expected by the project loaders."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def stats(root: Path, columns: list[str]) -> tuple[list[float], list[float], int]:
    count = 0
    sums = [0.0] * len(columns)
    square_sums = [0.0] * len(columns)
    files = sorted(root.glob("*.csv"))
    if not files:
        raise SystemExit(f"no CSV files found in {root}")
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = set(columns) - set(reader.fieldnames or [])
            if missing:
                raise SystemExit(f"{path} misses columns: {sorted(missing)}")
            for row in reader:
                values = [float(row[column]) for column in columns]
                if any(not math.isfinite(value) for value in values):
                    continue
                count += 1
                for index, value in enumerate(values):
                    sums[index] += value
                    square_sums[index] += value * value
    if not count:
        raise SystemExit("no valid numeric rows")
    means = [value / count for value in sums]
    stds = [math.sqrt(max(0.0, square_sums[i] / count - means[i] ** 2)) for i in range(len(columns))]
    if any(value == 0 for value in stds):
        raise SystemExit("at least one column has zero standard deviation")
    return means, stds, count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-dir", required=True, type=Path)
    parser.add_argument("--features", required=True, help="comma-separated, exact model order")
    parser.add_argument("--target", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    features = [item.strip() for item in args.features.split(",") if item.strip()]
    x_mean, x_std, x_count = stats(args.train_dir, features)
    y_mean, y_std, y_count = stats(args.train_dir, [args.target])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, mean, std in (("scaler_x.json", x_mean, x_std), ("scaler_y.json", y_mean, y_std)):
        (args.output_dir / name).write_text(
            json.dumps({"mean": mean, "std": std}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"features": features, "target": args.target, "rows": min(x_count, y_count)}, ensure_ascii=False))


if __name__ == "__main__":
    main()


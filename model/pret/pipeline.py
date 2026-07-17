from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import timedelta
from pathlib import Path

import numpy as np

from data import column_stats, load_config, read_experiment_csv
from informer_runtime import InformerPredictor
from kalman import kalman_filter


def resolve_checkpoint(root: Path, checkpoint_root: Path, target: str) -> Path:
    matches = sorted((root / checkpoint_root).glob(f"*tg{target}_*/checkpoint.pth"))
    if len(matches) != 1:
        raise RuntimeError(f"目标{target}应匹配一个checkpoint，实际为{len(matches)}: {matches}")
    return matches[0]


def safe_std(values: np.ndarray) -> float:
    value = float(np.std(values))
    return value if value > 1e-8 else 1.0


def run(args: argparse.Namespace) -> dict:
    here = Path(__file__).resolve().parent
    root = here.parent
    config = load_config(args.config or here / "config.json")
    rows = read_experiment_csv(args.input)
    if not rows:
        raise ValueError("输入CSV为空")

    initial = config["initial_core_temperature"]
    if args.use_ground_truth_initial_core:
        if rows[0]["CoreTruth"] is None:
            raise ValueError("输入文件没有Core，不能使用真实Core初始化")
        initial = rows[0]["CoreTruth"]
    for row, value in zip(rows, kalman_filter([r["HR"] for r in rows], initial)):
        row["Kalman_Result"] = value
        row["Core"] = None

    m1 = config["model1"]
    checkpoint1 = root / m1["checkpoint"]
    if not checkpoint1.is_file():
        raise FileNotFoundError(checkpoint1)
    x_mean, x_std = column_stats(root / m1["scaler_reference_dir"], m1["features"])
    y_mean, y_std = column_stats(root / m1["scaler_reference_dir"], [m1["target"]])
    x_mean, x_std = np.asarray(x_mean), np.maximum(np.asarray(x_std), 1e-8)
    y_mean, y_std = np.asarray(y_mean), np.maximum(np.asarray(y_std), 1e-8)
    predictor1 = InformerPredictor(root, checkpoint1, m1, len(m1["features"]), args.device)

    for index in range(m1["seq_len"] - 1, len(rows)):
        window = rows[index - m1["seq_len"] + 1:index + 1]
        values = np.asarray([[row[key] for key in m1["features"]] for row in window])
        predicted = predictor1.predict(values, [r["timestamp"] for r in window], x_mean, x_std, y_mean, y_std)
        rows[index]["Core"] = predicted[0]

    m2 = config["model2"]
    predictors = {}
    for target in m2["targets"]:
        checkpoint = resolve_checkpoint(root, Path(m2["checkpoint_root"]), target)
        predictors[target] = InformerPredictor(root, checkpoint, m2, 1, args.device)

    output_rows = []
    for index in range(len(rows)):
        begin = index - m2["seq_len"] + 1
        if begin < 0 or any(rows[i]["Core"] is None for i in range(begin, index + 1)):
            continue
        combined = {
            "origin_timestamp": rows[index]["timestamp"].isoformat(),
            "Core_model1": rows[index]["Core"],
            "Core_truth": rows[index]["CoreTruth"],
        }
        target_predictions = {}
        for target, target_cfg in m2["targets"].items():
            source = target_cfg["source"]
            values = np.asarray([[rows[i][source]] for i in range(begin, index + 1)], dtype=float)
            timestamps = [rows[i]["timestamp"] for i in range(begin, index + 1)]
            scaler_dir = target_cfg.get("scaler_reference_dir")
            if scaler_dir:
                mean, std = column_stats(root / scaler_dir, [source])
                scaler = "reference"
            else:
                mean, std = [float(np.mean(values))], [safe_std(values)]
                scaler = "window"
            target_predictions[target] = predictors[target].predict(
                values, timestamps, np.asarray(mean), np.asarray(std),
                np.asarray(mean), np.asarray(std), decoder_feature_index=0,
            )
            combined[f"{target}_scaler"] = scaler
        for horizon in range(m2["pred_len"]):
            record = dict(combined)
            record["horizon_minutes"] = horizon
            record["predicted_timestamp"] = (rows[index]["timestamp"] + timedelta(minutes=horizon)).isoformat()
            for target, predictions in target_predictions.items():
                record[target] = predictions[horizon]
            output_rows.append(record)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if output_rows:
        with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
            writer.writeheader()
            writer.writerows(output_rows)

    errors = [row["Core"] - row["CoreTruth"] for row in rows if row["Core"] is not None and row["CoreTruth"] is not None]
    summary = {
        "input_rows": len(rows), "model1_predictions": sum(row["Core"] is not None for row in rows),
        "model2_origins": len(output_rows) // m2["pred_len"], "forecast_rows": len(output_rows),
        "output": str(args.output), "kalman_initial_core": initial,
    }
    if errors:
        summary.update(core_mae=sum(abs(x) for x in errors) / len(errors), core_rmse=math.sqrt(sum(x*x for x in errors) / len(errors)))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Kalman→模型1→模型2端到端联合测试")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--use-ground-truth-initial-core", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

import numpy as np


@dataclass
class Scaler:
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def load(cls, path: str) -> "Scaler":
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        mean = np.asarray(value["mean"], dtype=np.float32)
        std = np.asarray(value["std"], dtype=np.float32)
        if np.any(std == 0):
            raise ValueError(f"zero standard deviation in {path}")
        return cls(mean, std)

    def transform(self, value: np.ndarray) -> np.ndarray:
        return (value - self.mean) / self.std

    def inverse(self, value: np.ndarray) -> np.ndarray:
        return value * self.std + self.mean


def time_marks(timestamps: Sequence[datetime]) -> np.ndarray:
    marks = []
    for value in timestamps:
        day_of_year = value.timetuple().tm_yday
        marks.append([
            value.minute / 59.0 - 0.5,
            value.hour / 23.0 - 0.5,
            value.weekday() / 6.0 - 0.5,
            (value.day - 1) / 30.0 - 0.5,
            (day_of_year - 1) / 365.0 - 0.5,
        ])
    return np.asarray(marks, dtype=np.float32)


class InformerRuntime:
    def __init__(self, checkpoint: str, config_path: str, scaler_x: str, scaler_y: str, device: str):
        self.ready = False
        self.error: str | None = None
        self.version = "unavailable"
        try:
            import torch
            from models.model import Informer

            with open(config_path, encoding="utf-8") as handle:
                config = json.load(handle)
            self.config = config
            self.scaler_x = Scaler.load(scaler_x)
            self.scaler_y = Scaler.load(scaler_y)
            self.device = torch.device(device)
            self.torch = torch
            self.model = Informer(
                enc_in=len(config["features"]), dec_in=1, c_out=1,
                seq_len=config["seq_len"], label_len=config["label_len"], out_len=config["pred_len"],
                factor=config.get("factor", 5), d_model=config.get("d_model", 512),
                n_heads=config.get("n_heads", 8), e_layers=config.get("e_layers", 2),
                d_layers=config.get("d_layers", 1), d_ff=config.get("d_ff", 2048),
                dropout=config.get("dropout", 0.01), attn=config.get("attn", "prob"),
                embed=config.get("embed", "timeF"), freq=config.get("freq", "t"),
                activation=config.get("activation", "gelu"), output_attention=False,
                distil=config.get("distil", True), mix=config.get("mix", True), device=self.device,
            ).float().to(self.device)
            state = torch.load(checkpoint, map_location=self.device, weights_only=True)
            self.model.load_state_dict(state)
            self.model.eval()
            self.version = config.get("version", os.path.basename(os.path.dirname(checkpoint)))
            self.ready = True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def predict(self, values: np.ndarray, timestamps: Sequence[datetime]) -> list[float]:
        if not self.ready:
            raise RuntimeError(self.error or "model is not ready")
        torch = self.torch
        cfg = self.config
        seq_len, label_len, pred_len = cfg["seq_len"], cfg["label_len"], cfg["pred_len"]
        values = values[-seq_len:].astype(np.float32)
        timestamps = list(timestamps[-seq_len:])
        scaled = self.scaler_x.transform(values)
        # The original Dataset_* uses r_begin = s_end - label_len - 1.
        # Therefore decoder history excludes the final encoder point and the
        # first predicted value is aligned with that final (current) point.
        prediction_times = [timestamps[-1] + timedelta(minutes=index) for index in range(pred_len)]
        decoder_history_times = timestamps[-label_len - 1:-1] if label_len else []
        decoder_times = decoder_history_times + prediction_times
        decoder_seed = np.zeros((label_len + pred_len, 1), dtype=np.float32)
        if label_len:
            target_index = int(cfg.get("decoder_feature_index", 0))
            decoder_seed[:label_len, 0] = scaled[-label_len - 1:-1, target_index]
        with torch.inference_mode():
            output = self.model(
                torch.from_numpy(scaled[None]).to(self.device),
                torch.from_numpy(time_marks(timestamps)[None]).to(self.device),
                torch.from_numpy(decoder_seed[None]).to(self.device),
                torch.from_numpy(time_marks(decoder_times)[None]).to(self.device),
            )
        raw = output.detach().cpu().numpy()[0, :, 0]
        return self.scaler_y.inverse(raw.reshape(-1, 1)).reshape(-1).astype(float).tolist()

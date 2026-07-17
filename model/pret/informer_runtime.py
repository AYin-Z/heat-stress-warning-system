from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np


def time_marks(timestamps: list[datetime]) -> np.ndarray:
    values = []
    for item in timestamps:
        values.append([
            item.minute / 59.0 - 0.5,
            item.hour / 23.0 - 0.5,
            item.weekday() / 6.0 - 0.5,
            (item.day - 1) / 30.0 - 0.5,
            (item.timetuple().tm_yday - 1) / 365.0 - 0.5,
        ])
    return np.asarray(values, dtype=np.float32)


class InformerPredictor:
    def __init__(self, project_root: Path, checkpoint: Path, config: dict, enc_in: int, device: str = "cpu"):
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("需要安装PyTorch CPU版后才能加载checkpoint") from exc
        informer_root = project_root / "模型1"
        if str(informer_root) not in sys.path:
            sys.path.insert(0, str(informer_root))
        from models.model import Informer

        self.torch = torch
        self.device = torch.device(device)
        self.config = config
        self.model = Informer(
            enc_in=enc_in, dec_in=1, c_out=1,
            seq_len=config["seq_len"], label_len=config["label_len"], out_len=config["pred_len"],
            factor=5, d_model=512, n_heads=8, e_layers=2, d_layers=1, d_ff=2048,
            dropout=config.get("dropout", 0.05), attn="prob", embed="timeF", freq="t",
            activation="gelu", output_attention=False, distil=True, mix=True, device=self.device,
        ).float().to(self.device)
        state = torch.load(checkpoint, map_location=self.device, weights_only=True)
        self.model.load_state_dict(state)
        self.model.eval()

    def predict(
        self,
        values: np.ndarray,
        timestamps: list[datetime],
        x_mean: np.ndarray,
        x_std: np.ndarray,
        y_mean: np.ndarray,
        y_std: np.ndarray,
        decoder_feature_index: int = 0,
    ) -> list[float]:
        cfg = self.config
        seq_len, label_len, pred_len = cfg["seq_len"], cfg["label_len"], cfg["pred_len"]
        values = values[-seq_len:].astype(np.float32)
        timestamps = timestamps[-seq_len:]
        scaled = (values - x_mean) / x_std
        prediction_times = [timestamps[-1] + timedelta(minutes=i) for i in range(pred_len)]
        decoder_history_times = timestamps[-label_len - 1:-1] if label_len else []
        decoder_times = decoder_history_times + prediction_times
        decoder = np.zeros((label_len + pred_len, 1), dtype=np.float32)
        if label_len:
            decoder[:label_len, 0] = scaled[-label_len - 1:-1, decoder_feature_index]
        torch = self.torch
        with torch.inference_mode():
            output = self.model(
                torch.from_numpy(scaled[None]).to(self.device),
                torch.from_numpy(time_marks(timestamps)[None]).to(self.device),
                torch.from_numpy(decoder[None]).to(self.device),
                torch.from_numpy(time_marks(decoder_times)[None]).to(self.device),
            )
        predicted = output.detach().cpu().numpy()[0, :, 0]
        return (predicted * y_std[0] + y_mean[0]).astype(float).tolist()


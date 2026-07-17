"""TDgpt 3.4.1.9 adapter for the project's Informer core forecast model."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import numpy as np

from runtime import InformerRuntime
from taosanalytics.algo.forecast import insert_ts_list
from taosanalytics.base import AbstractForecastService


class _CoreTemperatureService(AbstractForecastService):
    name = "coretemp"
    desc = "forecast core temperature with the project Informer model"
    _builtins = False

    def __init__(self):
        super().__init__()
        root = "/usr/local/taos/taosanode/model/core-temperature-forecast"
        self.runtime = InformerRuntime(
            checkpoint=os.path.join(root, "checkpoint.pth"),
            config_path=os.path.join(root, "model_config.json"),
            scaler_x=os.path.join(root, "scaler_x.json"),
            scaler_y=os.path.join(root, "scaler_y.json"),
            device=os.getenv("MODEL_DEVICE", "cpu"),
        )

    def execute(self):
        if not self.runtime.ready:
            raise RuntimeError(f"coretemp model is not ready: {self.runtime.error}")
        required = int(self.runtime.config["seq_len"])
        if self.list is None or len(self.list) < required:
            raise ValueError(f"coretemp needs at least {required} input values")
        if self.rows <= 0:
            raise ValueError("forecast rows is not specified")
        available = int(self.runtime.config["pred_len"])
        if self.rows > available:
            raise ValueError(f"coretemp supports at most {available} forecast rows")

        # TDgpt start_ts is the first forecast timestamp, so reconstruct the
        # historical minute marks expected by the original Informer model.
        unit = 1_000 if self.start_ts > 10_000_000_000 else 1
        start = datetime.fromtimestamp(self.start_ts / unit, tz=timezone.utc)
        step = timedelta(milliseconds=self.time_step) if unit == 1_000 else timedelta(seconds=self.time_step)
        timestamps = [start - step * (required - index) for index in range(required)]
        values = np.asarray(self.list[-required:], dtype=np.float32).reshape(-1, 1)
        predictions = self.runtime.predict(values, timestamps)[:self.rows]
        result = [predictions]
        insert_ts_list(result, self.start_ts, self.time_step, self.rows)
        return {
            "mse": 0.0,
            "model_info": f"Informer:{self.runtime.version}",
            "res": result,
        }


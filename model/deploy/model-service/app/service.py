from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from .informer import InformerRuntime
from .processing import append_raw_and_aggregate, kalman_step, normalize_timestamp, to_sample, update_kalman
from .schemas import DeviceState, ForecastPoint, ThermalResult, WatchUpload
from .settings import Settings
from .state import StateRepository


class ThermalService:
    def __init__(self, config: Settings, repository: StateRepository):
        self.repository = repository
        self.model1 = InformerRuntime(
            config.model1_checkpoint, config.model1_config, config.model1_scaler_x,
            config.model1_scaler_y, config.model_device,
        ) if config.model1_enabled else None
        self.model2 = InformerRuntime(
            config.model2_checkpoint, config.model2_config, config.model2_scaler_x,
            config.model2_scaler_y, config.model_device,
        ) if config.model2_enabled else None

    def status(self) -> dict:
        return {
            "estimator": self._model_status(self.model1),
            "forecaster": self._model_status(self.model2),
            "redis": self.repository.redis_available,
        }

    @staticmethod
    def _model_status(model: InformerRuntime | None) -> dict:
        if model is None:
            return {"enabled": False, "ready": False}
        return {"enabled": True, "ready": model.ready, "version": model.version, "error": model.error}

    def estimate_hr_window(self, heart_rates: list[int], latest_timestamp: datetime) -> dict:
        """Run model 1 from one self-contained 20-minute HR window."""
        if not self.model1 or not self.model1.ready:
            error = self.model1.error if self.model1 else "model 1 is disabled"
            raise RuntimeError(error or "model 1 is not ready")
        required = int(self.model1.config["seq_len"])
        if len(heart_rates) != required:
            raise ValueError(f"model 1 requires exactly {required} heart rates")

        temperature = 37.0
        variance = 0.0
        kalman_values = []
        for heart_rate in heart_rates:
            temperature, variance = kalman_step(heart_rate, temperature, variance)
            kalman_values.append([temperature])

        latest = normalize_timestamp(latest_timestamp).replace(second=0, microsecond=0)
        timestamps = [latest - timedelta(minutes=required - 1 - index) for index in range(required)]
        core_temperature = float(self.model1.predict(
            np.asarray(kalman_values, dtype=np.float32), timestamps
        )[0])
        if not 30.0 <= core_temperature <= 45.0:
            raise RuntimeError(f"model 1 returned an invalid temperature: {core_temperature}")
        return {
            "core_temperature": round(core_temperature, 3),
            "source": "informer_model_1",
            "model_version": self.model1.version,
            "window_size": required,
            "timestamp": latest,
        }

    async def process(self, device_id: str, upload: WatchUpload) -> ThermalResult:
        async with self.repository.lock(device_id):
            state = await self.repository.get(device_id)
            sample = to_sample(upload)
            state.raw_samples, state.minute_samples = append_raw_and_aggregate(state.raw_samples, sample)
            minute_sample = state.minute_samples[-1]
            current = update_kalman(state, minute_sample)
            source = "measured" if minute_sample.core_temperature is not None else "kalman_fallback"
            confidence = "high" if source == "measured" else "low"
            # Every minute needs one canonical core-temperature value so model 2
            # can warm up even when the watch cannot measure core temperature.
            minute_sample.core_temperature = current
            warnings: list[str] = []
            versions = {"estimator": "kalman-v1"}

            if self.model1 and self.model1.ready:
                try:
                    values, times = self._model1_input(state)
                    if len(values) >= self.model1.config["seq_len"]:
                        current = self.model1.predict(values, times)[0]
                        source, confidence = "informer_model_1", "medium"
                        versions["estimator"] = self.model1.version
                        minute_sample.core_temperature = current
                except Exception as exc:
                    warnings.append(f"model1 fallback: {type(exc).__name__}")
            elif self.model1:
                warnings.append("model1 enabled but not ready")

            state.core_history = [item for item in state.core_history if item.timestamp != minute_sample.timestamp]
            state.core_history.append(minute_sample.model_copy(update={"core_temperature": current}))
            state.core_history = sorted(state.core_history, key=lambda item: item.timestamp)[-180:]
            core_samples = state.core_history
            forecast = None
            forecast_source = None
            if self.model2 and self.model2.ready and len(core_samples) >= self.model2.config["seq_len"]:
                try:
                    values = np.asarray([[item.core_temperature] for item in core_samples], dtype=np.float32)
                    predictions = self.model2.predict(values, [item.timestamp for item in core_samples])
                    forecast = [ForecastPoint(minutes_ahead=i, core_temperature=round(value, 3)) for i, value in enumerate(predictions)]
                    forecast_source = "informer_model_2"
                    versions["forecaster"] = self.model2.version
                except Exception as exc:
                    warnings.append(f"model2 unavailable: {type(exc).__name__}")
            elif self.model2:
                warnings.append("model2 warming up or not ready")

            await self.repository.put(device_id, state)
            required = max(20, self.model1.config["seq_len"] if self.model1 and self.model1.ready else 20)
            status = "ready" if source in {"measured", "informer_model_1"} and len(state.minute_samples) >= required else "warming_up"
            return ThermalResult(
                status=status,
                current_core_temperature=round(current, 3),
                current_source=source,
                confidence=confidence,
                samples_collected=min(len(state.minute_samples), required),
                samples_required=required,
                forecast=forecast,
                max_forecast_temperature=max((p.core_temperature for p in forecast), default=None) if forecast else None,
                forecast_source=forecast_source,
                model_versions=versions,
                warnings=warnings,
            )

    def _model1_input(self, state: DeviceState):
        cfg = self.model1.config
        rows, times = [], []
        # Rebuild the notebook's Kalman_Result series entirely from HR.  This
        # makes the estimator deployable on watches that expose no temperature
        # sensor while keeping the checkpoint's exact one-feature contract.
        kalman_temperature = 37.0
        kalman_variance = 0.0
        for sample in state.minute_samples:
            if sample.heart_rate is not None:
                kalman_temperature, kalman_variance = kalman_step(
                    sample.heart_rate, kalman_temperature, kalman_variance
                )
            row = []
            for feature in cfg["features"]:
                if feature == "HR":
                    value = sample.heart_rate
                elif feature == "Kalman_Result":
                    value = kalman_temperature if sample.heart_rate is not None else None
                elif feature == "MeanSkin":
                    values = list(sample.skin_temperatures.values())
                    value = sum(values) / len(values) if values else sample.skin_temperature
                else:
                    value = sample.skin_temperatures.get(feature)
                if value is None:
                    break
                row.append(value)
            if len(row) == len(cfg["features"]):
                rows.append(row)
                times.append(sample.timestamp)
        return np.asarray(rows, dtype=np.float32), times


def alert_for(result: ThermalResult) -> dict | None:
    current = result.current_core_temperature
    predicted = result.max_forecast_temperature or current
    if current >= 39 or predicted >= 39:
        return {"type": "high_risk" if current >= 39 else "forecast_high_risk", "risk_level": "high_risk", "advice": "立即停止当前活动，转移至阴凉处并寻求医疗支持"}
    if current >= 38 or predicted >= 38:
        return {"type": "normal" if current >= 38 else "forecast", "risk_level": "warning", "advice": "适当降低活动强度，注意补充水分"}
    return None

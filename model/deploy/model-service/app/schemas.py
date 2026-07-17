from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WatchUpload(BaseModel):
    model_config = ConfigDict(extra="allow")

    heart_rate: int | None = Field(default=None, ge=30, le=250)
    blood_oxygen: float | None = Field(default=None, ge=50, le=100)
    blood_pressure_sys: int | None = Field(default=None, ge=40, le=300)
    blood_pressure_dia: int | None = Field(default=None, ge=20, le=200)
    step_frequency: int | None = Field(default=None, ge=0, le=400)
    core_temperature: float | None = Field(default=None, ge=30, le=45)
    skin_temperature: float | None = Field(default=None, ge=15, le=45)
    skin_temperatures: dict[str, float] | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timestamp: datetime | None = None

    @field_validator("skin_temperatures")
    @classmethod
    def validate_skin_temperatures(cls, value: dict[str, float] | None):
        if value is not None and any(not 15 <= item <= 45 for item in value.values()):
            raise ValueError("skin temperature must be between 15 and 45 Celsius")
        return value


class Sample(BaseModel):
    timestamp: datetime
    heart_rate: float | None = None
    core_temperature: float | None = None
    skin_temperature: float | None = None
    skin_temperatures: dict[str, float] = Field(default_factory=dict)


class DeviceState(BaseModel):
    raw_samples: list[Sample] = Field(default_factory=list)
    minute_samples: list[Sample] = Field(default_factory=list)
    core_history: list[Sample] = Field(default_factory=list)
    kalman_temperature: float = 37.0
    kalman_variance: float = 0.0
    last_kalman_minute: datetime | None = None


class ForecastPoint(BaseModel):
    minutes_ahead: int
    core_temperature: float


class ThermalResult(BaseModel):
    status: str
    current_core_temperature: float
    current_source: str
    confidence: str
    samples_collected: int
    samples_required: int
    forecast: list[ForecastPoint] | None = None
    max_forecast_temperature: float | None = None
    forecast_source: str | None = None
    model_versions: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class EstimateRequest(BaseModel):
    device_id: str
    samples: list[Sample]


class HeartRateWindowRequest(BaseModel):
    """One complete model-1 window, ordered from oldest to newest."""

    device_id: str = Field(min_length=1, max_length=128)
    heart_rates: list[int] = Field(min_length=20, max_length=20)
    timestamp: datetime

    @field_validator("heart_rates")
    @classmethod
    def validate_heart_rates(cls, values: list[int]):
        if any(value < 30 or value > 250 for value in values):
            raise ValueError("each heart rate must be between 30 and 250 bpm")
        return values


class GenericResponse(BaseModel):
    ok: bool = True
    thermal: ThermalResult
    upstream: dict[str, Any] | None = None

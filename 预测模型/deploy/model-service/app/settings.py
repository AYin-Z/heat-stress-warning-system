from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    upstream_watch_api: str = os.getenv("UPSTREAM_WATCH_API", "").rstrip("/")
    upstream_timeout_seconds: float = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "10"))
    forward_upload: bool = _bool("FORWARD_UPLOAD", True)
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    state_ttl_seconds: int = int(os.getenv("STATE_TTL_SECONDS", "86400"))
    model_device: str = os.getenv("MODEL_DEVICE", "cpu")
    model1_enabled: bool = _bool("MODEL1_ENABLED", False)
    model1_checkpoint: str = os.getenv("MODEL1_CHECKPOINT", "")
    model1_config: str = os.getenv("MODEL1_CONFIG", "")
    model1_scaler_x: str = os.getenv("MODEL1_SCALER_X", "")
    model1_scaler_y: str = os.getenv("MODEL1_SCALER_Y", "")
    model2_enabled: bool = _bool("MODEL2_ENABLED", False)
    model2_checkpoint: str = os.getenv("MODEL2_CHECKPOINT", "")
    model2_config: str = os.getenv("MODEL2_CONFIG", "")
    model2_scaler_x: str = os.getenv("MODEL2_SCALER_X", "")
    model2_scaler_y: str = os.getenv("MODEL2_SCALER_Y", "")


settings = Settings()


from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median

from .schemas import DeviceState, Sample, WatchUpload


SKIN_ALIASES = {
    "head": "Head",
    "chest": "Chest",
    "forearm": "Forearm",
    "hand": "Hand",
    "wrist": "Hand",
    "thigh": "Thigh",
    "calf": "Calf",
    "foot": "Foot",
}


def normalize_timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_sample(upload: WatchUpload) -> Sample:
    skin = {}
    for key, value in (upload.skin_temperatures or {}).items():
        skin[SKIN_ALIASES.get(key.lower(), key)] = value
    if upload.skin_temperature is not None:
        skin.setdefault("Hand", upload.skin_temperature)
    return Sample(
        timestamp=normalize_timestamp(upload.timestamp),
        heart_rate=upload.heart_rate,
        core_temperature=upload.core_temperature,
        skin_temperature=upload.skin_temperature,
        skin_temperatures=skin,
    )


def _median(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return float(median(clean)) if clean else None


def aggregate_minute(existing: list[Sample], incoming: Sample) -> list[Sample]:
    minute = incoming.timestamp.replace(second=0, microsecond=0)
    same = [item for item in existing if item.timestamp.replace(second=0, microsecond=0) == minute]
    others = [item for item in existing if item.timestamp.replace(second=0, microsecond=0) != minute]
    same.append(incoming)

    sites = set().union(*(item.skin_temperatures.keys() for item in same))
    aggregated = Sample(
        timestamp=minute,
        heart_rate=_median([item.heart_rate for item in same]),
        core_temperature=_median([item.core_temperature for item in same]),
        skin_temperature=_median([item.skin_temperature for item in same]),
        skin_temperatures={
            site: value
            for site in sites
            if (value := _median([item.skin_temperatures.get(site) for item in same])) is not None
        },
    )
    result = sorted(others + [aggregated], key=lambda item: item.timestamp)
    cutoff = minute - timedelta(hours=3)
    return [item for item in result if item.timestamp >= cutoff][-180:]


def append_raw_and_aggregate(raw: list[Sample], incoming: Sample) -> tuple[list[Sample], list[Sample]]:
    """Keep raw points so repeated median aggregation does not bias a minute."""
    cutoff = incoming.timestamp - timedelta(hours=3)
    raw = sorted([item for item in raw if item.timestamp >= cutoff] + [incoming], key=lambda item: item.timestamp)[-3000:]
    groups: dict[datetime, list[Sample]] = {}
    for item in raw:
        minute = item.timestamp.replace(second=0, microsecond=0)
        groups.setdefault(minute, []).append(item)
    minutes: list[Sample] = []
    for minute, items in sorted(groups.items()):
        sites = set().union(*(item.skin_temperatures.keys() for item in items))
        minutes.append(Sample(
            timestamp=minute,
            heart_rate=_median([item.heart_rate for item in items]),
            core_temperature=_median([item.core_temperature for item in items]),
            skin_temperature=_median([item.skin_temperature for item in items]),
            skin_temperatures={
                site: value
                for site in sites
                if (value := _median([item.skin_temperatures.get(site) for item in items])) is not None
            },
        ))
    return raw, minutes[-180:]


KALMAN_PARAMS = (1.0, 0.0, 0.022**2, -7887.1, 384.4286, -4.5714, 18.88**2)


def kalman_step(heart_rate: float, temperature: float, variance: float) -> tuple[float, float]:
    a0, a1, gamma, b0, b1, b2, sigma = KALMAN_PARAMS
    predicted = a0 * temperature + a1
    predicted_variance = a0 * a0 * variance + gamma
    derivative = 2 * b2 * predicted + b1
    gain = predicted_variance * derivative / (derivative * derivative * predicted_variance + sigma)
    updated = predicted + gain * (heart_rate - (b2 * predicted * predicted + b1 * predicted + b0))
    updated_variance = (1 - gain * derivative) * predicted_variance
    return float(min(43.0, max(35.0, updated))), float(max(0.0, updated_variance))


def update_kalman(state: DeviceState, sample: Sample) -> float:
    if sample.core_temperature is not None:
        state.kalman_temperature = sample.core_temperature
        state.kalman_variance = 0.0
    elif sample.heart_rate is not None and state.last_kalman_minute != sample.timestamp:
        state.kalman_temperature, state.kalman_variance = kalman_step(
            sample.heart_rate, state.kalman_temperature, state.kalman_variance
        )
    state.last_kalman_minute = sample.timestamp
    return state.kalman_temperature

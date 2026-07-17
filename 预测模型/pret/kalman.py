from __future__ import annotations

from dataclasses import dataclass


DEFAULT_PARAMS = (1.0, 0.0, 0.022**2, -7887.1, 384.4286, -4.5714, 18.88**2)


@dataclass
class KalmanCoreEstimator:
    temperature: float = 37.0
    variance: float = 0.0
    params: tuple[float, ...] = DEFAULT_PARAMS

    def update(self, heart_rate: float) -> float:
        a0, a1, gamma, b0, b1, b2, sigma = self.params
        predicted = a0 * self.temperature + a1
        predicted_variance = a0 * a0 * self.variance + gamma
        derivative = 2 * b2 * predicted + b1
        gain = predicted_variance * derivative / (
            derivative * derivative * predicted_variance + sigma
        )
        self.temperature = predicted + gain * (
            heart_rate - (b2 * predicted * predicted + b1 * predicted + b0)
        )
        self.variance = (1 - gain * derivative) * predicted_variance
        return float(self.temperature)


def kalman_filter(heart_rates: list[float], initial_core: float = 37.0) -> list[float]:
    estimator = KalmanCoreEstimator(temperature=initial_core)
    return [estimator.update(value) for value in heart_rates]


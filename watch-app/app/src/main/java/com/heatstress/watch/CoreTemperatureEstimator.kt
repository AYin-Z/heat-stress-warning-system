package com.heatstress.watch

/**
 * Lightweight Kalman estimator already used by the project's A80 fallback path.
 * It is driven by a validated heart-rate sample and is never labelled as a
 * physical temperature measurement.
 */
class CoreTemperatureEstimator {
    private var currentCore = INITIAL_CORE

    fun update(heartRate: Int): Double {
        val xPred = currentCore
        val variance = PROCESS_NOISE
        val derivative = 2 * B2 * xPred + B1
        val gain = (variance * derivative) /
            (derivative * derivative * variance + MEASUREMENT_NOISE)
        val predictedHeartRate = B2 * xPred * xPred + B1 * xPred + B0
        currentCore = (xPred + gain * (heartRate - predictedHeartRate))
            .coerceIn(MIN_CORE, MAX_CORE)
        return currentCore
    }

    fun reset() {
        currentCore = INITIAL_CORE
    }

    companion object {
        const val SOURCE = "kalman_hr_v1"
        private const val INITIAL_CORE = 37.0
        private const val MIN_CORE = 35.5
        private const val MAX_CORE = 41.5
        private const val PROCESS_NOISE = 0.022 * 0.022
        private const val B0 = -7887.1
        private const val B1 = 384.4286
        private const val B2 = -4.5714
        private const val MEASUREMENT_NOISE = 18.88 * 18.88
    }
}

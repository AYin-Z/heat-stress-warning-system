package com.heatstress.watch

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CoreTemperatureEstimatorTest {
    @Test
    fun neutralHeartRateKeepsEstimateNearBaseline() {
        val estimator = CoreTemperatureEstimator()
        repeat(20) { estimator.update(75) }
        assertEquals(37.0, estimator.update(75), 0.1)
    }

    @Test
    fun sustainedHighHeartRateRaisesEstimate() {
        val estimator = CoreTemperatureEstimator()
        val baseline = estimator.update(75)
        var estimate = baseline
        repeat(120) { estimate = estimator.update(150) }
        assertTrue(estimate > baseline)
        assertTrue(estimate <= 41.5)
    }

    @Test
    fun resetReturnsEstimatorToBaseline() {
        val estimator = CoreTemperatureEstimator()
        repeat(120) { estimator.update(150) }
        estimator.reset()
        assertEquals(37.0, estimator.update(75), 0.1)
    }
}

package com.heatstress.watch

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NtpSyncTest {
    @Test
    fun acceptsProductionEraTimestamps() {
        assertTrue(NtpSync.isPlausibleTimestamp(1_783_958_400_000L))
    }

    @Test
    fun rejectsTheA80ResetClockAndFarFutureValues() {
        assertFalse(NtpSync.isPlausibleTimestamp(1_328_468_000_000L))
        assertFalse(NtpSync.isPlausibleTimestamp(4_102_444_800_001L))
    }
}

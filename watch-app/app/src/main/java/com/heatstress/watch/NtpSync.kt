package com.heatstress.watch

import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import kotlin.math.abs

object NtpSync {
    suspend fun synchronizeClock(): SyncResult = withContext(Dispatchers.IO) {
        val ntpTime = getNtpTime() ?: return@withContext SyncResult(false, null, "NTP unavailable")
        val drift = ntpTime - System.currentTimeMillis()
        if (abs(drift) <= SET_THRESHOLD_MS) {
            return@withContext SyncResult(true, drift, "Clock current", corrected = false)
        }

        val updated = try {
            SystemClock.setCurrentTimeMillis(ntpTime)
        } catch (e: SecurityException) {
            Log.e(TAG, "SET_TIME denied", e)
            false
        }
        SyncResult(
            updated,
            drift,
            if (updated) "Clock corrected by NTP" else "Clock correction denied",
            corrected = updated
        )
    }

    fun applyServerTime(timestampMs: Long): SyncResult {
        if (!isPlausibleTimestamp(timestampMs)) {
            return SyncResult(false, null, "Server time rejected", corrected = false)
        }
        val drift = timestampMs - System.currentTimeMillis()
        if (abs(drift) <= SET_THRESHOLD_MS) {
            return SyncResult(true, drift, "Clock current", corrected = false)
        }
        val updated = try {
            SystemClock.setCurrentTimeMillis(timestampMs)
        } catch (e: SecurityException) {
            Log.e(TAG, "SET_TIME denied", e)
            false
        }
        return SyncResult(
            updated,
            drift,
            if (updated) "Clock corrected by MQTT" else "Clock correction denied",
            corrected = updated
        )
    }

    internal fun isPlausibleTimestamp(timestampMs: Long): Boolean =
        timestampMs in MIN_TRUSTED_TIME_MS..MAX_TRUSTED_TIME_MS

    private fun getNtpTime(): Long? {
        var socket: DatagramSocket? = null
        return try {
            val request = ByteArray(PACKET_SIZE)
            request[0] = 0x23 // LI=0, VN=4, mode=3
            socket = DatagramSocket().apply { soTimeout = TIMEOUT_MS }
            val address = InetAddress.getByName(NTP_HOST)
            val started = SystemClock.elapsedRealtime()
            socket.send(DatagramPacket(request, request.size, address, NTP_PORT))
            val response = DatagramPacket(ByteArray(PACKET_SIZE), PACKET_SIZE)
            socket.receive(response)
            val elapsed = SystemClock.elapsedRealtime() - started

            val mode = response.data[0].toInt() and 0x7
            val stratum = response.data[1].toInt() and 0xff
            if (mode !in 4..5 || stratum !in 1..15) return null
            readTimestamp(response.data, TRANSMIT_OFFSET) + elapsed / 2
        } catch (e: Exception) {
            Log.w(TAG, "NTP request failed: ${e.message}")
            null
        } finally {
            socket?.close()
        }
    }

    private fun readTimestamp(buffer: ByteArray, offset: Int): Long {
        var seconds = 0L
        var fraction = 0L
        for (i in 0 until 4) seconds = (seconds shl 8) or (buffer[offset + i].toLong() and 0xff)
        for (i in 4 until 8) fraction = (fraction shl 8) or (buffer[offset + i].toLong() and 0xff)
        return (seconds - EPOCH_DIFF_SECONDS) * 1_000L + (fraction * 1_000L) / 0x100000000L
    }

    data class SyncResult(
        val success: Boolean,
        val driftMs: Long?,
        val message: String,
        val corrected: Boolean = false
    )

    private const val TAG = "NtpSync"
    private const val NTP_HOST = "ntp.aliyun.com"
    private const val NTP_PORT = 123
    private const val TIMEOUT_MS = 5_000
    private const val PACKET_SIZE = 48
    private const val TRANSMIT_OFFSET = 40
    private const val EPOCH_DIFF_SECONDS = 2_208_988_800L
    private const val SET_THRESHOLD_MS = 30_000L
    private const val MIN_TRUSTED_TIME_MS = 1_704_067_200_000L // 2024-01-01 UTC
    private const val MAX_TRUSTED_TIME_MS = 4_102_444_800_000L // 2100-01-01 UTC
}

package com.heatstress.watch

import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/**
 * SNTP 时间同步客户端
 *
 * 当手表系统时间偏差超过阈值时，从 NTP 服务器校准。
 * 作为系统级应用（platform 签名），可通过 AlarmManager 设置系统时间。
 *
 * NTP 协议: RFC 4330 (SNTP v4)
 * 请求: 48 字节，首字节 0x1B (LI=0, VN=4, Mode=3 Client)
 * 响应: transmit_timestamp (offset 40-47) 为 NTP 时间
 *
 * NTP epoch: 1900-01-01. Unix epoch: 1970-01-01. 差值 = 2208988800L 秒
 */
object NtpSync {

    private const val TAG = "NtpSync"

    // 阿里云 NTP (国内首选)
    private const val NTP_HOST = "ntp.aliyun.com"
    private const val NTP_PORT = 123
    private const val NTP_TIMEOUT_MS = 5000
    private const val NTP_PACKET_SIZE = 48
    private const val NTP_OFFSET_TRANSMIT = 40

    // Unix epoch 与 NTP epoch 的秒差
    private const val EPOCH_DIFF_SECONDS = 2208988800L

    // 时间偏差阈值 (毫秒) — 超过此值触发告警
    const val DRIFT_WARNING_MS = 60_000L  // 1 分钟

    /**
     * 从 NTP 服务器获取时间
     * @return Unix 时间戳 (ms)，失败返回 null
     */
    suspend fun getNtpTime(): Long? = withContext(Dispatchers.IO) {
        try {
            val address = InetAddress.getByName(NTP_HOST)
            val socket = DatagramSocket().apply {
                soTimeout = NTP_TIMEOUT_MS
            }

            // 构造 SNTP 请求包
            val request = ByteArray(NTP_PACKET_SIZE)
            request[0] = 0x1B.toByte() // LI=0, VN=4, Mode=3

            val sendPacket = DatagramPacket(request, request.size, address, NTP_PORT)
            val receivePacket = DatagramPacket(ByteArray(NTP_PACKET_SIZE), NTP_PACKET_SIZE)

            // send+receive (1 RTT)
            val t0 = SystemClock.elapsedRealtime()
            socket.send(sendPacket)
            socket.receive(receivePacket)
            val t3 = SystemClock.elapsedRealtime()
            socket.close()

            // 解析 transmit_timestamp
            val response = receivePacket.data
            val transmitTimestamp = readTimestamp(response, NTP_OFFSET_TRANSMIT)

            // 补偿网络延迟 (简化: 假设 RTT 对称)
            val rtt = t3 - t0
            val ntpTime = transmitTimestamp + rtt / 2

            Log.i(TAG, "NTP 时间: $ntpTime (偏差=${ntpTime - System.currentTimeMillis()}ms, RTT=${rtt}ms)")
            ntpTime
        } catch (e: Exception) {
            Log.e(TAG, "NTP 同步失败: ${e.message}")
            null
        }
    }

    /**
     * 检查并报告时间偏差
     * @return 偏差值 (ms)，正数表示系统时间慢于 NTP
     */
    suspend fun checkDrift(): Long? {
        val ntpTime = getNtpTime() ?: return null
        val localTime = System.currentTimeMillis()
        return ntpTime - localTime
    }

    /**
     * 从 NTP 数据包的 offset 位置读取 64 位 NTP 时间戳
     * 返回 Unix 毫秒时间戳
     */
    private fun readTimestamp(buffer: ByteArray, offset: Int): Long {
        // NTP 时间戳: 前32位=秒 (1900 epoch), 后32位=秒的小数部分
        var seconds = 0L
        var fraction = 0L

        for (i in 0 until 4) {
            seconds = (seconds shl 8) or (buffer[offset + i].toLong() and 0xFF)
        }
        for (i in 4 until 8) {
            fraction = (fraction shl 8) or (buffer[offset + i].toLong() and 0xFF)
        }

        // NTP epoch → Unix epoch
        val unixSeconds = seconds - EPOCH_DIFF_SECONDS
        // 小数部分转毫秒
        val millis = (fraction * 1000L) / 0x100000000L

        return unixSeconds * 1000L + millis
    }
}

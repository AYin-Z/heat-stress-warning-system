package com.heatstress.watch

import com.google.gson.Gson
import kotlinx.coroutines.*
import org.eclipse.paho.client.mqttv3.*
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence

/**
 * MQTT 管理器 — 连接 EMQX 中继服务器
 *
 * Topic 约定:
 *   watch/{deviceId}/vital   — 生理数据上报
 *   watch/{deviceId}/alert   — 接收预警推送
 *   watch/{deviceId}/status  — 设备在线状态
 */
class MqttManager(
    deviceId: String
) {
    @Volatile var deviceId: String = deviceId
        private set
    companion object {
        // EMQX 中继服务器
        private const val BROKER_URL = "tcp://localhost:1883"
        private const val CLIENT_ID_PREFIX = "watch-android-"
        private const val QOS = 1
        private const val KEEP_ALIVE = 30
    }

    private var client: MqttClient? = null
    private var connected = false

    // 回调
    var onAlertReceived: ((String) -> Unit)? = null  // 收到的预警建议文本

    /**
     * 连接 EMQX
     */
    suspend fun connect() = withContext(Dispatchers.IO) {
        try {
            val clientId = "$CLIENT_ID_PREFIX$deviceId"
            client = MqttClient(BROKER_URL, clientId, MemoryPersistence()).apply {
                val options = MqttConnectOptions().apply {
                    isCleanSession = true
                    connectionTimeout = 10
                    keepAliveInterval = KEEP_ALIVE
                    isAutomaticReconnect = true
                    maxInflight = 10
                }

                setCallback(object : MqttCallback {
                    override fun connectionLost(cause: Throwable?) {
                        connected = false
                    }

                    override fun messageArrived(topic: String?, message: MqttMessage?) {
                        topic?.let { t ->
                            message?.payload?.let { payload ->
                                val text = String(payload, Charsets.UTF_8)
                                if (t.endsWith("/alert")) {
                                    onAlertReceived?.invoke(text)
                                }
                            }
                        }
                    }

                    override fun deliveryComplete(token: IMqttDeliveryToken?) {}
                })

                connect(options)
                connected = true

                // 订阅预警推送
                subscribe("watch/$deviceId/alert", QOS)

                // 发布上线状态
                publishStatus(true)
            }
        } catch (e: Exception) {
            connected = false
        }
    }

    /**
     * 上报生理数据
     */
    suspend fun publishVital(data: VitalReport) = withContext(Dispatchers.IO) {
        if (!connected) return@withContext
        try {
            val json = Gson().toJson(data)
            client?.publish(
                "watch/$deviceId/vital",
                MqttMessage(json.toByteArray()).apply { qos = QOS }
            )
        } catch (_: Exception) {}
    }

    /**
     * 发布上下线状态
     */
    fun publishStatus(online: Boolean) {
        try {
            client?.publish(
                "watch/$deviceId/status",
                MqttMessage(
                    """{"status":"${if (online) "online" else "offline"}"}""".toByteArray()
                ).apply { qos = QOS }
            )
        } catch (_: Exception) {}
    }

    /**
     * 断开连接
     */
    fun disconnect() {
        try {
            publishStatus(false)
            client?.disconnect()
            client?.close()
        } catch (_: Exception) {}
        connected = false
    }

    fun isConnected(): Boolean = connected
}

/**
 * 生理数据上报格式
 * 与前端 types/index.ts 中的 VitalData 对齐
 */
data class VitalReport(
    val deviceId: String,
    val timestamp: Long = System.currentTimeMillis(),

    // 定位
    val latitude: Double,
    val longitude: Double,

    // 生理
    val heartRate: Int,         // bpm
    val spo2: Double,           // %
    val bloodPressure: String,  // "120/80"
    val steps: Int,
)

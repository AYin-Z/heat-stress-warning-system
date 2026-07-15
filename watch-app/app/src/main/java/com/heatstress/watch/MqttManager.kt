package com.heatstress.watch

import android.util.Log
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
    deviceId: String,
    private val offlineQueue: OfflineQueue? = null
) {
    companion object {
        private const val TAG = "MqttManager"
        // 通过 BuildConfig 配置，默认指向公网 EMQX
        // 本地调试: ./gradlew assembleDebug -Pmqtt_url=tcp://localhost:1883
        private val BROKER_URL = BuildConfig.MQTT_BROKER_URL
        private val USERNAME = BuildConfig.MQTT_USERNAME
        private val PASSWORD = BuildConfig.MQTT_PASSWORD
        private const val CLIENT_ID_PREFIX = "watch-android-"
        private const val QOS = 1
        private const val KEEP_ALIVE = 30
    }

    @Volatile var deviceId: String = deviceId
        private set

    private var client: MqttClient? = null
    @Volatile private var connected = false

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
                    // 凭证（非空时启用鉴权）
                    if (USERNAME.isNotEmpty()) userName = USERNAME
                    if (PASSWORD.isNotEmpty()) password = PASSWORD.toCharArray()
                }

                setCallback(object : MqttCallback {
                    override fun connectionLost(cause: Throwable?) {
                        Log.w(TAG, "MQTT 连接断开: ${cause?.message}")
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
                Log.i(TAG, "MQTT 已连接: $BROKER_URL")

                // 订阅预警推送
                subscribe("watch/$deviceId/alert", QOS)

                // 发布上线状态
                publishStatus(true)

                // 重连后刷新离线队列
                flushOfflineQueue()
            }
        } catch (e: Exception) {
            Log.e(TAG, "MQTT 连接失败: ${e.message}")
            connected = false
        }
    }

    /**
     * 上报生理数据 — 离线时入队缓冲
     */
    suspend fun publishVital(data: VitalReport) = withContext(Dispatchers.IO) {
        val json = Gson().toJson(data)
        if (!connected) {
            // 离线 → 写入本地队列
            offlineQueue?.enqueue("watch/$deviceId/vital", json)
            Log.d(TAG, "离线缓冲: 队列大小=${offlineQueue?.size()}")
            return@withContext
        }
        try {
            client?.publish(
                "watch/$deviceId/vital",
                MqttMessage(json.toByteArray()).apply { qos = QOS }
            )
        } catch (e: Exception) {
            // 发送失败也入队
            offlineQueue?.enqueue("watch/$deviceId/vital", json)
            Log.w(TAG, "发送失败，已入队: ${e.message}")
        }
    }

    /**
     * 发布上下线状态 — 不入队（低价值数据）
     */
    fun publishStatus(online: Boolean) {
        if (!connected) return
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
     * 离线队列回传
     */
    private suspend fun flushOfflineQueue() {
        val queue = offlineQueue ?: return
        val pending = queue.dequeuePending(50)
        if (pending.isEmpty()) return

        Log.i(TAG, "开始回传离线数据: ${pending.size} 条")
        var sent = 0
        for ((id, topic, payload) in pending) {
            try {
                client?.publish(
                    topic,
                    MqttMessage(payload.toByteArray()).apply { qos = QOS }
                )
                queue.markSent(id)
                sent++
            } catch (e: Exception) {
                queue.markRetry(id)
                Log.w(TAG, "回传失败 id=$id: ${e.message}")
            }
        }
        Log.i(TAG, "离线数据回传完成: $sent/${pending.size}")
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

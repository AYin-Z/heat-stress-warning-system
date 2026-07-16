package com.heatstress.watch

import android.util.Log
import com.google.gson.Gson
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken
import org.eclipse.paho.client.mqttv3.MqttCallbackExtended
import org.eclipse.paho.client.mqttv3.MqttClient
import org.eclipse.paho.client.mqttv3.MqttConnectOptions
import org.eclipse.paho.client.mqttv3.MqttMessage
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence

class MqttManager(
    val deviceId: String,
    private val offlineQueue: OfflineQueue
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val gson = Gson()
    private val statusTopic = "watch/$deviceId/status"
    private val vitalTopic = "watch/$deviceId/vital"
    private val alertTopic = "watch/$deviceId/alert"
    private val timeTopic = "watch/$deviceId/time"

    @Volatile private var connected = false
    @Volatile private var stopped = false
    private var flushJob: Job? = null
    private var reconnectJob: Job? = null

    private val client = MqttClient(
        BuildConfig.MQTT_BROKER_URL,
        "$CLIENT_ID_PREFIX$deviceId",
        MemoryPersistence()
    )

    var onAlertReceived: ((String) -> Unit)? = null
    var onTimeSyncReceived: ((String) -> Unit)? = null
    var onConnectionChanged: ((Boolean) -> Unit)? = null

    init {
        client.setCallback(object : MqttCallbackExtended {
            override fun connectComplete(reconnect: Boolean, serverURI: String?) {
                connected = true
                reconnectJob = null
                Log.i(TAG, "Connected to $serverURI reconnect=$reconnect")
                onConnectionChanged?.invoke(true)
                scope.launch { initializeSession() }
            }

            override fun connectionLost(cause: Throwable?) {
                connected = false
                Log.w(TAG, "Connection lost: ${cause?.message}")
                onConnectionChanged?.invoke(false)
                scheduleReconnect()
            }

            override fun messageArrived(topic: String?, message: MqttMessage?) {
                if (topic == alertTopic && message != null) {
                    onAlertReceived?.invoke(String(message.payload, Charsets.UTF_8))
                } else if (topic == timeTopic && message != null) {
                    onTimeSyncReceived?.invoke(String(message.payload, Charsets.UTF_8))
                }
            }

            override fun deliveryComplete(token: IMqttDeliveryToken?) = Unit
        })
    }

    suspend fun connectUntilAvailable() = withContext(Dispatchers.IO) {
        var delayMs = INITIAL_RETRY_MS
        while (isActive && !stopped && !client.isConnected) {
            try {
                client.connect(connectOptions())
                return@withContext
            } catch (e: Exception) {
                connected = false
                onConnectionChanged?.invoke(false)
                Log.w(TAG, "Connect failed; retry in ${delayMs}ms: ${e.message}")
                delay(delayMs)
                delayMs = (delayMs * 2).coerceAtMost(MAX_RETRY_MS)
            }
        }
    }

    suspend fun publishVital(data: VitalReport) = withContext(Dispatchers.IO) {
        val payload = gson.toJson(data)
        if (!isConnected()) {
            offlineQueue.enqueue(vitalTopic, payload)
            return@withContext
        }
        try {
            publish(vitalTopic, payload, retained = false)
        } catch (e: Exception) {
            connected = false
            offlineQueue.enqueue(vitalTopic, payload)
            onConnectionChanged?.invoke(false)
            Log.w(TAG, "Vital publish queued: ${e.message}")
        }
    }

    fun publishStatus(
        online: Boolean,
        latitude: Double? = null,
        longitude: Double? = null,
        batteryLevel: Int? = null
    ) {
        if (!isConnected()) return
        val payload = linkedMapOf<String, Any>(
            "status" to if (online) "online" else "offline",
            "timestamp" to System.currentTimeMillis()
        )
        if (latitude != null) payload["latitude"] = latitude
        if (longitude != null) payload["longitude"] = longitude
        if (batteryLevel != null) payload["batteryLevel"] = batteryLevel
        try {
            publish(statusTopic, gson.toJson(payload), retained = true)
        } catch (e: Exception) {
            Log.w(TAG, "Status publish failed: ${e.message}")
        }
    }

    fun isConnected(): Boolean = connected && client.isConnected

    fun disconnect() {
        stopped = true
        flushJob?.cancel()
        reconnectJob?.cancel()
        try {
            publishStatus(false)
            client.disconnect(2_000)
        } catch (_: Exception) {
        }
        try {
            client.close()
        } catch (_: Exception) {
        }
        connected = false
        scope.cancel()
    }

    private fun connectOptions(): MqttConnectOptions = MqttConnectOptions().apply {
        isCleanSession = false
        connectionTimeout = 8
        keepAliveInterval = 30
        isAutomaticReconnect = false
        maxInflight = 20
        setWill(statusTopic, offlineStatusPayload(), QOS, true)
        if (BuildConfig.MQTT_USERNAME.isNotBlank()) userName = BuildConfig.MQTT_USERNAME
        if (BuildConfig.MQTT_PASSWORD.isNotBlank()) password = BuildConfig.MQTT_PASSWORD.toCharArray()
        if (BuildConfig.MQTT_FALLBACK_URL.isNotBlank()) {
            serverURIs = arrayOf(BuildConfig.MQTT_BROKER_URL, BuildConfig.MQTT_FALLBACK_URL)
        }
    }

    private suspend fun initializeSession() {
        try {
            client.subscribe(arrayOf(alertTopic, timeTopic), intArrayOf(QOS, QOS))
            publishStatus(true)
            flushOfflineQueue()
        } catch (e: Exception) {
            Log.w(TAG, "Session initialization failed: ${e.message}")
        }
    }

    @Synchronized
    private fun scheduleReconnect() {
        if (stopped || reconnectJob?.isActive == true) return
        reconnectJob = scope.launch { connectUntilAvailable() }
    }

    private fun flushOfflineQueue() {
        if (flushJob?.isActive == true) return
        flushJob = scope.launch {
            var sent = 0
            while (isActive && isConnected()) {
                val batch = offlineQueue.dequeuePending(FLUSH_BATCH_SIZE)
                if (batch.isEmpty()) break
                for ((id, topic, payload) in batch) {
                    if (!isConnected()) return@launch
                    try {
                        publish(topic, payload, retained = false)
                        offlineQueue.markSent(id)
                        sent++
                    } catch (e: Exception) {
                        offlineQueue.markRetry(id)
                        Log.w(TAG, "Queue flush paused at id=$id: ${e.message}")
                        return@launch
                    }
                }
                delay(100)
            }
            if (sent > 0) Log.i(TAG, "Flushed $sent queued records")
        }
    }

    @Synchronized
    private fun publish(topic: String, payload: String, retained: Boolean) {
        if (!client.isConnected) throw IllegalStateException("MQTT disconnected")
        client.publish(topic, MqttMessage(payload.toByteArray(Charsets.UTF_8)).apply {
            qos = QOS
            isRetained = retained
        })
    }

    private fun offlineStatusPayload(): ByteArray =
        "{\"status\":\"offline\"}".toByteArray(Charsets.UTF_8)

    companion object {
        private const val TAG = "MqttManager"
        private const val CLIENT_ID_PREFIX = "a80-heatstress-"
        private const val QOS = 1
        private const val INITIAL_RETRY_MS = 2_000L
        private const val MAX_RETRY_MS = 60_000L
        private const val FLUSH_BATCH_SIZE = 100
    }
}

data class VitalReport(
    val deviceId: String,
    val timestamp: Long,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val gpsAccuracy: Float? = null,
    val heartRate: Int? = null,
    val spo2: Int? = null,
    val bloodPressure: String? = null,
    val coreTemp: Double? = null,
    val coreTempSource: String? = null,
    val steps: Int? = null,
    val batteryLevel: Int,
    val worn: Boolean? = null,
    val dataQuality: String,
    val firmwareVersion: String = BuildConfig.VERSION_NAME
)

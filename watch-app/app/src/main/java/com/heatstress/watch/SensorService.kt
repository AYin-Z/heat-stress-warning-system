package com.heatstress.watch

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.os.Vibrator
import android.provider.Settings
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import com.google.gson.JsonParser
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume
import kotlin.math.roundToInt

class SensorService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private lateinit var sensorManager: SensorManager
    private lateinit var locationManager: LocationManager
    private lateinit var offlineQueue: OfflineQueue
    private lateinit var mqttManager: MqttManager
    private var heartSensor: Sensor? = null
    private val coreEstimator = CoreTemperatureEstimator()

    @Volatile private var heartRate: Int? = null
    @Volatile private var spo2: Int? = null
    @Volatile private var systolic: Int? = null
    @Volatile private var diastolic: Int? = null
    @Volatile private var coreTemperature: Double? = null
    @Volatile private var steps: Int? = null
    @Volatile private var worn: Boolean? = null
    @Volatile private var batteryLevel = 0
    @Volatile private var latitude: Double? = null
    @Volatile private var longitude: Double? = null
    @Volatile private var gpsAccuracy: Float? = null
    @Volatile private var lastLocationElapsedMs = 0L

    private var lastHeartSampleMs = 0L
    private var lastSpo2SampleMs = 0L
    private var lastStatusPublishMs = 0L
    private var locationUpdatesStarted = false

    private val stateRequestReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == ACTION_REQUEST_STATE) broadcastState()
        }
    }

    private val locationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            latitude = location.latitude
            longitude = location.longitude
            gpsAccuracy = location.accuracy.takeIf { location.hasAccuracy() }
            lastLocationElapsedMs = SystemClock.elapsedRealtime()
            broadcastState()
        }

        override fun onProviderDisabled(provider: String) {
            if (provider == LocationManager.GPS_PROVIDER) gpsAccuracy = null
        }

        override fun onProviderEnabled(provider: String) = Unit
    }

    override fun onCreate() {
        super.onCreate()
        sensorManager = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        heartSensor = sensorManager.getDefaultSensor(Sensor.TYPE_HEART_RATE)
        JuWeiSystemApi.applyPowerSaveExemption(this)

        offlineQueue = OfflineQueue(this).apply { open() }
        mqttManager = MqttManager(resolveDeviceId(), offlineQueue).apply {
            onConnectionChanged = { broadcastState() }
            onAlertReceived = { payload -> handleAlert(payload) }
            onTimeSyncReceived = { payload ->
                serviceScope.launch { handleTimeSync(payload) }
            }
        }

        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("正在启动监测"))
        LocalBroadcastManager.getInstance(this).registerReceiver(
            stateRequestReceiver,
            IntentFilter(ACTION_REQUEST_STATE)
        )
        startWorkers()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        try {
            LocalBroadcastManager.getInstance(this).unregisterReceiver(stateRequestReceiver)
        } catch (_: IllegalArgumentException) {
        }
        if (locationUpdatesStarted) locationManager.removeUpdates(locationListener)
        JuWeiSystemProperties.set(HEART_MODE_PROPERTY, MODE_HEART)
        mqttManager.disconnect()
        offlineQueue.close()
        serviceScope.cancel()
        super.onDestroy()
    }

    private fun startWorkers() {
        serviceScope.launch { mqttManager.connectUntilAvailable() }
        serviceScope.launch {
            delay(2_000L)
            while (isActive) {
                val result = NtpSync.synchronizeClock()
                Log.i(TAG, "Time sync: ${result.message}, drift=${result.driftMs}")
                delay(if (result.success) TIME_SYNC_INTERVAL_MS else TIME_SYNC_RETRY_MS)
            }
        }
        serviceScope.launch {
            while (isActive) {
                val cycleStarted = SystemClock.elapsedRealtime()
                try {
                    withCollectionWakeLock { collectAndReport() }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    Log.e(TAG, "Collection cycle failed", e)
                }
                val elapsed = SystemClock.elapsedRealtime() - cycleStarted
                delay((REPORT_INTERVAL_MS - elapsed).coerceAtLeast(1_000L))
            }
        }
    }

    private suspend fun collectAndReport() {
        ensureLocationUpdates()
        updateBatteryLevel()
        steps = JuWeiSystemApi.getStepCount(this) ?: readStandardStepCounter()

        val heartFrame = readHeartAndBloodPressure()
        if (heartFrame != null) {
            worn = heartFrame.worn
            if (heartFrame.worn == false) {
                clearVitalsForNoWear()
            } else {
                heartFrame.heartRate?.let { heartRate = it }
                heartFrame.heartRate?.let { coreTemperature = coreEstimator.update(it) }
                heartFrame.systolic?.let { systolic = it }
                heartFrame.diastolic?.let { diastolic = it }
                if (heartFrame.heartRate != null || heartFrame.systolic != null) {
                    lastHeartSampleMs = SystemClock.elapsedRealtime()
                }
            }
        }

        val now = SystemClock.elapsedRealtime()
        if (lastSpo2SampleMs == 0L || now - lastSpo2SampleMs >= SPO2_INTERVAL_MS) {
            val oxygenFrame = readBloodOxygen()
            JuWeiSystemProperties.set(HEART_MODE_PROPERTY, MODE_HEART)
            if (oxygenFrame != null) {
                worn = oxygenFrame.worn
                if (oxygenFrame.worn == false) {
                    clearVitalsForNoWear()
                } else if (oxygenFrame.spo2 != null) {
                    spo2 = oxygenFrame.spo2
                    lastSpo2SampleMs = SystemClock.elapsedRealtime()
                }
            }
        }

        expireStaleValues()
        val report = currentReport()
        mqttManager.publishVital(report)
        Log.i(
            TAG,
            "Report connected=${mqttManager.isConnected()} worn=${report.worn} " +
                "hr=${report.heartRate} spo2=${report.spo2} bp=${report.bloodPressure} " +
                "core=${report.coreTemp} steps=${report.steps} gps=${report.latitude},${report.longitude} " +
                "quality=${report.dataQuality} queued=${offlineQueue.size()}"
        )

        if (now - lastStatusPublishMs >= STATUS_INTERVAL_MS) {
            mqttManager.publishStatus(true, report.latitude, report.longitude, batteryLevel)
            lastStatusPublishMs = now
        }
        broadcastState()
        updateNotification(summaryText())
    }

    private suspend fun readHeartAndBloodPressure(): SensorFrame? {
        val sensor = heartSensor ?: return null
        if (!JuWeiSystemProperties.set(HEART_MODE_PROPERTY, MODE_HEART)) {
            Log.w(TAG, "Unable to select heart-rate mode")
        }
        delay(MODE_SETTLE_MS)
        val wearReadyAt = SystemClock.elapsedRealtime() + WEAR_SETTLE_MS
        return readSensorFrame(sensor) { event ->
            val wear = event.wearState()
            val wearStable = SystemClock.elapsedRealtime() >= wearReadyAt
            if (wear != null && wearStable) worn = wear
            if (wear == false) {
                return@readSensorFrame if (wearStable) SensorFrame(worn = false) else null
            }
            val hr = event.valueAt(0)?.roundToInt()?.takeIf { it in 30..250 }
            val sys = event.valueAt(2)?.roundToInt()?.takeIf { it in 70..230 }
            val dia = event.valueAt(3)?.roundToInt()?.takeIf { it in 40..160 }
            if (hr == null && (sys == null || dia == null)) return@readSensorFrame null
            SensorFrame(
                heartRate = hr,
                systolic = sys?.takeIf { dia != null },
                diastolic = dia?.takeIf { sys != null },
                worn = wear
            )
        }
    }

    private suspend fun readBloodOxygen(): SensorFrame? {
        val sensor = heartSensor ?: return null
        if (!JuWeiSystemProperties.set(HEART_MODE_PROPERTY, MODE_BLOOD_OXYGEN)) return null
        delay(MODE_SETTLE_MS)
        val wearReadyAt = SystemClock.elapsedRealtime() + WEAR_SETTLE_MS
        return readSensorFrame(sensor) { event ->
            val wear = event.wearState()
            val wearStable = SystemClock.elapsedRealtime() >= wearReadyAt
            if (wear != null && wearStable) worn = wear
            if (wear == false) {
                return@readSensorFrame if (wearStable) SensorFrame(worn = false) else null
            }
            val value = event.valueAt(1)?.roundToInt()?.takeIf { it in 70..100 } ?: return@readSensorFrame null
            SensorFrame(spo2 = value, worn = wear)
        }
    }

    private suspend fun readSensorFrame(
        sensor: Sensor,
        mapper: (SensorEvent) -> SensorFrame?
    ): SensorFrame? = withTimeoutOrNull(SENSOR_TIMEOUT_MS) {
        suspendCancellableCoroutine { continuation ->
            val listener = object : SensorEventListener {
                override fun onSensorChanged(event: SensorEvent?) {
                    val frame = event?.let(mapper) ?: return
                    sensorManager.unregisterListener(this)
                    if (continuation.isActive) continuation.resume(frame)
                }

                override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
            }
            val registered = sensorManager.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_NORMAL)
            if (!registered && continuation.isActive) continuation.resume(null)
            continuation.invokeOnCancellation { sensorManager.unregisterListener(listener) }
        }
    }

    private fun SensorEvent.valueAt(index: Int): Float? = values.getOrNull(index)

    private fun SensorEvent.wearState(): Boolean? =
        valueAt(7)?.roundToInt()?.let { it == WEAR_ON_WRIST }

    private suspend fun readStandardStepCounter(): Int? {
        val sensor = sensorManager.getDefaultSensor(Sensor.TYPE_STEP_COUNTER) ?: return null
        return withTimeoutOrNull(STEP_TIMEOUT_MS) {
            suspendCancellableCoroutine { continuation ->
                val listener = object : SensorEventListener {
                    override fun onSensorChanged(event: SensorEvent?) {
                        val value = event?.values?.getOrNull(0)?.toInt() ?: return
                        sensorManager.unregisterListener(this)
                        if (continuation.isActive) continuation.resume(value)
                    }

                    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
                }
                val registered = sensorManager.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_NORMAL)
                if (!registered && continuation.isActive) continuation.resume(null)
                continuation.invokeOnCancellation { sensorManager.unregisterListener(listener) }
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun ensureLocationUpdates() {
        if (locationUpdatesStarted) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) !=
            PackageManager.PERMISSION_GRANTED
        ) return

        if (!locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
            JuWeiSystemApi.setGpsEnabled(this, true)
        }
        try {
            locationManager.requestLocationUpdates(
                LocationManager.GPS_PROVIDER,
                GPS_INTERVAL_MS,
                GPS_MIN_DISTANCE_M,
                locationListener,
                Looper.getMainLooper()
            )
            locationUpdatesStarted = true
            locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)?.let { location ->
                val age = SystemClock.elapsedRealtimeNanos() - location.elapsedRealtimeNanos
                if (age in 0..GPS_LAST_KNOWN_MAX_AGE_NS) locationListener.onLocationChanged(location)
            }
        } catch (e: Exception) {
            Log.w(TAG, "GPS registration failed: ${e.message}")
        }
    }

    private fun currentReport(): VitalReport {
        val locationFresh = lastLocationElapsedMs > 0L &&
            SystemClock.elapsedRealtime() - lastLocationElapsedMs <= GPS_STALE_MS
        val bp = if (systolic != null && diastolic != null) "$systolic/$diastolic" else null
        val quality = when {
            worn == false -> "not_worn"
            heartRate != null && spo2 != null && bp != null && coreTemperature != null -> "complete"
            heartRate != null || spo2 != null || bp != null || coreTemperature != null -> "partial"
            else -> "no_vitals"
        }
        return VitalReport(
            deviceId = mqttManager.deviceId,
            timestamp = System.currentTimeMillis(),
            latitude = latitude.takeIf { locationFresh },
            longitude = longitude.takeIf { locationFresh },
            gpsAccuracy = gpsAccuracy.takeIf { locationFresh },
            heartRate = heartRate,
            spo2 = spo2,
            bloodPressure = bp,
            coreTemp = coreTemperature,
            coreTempSource = coreTemperature?.let { CoreTemperatureEstimator.SOURCE },
            steps = steps,
            batteryLevel = batteryLevel,
            worn = worn,
            dataQuality = quality
        )
    }

    private fun clearVitalsForNoWear() {
        heartRate = null
        spo2 = null
        systolic = null
        diastolic = null
        coreTemperature = null
        coreEstimator.reset()
        lastHeartSampleMs = 0L
        lastSpo2SampleMs = 0L
    }

    private fun expireStaleValues() {
        val now = SystemClock.elapsedRealtime()
        if (lastHeartSampleMs > 0L && now - lastHeartSampleMs > VITAL_STALE_MS) {
            heartRate = null
            systolic = null
            diastolic = null
            coreTemperature = null
        }
        if (lastSpo2SampleMs > 0L && now - lastSpo2SampleMs > VITAL_STALE_MS) spo2 = null
        if (lastLocationElapsedMs > 0L && now - lastLocationElapsedMs > GPS_STALE_MS) gpsAccuracy = null
    }

    private fun updateBatteryLevel() {
        val battery = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return
        val level = battery.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = battery.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level >= 0 && scale > 0) batteryLevel = level * 100 / scale
    }

    private fun handleAlert(payload: String) {
        try {
            val json = JsonParser.parseString(payload).asJsonObject
            val type = json.get("alertType")?.asString ?: "热应激预警"
            val advice = json.get("advice")?.asString?.takeIf { it.isNotBlank() }
                ?: "请立即停止活动并转移至阴凉处"
            LocalBroadcastManager.getInstance(this).sendBroadcast(
                Intent(ACTION_ALERT_UPDATE)
                    .putExtra(EXTRA_ALERT_TYPE, type)
                    .putExtra(EXTRA_ALERT_ADVICE, advice)
            )
            val vibrator = getSystemService(Vibrator::class.java)
            @Suppress("DEPRECATION")
            vibrator.vibrate(longArrayOf(0, 500, 250, 500, 250, 800), -1)
            updateNotification("$type：$advice")
        } catch (e: Exception) {
            Log.w(TAG, "Invalid alert payload: ${e.message}")
        }
    }

    private fun handleTimeSync(payload: String) {
        try {
            val json = JsonParser.parseString(payload).asJsonObject
            if (json.get("source")?.asString != "heatstress-bridge") {
                Log.w(TAG, "Ignoring time sync from unknown source")
                return
            }
            val timestamp = json.get("timestamp")?.asLong
                ?: throw IllegalArgumentException("timestamp missing")
            val result = NtpSync.applyServerTime(timestamp)
            Log.i(TAG, "MQTT time sync: ${result.message}, drift=${result.driftMs}")
            if (result.corrected) {
                mqttManager.publishStatus(true, latitude, longitude, batteryLevel)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Invalid time sync payload: ${e.message}")
        }
    }

    private fun broadcastState() {
        val intent = Intent(ACTION_STATE_UPDATE).setPackage(packageName)
            .putExtra(EXTRA_CONNECTED, mqttManager.isConnected())
            .putExtra(EXTRA_BATTERY, batteryLevel)
            .putExtra(EXTRA_WORN, when (worn) { true -> 1; false -> 0; null -> -1 })
            .putExtra(EXTRA_SUMMARY, summaryText())
        heartRate?.let { intent.putExtra(EXTRA_HEART_RATE, it) }
        spo2?.let { intent.putExtra(EXTRA_SPO2, it) }
        systolic?.let { intent.putExtra(EXTRA_BP_SYS, it) }
        diastolic?.let { intent.putExtra(EXTRA_BP_DIA, it) }
        coreTemperature?.let { intent.putExtra(EXTRA_CORE_TEMP, it) }
        steps?.let { intent.putExtra(EXTRA_STEPS, it) }
        gpsAccuracy?.let { intent.putExtra(EXTRA_GPS_ACCURACY, it) }
        LocalBroadcastManager.getInstance(this).sendBroadcast(intent)
    }

    private fun summaryText(): String = when {
        heartSensor == null -> "心率传感器不可用"
        worn == false -> "请贴紧皮肤重新佩戴"
        !mqttManager.isConnected() && offlineQueue.size() > 0 -> "网络离线，数据已安全缓存"
        !mqttManager.isConnected() -> "传感器运行中，等待网络"
        heartRate == null -> "中继已连接，正在读取传感器"
        else -> "监测和上报运行正常"
    }

    private suspend fun <T> withCollectionWakeLock(block: suspend () -> T): T {
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        val wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "HeatStress:CollectCycle")
        return try {
            wakeLock.acquire(CYCLE_WAKELOCK_TIMEOUT_MS)
            block()
        } finally {
            try {
                if (wakeLock.isHeld) wakeLock.release()
            } catch (_: Exception) {
            }
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "热应激监测",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "A80 生理数据采集与上报"
            setShowBadge(false)
        }
        (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
            .createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("热应激监测运行中")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

    private fun updateNotification(text: String) {
        (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
            .notify(NOTIFICATION_ID, buildNotification(text))
    }

    @Suppress("DEPRECATION")
    private fun resolveDeviceId(): String {
        BuildConfig.DEVICE_ID.trim().takeIf { it.isNotEmpty() }?.let { return it }
        val serial = Build.SERIAL.takeIf { it.isNotBlank() && it != Build.UNKNOWN }
        if (serial != null) return "A80-$serial"
        val androidId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
        return "A80-${androidId.takeLast(12)}"
    }

    private data class SensorFrame(
        val heartRate: Int? = null,
        val spo2: Int? = null,
        val systolic: Int? = null,
        val diastolic: Int? = null,
        val worn: Boolean? = null
    )

    companion object {
        private const val TAG = "HeatStress"
        private const val CHANNEL_ID = "heatstress_collection"
        private const val NOTIFICATION_ID = 1
        private const val HEART_MODE_PROPERTY = "persist.sys.heartrate_test_mode"
        private const val MODE_HEART = "1"
        private const val MODE_BLOOD_OXYGEN = "2"
        private const val WEAR_ON_WRIST = 2

        private const val REPORT_INTERVAL_MS = 15_000L
        private const val SPO2_INTERVAL_MS = 60_000L
        private const val STATUS_INTERVAL_MS = 60_000L
        private const val SENSOR_TIMEOUT_MS = 5_000L
        private const val STEP_TIMEOUT_MS = 2_000L
        private const val MODE_SETTLE_MS = 250L
        private const val WEAR_SETTLE_MS = 1_500L
        private const val VITAL_STALE_MS = 3 * 60_000L
        private const val GPS_INTERVAL_MS = 30_000L
        private const val GPS_MIN_DISTANCE_M = 5f
        private const val GPS_STALE_MS = 10 * 60_000L
        private const val GPS_LAST_KNOWN_MAX_AGE_NS = 10 * 60_000_000_000L
        private const val CYCLE_WAKELOCK_TIMEOUT_MS = 14_000L
        private const val TIME_SYNC_INTERVAL_MS = 6 * 60 * 60_000L
        private const val TIME_SYNC_RETRY_MS = 5 * 60_000L

        const val ACTION_STATE_UPDATE = "com.heatstress.watch.STATE_UPDATE"
        const val ACTION_ALERT_UPDATE = "com.heatstress.watch.ALERT_UPDATE"
        const val ACTION_REQUEST_STATE = "com.heatstress.watch.REQUEST_STATE"
        const val EXTRA_CONNECTED = "connected"
        const val EXTRA_BATTERY = "battery"
        const val EXTRA_HEART_RATE = "heart_rate"
        const val EXTRA_SPO2 = "spo2"
        const val EXTRA_BP_SYS = "bp_sys"
        const val EXTRA_BP_DIA = "bp_dia"
        const val EXTRA_CORE_TEMP = "core_temp"
        const val EXTRA_STEPS = "steps"
        const val EXTRA_WORN = "worn"
        const val EXTRA_GPS_ACCURACY = "gps_accuracy"
        const val EXTRA_SUMMARY = "summary"
        const val EXTRA_ALERT_TYPE = "alert_type"
        const val EXTRA_ALERT_ADVICE = "alert_advice"
    }
}

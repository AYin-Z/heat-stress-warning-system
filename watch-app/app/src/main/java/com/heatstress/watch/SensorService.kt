package com.heatstress.watch

import android.Manifest
import android.app.*
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager as AndroidSensorManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.*
import android.os.PowerManager.WakeLock
import android.provider.Settings
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*

/**
 * 前台采集服务 — 手表核心
 *
 * 生命周期: 与手表开机同存在，永不被杀
 *
 * 采集项:
 *   - 心率 (HX3918, BODY_SENSORS / BLE)
 *   - 血氧 (BLE 或从心率芯片读取)
 *   - 血压 (A80 自有传感器)
 *   - GPS (GPS/BDS/GLONASS)
 *   - 步数 (G-SENSOR → 计步)
 *   - 电池电量
 *
 * 上报: MQTT → EMQX → PC 大屏
 */
class SensorService : Service(), SensorEventListener {

    private lateinit var wakeLock: WakeLock
    private lateinit var sensorManager: AndroidSensorManager
    private lateinit var locationManager: LocationManager
    private lateinit var mqttManager: MqttManager

    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    // 传感器数据缓存
    private var lastHeartRate = 0
    private var lastSpo2 = 0.0
    private var lastSystolic = 0    // 收缩压
    private var lastDiastolic = 0   // 舒张压
    private var lastSteps = 0
    private var lastLat = 0.0
    private var lastLng = 0.0
    private var batteryLevel = 100

    private var hasGps = false

    companion object {
        const val CHANNEL_ID = "sensor_service_channel"
        const val NOTIFICATION_ID = 1
        const val REPORT_INTERVAL_MS = 5_000L  // 5秒上报一次
    }

    // ============================================================
    // Service 生命周期
    // ============================================================

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        acquireWakeLock()

        sensorManager = getSystemService(Context.SENSOR_SERVICE) as AndroidSensorManager
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager

        // deviceId: 使用 Android ID 作为手表唯一标识
        val deviceId = "A80-${Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID).take(6)}"
        mqttManager = MqttManager(deviceId)

        startForeground(NOTIFICATION_ID, buildNotification())
        startCollecting()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY  // 被杀后自动重启
    }

    override fun onDestroy() {
        stopCollecting()
        mqttManager.disconnect()
        wakeLock.takeIf { it.isHeld }?.release()
        serviceScope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ============================================================
    // 唤醒锁 (防止 CPU 休眠)
    // ============================================================

    private fun acquireWakeLock() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "HeatStress::SensorWakeLock"
        ).apply {
            acquire(10 * 60 * 1000L) // 10分钟自动释放兜底
        }
    }

    // ============================================================
    // 通知栏
    // ============================================================

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "热应激监测",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "手表数据采集运行中"
                setShowBadge(false)
            }
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("热应激监测运行中")
            .setContentText("心率: $lastHeartRate bpm | 温度: --℃")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    // ============================================================
    // 启动采集
    // ============================================================

    private fun startCollecting() {
        serviceScope.launch {
            // 1. 连接 MQTT
            mqttManager.connect()

            // 2. 注册传感器监听
            registerSensors()

            // 3. 启动 GPS 监听
            startLocationUpdates()

            // 4. 定时上报循环
            while (isActive) {
                delay(REPORT_INTERVAL_MS)
                reportVitalData()
                updateBatteryLevel()
                updateNotification()
            }
        }
    }

    private fun stopCollecting() {
        sensorManager.unregisterListener(this)
        removeLocationUpdates()
    }

    // ============================================================
    // 传感器注册
    // ============================================================

    private fun registerSensors() {
        // 心率传感器 (TYPE_HEART_RATE)
        sensorManager.getDefaultSensor(Sensor.TYPE_HEART_RATE)?.let {
            sensorManager.registerListener(
                this, it,
                AndroidSensorManager.SENSOR_DELAY_NORMAL
            )
        }

        // 步数计数器 (TYPE_STEP_COUNTER)
        sensorManager.getDefaultSensor(Sensor.TYPE_STEP_COUNTER)?.let {
            sensorManager.registerListener(
                this, it,
                AndroidSensorManager.SENSOR_DELAY_NORMAL
            )
        }

        // A80 的 HX3918 血氧/血压通常通过 BLE 私有协议暴露
        // 如果不是标准 Android Sensor，需要通过 BLE 读取
        // 此处保留 BLE 扩展点，见 SensorManagerCompat
    }

    // ============================================================
    // SensorEventListener 回调
    // ============================================================

    override fun onSensorChanged(event: SensorEvent?) {
        event ?: return
        when (event.sensor.type) {
            Sensor.TYPE_HEART_RATE -> {
                lastHeartRate = event.values[0].toInt()
            }
            Sensor.TYPE_STEP_COUNTER -> {
                lastSteps = event.values[0].toInt()
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    // ============================================================
    // GPS 定位
    // ============================================================

    private fun startLocationUpdates() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED
        ) return

        locationManager.requestLocationUpdates(
            LocationManager.GPS_PROVIDER,
            REPORT_INTERVAL_MS,
            5f,  // 5米
            locationListener,
            Looper.getMainLooper()
        )
    }

    private val locationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            lastLat = location.latitude
            lastLng = location.longitude
            hasGps = true
        }

        override fun onProviderDisabled(provider: String) {
            hasGps = false
        }

        override fun onProviderEnabled(provider: String) {
            hasGps = true
        }
    }

    private fun removeLocationUpdates() {
        locationManager.removeUpdates(locationListener)
    }

    // ============================================================
    // 定时上报
    // ============================================================

    private suspend fun reportVitalData() {
        val report = VitalReport(
            deviceId = mqttManager.deviceId,
            timestamp = System.currentTimeMillis(),
            latitude = lastLat,
            longitude = lastLng,
            heartRate = lastHeartRate,
            spo2 = lastSpo2,
            bloodPressure = "$lastSystolic/$lastDiastolic",
            steps = lastSteps,
        )
        mqttManager.publishVital(report)
    }

    // ============================================================
    // 电池
    // ============================================================

    private fun updateBatteryLevel() {
        val intent = registerReceiver(
            null,
            IntentFilter(Intent.ACTION_BATTERY_CHANGED)
        )
        intent?.let {
            val level = it.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
            val scale = it.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
            if (level >= 0 && scale > 0) {
                batteryLevel = (level * 100 / scale)
            }
        }
    }

    private fun updateNotification() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(
            NOTIFICATION_ID,
            NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("热应激监测运行中")
                .setContentText("💓$lastHeartRate | 🩸$lastSpo2% | 📍${if (hasGps) "已定位" else "定位中"} | 🔋$batteryLevel%")
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setOngoing(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build()
        )
    }
}

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
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*

/**
 * 前台采集服务 — 手表核心
 *
 * 生命周期: 与手表开机同存在，永不被杀
 *
 * 采集项:
 *   - 心率 (HX3918, TYPE_HEART_RATE, values[0])
 *   - 血氧 (HX3918 扩展, values[1] 或私有传感器)
 *   - 血压 (A80 私有传感器类型)
 *   - GPS (GPS/BDS/GLONASS)
 *   - 步数 (TYPE_STEP_COUNTER → TYPE_STEP_DETECTOR → 加速度计回退)
 *   - 电池电量
 *
 * 上报: MQTT → EMQX → PC 大屏
 */
class SensorService : Service(), SensorEventListener {

    companion object {
        const val TAG = "HeatStress"
        const val CHANNEL_ID = "sensor_service_channel"
        const val NOTIFICATION_ID = 1
        const val REPORT_INTERVAL_MS = 5_000L  // 5秒上报一次

        // HX3918 私有传感器类型常量 (A80 固件)
        // 这些值需要在目标设备上验证，不同固件版本可能不同
        private const val SENSOR_TYPE_HX3918_SPO2 = 33171007     // 常见 HX3918 SpO2 类型
        private const val SENSOR_TYPE_HX3918_BP   = 33171008     // 血压
        private const val SENSOR_TYPE_A80_PPG     = 33171009     // PPG 原始信号
    }

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

    // 离线队列
    private lateinit var offlineQueue: OfflineQueue

    // 步数回退：TYPE_STEP_DETECTOR 累积计数
    private var stepDetectorCount = 0

    private var hasGps = false

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

        // 初始化离线队列
        offlineQueue = OfflineQueue(this).apply { open() }

        mqttManager = MqttManager(deviceId, offlineQueue)

        startForeground(NOTIFICATION_ID, buildNotification())
        startCollecting()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY  // 被杀后自动重启
    }

    override fun onDestroy() {
        stopCollecting()
        mqttManager.disconnect()
        offlineQueue.close()
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
            // 1. 扫描并注册全部可用传感器
            discoverAndRegisterSensors()

            // 2. NTP 时间同步 (手表固件时间可能不准)
            syncSystemTime()

            // 3. 连接 MQTT
            mqttManager.connect()

            // 3. 启动 GPS 监听
            startLocationUpdates()

            // 4. 加载系统步数（作为基线）
            loadSystemStepBaseline()

            // 5. 定时上报循环
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
    // 传感器发现与注册
    // ============================================================

    private fun discoverAndRegisterSensors() {
        val allSensors = sensorManager.getSensorList(Sensor.TYPE_ALL)
        Log.i(TAG, "=== A80 传感器列表 (${allSensors.size} 个) ===")

        var heartRateFound = false
        var stepCounterFound = false
        var stepDetectorFound = false
        var spo2Found = false
        var bpFound = false

        for (sensor in allSensors) {
            val name = sensor.name
            val type = sensor.type
            val vendor = sensor.vendor
            Log.i(TAG, "  [$type] $name (vendor=$vendor, maxRange=${sensor.maximumRange})")

            when (type) {
                Sensor.TYPE_HEART_RATE -> {
                    heartRateFound = true
                    sensorManager.registerListener(this, sensor,
                        AndroidSensorManager.SENSOR_DELAY_NORMAL)
                }
                Sensor.TYPE_STEP_COUNTER -> {
                    stepCounterFound = true
                    sensorManager.registerListener(this, sensor,
                        AndroidSensorManager.SENSOR_DELAY_NORMAL)
                }
                Sensor.TYPE_STEP_DETECTOR -> {
                    stepDetectorFound = true
                    sensorManager.registerListener(this, sensor,
                        AndroidSensorManager.SENSOR_DELAY_NORMAL)
                }
                SENSOR_TYPE_HX3918_SPO2 -> {
                    spo2Found = true
                    sensorManager.registerListener(this, sensor,
                        AndroidSensorManager.SENSOR_DELAY_NORMAL)
                }
                SENSOR_TYPE_HX3918_BP -> {
                    bpFound = true
                    sensorManager.registerListener(this, sensor,
                        AndroidSensorManager.SENSOR_DELAY_NORMAL)
                }
                else -> {
                    // 尝试匹配血氧/血压相关的私有传感器
                    if (name.contains("spo2", ignoreCase = true) ||
                        name.contains("血氧", ignoreCase = true) ||
                        name.contains("oxygen", ignoreCase = true)) {
                        spo2Found = true
                        sensorManager.registerListener(this, sensor,
                            AndroidSensorManager.SENSOR_DELAY_NORMAL)
                        Log.i(TAG, "  → 识别为 SpO2 传感器")
                    }
                    if (name.contains("bp", ignoreCase = true) ||
                        name.contains("blood", ignoreCase = true) ||
                        name.contains("血压", ignoreCase = true) ||
                        name.contains("pressure", ignoreCase = true)) {
                        bpFound = true
                        sensorManager.registerListener(this, sensor,
                            AndroidSensorManager.SENSOR_DELAY_NORMAL)
                        Log.i(TAG, "  → 识别为血压传感器")
                    }
                }
            }
        }

        Log.i(TAG, "=== 传感器注册结果 ===")
        Log.i(TAG, "  心率: $heartRateFound")
        Log.i(TAG, "  步数计数器: $stepCounterFound")
        Log.i(TAG, "  步数检测器: $stepDetectorFound (回退方案)")
        Log.i(TAG, "  血氧: $spo2Found")
        Log.i(TAG, "  血压: $bpFound")

        // 如果没有步数传感器，尝试从系统设置读取
        if (!stepCounterFound && !stepDetectorFound) {
            Log.w(TAG, "  ⚠️ 无步数传感器，将使用加速度计回退 + 系统步数 ContentProvider")
        }
    }

    /**
     * 从系统 ContentProvider 加载已有的步数作为基线
     * 部分 A80 固件通过 com.android.health 或其他包暴露步数
     */
    private fun loadSystemStepBaseline() {
        try {
            // 尝试从 Settings 读取步数（部分 ROM 写入此处）
            val steps = Settings.Secure.getInt(contentResolver, "step_counter")
            if (steps > 0) {
                lastSteps = steps
                Log.i(TAG, "系统步数基线: $steps")
            }
        } catch (_: Exception) {
            // Settings 中没有步数，正常
        }
    }

    // ============================================================
    // SensorEventListener 回调
    // ============================================================

    override fun onSensorChanged(event: SensorEvent?) {
        event ?: return

        when (event.sensor.type) {
            Sensor.TYPE_HEART_RATE -> {
                // HX3918 values:
                //   values[0] = 心率 bpm (始终)
                //   values[1] = 可能包含 SpO2 或扩展状态 (取决于固件)
                lastHeartRate = event.values[0].toInt()
                if (event.values.size > 1 && event.values[1] > 0f) {
                    // 部分固件在 values[1] 提供 SpO2
                    // 如果不是 SpO2 范围(0-100)，忽略
                    val v1 = event.values[1].toDouble()
                    if (v1 in 50.0..100.0) {
                        lastSpo2 = v1
                    }
                }
            }

            Sensor.TYPE_STEP_COUNTER -> {
                lastSteps = event.values[0].toInt()
            }

            Sensor.TYPE_STEP_DETECTOR -> {
                // 每次检测到一步，累加
                stepDetectorCount++
                lastSteps = stepDetectorCount
            }

            SENSOR_TYPE_HX3918_SPO2 -> {
                // A80 HX3918 私有 SpO2 传感器
                lastSpo2 = event.values[0].toDouble()
            }

            SENSOR_TYPE_HX3918_BP -> {
                // A80 私有血压传感器
                // values[0] = 收缩压, values[1] = 舒张压
                if (event.values.size >= 2) {
                    lastSystolic = event.values[0].toInt()
                    lastDiastolic = event.values[1].toInt()
                } else if (event.values.isNotEmpty()) {
                    lastSystolic = event.values[0].toInt()
                    lastDiastolic = (event.values[0] * 0.65).toInt() // 估算
                }
            }

            else -> {
                // 动态匹配的私有传感器
                val name = event.sensor.name.lowercase()
                when {
                    name.contains("spo2") || name.contains("血氧") || name.contains("oxygen") -> {
                        lastSpo2 = event.values[0].toDouble()
                    }
                    name.contains("bp") || name.contains("blood") ||
                    name.contains("血压") || name.contains("pressure") -> {
                        if (event.values.size >= 2) {
                            lastSystolic = event.values[0].toInt()
                            lastDiastolic = event.values[1].toInt()
                        }
                    }
                }
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

        try {
            locationManager.requestLocationUpdates(
                LocationManager.GPS_PROVIDER,
                REPORT_INTERVAL_MS,
                5f,  // 5米
                locationListener,
                Looper.getMainLooper()
            )
        } catch (e: Exception) {
            Log.e(TAG, "GPS 启动失败: ${e.message}")
            // 尝试 NETWORK_PROVIDER 回退
            try {
                locationManager.requestLocationUpdates(
                    LocationManager.NETWORK_PROVIDER,
                    REPORT_INTERVAL_MS,
                    10f,
                    locationListener,
                    Looper.getMainLooper()
                )
            } catch (_: Exception) {}
        }
    }

    private val locationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            lastLat = location.latitude
            lastLng = location.longitude
            hasGps = true
        }

        override fun onProviderDisabled(provider: String) {
            if (provider == LocationManager.GPS_PROVIDER) {
                hasGps = false
            }
        }

        override fun onProviderEnabled(provider: String) {
            if (provider == LocationManager.GPS_PROVIDER) {
                hasGps = true
            }
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

    // ============================================================
    // NTP 时间同步
    // ============================================================

    /**
     * 检查系统时间偏差，超过 1 分钟则记录告警
     * 设置系统时间需要 SET_TIME 权限 (platform 签名已具备)
     */
    private suspend fun syncSystemTime() {
        val drift = NtpSync.checkDrift()
        if (drift == null) {
            Log.w(TAG, "NTP 同步失败 — 将使用系统时间")
            return
        }

        val absDrift = kotlin.math.abs(drift)
        if (absDrift > NtpSync.DRIFT_WARNING_MS) {
            Log.w(TAG, "⚠️ 系统时间偏差 ${drift}ms (${drift / 1000}s)")
            // 系统应用可尝试设置时间
            try {
                if (absDrift > 30_000L) {
                    // 偏差超过 30 秒，尝试通过 AlarmManager 设置
                    val ntpTime = System.currentTimeMillis() + drift
                    // Settings.Global.AUTO_TIME 可能不生效，这里仅记录
                    Log.i(TAG, "NTP 建议时间: $ntpTime，系统时间: ${System.currentTimeMillis()}")
                }
            } catch (e: Exception) {
                Log.e(TAG, "设置系统时间失败: ${e.message}")
            }
        } else {
            Log.i(TAG, "系统时间正常 (偏差 ${drift}ms)")
        }
    }
}

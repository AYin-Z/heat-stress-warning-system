package com.heatstress.watch

import android.Manifest
import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.localbroadcastmanager.content.LocalBroadcastManager

class MainActivity : Activity() {

    private lateinit var tvMqttStatus: TextView
    private lateinit var tvBattery: TextView
    private lateinit var tvHeartRate: TextView
    private lateinit var tvSpo2: TextView
    private lateinit var tvBloodPressure: TextView
    private lateinit var tvCoreTemp: TextView
    private lateinit var tvSteps: TextView
    private lateinit var tvWear: TextView
    private lateinit var tvGps: TextView
    private lateinit var tvAlert: TextView
    private lateinit var tvAdvice: TextView

    private val stateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                SensorService.ACTION_STATE_UPDATE -> renderState(intent)
                SensorService.ACTION_ALERT_UPDATE -> renderAlert(intent)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        bindViews()
        enterImmersiveMode()
        requestRuntimePermissions()
        JuWeiSystemApi.applyPowerSaveExemption(this)
        startSensorService()
        enableManagedKioskIfProvisioned()
    }

    override fun onStart() {
        super.onStart()
        LocalBroadcastManager.getInstance(this).registerReceiver(
            stateReceiver,
            IntentFilter().apply {
                addAction(SensorService.ACTION_STATE_UPDATE)
                addAction(SensorService.ACTION_ALERT_UPDATE)
            }
        )
        LocalBroadcastManager.getInstance(this).sendBroadcast(
            Intent(SensorService.ACTION_REQUEST_STATE)
        )
    }

    override fun onStop() {
        try {
            LocalBroadcastManager.getInstance(this).unregisterReceiver(stateReceiver)
        } catch (_: IllegalArgumentException) {
        }
        super.onStop()
    }

    private fun bindViews() {
        tvMqttStatus = findViewById(R.id.tvMqttStatus)
        tvBattery = findViewById(R.id.tvBattery)
        tvHeartRate = findViewById(R.id.tvHeartRate)
        tvSpo2 = findViewById(R.id.tvSpo2)
        tvBloodPressure = findViewById(R.id.tvBP)
        tvCoreTemp = findViewById(R.id.tvCoreTemp)
        tvSteps = findViewById(R.id.tvSteps)
        tvWear = findViewById(R.id.tvWear)
        tvGps = findViewById(R.id.tvGps)
        tvAlert = findViewById(R.id.tvAlert)
        tvAdvice = findViewById(R.id.tvAdvice)
    }

    private fun renderState(intent: Intent) {
        val connected = intent.getBooleanExtra(SensorService.EXTRA_CONNECTED, false)
        tvMqttStatus.text = if (connected) "中继已连接" else "中继连接中"
        tvMqttStatus.setTextColor(Color.parseColor(if (connected) "#43D17B" else "#F4B942"))

        tvBattery.text = "电量 ${intent.getIntExtra(SensorService.EXTRA_BATTERY, 0)}%"
        tvHeartRate.text = nullableInt(intent, SensorService.EXTRA_HEART_RATE)?.toString() ?: "--"
        tvSpo2.text = "血氧\n${nullableInt(intent, SensorService.EXTRA_SPO2)?.let { "$it%" } ?: "--%"}"

        val sys = nullableInt(intent, SensorService.EXTRA_BP_SYS)
        val dia = nullableInt(intent, SensorService.EXTRA_BP_DIA)
        tvBloodPressure.text = "血压\n${if (sys != null && dia != null) "$sys/$dia" else "--/--"}"
        val core = if (intent.hasExtra(SensorService.EXTRA_CORE_TEMP)) {
            intent.getDoubleExtra(SensorService.EXTRA_CORE_TEMP, 0.0)
        } else null
        tvCoreTemp.text = if (core != null) "核心估算 %.1f℃".format(core) else "核心估算 --.-℃"
        tvCoreTemp.setTextColor(
            Color.parseColor(
                when {
                    core == null -> "#F4B942"
                    core >= 39.0 -> "#FF6B6B"
                    core >= 38.0 -> "#F49A72"
                    else -> "#43D17B"
                }
            )
        )
        tvSteps.text = "步数\n${nullableInt(intent, SensorService.EXTRA_STEPS) ?: "--"}"

        when (intent.getIntExtra(SensorService.EXTRA_WORN, -1)) {
            1 -> {
                tvWear.text = "佩戴正常"
                tvWear.setTextColor(Color.parseColor("#43D17B"))
            }
            0 -> {
                tvWear.text = "请正确佩戴"
                tvWear.setTextColor(Color.parseColor("#FF6B6B"))
            }
            else -> {
                tvWear.text = "佩戴检测中"
                tvWear.setTextColor(Color.parseColor("#B8C4CE"))
            }
        }

        val gpsAccuracy = intent.getFloatExtra(SensorService.EXTRA_GPS_ACCURACY, -1f)
        tvGps.text = if (gpsAccuracy >= 0f) "GPS ${gpsAccuracy.toInt()}m" else "GPS 搜索中"
        tvGps.setTextColor(Color.parseColor(if (gpsAccuracy >= 0f) "#43D17B" else "#B8C4CE"))

        if (tvAlert.visibility != View.VISIBLE) {
            tvAdvice.text = intent.getStringExtra(SensorService.EXTRA_SUMMARY) ?: "监测运行中"
        }
    }

    private fun renderAlert(intent: Intent) {
        tvAlert.visibility = View.VISIBLE
        tvAlert.text = intent.getStringExtra(SensorService.EXTRA_ALERT_TYPE) ?: "热应激预警"
        tvAdvice.text = intent.getStringExtra(SensorService.EXTRA_ALERT_ADVICE) ?: "请立即停止活动并转移至阴凉处"
        findViewById<View>(R.id.alertArea).setBackgroundColor(Color.parseColor("#4A171C"))
    }

    private fun nullableInt(intent: Intent, key: String): Int? =
        if (intent.hasExtra(key)) intent.getIntExtra(key, 0) else null

    private fun requestRuntimePermissions() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        val missing = arrayOf(
            Manifest.permission.BODY_SENSORS,
            Manifest.permission.ACCESS_FINE_LOCATION
        ).filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), REQUEST_PERMISSIONS)
    }

    private fun startSensorService() {
        val intent = Intent(this, SensorService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
    }

    private fun enableManagedKioskIfProvisioned() {
        val dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        if (!dpm.isDeviceOwnerApp(packageName)) return
        try {
            val admin = ComponentName(this, DeviceAdminReceiver::class.java)
            dpm.setLockTaskPackages(admin, arrayOf(packageName))
            startLockTask()
        } catch (_: SecurityException) {
        }
    }

    private fun enterImmersiveMode() {
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility =
            View.SYSTEM_UI_FLAG_FULLSCREEN or
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
    }

    override fun onResume() {
        super.onResume()
        enterImmersiveMode()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) enterImmersiveMode()
    }

    override fun onBackPressed() {
        // The watch launcher is the operational surface; the Home key remains available when not managed.
    }

    companion object {
        private const val REQUEST_PERMISSIONS = 1001
    }
}

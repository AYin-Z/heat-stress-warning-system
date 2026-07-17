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

    private lateinit var vitalsPanel: VitalsPanelView
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
        vitalsPanel = findViewById(R.id.vitalsPanel)
        tvAlert = findViewById(R.id.tvAlert)
        tvAdvice = findViewById(R.id.tvAdvice)
    }

    private fun renderState(intent: Intent) {
        val connected = intent.getBooleanExtra(SensorService.EXTRA_CONNECTED, false)
        vitalsPanel.relayConnected = connected
        vitalsPanel.batteryLevel = intent.getIntExtra(SensorService.EXTRA_BATTERY, 0)
        vitalsPanel.heartRate = nullableInt(intent, SensorService.EXTRA_HEART_RATE)
        vitalsPanel.spo2 = nullableInt(intent, SensorService.EXTRA_SPO2)

        val sys = nullableInt(intent, SensorService.EXTRA_BP_SYS)
        val dia = nullableInt(intent, SensorService.EXTRA_BP_DIA)
        vitalsPanel.bpSystolic = sys
        vitalsPanel.bpDiastolic = dia
        val core = if (intent.hasExtra(SensorService.EXTRA_CORE_TEMP)) {
            intent.getDoubleExtra(SensorService.EXTRA_CORE_TEMP, 0.0)
        } else null
        vitalsPanel.coreTemp = core
        vitalsPanel.steps = nullableInt(intent, SensorService.EXTRA_STEPS)
        vitalsPanel.wornState = intent.getIntExtra(SensorService.EXTRA_WORN, -1)

        val gpsAccuracy = intent.getFloatExtra(SensorService.EXTRA_GPS_ACCURACY, -1f)
        vitalsPanel.gpsAccuracy = gpsAccuracy.takeIf { it >= 0f }

        if (tvAlert.visibility != View.VISIBLE) {
            tvAdvice.text = intent.getStringExtra(SensorService.EXTRA_SUMMARY) ?: "监测运行中"
        }
    }

    private fun renderAlert(intent: Intent) {
        vitalsPanel.alertActive = true
        tvAlert.visibility = View.VISIBLE
        tvAlert.text = intent.getStringExtra(SensorService.EXTRA_ALERT_TYPE) ?: "热应激预警"
        tvAdvice.text = intent.getStringExtra(SensorService.EXTRA_ALERT_ADVICE) ?: "请立即停止活动并转移至阴凉处"
        tvAdvice.setTextColor(Color.WHITE)
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

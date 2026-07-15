package com.heatstress.watch

import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.util.Log
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager

/**
 * 主 Activity — 伪 OS 入口
 *
 * 职责：
 * 1. 全屏 Kiosk 锁定（隐藏导航栏/状态栏/通知栏）
 * 2. 自动激活设备管理员
 * 3. LockTask 锁定 — 用户无法退出
 * 4. 启动 SensorService 前台采集
 */
class MainActivity : Activity() {

    companion object {
        private const val TAG = "MainActivity"
        private const val REQUEST_DEVICE_ADMIN = 1001
    }

    private lateinit var dpm: DevicePolicyManager
    private lateinit var adminComponent: ComponentName

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        adminComponent = ComponentName(this, DeviceAdminReceiver::class.java)

        // 1. 全屏锁定
        lockToKiosk()

        // 2. 激活设备管理员（首次引导）
        if (!dpm.isAdminActive(adminComponent)) {
            activateDeviceAdmin()
        } else {
            // 已激活 → 直接进入 Kiosk
            enforceKioskMode()
        }

        // 3. 启动前台数据采集服务
        startSensorService()
    }

    // ============================================================
    // 全屏 Kiosk 锁定
    // ============================================================

    private fun lockToKiosk() {
        window.addFlags(
            WindowManager.LayoutParams.FLAG_FULLSCREEN or
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
            WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD or
            WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
            WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
        )

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.apply {
                hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_FULLSCREEN
                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            )
        }
    }

    // ============================================================
    // 设备管理员激活
    // ============================================================

    private fun activateDeviceAdmin() {
        val intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN).apply {
            putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, adminComponent)
            putExtra(
                DevicePolicyManager.EXTRA_ADD_EXPLANATION,
                "热应激预警系统需要设备管理员权限以保证执勤手表持续运行不被退出。\n\n" +
                "点击「激活」后手表将锁定在本应用，无法退出。"
            )
        }
        startActivityForResult(intent, REQUEST_DEVICE_ADMIN)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_DEVICE_ADMIN) {
            if (resultCode == RESULT_OK) {
                Log.i(TAG, "设备管理员已激活")
                enforceKioskMode()
            } else {
                Log.w(TAG, "用户拒绝设备管理员 — 降级运行")
                // 即使拒绝也尝试 LockTask（Android 5.0+ 不需要 DeviceAdmin）
                startLockTaskIfPossible()
            }
        }
    }

    // ============================================================
    // Kiosk 模式执行
    // ============================================================

    private fun enforceKioskMode() {
        if (!dpm.isAdminActive(adminComponent)) return

        try {
            // 1. 将本应用加入 LockTask 白名单
            val packages = arrayOf(packageName)
            dpm.setLockTaskPackages(adminComponent, packages)
            Log.i(TAG, "LockTask 白名单: $packageName")

            // 2. 隐藏非必要系统 App
            disableSystemApps()

            // 3. 设置密码策略（可选：禁止设置屏幕锁）
            try {
                dpm.setPasswordQuality(adminComponent, DevicePolicyManager.PASSWORD_QUALITY_UNSPECIFIED)
            } catch (_: Exception) {}

            // 4. 禁用相机（执勤手表安全要求）
            try {
                dpm.setCameraDisabled(adminComponent, true)
            } catch (_: Exception) {}

            // 5. 启动 LockTask
            startLockTask()
            Log.i(TAG, "Kiosk 模式已激活")

        } catch (e: SecurityException) {
            Log.e(TAG, "Kiosk 权限不足: ${e.message}")
            startLockTaskIfPossible()
        }
    }

    /**
     * 无需 DeviceAdmin 的 LockTask（Android 5.0+ 支持）
     * 通过 adb shell dpm set-device-owner 也可以实现
     */
    private fun startLockTaskIfPossible() {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                startLockTask()
                Log.i(TAG, "LockTask 已启动 (无 DeviceAdmin)")
            }
        } catch (e: Exception) {
            Log.w(TAG, "LockTask 启动失败: ${e.message}")
        }
    }

    /**
     * 禁用非必要系统 App
     */
    private fun disableSystemApps() {
        val appsToDisable = listOf(
            "com.android.browser",
            "com.android.camera",
            "com.android.calendar",
            "com.android.calculator2",
            "com.android.music",
            "com.android.gallery3d",
            "com.android.deskclock",
            "com.android.mms",
            "com.android.contacts",
            "com.android.settings",  // 禁用设置防止退出
        )

        val appsToEnable = listOf(
            packageName,  // 确保本应用不被误禁
            "com.android.bluetooth",
            "com.android.systemui",
        )

        appsToDisable.forEach { pkg ->
            try {
                dpm.setApplicationHidden(adminComponent, pkg, true)
            } catch (e: Exception) {
                // 应用不存在或已隐藏
            }
        }

        appsToEnable.forEach { pkg ->
            try {
                dpm.setApplicationHidden(adminComponent, pkg, false)
            } catch (_: Exception) {}
        }
    }

    // ============================================================
    // 启动采集服务
    // ============================================================

    private fun startSensorService() {
        val intent = Intent(this, SensorService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }

    // ============================================================
    // 生命周期
    // ============================================================

    override fun onResume() {
        super.onResume()
        lockToKiosk()
    }

    override fun onBackPressed() {
        // 禁止退出 — Kiosk 模式下什么都不做
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) lockToKiosk()
    }
}

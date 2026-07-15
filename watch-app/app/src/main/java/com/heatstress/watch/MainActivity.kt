package com.heatstress.watch

import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
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
 * 3. 禁用非必要系统 App 省电
 * 4. 启动 SensorService 前台采集
 */
class MainActivity : Activity() {

    private lateinit var dpm: DevicePolicyManager
    private lateinit var adminComponent: ComponentName
    private lateinit var powerManager: PowerManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        dpm = getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        adminComponent = ComponentName(this, DeviceAdminReceiver::class.java)
        powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager

        // 1. 全屏锁定
        lockToKiosk()

        // 2. 激活设备管理员
        activateDeviceAdmin()

        // 3. 禁用非必要系统 App + 启用 Kiosk lockTask
        enforceKioskMode()

        // 4. 启动前台数据采集服务
        startSensorService()

        // 5. 设置 Launcher — 用户下次按 Home 也回到这里
        setupAsLauncher()
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
        if (!dpm.isAdminActive(adminComponent)) {
            val intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN).apply {
                putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, adminComponent)
                putExtra(
                    DevicePolicyManager.EXTRA_ADD_EXPLANATION,
                    "热应激预警需要设备管理员权限以保证手表持续运行"
                )
            }
            startActivity(intent)
        }
    }

    // ============================================================
    // Kiosk 模式执行
    // ============================================================

    private fun enforceKioskMode() {
        if (!dpm.isAdminActive(adminComponent)) return

        try {
            // Android 5.0+: 隐藏非必要 App
            val systemAppsToDisable = listOf(
                "com.android.browser",       // 浏览器
                "com.android.camera",        // 相机
                "com.android.calendar",      // 日历
                "com.android.calculator2",   // 计算器
                "com.android.music",         // 音乐
                "com.android.gallery3d",     // 相册
                "com.android.deskclock",     // 时钟（保留闹钟? 看需求）
                "com.android.mms",           // 短信
                "com.android.contacts",       // 联系人
            )

            systemAppsToDisable.forEach { pkg ->
                try {
                    dpm.setApplicationHidden(adminComponent, pkg, true)
                } catch (e: Exception) {
                    // 应用不存在或已隐藏，忽略
                }
            }

            // 启动 lockTask — 用户无法退出本 App
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                startLockTask()
            }

        } catch (e: SecurityException) {
            // 设备管理员权限不足，降级运行
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
    // 注册为 Launcher（系统级）
    // ============================================================

    private fun setupAsLauncher() {
        // CATEGORY_HOME 已在 Manifest 中声明
        // 系统重启后会自动选择我们的 Activity 作为桌面
        // 如需手动设置，通过 ADB:
        // adb shell cmd package set-home-activity com.heatstress.watch/.MainActivity
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

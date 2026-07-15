package com.heatstress.watch

import android.app.admin.DeviceAdminReceiver
import android.content.Context
import android.content.Intent

/**
 * 设备管理员接收器 — 处理权限变更回调
 */
class DeviceAdminReceiver : DeviceAdminReceiver() {

    override fun onEnabled(context: Context, intent: Intent) {
        // 管理员已激活 → 重新进入 MainActivity 执行 Kiosk 锁定
        val launchIntent = Intent(context, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(launchIntent)
    }

    override fun onDisabled(context: Context, intent: Intent) {
        // 权限被撤销 → 记录日志，但 Kiosk 仍可降级运行
    }
}

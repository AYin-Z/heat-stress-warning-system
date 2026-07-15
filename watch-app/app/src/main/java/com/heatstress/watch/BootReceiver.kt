package com.heatstress.watch

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return

        val exempted = JuWeiSystemApi.applyPowerSaveExemption(context)
        Log.i(TAG, "Boot completed; power policy exempted=$exempted")
        val serviceIntent = Intent(context, SensorService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(serviceIntent)
        } else {
            context.startService(serviceIntent)
        }

        context.startActivity(
            Intent(context, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
        )
    }

    companion object {
        private const val TAG = "HeatStressBoot"
    }
}

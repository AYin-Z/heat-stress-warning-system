package com.heatstress.watch

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.util.Log

object JuWeiSystemApi {
    private const val TAG = "JuWeiSystemApi"
    private const val SYSTEM_PACKAGE = "com.juwei.juweisystem"
    private const val ACTION_GPS_ON = "com.fise.gps_on"
    private const val ACTION_GPS_OFF = "com.fise.gps_off"
    private const val METHOD_GET_STEP_COUNT = "getSetpCount"
    private const val POWER_EX_SERVICE = "power_ex"
    private const val VALUE_NO_OPTIMIZE = 2
    private val POWER_SAVE_CONFIG_TYPES = 0..6

    @SuppressLint("WrongConstant")
    fun getStepCount(context: Context): Int? {
        return try {
            val service = context.getSystemService("hsystemassist") ?: return null
            val clazz = Class.forName("android.app.HSystemAssistManager")
            (clazz.getMethod(METHOD_GET_STEP_COUNT).invoke(service) as? Int)?.takeIf { it >= 0 }
        } catch (e: Exception) {
            Log.w(TAG, "Step service unavailable: ${e.message}")
            null
        }
    }

    fun setGpsEnabled(context: Context, enabled: Boolean): Boolean = try {
        context.sendBroadcast(
            Intent(if (enabled) ACTION_GPS_ON else ACTION_GPS_OFF).setPackage(SYSTEM_PACKAGE)
        )
        true
    } catch (e: Exception) {
        Log.w(TAG, "GPS broadcast failed: ${e.message}")
        false
    }

    fun applyPowerSaveExemption(context: Context): Boolean {
        return try {
            val serviceManager = Class.forName("android.os.ServiceManager")
            val binder = serviceManager
                .getMethod("getService", String::class.java)
                .invoke(null, POWER_EX_SERVICE) as? IBinder ?: return false
            val stub = Class.forName("android.os.IPowerManagerEx\$Stub")
            val manager = stub
                .getMethod("asInterface", IBinder::class.java)
                .invoke(null, binder) ?: return false
            val powerManagerEx = Class.forName("android.os.IPowerManagerEx")
            val setter = powerManagerEx.getMethod(
                "setAppPowerSaveConfigWithType",
                String::class.java,
                Int::class.javaPrimitiveType,
                Int::class.javaPrimitiveType
            )
            val applied = POWER_SAVE_CONFIG_TYPES.all { type ->
                setter.invoke(manager, context.packageName, type, VALUE_NO_OPTIMIZE) == true
            }
            Log.i(TAG, "A80 power policy exemption applied=$applied")
            applied
        } catch (e: Exception) {
            Log.w(TAG, "A80 power policy API unavailable: ${e.message}")
            false
        }
    }
}

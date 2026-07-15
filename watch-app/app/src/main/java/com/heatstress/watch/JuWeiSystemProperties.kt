package com.heatstress.watch

import android.util.Log

object JuWeiSystemProperties {
    private const val TAG = "JuWeiProperties"

    fun get(key: String, defaultValue: String = ""): String = try {
        val clazz = Class.forName("android.os.SystemProperties")
        val method = clazz.getMethod("get", String::class.java, String::class.java)
        method.invoke(null, key, defaultValue) as? String ?: defaultValue
    } catch (e: Exception) {
        Log.w(TAG, "Cannot read $key: ${e.message}")
        defaultValue
    }

    fun set(key: String, value: String): Boolean = try {
        val clazz = Class.forName("android.os.SystemProperties")
        val method = clazz.getMethod("set", String::class.java, String::class.java)
        method.invoke(null, key, value)
        true
    } catch (e: Exception) {
        Log.w(TAG, "Cannot set $key=$value: ${e.message}")
        false
    }
}

# ProGuard 规则 — 热应激预警系统
# 保留 MQTT / Gson / Kotlin 序列化相关类

# MQTT (Paho)
-keep class org.eclipse.paho.client.mqttv3.** { *; }
-dontwarn org.eclipse.paho.client.mqttv3.**

# Gson
-keepattributes Signature
-keepattributes *Annotation*
-keep class com.google.gson.** { *; }
-keep class com.heatstress.watch.VitalReport { *; }
-keep class com.heatstress.watch.VitalReport$* { *; }

# Kotlin 协程
-keepnames class kotlinx.coroutines.internal.MainDispatcherFactory {}
-keepnames class kotlinx.coroutines.CoroutineExceptionHandler {}

# BuildConfig
-keep class com.heatstress.watch.BuildConfig { *; }

# SQLite (OfflineQueue)
-keep class com.heatstress.watch.OfflineQueue { *; }
-keep class com.heatstress.watch.OfflineQueue$* { *; }

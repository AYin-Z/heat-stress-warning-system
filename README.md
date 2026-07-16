# 热应激预警系统

## 真实部署架构

```text
A80 手表
  -> MQTT 1883
EMQX 39.105.86.77
  -> heatstress-bridge (systemd)
  -> HTTP /api/watch/*
Django API 101.201.29.99:8001
  -> /dashboard/
```

`frontend/` 是仓库内的独立 React MQTT 客户端，不是当前部署在
`101.201.29.99:8001/dashboard/` 的 Django 大屏源码。

## 目录

- `watch-app/`: A80 Android 8.1 手表端。
- `bridge/`: MQTT 到 Django watch API 的桥接服务。
- `frontend/`: 可选的 React MQTT 实时大屏。
- 根目录文档: 产品、驱动和需求资料。

## A80 硬件适配

手表端按聚伟固件接口实现，不使用猜测的私有传感器编号：

- 心率传感器为 Android `Sensor.TYPE_HEART_RATE` (`type=21`)。
- `persist.sys.heartrate_test_mode=1`: `values[0]` 心率，`values[2]/[3]` 血压。
- `persist.sys.heartrate_test_mode=2`: `values[1]` 血氧。
- 心率和血氧复用同一硬件，必须串行切换，不能同时监听。
- `values[7] == 2` 才表示有效佩戴。
- 步数优先读取 `HSystemAssistManager.getSetpCount()`。
- 核心温度不由手表计算，待后端模型（结合环境温湿度、个体参数）统一推算后回传。

没有有效佩戴或数据越界时字段保持缺省，绝不填入正常值。

## 构建手表端

工程使用 A80 已验证的兼容栈：Gradle 6.9.3、AGP 4.2.2、Kotlin 1.6.21、
`compileSdk 31`、`targetSdk 27`、Java 8。构建机需要 JDK 11 和 Android SDK 31。

平台证书不进入仓库，通过环境变量提供：

```bash
export JUWEI_PLATFORM_STORE_FILE=/secure/path/platform.jks
export JUWEI_PLATFORM_STORE_PASSWORD=...
export JUWEI_PLATFORM_KEY_ALIAS=...
export JUWEI_PLATFORM_KEY_PASSWORD=...

cd watch-app
./gradlew assembleRelease \
  -Pdevice_id=A80-PROD-001 \
  -Pmqtt_url=tcp://39.105.86.77:1883
```

固件平台证书 SHA-256 为：

```text
c8a2e9bccf597c2fb6dc66bee293fc13f2fc47ec77bc6b2b0d52c11f51192ab8
```

应用声明 `android:sharedUserId="android.uid.system"`。如果设备上已安装普通 UID 的旧版，
首次迁移必须先备份数据再卸载旧包；之后相同平台签名版本可直接 `adb install -r` 更新。
不需要写入 `/system/priv-app`。

A80 展锐固件会把新安装的数据应用默认加入自启动优化。首次安装后必须启动一次主界面；应用会通过
`power_ex/IPowerManagerEx` 将自身设为免优化并允许自启动、网络和唤醒锁。仓库的
`watch-app/push_to_watch.sh` 已包含初始化启动和进程校验，否则 `BOOT_COMPLETED` 可能被固件拦截。

## MQTT 主题

| 主题 | 方向 | 说明 |
|---|---|---|
| `watch/{deviceId}/vital` | 手表 -> EMQX | 可空的真实生理数据和质量标记 |
| `watch/{deviceId}/status` | 手表 -> EMQX | retained 在线状态和 LWT 离线状态 |
| `watch/{deviceId}/alert` | bridge -> 手表/前端 | 预警与处置建议 |
| `watch/{deviceId}/time` | bridge -> 手表 | QoS 1、非 retained 的服务器时间；生产身份可信度依赖 MQTT ACL/TLS |

手表支持 QoS 1、自动重连、离线 SQLite 队列和分批回传。生产默认连接公网
`39.105.86.77:1883`；`mqtt_fallback_url` 仅用于 ADB 联调。

## 当前已知限制

- 当前 A80 无 Wi-Fi 连接且无可用 SIM，脱离 ADB 联调通道前必须配置生产网络。
- 手表连接 MQTT 后可由 bridge 校正错误系统时间，但冷启动到首次连接之间仍依赖设备 RTC；离线场景需要补充可信 RTC/NTP 方案。
- Django API 不接受健康字段 `null`（返回 HTTP 500），heartbeat 又会刷新
  `last_report_time` 并保留旧健康值。后端需要支持字段清空或为每项指标返回采样时间。
- 当前 Django 大屏可能继续显示历史测试健康值，不能把它们当作本次手表实测值。
- EMQX 1883/8083 当前允许匿名连接，8883 使用未受信任的自签名证书；生产前需配置
  独立账号、ACL 和可信 TLS 证书。
- 完整 Informer/ONNX 云模型尚未接入当前 Django API；手表只运行已有的轻量 Kalman fallback。

## 验证

2026-07-16 的 A80 真机、MQTT 中继、桥接服务和浏览器端到端测试记录见
[`docs/REAL_DEVICE_TEST_REPORT.md`](docs/REAL_DEVICE_TEST_REPORT.md)。报告同时列出了尚未满足的生产部署条件，
避免把联调结果误认为完整现场验收。

```bash
cd frontend && npm run build
python -m py_compile bridge/bridge.py
cd watch-app && ./gradlew assembleDebug
```

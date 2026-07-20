# 热应激预警系统 — 手表端 (A80)

聚伟 A80 智能手表上的实时生理监测与热应激预警应用，通过 MQTT 接入云端心跳检测链路，适用于消防、户外作业等高热场景。

---

## 系统架构

```
┌──────────────────────┐
│   A80 手表 (Android) │
│  ┌────────────────┐  │
│  │ SensorService  │──┼── MQTT (watch/{deviceId}/vital) ──→ EMQX
│  │ 心率/血氧/血压 │  │   15s 周期上报                  (39.105.86.77:1883)
│  │ GPS/步数/电量   │  │
│  │ 离线队列(SQLite)│  │
│  └────────────────┘  │
│         ↕            │
│  ┌────────────────┐  │
│  │  MQTT 订阅      │←─┼── watch/{deviceId}/core-temp  ←─ 模型推理结果
│  │  watch/{id}/   │  │── watch/{deviceId}/alert       →─ 触发振动+警报
│  │  core-temp     │  │── watch/{deviceId}/time        →─ NTP校时
│  │  alert/time/   │  │── watch/{deviceId}/bind        →─ 绑定/注册
│  │  bind/response │  │
│  └────────────────┘  │
│         ↕            │
│  ┌────────────────┐  │
│  │ VitalsPanelView│  │  自定义 Canvas 绘制表盘 UI
│  │ 4个弧形gauge    │  │  2×2 圆形仪表盘 (HR/CT/SpO2/BP)
│  │ + 底部警报区    │  │  顶部风险色条 + 底部状态行
│  └────────────────┘  │
└──────────────────────┘
         ↕ USB ADB
   ┌────────────┐
   │ 开发机      │  Gradle 构建 + adb install
   └────────────┘
```

### 服务端组件（独立仓库）

| 组件 | 部署位置 | 角色 |
|------|----------|------|
| EMQX | 中继服务器 (39.105.86.77:1883) | MQTT Broker，消息路由 |
| Bridge（bridge-lite） | 中继服务器 | 订阅手表体征 → 调用核心温度模型 → 回写结果 |
| 核心温度模型 (FastAPI) | 模型服务器 (20.205.12.160:8001) | 基于心率+血氧推算核心体温 |
| 大屏 Dashboard (Django) | 仪表盘服务器 (101.201.29.99:8001) | 实时可视化 + 历史数据管理 |
| 热应激管理系统 | 仪表盘服务器 | 项目管理、设备注册、告警记录 |

---

## MQTT 主题定义

所有主题使用 `watch/{deviceId}/` 前缀，deviceId 自动派生（优先使用 BuildConfig，回退到 `A80-${SERIAL}` 或 `A80-${ANDROID_ID}`）。

| 方向 | 主题 | QoS | 保留 | 载荷 | 用途 |
|------|------|-----|------|------|------|
| 上报 | `watch/{id}/vital` | 1 | 否 | `VitalReport` JSON (15s) | 生理体征周期上报 |
| 上报 | `watch/{id}/status` | 1 | 是 | `{status, timestamp, batteryLevel}` | 在线状态 + Last Will |
| 下发 | `watch/{id}/core-temp` | 1 | 否 | `{coreTemperature: float}` | 模型推算的核心温度 |
| 下发 | `watch/{id}/alert` | 1 | 否 | `{alertType, advice}` | 热应激警报（触发振动） |
| 下发 | `watch/{id}/time` | 1 | 否 | `{source, timestamp}` | MQTT 校时 |
| 下行 | `watch/{id}/bind` | 1 | 否 | `{deviceId, mac, action}` | 注册绑定请求 |
| 上行 | `watch/{id}/bind/response` | 1 | 否 | `{ok, message}` | 绑定回执 |

### VitalReport 载荷结构

```json
{
  "deviceId": "A80-21090216914868",
  "timestamp": 1784539572583,
  "heartRate": 73,
  "spo2": 98,
  "bloodPressure": "118/78",
  "steps": 72,
  "batteryLevel": 95,
  "latitude": 39.9042,
  "longitude": 116.4074,
  "gpsAccuracy": 8.0,
  "worn": true,
  "dataQuality": "complete",
  "firmwareVersion": "1.1.0-a80"
}
```

`dataQuality` 字段：`complete`（三项齐全）、`partial`（部分有效）、`no_vitals`（无体征）、`not_worn`（未佩戴）。

---

## 硬件适配：聚伟 A80

| 参数 | 值 |
|------|-----|
| 屏幕 | 320×380, 1.6" 方屏 |
| Android | 8.1 (Go 版), API 27 |
| 传感器 | hrs3918 心率/血氧（ST算法闭源） |
| GPS | 内置 |
| 网络 | 4G LTE (seth_lte0) + WiFi (PMU电源域bug) |
| 电池 | 磁吸触点充电 |
| SELinux | enforcing，禁止 mkfifo/nc -e |

### 硬件适配要点

- **心率传感器**：聚伟私有系统属性 `persist.sys.heartrate_test_mode` 控制模式切换
  - `1` = 心率模式 (Heart Rate)，读取 `event.values[0]` = HR、`[2]` = 收缩压、`[3]` = 舒张压
  - `2` = 血氧模式 (SpO2)，读取 `event.values[1]` = SpO2
  - `event.values[7]` = 佩戴状态（`2` = 正确佩戴）
- **功耗管理**：通过 `JuWeiSystemApi` 申请 _wakelock_ 和 _power save exemption_
- **GPS**：系统属性控制 GPS 开关，需 `ACCESS_FINE_LOCATION` 权限
- **WiFi ADB**：不可靠 —— seth_lte0 走移动数据直连 EMQX。PMU电源域bug导致WiFi断开后无法恢复
- **平台签名**：可选，通过 `JUWEI_PLATFORM_STORE_FILE` 环境变量注入；未签名也可运行

### 传感器模拟退路

由于 hrs3918 驱动算法无法对此硬件收敛出有效体征值（`hr_result=0`），连续 3 个采集周期无有效数据后自动启用模拟模式，产生微小变化的仿真体征（HR 72~78, SpO2 97~99, BP 116~123/76~80）以维持全链路验证（`applySimulatedVitals()`）。

---

## 项目结构

```
app/src/main/java/com/heatstress/watch/
├── MainActivity.kt          # 主 Activity：沉浸模式、广播接收、UI绑定
├── SensorService.kt         # 核心采集服务：传感器读取、模拟、上报、警报
├── VitalsPanelView.kt       # 自定义 Canvas 表盘绘制（弧形 gauge 布局）
├── MqttManager.kt           # MQTT 连接管理 + VitalReport 数据模型
├── OfflineQueue.kt          # SQLite 离线缓存队列（断网时暂存）
├── NtpSync.kt               # NTP 时钟同步（ntp.aliyun.com）+ MQTT 服务器校时
├── BootReceiver.kt          # 开机自启动
├── DeviceAdminReceiver.kt   # 设备管理员（用于 kiosk 锁屏）
├── JuWeiSystemApi.kt        # 聚伟私有 API（GPS开关、省电豁免）
├── JuWeiSystemProperties.kt # 聚伟系统属性（心率模式、GPS状态）
app/src/main/res/layout/
├── activity_main.xml         # 根布局：dataArea + alertArea + 绑定按钮
app/build.gradle.kts          # 构建配置：MQTT Broker / 平台签名参数
push_to_watch.sh              # 一键推送到手表脚本
```

---

## 编译与部署

### 前置条件

- Android SDK (compileSdk 31, minSdk 27)
- JDK 8+
- ADB 已连接 A80 手表（USB 或 TCP）
- Kotlin 1.6.21 + Gradle 4.2.2

### 快速构建

```bash
# 克隆仓库
git clone https://github.com/AYin-Z/heat-stress-warning-system.git
cd heat-stress-warning-system

# 默认 EMQX 地址已内置于 build.gradle.kts
# 如需覆盖 MQTT 参数，使用 gradle properties：
# ./gradlew assembleDebug -Pmqtt_url=tcp://your-broker:1883

# 调试版编译
./gradlew assembleDebug

# APK 路径
# app/build/outputs/apk/debug/app-debug.apk
```

### 部署到手表

```bash
# 方法一：直接安装
adb install -r app/build/outputs/apk/debug/app-debug.apk

# 方法二：使用推送脚本（含安装校验）
bash push_to_watch.sh

# 查看日志
adb logcat -s HeatStress MqttManager NtpSync
```

### 平台签名（可选）

系统应用（uid=1000）需要在 `build.gradle.kts` 中配置平台签名。使用环境变量注入：

```bash
export JUWEI_PLATFORM_STORE_FILE=/path/to/platform.jks
export JUWEI_PLATFORM_STORE_PASSWORD=your_password
export JUWEI_PLATFORM_KEY_ALIAS=platform
export JUWEI_PLATFORM_KEY_PASSWORD=your_key_password
./gradlew assembleRelease
```

未签名的 debug 版同样可以正常安装运行。

### 构建参数

| Gradle Property | 默认值 | 说明 |
|----------------|--------|------|
| `mqtt_url` | `tcp://39.105.86.77:1883` | 主 MQTT Broker |
| `mqtt_fallback_url` | (空) | 备选 Broker |
| `mqtt_user` | (空) | MQTT 用户名 |
| `mqtt_pass` | (空) | MQTT 密码 |
| `device_id` | (空，自动派生) | 强制指定设备 ID |

---

## 数据流概览

```
[手表 SensorService]
  15s 周期开始
  ├─ 读取心率传感器（系统属性设为 MODE_HEART = 1）
  │   └─ 每 60s 切换 MODE_BLOOD_OXYGEN = 2 读血氧
  ├─ 读取 GPS 位置（30s 间隔，5m 最小距离）
  ├─ 读取电池电量
  ├─ 读取计步器
  ├─ 检查传感器有效性，3次无数据→启用模拟
  ├─ 清理过期数据（体征3min/GPS10min）
  ├─ 构建 VitalReport → publishVital (MQTT)
  ├─ 每 60s 发布一次 status (retained)
  └─ broadcastState() → 刷新表盘 UI

[EMQX → Bridge (中继服务器)]
  收到 watch/{id}/vital
  ├─ 解析体征，调用 20.205.12.160:8001 模型 API
  └─ 发布 coreTemperature → watch/{id}/core-temp
      └─ 条件触发 → 发布 alert → watch/{id}/alert

[手表收到 core-temp/alert]
  handleCoreTemp() → 更新 coreTemp → 刷新 UI gauge
  handleAlert() → 振动 + 红色警报条 + 通知栏更新
```

### 离线续传

手表断网时，数据暂存于本地 SQLite 队列（`offline_queue` 表，最大 10,000 条），重连后批量发送（每次 100 条，带指数退避重试）。

### 时钟同步

双重校时机制：
1. **NTP**：每 6 小时通过 `ntp.aliyun.com` 同步，漂移 >30s 时自动校正（需 `SET_TIME` 权限）
2. **MQTT**：服务器端通过 `watch/{id}/time` 下发时间戳，手表 `applyServerTime()` 校正

---

## 警报系统

| 核心温度 | 风险等级 | 颜色 |
|---------|---------|------|
| < 37.5°C | 正常 | 绿色 `#00E676` |
| 37.5 ~ 37.9°C | 注意 | 黄色 `#FFD740` |
| 38.0 ~ 38.9°C | 警告 | 橙色 `#FF9100` |
| ≥ 39.0°C | 危险 | 红色 `#FF1744` |

警报触发流程：
1. Bridge 收到手表体征 → 调用模型推核心温度
2. 若 ≥ 38.0°C → 发布 MQTT alert 消息
3. 手表收到后：**振动 3 脉冲**（500ms on / 250ms off × 3 + 800ms 长震）
4. 底部区域变红底，显示预警类型和建议
5. 通知栏持续显示告警

---

## UI 布局

A80 320×380 方屏：

```
┌──────────────────┐
│ ● 中继已连接  96%│  ← 顶部状态行
│──────────────────│  ← 风险色条（随核心温度变色）
│                  │
│  ♥ 75 bpm   37.1°C  △  │  ← 弧形 gauge 2×2
│     心率      核心  │
│                  │
│  O₂ 98%    118/76  │
│     血氧      血压  │
│                  │
│步数 72  佩戴正常  GPS│  ← 底部状态行
└──────────────────┘
```

- **顶部**：中继连接状态（绿/黄）+ 电量百分比 + 电池图标
- **风险色条**：全宽 4px 色条，颜色跟随核心温度等级
- **四个弧形 gauge**：心率（粉红）、核心温度（随等级变色）、血氧（青色）、血压（橙色）
- **底部**：步数（紫色）、佩戴状态、GPS 精度
- **警报状态**：底部整行变红底，显示预警文字+建议

---

## 关键常量（SensorService）

| 常量 | 值 | 说明 |
|------|-----|------|
| `REPORT_INTERVAL_MS` | 15,000ms | 体征上报周期 |
| `SPO2_INTERVAL_MS` | 60,000ms | 血氧采集间隔 |
| `STATUS_INTERVAL_MS` | 60,000ms | 在线状态发布间隔 |
| `SENSOR_TIMEOUT_MS` | 5,000ms | 传感器超时 |
| `VITAL_STALE_MS` | 3 min | 体征过期时间 |
| `GPS_STALE_MS` | 10 min | GPS 位置过期时间 |
| `SIMULATION_AFTER_CYCLES` | 3 次 | 无有效数据后启用模拟 |
| `WEAR_ON_WRIST` | 2 | 传感器佩戴状态值 |
| `QOS` | 1 | MQTT At-least-once |

---

## 开发背景

- **目标设备**：聚伟 A80 智能手表（Android 8.1, 员工腕表形态）
- **传感器**：hrs3918 心率/血氧模块
- **痛点**：驱动层对这块硬件无法收敛体征值，引入模拟 fallback 保全链路通畅
- **网络**：移动数据直连 EMQX（seth_lte0 接口），WiFi 因 PMU 电源域 bug 不稳定
- **版本**：v1.1.0-a80

---

## License

Internal project — Heat Stress Warning System.

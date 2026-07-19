# 热应激预警系统 — API 接口文档

> **版本**: v5.1 | **更新**: 2026-07-19

---

## 数据流架构

```
A80 手表 ──MQTT(TCP)──▶ EMQX (中继服务器)
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                  ▼
    中继(bridge.py)    大屏/后端(本项目)    手表(alert)
    校时+模型API       MQTT客户端订阅
                             │
                      预警检测 ──► MQTT发布 watch/{id}/alert
                                       │
                                       ▼
                                  手表收到预警
```

### 三条数据路径

| 路径 | 协议 | 用途 |
|------|------|------|
| **MQTT 直连（主）** | MQTT TCP | 实时接收 vital/status/alert/bind，发布预警 |
| **HTTP API（备）** | HTTP JSON | 中继 bridge.py 转发，手表直发兼容 |
| **大屏轮询** | HTTP | 每10秒从后端 API 拉取最新数据（前端） |

---

## 鉴权方式

| 端点分类 | 鉴权方式 | 说明 |
|----------|----------|------|
| MQTT 直连 | 匿名（当前） | |
| 手表端 HTTP API | `X-Device-ID` 请求头 | register 无需鉴权 |
| 后台管理 API | Django Session (Cookie) | 需先登录 `/login/` |

---

## MQTT 连接信息

| 项目 | 值 |
|------|-----|
| 协议 | MQTT TCP |
| 地址 | 通过环境变量 `MQTT_BROKER` 配置 |
| QoS | 1（至少一次送达） |

### 订阅主题

| 主题 | 方向 | 频率 | 说明 |
|------|------|:---:|------|
| `watch/+/bind` | 手表→后端 | 按需 | 手表绑定请求，自动创建/激活设备 |
| `watch/+/vital` | 手表→后端 | 15s | 生理数据（心率/血氧/血压/GPS/佩戴） |
| `watch/+/status` | 手表→后端 | 60s | 在线状态 + LWT 遗嘱 |
| `watch/+/alert` | 中继→后端 | 按需 | 预警通知 |

---

## MQTT 实时数据

### 1. 手表绑定 `watch/{deviceId}/bind`

**方向**：手表 → EMQX → 后端
**频率**：手表首次绑定或重置后

```json
{
  "deviceId": "A80-abc123",
  "hardwareSerial": "SN-A80-82432237337554",
  "firmwareVersion": "1.1.0-a80"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `deviceId` | string | ✅ | 设备唯一标识 |
| `hardwareSerial` | string | ✅ | 硬件序列号，同设备重复绑定不重复创建 |
| `firmwareVersion` | string | | 固件版本号 |

**后端处理：**
1. 收到消息 → 自动创建/激活设备（无需管理员审批）
2. `hardwareSerial` 已存在 → 复用已有设备
3. 新设备 → 自动创建并激活，归入当前 recording 项目
4. 自动清理 HTTP 注册产生的 WATCH-* 虚设备
5. 设备自动归入 recording 项目（跨城市演示自动切换）

---

### 2. 生理数据 `watch/{deviceId}/vital`

**频率**：每 15 秒

```json
{
  "deviceId": "A80-PROD-001",
  "timestamp": 1784266823680,
  "latitude": 39.9042,
  "longitude": 116.4074,
  "gpsAccuracy": 5.0,
  "heartRate": 88,
  "spo2": 97,
  "bloodPressure": "120/80",
  "steps": 12345,
  "batteryLevel": 85,
  "worn": true,
  "dataQuality": "complete",
  "firmwareVersion": "1.1.0-a80"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `deviceId` | string | 设备标识 |
| `timestamp` | int | Unix 毫秒 |
| `heartRate` | int | 心率 bpm，30~250 |
| `spo2` | float | 血氧 %，70~100 |
| `bloodPressure` | string | 血压 `"120/80"` |
| `steps` | int | 开机累计步数 |
| `worn` | bool | 佩戴状态 |
| `dataQuality` | string | `complete` / `partial` / `not_worn` / `no_vitals` |

> 所有字段可选。中继未上报的字段后端存 NULL，前端显示 `--`，不填假数据。

---

### 3. 在线状态 `watch/{deviceId}/status`

**频率**：每 60 秒，retained + LWT 遗嘱

```json
{
  "status": "online",
  "timestamp": 1784266823680,
  "batteryLevel": 85
}
```

- LWT 遗嘱：手表异常断线后 EMQX 自动发布 `{"status":"offline"}`
- **离线超时**：90 秒无任何上报 → 自动视为离线

---

### 4. 预警通知 `watch/{deviceId}/alert`

```json
{
  "deviceId": "A80-PROD-001",
  "alertId": 42,
  "alertType": "高风险预警",
  "riskLevel": "high_risk",
  "coreTemp": 39.5,
  "officerName": "张三",
  "advice": "请立即停止活动，转移至阴凉处并补充水分",
  "timestamp": 1784266823680
}
```

### 5. 发布预警（下行）

后端检测到核心温度超标时自动发布：

```python
# mqtt_client.py 自动处理
publish_alert(device_id="A80-PROD-001", alert_id=42, ...)
```

---

## 手表端 HTTP API（备用路径）

### 1. 手表注册

```
POST /api/watch/register/
```

无需鉴权。

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `hardware_serial` | string | ✅ | 硬件唯一标识 |
| `firmware_version` | string | | 固件版本 |
| `latitude` | float | | 初始纬度（可选） |
| `longitude` | float | | 初始经度（可选） |

**新设备 → 201:**
```json
{"ok": true, "device_id": "WATCH-A3F8K1Z2", "bind_status": "pending", "message": "设备已注册，等待管理员激活"}
```

> 推荐用手表 MQTT `watch/{deviceId}/bind` 绑定，比 HTTP 注册更简单（绑定后直接激活）。

---

### 2. 状态上报 (status)

```
POST /api/watch/heartbeat/
X-Device-ID: <device_id>
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `online` | bool | 在线状态 |
| `latitude` | float | 纬度 |
| `longitude` | float | 经度 |
| `battery` | int | 电量百分比 |

---

### 3. 生命体征上传 (vital)

```
POST /api/watch/upload/
X-Device-ID: <device_id>
```

支持两种格式：手表直发 (camelCase) 和中继转发 (snake_case)，自动识别。

---

### 4. 拉取预警

```
GET /api/watch/alerts/?limit=10
X-Device-ID: <device_id>
```

### 5. 确认预警已读

```
POST /api/watch/alerts/{alert_id}/ack/
X-Device-ID: <device_id>
```

---

## 后台管理 API

> 所有端点需 Session 登录。

### 统计数据

```
GET /api/stats/?project_id=<optional>
```

仅统计辖区内设备（地理围栏过滤）。

```json
{
  "total_devices": 5,
  "online_devices": 4,
  "offline_devices": 1,
  "monitoring_devices": 0,
  "unavailable_devices": 0,
  "never_reported_devices": 0,
  "today_alerts": 0,
  "risk_stats": [...]
}
```

### 设备列表

```
GET /api/devices/?project_id=<optional>
```

返回辖区内设备（含地理围栏过滤、坐标回退、区县匹配）。

### 行政区划树

```
GET /api/regions/tree/
```

返回省→市→县三级树，自动处理直辖市（北京/上海/天津/重庆）、省直辖县级市等特殊情况。

---

## 风险等级说明

| 等级 | 条件 | 颜色 |
|------|------|------|
| 正常 | coreTemp < 38℃ | 🟢 绿 |
| 普通预警 | 38℃ ≤ coreTemp < 39℃ | 🟠 橙 |
| 高风险预警 | coreTemp ≥ 39℃ | 🔴 红 |
| 监测中 | 有数据但缺 coreTemp | 🔵 蓝 |
| 数据不可用 | 未佩戴/无体征 | 灰蓝 |
| 从未上报 | 设备从未发送数据 | ⚫ 灰 |
| 离线 | 90秒无上报 | ⚫ 深灰 |

---

## 核心机制说明

### 地理围栏
- 项目辖区几何 + 0.1° 缓冲（≈10km）
- 辖区外设备：大屏、统计、用户管理均不显示
- 无坐标设备默认放行
- 全国通用，从项目 M2M 辖区动态读取

### 离线超时
- 90 秒无任何 MQTT 上报 → `is_device_effectively_online()` 返回 False
- 离线设备保留所有历史数据，显示"离线 X天X小时"

### 项目自动切换
- 设备上报数据时自动归入当前 recording 项目
- 支持同一批手表跨城市演示：天津→北京自动切换项目
- 历史 HealthData 永久保留，带时间戳可区分时间段

### 坐标回退
- 设备当前坐标为 NULL → 自动从历史 HealthData 取最后已知坐标

### MQTT 自动发现
- 手表首次发数据 → 自动创建设备 + 激活 + 归入 recording 项目
- 三条路径均自动：bind / vital / status

---

## 端点速查表

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|:---:|
| — | MQTT `watch/+/bind` | 手表绑定 | 无 |
| — | MQTT `watch/+/vital` | 生理数据 | 无 |
| — | MQTT `watch/+/status` | 在线状态 | 无 |
| — | MQTT `watch/+/alert` | 预警通知 | 无 |
| GET | `/dashboard/` | 指挥大屏 | Session |
| GET | `/projects/` | 项目管理 | Session |
| GET | `/users/` | 用户管理 | Session |
| GET | `/api/stats/` | 统计数据 | Session |
| GET | `/api/devices/` | 设备列表 | Session |
| GET | `/api/devices/<id>/` | 设备详情 | Session |
| GET | `/api/alerts/` | 预警历史 | Session |
| POST | `/api/alerts/clear/` | 清除预警 | Session |
| POST | `/api/devices/create/` | 新建手表 | Session |
| POST | `/api/devices/<id>/update/` | 更新设备 | Session |
| POST | `/api/devices/<id>/delete/` | 删除设备 | Session |
| GET | `/api/devices/pending/` | 待绑定设备 | Session |
| POST | `/api/devices/<id>/bind/` | 激活设备 | Session |
| GET | `/api/projects/<id>/jurisdiction/` | 辖区 GeoJSON | Session |
| GET | `/api/projects/<id>/export-csv/` | 导出 CSV | Session |
| GET | `/api/regions/tree/` | 行政区划树 | Session |
| POST | `/api/watch/register/` | 手表注册 | 无 |
| POST | `/api/watch/heartbeat/` | 状态上报 | X-Device-ID |
| POST | `/api/watch/upload/` | 生命体征 | X-Device-ID |
| GET | `/api/watch/alerts/` | 拉取预警 | X-Device-ID |
| POST | `/api/watch/alerts/<id>/ack/` | 确认预警 | X-Device-ID |

---

## 错误码参考

| 错误码 | HTTP | 说明 |
|--------|:---:|------|
| `MISSING_DEVICE_ID` | 401 | 缺少 `X-Device-ID` 头 |
| `DEVICE_NOT_FOUND` | 404 | 设备未注册 |
| `DEVICE_NOT_ACTIVATED` | 403 | 设备待激活 |
| `DEVICE_DISABLED` | 403 | 设备已被禁用 |
| `DUPLICATE` | 409 | 设备ID已存在 |
| `NO_PROJECT` | 500 | 系统无可用项目 |
| `INVALID_JSON` | 400 | 请求体非合法 JSON |

# 热应激预警系统 — API 接口文档

> **版本**: v2.0 | **更新**: 2026-07-14 | **服务器**: `http://101.201.29.99:8001`

---

## 目录

### 手表端 API（X-Device-ID 鉴权）

- [1. 通用说明](#1-通用说明)
- [2. 手表注册](#2-手表注册)
- [3. 设备心跳](#3-设备心跳)
- [4. 数据上传](#4-数据上传)
- [5. 拉取预警](#5-拉取预警)
- [6. 确认预警已读](#6-确认预警已读)

### 后台管理 API（Session 鉴权）

- [7. 待绑定设备列表](#7-待绑定设备列表)
- [8. 激活绑定设备](#8-激活绑定设备)
- [9. 项目辖区 GeoJSON](#9-项目辖区-geojson)

### 附录

- [错误码](#错误码参考)
- [上报频率建议](#附录-a上报频率建议)
- [cURL 示例](#附录-b完整请求示例curl)
- [数据范围参考](#附录-c数据字段范围参考)

---

## 1. 通用说明

### 请求格式

- **Content-Type**: `application/json`
- **字符编码**: UTF-8

### 响应格式

```json
{"ok": true, ...}          // 成功
{"error": "描述", "code": "ERROR_CODE"}  // 失败
```

### 绑定状态流转

```
手表首次开机 → register → bind_status: pending（待管理员激活）
管理员后台激活 → bind_status: active
手表可正常使用 → upload / alerts / ack
管理员禁用 → bind_status: disabled
```

---

## 2. 手表注册

手表首次开机时调用，上报硬件序列号获取 `device_id`。

```test
POST /api/watch/register/
```

**无需鉴权**

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `hardware_serial` | string | ✅ | 硬件唯一标识（序列号/MAC） |
| `firmware_version` | string | | 固件版本 |
| `latitude` | float | | 初始纬度 |
| `longitude` | float | | 初始经度 |

**新设备 → 201：**

```json
{"ok": true, "device_id": "WATCH-A3F8K1Z2", "bind_status": "pending", "message": "设备已注册，等待管理员激活"}
```

**已激活重连 → 200：**

```json
{"ok": true, "device_id": "WATCH-A3F8K1Z2", "bind_status": "active", "message": "设备已激活"}
```

---

## 3. 设备心跳

维持在线，所有状态设备均可调用。响应 `bind_status` 让手表感知激活状态变化。

```
POST /api/watch/heartbeat/
X-Device-ID: WATCH-A3F8K1Z2
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `latitude` | float | | 当前纬度 |
| `longitude` | float | | 当前经度 |

```json
{"ok": true, "server_time": "2026-07-14 10:30:05", "device_id": "WATCH-A3F8K1Z2", "bind_status": "pending"}
```

> 手表发现 `bind_status` 变为 `"active"` 后开始上传健康数据。

---

## 4. 数据上传

上传生理数据+GPS，**仅已激活设备可用**。服务器自动存储健康数据、轨迹、判断预警。

```
POST /api/watch/upload/
X-Device-ID: WATCH-001
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|:---:|------|------|
| `heart_rate` | int | | 75 | 心率 (bpm) |
| `blood_oxygen` | float | | 98.0 | 血氧 (%) |
| `blood_pressure_sys` | int | | 120 | 收缩压 (mmHg) |
| `blood_pressure_dia` | int | | 80 | 舒张压 (mmHg) |
| `step_frequency` | int | | 0 | 步频 (步/分) |
| `core_temperature` | float | | 37.0 | 核心温度 (℃) |
| `latitude` | float | | 上次值 | 纬度 (WGS84) |
| `longitude` | float | | 上次值 | 经度 (WGS84) |
| `timestamp` | string | | 服务器时间 | 采集时间 (ISO 8601) |

**正常响应：**
```json
{"ok": true, "server_time": "2026-07-14 10:30:01"}
```

**触发预警（38℃ ≤ T < 39℃）：**
```json
{"ok": true, "server_time": "...", "alert": {"type": "normal", "risk_level": "warning", "advice": "适当降低活动强度..."}}
```

**触发高风险（T ≥ 39℃）：**
```json
{"ok": true, "server_time": "...", "alert": {"type": "high_risk", "risk_level": "high_risk", "advice": "立即停止当前活动..."}}
```

### 预警阈值

| 核心温度 | 风险等级 | 颜色 |
|---------|---------|:---:|
| < 38.0℃ | normal 正常 | 🟢 |
| 38.0–39.0℃ | warning 普通预警 | 🟡 |
| ≥ 39.0℃ | high_risk 高风险 | 🔴 |

---

## 5. 拉取预警

获取服务端未读预警，**仅已激活设备可用**。

```
GET /api/watch/alerts/?limit=10
X-Device-ID: WATCH-001
```

```json
{"alerts": [{
  "id": 42, "alert_type": "normal", "risk_level": "warning",
  "core_temperature": 38.6, "heart_rate": 88, "blood_oxygen": 96.5,
  "advice_text": "适当降低活动强度，注意补充水分",
  "created_at": "2026-07-14 10:30:01"
}]}
```

---

## 6. 确认预警已读

```
POST /api/watch/alerts/{alert_id}/ack/
X-Device-ID: WATCH-001
```

```json
{"ok": true}
```

---

## 7. 待绑定设备列表

**需要 Session 登录**

```
GET /api/devices/pending/
```

```json
{"pending_devices": [{
  "id": 9, "device_id": "WATCH-A3F8K1Z2", "hardware_serial": "SN-001",
  "is_online": true, "last_report_time": "2026-07-14 18:30:00",
  "latitude": 30.58, "longitude": 104.07,
  "project_id": 1, "project_name": "成都某路执勤"
}]}
```

---

## 8. 激活绑定设备

管理员填写民警信息并激活设备。

```
POST /api/devices/{device_db_id}/bind/
Content-Type: application/json
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `project_id` | int | 所属项目 ID |
| `officer_name` | string | 民警姓名 |
| `officer_age` | int | 年龄 |
| `officer_gender` | string | 性别（男/女） |
| `asset_code` | string | 资产编码 |
| `marker_shape` | string | 图标形状 |
| `marker_color` | string | 图标颜色 |

```json
{"ok": true, "device_id": "WATCH-A3F8K1Z2", "bind_status": "active", "message": "设备已激活"}
```

---

## 9. 项目辖区 GeoJSON

获取项目关联的行政区划 GeoJSON，用于大屏地图渲染。

```
GET /api/projects/{project_id}/jurisdiction/
```

```json
{
  "project_id": 1, "project_name": "成都某路执勤",
  "fill_color": "#1890FF", "stroke_color": "#1890FF",
  "geojson": {
    "type": "FeatureCollection",
    "features": [{
      "type": "Feature",
      "geometry": {"type": "Polygon", "coordinates": [[[104.0,30.5], ...]]},
      "properties": {"name": "锦江区", "level": "county", "code": "510104"}
    }]
  }
}
```

---

## 错误码参考

| 错误码 | HTTP | 说明 |
|--------|:---:|------|
| `MISSING_DEVICE_ID` | 401 | 缺少 `X-Device-ID` 请求头 |
| `DEVICE_NOT_FOUND` | 404 | 设备未注册 |
| `DEVICE_NOT_ACTIVATED` | 403 | 设备待激活，不能上传数据 |
| `DEVICE_DISABLED` | 403 | 设备已被禁用 |
| `MISSING_SERIAL` | 400 | 注册时缺少硬件序列号 |
| `INVALID_JSON` | 400 | 请求体不是合法 JSON |

---

## 权限矩阵

| 端点 | pending | active | disabled |
|------|:---:|:---:|:---:|
| `POST /api/watch/register/` | ✅ | ✅ | ❌ |
| `POST /api/watch/heartbeat/` | ✅ | ✅ | ❌ |
| `POST /api/watch/upload/` | ❌ | ✅ | ❌ |
| `GET /api/watch/alerts/` | ❌ | ✅ | ❌ |
| `POST /api/watch/alerts/<id>/ack/` | ❌ | ✅ | ❌ |

---

## 附录 A：上报频率建议

| 场景 | 上传频率 | 心跳频率 | 拉预警频率 |
|------|:---:|:---:|:---:|
| 正常执勤 | 10s | — | 30s |
| 高强度活动 | 5s | — | 10s |
| 低功耗待机 | — | 30s | 60s |
| 预警触发后 | 3s | — | 5s |

---

## 附录 B：完整请求示例（cURL）

```bash
# 注册
curl -X POST http://101.201.29.99:8000/api/watch/register/ \
  -H "Content-Type: application/json" \
  -d '{"hardware_serial": "SN-001"}'

# 心跳
curl -X POST http://101.201.29.99:8000/api/watch/heartbeat/ \
  -H "Content-Type: application/json" \
  -H "X-Device-ID: WATCH-A3F8K1Z2" \
  -d '{"latitude": 30.57, "longitude": 104.07}'

# 上传数据
curl -X POST http://101.201.29.99:8000/api/watch/upload/ \
  -H "Content-Type: application/json" \
  -H "X-Device-ID: WATCH-A3F8K1Z2" \
  -d '{"heart_rate": 88, "core_temperature": 38.6, "latitude": 30.572, "longitude": 104.066}'

# 拉取预警
curl "http://101.201.29.99:8000/api/watch/alerts/?limit=5" \
  -H "X-Device-ID: WATCH-A3F8K1Z2"

# 确认已读
curl -X POST http://101.201.29.99:8000/api/watch/alerts/42/ack/ \
  -H "X-Device-ID: WATCH-A3F8K1Z2"
```

---

## 附录 C：数据字段范围参考

| 字段 | 合理范围 | 单位 |
|------|---------|------|
| heart_rate | 30–250 | bpm |
| blood_oxygen | 70–100 | % |
| blood_pressure_sys | 60–260 | mmHg |
| blood_pressure_dia | 30–150 | mmHg |
| step_frequency | 0–300 | 步/分 |
| core_temperature | 35.0–43.0 | ℃ |
| latitude | 18–54 | 度 |
| longitude | 73–136 | 度 |

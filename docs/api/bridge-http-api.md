# 中继服务器 API 文档 — Bridge ↔ 后端 HTTP

> 中继服务器（`bridge/`）订阅 EMQX 的手表数据，通过 HTTP 转发到后端 API。
> 本文档描述 Bridge 调用的后端 API 端点。

---

## 基础信息

| 项目 | 值 |
|---|---|
| 后端地址 | `http://101.201.29.99:8001` |
| 认证方式 | `X-Device-ID` 请求头（设备硬件序列号） |
| 超时 | 6 秒 |
| 重试 | 失败后 1 次（退避 2^n 秒） |

---

## 端点一览

| 方法 | 路径 | 说明 | 调用时机 |
|---|---|---|---|
| `POST` | `/api/watch/register/` | 设备注册 | 首次看到新设备 |
| `POST` | `/api/watch/upload/` | 上传生命体征 | 每 15s（完整帧放行后有数据时） |
| `POST` | `/api/watch/heartbeat/` | 心跳保活 | 每 60s |
| `GET`  | `/api/watch/alerts/` | 拉取待下发预警 | 每 15s 轮询 |
| `POST` | `/api/watch/alerts/{id}/ack/` | 确认预警已送达 | 每次预警下发后 |
| `POST` | `/v1/core-temperature/estimate` | 核心温度推算（独立模型服务） | 每凑齐 20 个心率样本 |

---

## API 来源说明

| API | 部署位置 | 负责人 |
|---|---|---|
| `/api/watch/*` | `101.201.29.99:8001` | 后端同学（待上线） |
| `/v1/core-temperature/estimate` | `20.205.12.160:8001` | 模型同学（已就绪 ✅） |

---

## 1. 设备注册

```
POST /api/watch/register/
X-Device-ID: A80-82432237337554
Content-Type: application/json
```

### 请求体

```jsonc
{
  "hardware_serial": "A80-82432237337554",   // A80 硬件序列号
  "firmware_version": "A80-bridge/v1.1"
}
```

### 成功响应（200）

```jsonc
{
  "ok": true,
  "device_id": "WATCH-001",     // 后端分配的内部 ID
  "bind_status": "active"       // active | pending | disabled
}
```

### 约定

- `bind_status=active` 的设备才能上传数据和触发告警。
- **幂等设计**：新设备返回 `pending`（等待管理员激活），已激活设备返回 `active`。

---

## 2. 上传生命体征

```
POST /api/watch/upload/
X-Device-ID: WATCH-001
Content-Type: application/json
```

### 请求体

```jsonc
{
  "heart_rate": 88,                  // 心率 bpm（Int, 30~250）
  "blood_oxygen": 97,                // 血氧 %（Float, 70~100）
  "blood_pressure_sys": 120,         // 收缩压 mmHg（Int）
  "blood_pressure_dia": 80,          // 舒张压 mmHg（Int）
  "step_frequency": 45,              // 步频 步/分钟（bridge 实时计算，非累计步数）
  "core_temperature": 37.2,          // 核心温度 ℃ — 手表不上报此字段，待后端模型推算
  "latitude": 39.9042,               // 缺 null
  "longitude": 116.4074,             // 缺 null
  "timestamp": "2026-07-17T14:30:00+08:00"  // ISO 8601 带时区
}
```

### 约定

- **所有字段可选**：只发送有值的字段，null 字段不传。
- **不完整帧**：Bridge 只要求至少有一项生命体征（心率/血氧/血压之一）就上传，不要求四项全齐。
- **核心温度**：手表不采集 coreTemp。如果后端模型推算成功 → 返回 alert。

### 成功响应（200）

```jsonc
{
  "ok": true,
  "alert": {                         // ★ 后端返回的预警（可能为空）
    "id": 42,
    "risk_level": "high_risk",       // high_risk | warning
    "core_temperature": 39.5,
    "officer_name": "张三",
    "advice": "请立即停止活动，转移至阴凉处"
  }
}
```

如果 `alert` 不为空，Bridge 会将其发布到 MQTT 主题 `watch/{deviceId}/alert`，同时完成 ack。

---

## 3. 心跳

```
POST /api/watch/heartbeat/
X-Device-ID: WATCH-001
Content-Type: application/json
```

### 请求体

```jsonc
{
  "latitude": 39.9042,     // 可选
  "longitude": 116.4074    // 可选
}
```

### 响应

```jsonc
{
  "ok": true,
  "bind_status": "active"
}
```

---

## 4. 拉取预警（Bridge 主动轮询）

```
GET /api/watch/alerts/?limit=5
X-Device-ID: WATCH-001
```

### 响应

```jsonc
{
  "alerts": [
    {
      "id": 42,
      "risk_level": "high_risk",
      "core_temperature": 39.5,
      "officer_name": "张三",
      "advice": "请立即停止活动"
    }
  ]
}
```

---

## 5. 确认预警送达

```
POST /api/watch/alerts/42/ack/
X-Device-ID: WATCH-001
Content-Type: application/json
```

### 请求体

```jsonc
{}
```

### 成功响应（200）

```jsonc
{
  "ok": true
}
```

---

## 6. 核心温度推算（独立模型服务）

```
POST /v1/core-temperature/estimate
Content-Type: application/json
```

### 请求体

```jsonc
{
  "device_id": "A80-PROD-001",
  "samples": [
    {"heart_rate": 82,  "timestamp": "2026-07-17T10:00:00+08:00"},
    {"heart_rate": 83,  "timestamp": "2026-07-17T10:01:00+08:00"},
    // ... 共 20 条
  ]
}
```

| 字段 | 说明 |
|---|---|
| `device_id` | 设备标识 |
| `samples[].heart_rate` | 心率 bpm（Int） |
| `samples[].timestamp` | ISO 8601 带时区 |

### 成功响应（200）

```jsonc
{
  "ok": true,
  "device_id": "WATCH-6B6D32BA",
  "core_temperature": 37.456,          // ★ 直接取这个字段
  "source": "informer_model_1",
  "model_version": "core-estimator-kalman-hr-only-1.0.0",
  "window_size": 20,
  "timestamp": "2026-07-17T02:19:00Z"
}
```

### 错误响应

| 状态码 | 含义 |
|---|---|
| 422 | 心率样本数量不是 20 或值超出 30~250 |
| 503 | 模型权重未成功加载 |

Bridge 只在 HTTP 200 且 `ok=true` 时提取 `core_temperature`，其他情况降级到缓存值。

### Bridge 集成方式

- Bridge 为每个手表缓冲心率样本（最近 20 条）。
- 凑齐 20 条后调用此 API，结果写入 `core_temperature`，夹带到下次 `upload` 请求中发送给后端。
- API 不可达时静默降级：使用上一次缓存结果，不影响数据上报。
- 配置环境变量：`BRIDGE_CORE_TEMP_API_URL=http://20.205.12.160:8001/v1/core-temperature/estimate`

---

## Bridge 内部约定（后端不需要关心）

- **离线队列**：手表断线时数据缓存 SQLite。重连后分批补传（每批 100 条）。中继不缓存——EMQX 断连时数据会丢失，需手表侧补偿。
- **校时**：Bridge 每次收到手表上线 → 发布 `watch/{deviceId}/time`（当前 UTC 毫秒），手表据此修正系统时钟。
- **去重**：同 ID 预警不会重复下发。发布失败会在下次轮询时重试（只重试 MQTT 发布，不重复调 ACK）。
- **僵尸恢复**：投递过程中如进程崩溃，in-flight 预警超 120 秒自动释放，后续轮询会重试。

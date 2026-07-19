# 大屏端 API 文档 — MQTT 实时数据

> **写给做大屏的同学**：你不需要看代码。大屏通过 MQTT WebSocket 直连消息中间件，
> 订阅以下 3 个主题即可拿到所有实时数据。不用管 HTTP、不用管数据库。

---

## 连接信息

| 项目 | 值 |
|---|---|
| 协议 | MQTT over WebSocket |
| 地址 | `ws://39.105.86.77:8083/mqtt` |
| 认证 | 当前无（匿名），生产环境会加 |
| QoS | 1（至少一次送达） |

---

## 主题一览

```
watch/{deviceId}/vital    ← 生理数据（核心）
watch/{deviceId}/status   ← 在线状态
watch/{deviceId}/alert    ← 预警通知
```

`{deviceId}` 是手表设备标识，例如 `A80-PROD-001`。大屏订阅 `watch/+/vital` 即可收到所有设备数据。

---

## 1. 生理数据 `watch/{deviceId}/vital`

**方向**：手表 → EMQX → 大屏  
**频率**：每 15 秒一帧

### JSON 格式

```jsonc
{
  // ── 设备标识 ──
  "deviceId": "A80-PROD-001",
  "timestamp": 1784266823680,        // Unix 毫秒（手表时钟，可能不准）

  // ── 定位 ──
  "latitude": 39.9042,               // 缺省 null（GPS 未定位时）
  "longitude": 116.4074,             // 缺省 null
  "gpsAccuracy": 5.0,                // 米，缺省 null

  // ── 生命体征（均为可空） ──
  "heartRate": 88,                   // 心率 bpm，范围 30~250
  "spo2": 97,                        // 血氧 %，范围 70~100
  "bloodPressure": "120/80",         // 收缩压/舒张压 mmHg（字符串），缺省 null
  "steps": 12345,                    // 开机累计步数（非步频）
  "batteryLevel": 85,                // 电量 0~100

  // ── 穿戴状态 ──
  "worn": true,                      // true=佩戴中, false=未佩戴, 缺省 null
  "dataQuality": "complete",         // complete | partial | not_worn | no_vitals

  // ── 版本 ──
  "firmwareVersion": "1.1.0-a80"
}
```

### 关键约定

- **没有 `coreTemp`**：核心温度由后端模型推算后经由「预警」主题下发，不在 vital 里。
- **血氧每 60s 才有**：15s 上报周期中，4 帧有 3 帧 `spo2` 为 null。这是正常的。
- **`dataQuality` 语义**：

| 值 | 含义 | 大屏建议 |
|---|---|---|
| `complete` | 心率+血氧+血压都有 | 正常展示 |
| `partial` | 至少缺一项（常见） | 正常展示，缺失值显 `--` |
| `not_worn` | 手表未佩戴 | 显示"未佩戴"，不展示生理数据 |
| `no_vitals` | 传感器无响应 | 显示"数据不可用" |

---

## 2. 在线状态 `watch/{deviceId}/status`

**方向**：手表 → EMQX → 大屏  
**频率**：每 60 秒  
**特性**：**retained**（重连后自动获取最后一条）

### JSON 格式

```jsonc
{
  "status": "online",                // "online" | "offline"
  "timestamp": 1784266823680,
  "batteryLevel": 85
}
```

### 约定

- 状态主题有 **LWT（遗嘱）**：手表异常断线 30 秒后 EMQX 自动发布 `{"status":"offline"}`。
- 大屏应缓存「上次见到数据」的时间戳，超过 90 秒无 vital 也视为离线。

---

## 3. 预警通知 `watch/{deviceId}/alert`

**方向**：中继服务器 → EMQX → 手表 & 大屏  
**频率**：按需（后端模型判定触发时）

### JSON 格式

```jsonc
{
  "deviceId": "A80-PROD-001",
  "alertId": 42,                     // 预警编号
  "alertType": "高风险预警",          // "高风险预警" | "普通预警"
  "riskLevel": "high_risk",          // high_risk | warning
  "coreTemp": 39.5,                  // ★ 模型推算的核心温度（这是唯一有 coreTemp 的主题）
  "officerName": "张三",             // 佩戴民警姓名
  "advice": "请立即停止活动，转移至阴凉处并补充水分",
  "timestamp": 1784266823680
}
```

### 大屏特别关注

- **`coreTemp` 只通过 alert 下发**。收到后写入设备状态，后续 vital 帧以此判断风险等级。
- 弹窗 + 侧边栏记录都要展示。

---

## 数据流全景（大屏视角）

```
                          订阅：watch/+/vital
                          订阅：watch/+/status
                          订阅：watch/+/alert
                                  ▲
A80 手表 ──MQTT──▶ EMQX (39.105.86.77) ◀──WS── 大屏
                            │
                            └──▶ 中继服务器 ──HTTP──▶ 后端 API
                                    │
                                    │ 轮询告警
                                    └──▶ 发布到 watch/{id}/alert
```

**大屏不需要关心中继服务器和 HTTP API**。你只连 EMQX WebSocket，收上面 3 个主题就够了。

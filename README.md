# 热应激预警系统

> A80 智能手表生理监测 → MQTT 消息中继 → 大屏实时可视化
> 
> **项目地址**：[github.com/AYin-Z/heat-stress-warning-system](https://github.com/AYin-Z/heat-stress-warning-system)

---

## 仓库结构

```
├── watch-app/                 ← 移动端（A80 手表 Android 应用）
│   ├── app/src/               Android 源码（Kotlin）
│   └── keystore/              平台签名证书
│
├── frontend/                  ← 大屏端（React 实时监控面板）
│   ├── src/components/        6 个 UI 组件
│   ├── src/services/mqtt.ts   MQTT WebSocket 客户端
│   ├── src/store/             全局状态（Context + Reducer）
│   └── src/types/             类型定义
│
├── bridge/                    ← 中继服务器（MQTT ↔ HTTP 桥接）
│   ├── bridge.py              主程序（596 行 Python）
│   ├── test_bridge.py         单元测试
│   └── heatstress-bridge.service  systemd 部署文件
│
├── model/                     ← 模型端（核心温度推算，待实现）
│
├── docs/                      ← 文档
│   ├── api/                    API 文档（大屏同学从这里开始）
│   │   ├── mqtt-api.md         大屏 ↔ MQTT 接口
│   │   └── bridge-http-api.md  中继 ↔ 后端 HTTP 接口
│   ├── product/                产品需求与硬件文档
│   └── reports/                测试报告
│
└── .github/workflows/         CI（三端构建 + 测试）
```

---

## 面向不同角色的阅读顺序

| 角色 | 先读 |
|---|---|
| 🖥 **做大屏的同学** | → [`docs/api/mqtt-api.md`](docs/api/mqtt-api.md)（连接 MQTT 就能拿到数据） |
| 🔧 **做后端的同学** | → [`docs/api/bridge-http-api.md`](docs/api/bridge-http-api.md)（实现 watch API） |
| 🤖 **做模型的同学** | → [`model/README.md`](model/README.md) |
| 📱 **做移动端的同学** | → `mobile/` 源码 + [测试报告](docs/reports/REAL_DEVICE_TEST_REPORT.md) |
| 🚀 **部署运维** | → [`bridge/heatstress-bridge.service`](bridge/heatstress-bridge.service) + 下方架构图 |

---

## 数据流

```
A80 手表 ──MQTT──▶ EMQX (39.105.86.77)
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      中继服务器     大屏(WS)     手表(alert)
      (bridge)     (dashboard)   (订阅)
          │
      HTTP ▼
    后端 API (101.201.29.99:8001)
```

| 链路 | 协议 | 说明 |
|---|---|---|
| 手表 → EMQX | MQTT TCP | 15s vital + 60s status + LWT 遗嘱 |
| 大屏 → EMQX | MQTT WebSocket | 订阅 `watch/+/vital` `watch/+/status` `watch/+/alert` |
| 中继 → EMQX | MQTT TCP | 订阅 vital/status，发布 alert/time |
| 中继 → 后端 | HTTP JSON | 6 秒超时，指数退避重试 |

---

## MQTT 主题

| 主题 | 方向 | QoS | 说明 |
|---|---|---|---|
| `watch/{id}/vital` | 手表→大屏/中继 | 1 | 生理数据（15s） |
| `watch/{id}/status` | 手表→大屏/中继 | 1 | 在线状态（60s，retained，LWT） |
| `watch/{id}/alert` | 中继→手表/大屏 | 1 | 预警下发（按需） |
| `watch/{id}/time` | 中继→手表 | 1 | 校时（上线时） |

---

## 当前状态

- ✅ 手表端：采集+MQTT+离线队列+告警接收+开机自启
- ✅ 中继端：MQTT↔HTTP 桥接+校时+告警轮询+ACK
- ✅ 大屏端：实时面板+风险饼图+地图+预警弹窗
- ✅ CI：GitHub Actions 三端自动化
- ❌ 模型端：尚未接入
- ❌ 手表：无独立网络（依赖 ADB USB）
- ❌ 后端：队友 API 未上线

详见 [测试报告](docs/reports/REAL_DEVICE_TEST_REPORT.md)。

---

## 构建

### 移动端
### 移动端

```bash
cd watch-app
export JUWEI_PLATFORM_STORE_FILE=/path/to/platform.jks
export JUWEI_PLATFORM_STORE_PASSWORD=your_password
export JUWEI_PLATFORM_KEY_ALIAS=android_platform
export JUWEI_PLATFORM_KEY_PASSWORD=your_password
./gradlew assembleRelease \
  -Pdevice_id=A80-PROD-001 \
  -Pmqtt_url=tcp://39.105.86.77:1883
```

### 大屏端

```bash
cd frontend
cp .env.example .env   # 编辑 MQTT 地址
npm install && npm run build
```

### 中继端

```bash
cd bridge
pip install -r requirements.txt
BRIDGE_MQTT_BROKER=localhost BRIDGE_API_BASE=http://... python bridge.py
```

---

## 已知限制

- A80 无 Wi-Fi/SIM：MQTT 依赖 `adb reverse`，脱离电脑断连
- 时钟不可信：冷启动回到 2012 年，依赖 MQTT 校时（离线无 NTP 兜底）
- MQTT 无安全：匿名访问 + 明文 + 自签名证书
- 核心温度缺失：手表不计算，后端模型未接入
- Django 大屏后端存在空值写入故障（README 历史记录）

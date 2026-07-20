# 热应激预警系统

> A80 智能手表实时生理监测 → EMQX MQTT → 核心温度模型 → Django 大屏可视化
>
> 适用于消防、户外作业、高强度训练等热应激高危场景的全链路预警系统。

---

## 仓库结构

```
├── watch-app/                 ← A80 手表 Android 应用（Kotlin）
│   ├── docs/                  聚伟硬件驱动文档
│   └── keystore/              平台签名证书
│
├── frontend/                  ← 大屏端（Django 5.2 实时监控面板）
│   ├── core/                  Django 主应用（models/views/admin）
│   ├── heatstress/            Django 项目配置
│   ├── templates/             4 个模板（dashboard/login/projects/users）
│   ├── static/                CSS/JS/图片
│   ├── data/gis/              行政区划 Shapefile
│   ├── docs/                  API 接口文档 + 部署指南
│   └── deploy.sh              一键部署脚本
│
├── bridge/                    ← 中继桥接（MQTT ↔ 核心温度模型 HTTP）
│   ├── bridge.py              主程序
│   ├── test_bridge.py + test_bind.py  单元测试
│   ├── simulate_watch_mqtt.py 手表 MQTT 模拟器
│   └── heatstress-bridge.service  systemd 部署文件
│
├── model/                     ← 核心温度推算模型（Informer）
│   ├── deploy/                Docker Compose + 生产代码
│   ├── artifacts/             模型配置与 Scaler
│   └── pret/                  旧推理原型
│
├── docs/                      ← 统一文档索引
│   ├── api/                   通信协议文档（MQTT / HTTP）
│   ├── product/               产品需求与硬件文档
│   └── reports/               测试报告
│
└── .github/workflows/         CI（三端构建 + 测试）
```

---

## 数据流

```
┌─────────────────────────────────────────────────────────────┐
│                        A80 手表                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ SensorService (15s 周期)                              │  │
│  │  hrs3918 传感器 → 心率/血氧/血压/GPS/步数/电量         │  │
│  │  传感器3次收敛失败 → 自动模拟 fallback (HR 72~78)      │  │
│  │  离线数据暂存 SQLite 队列 (最大10,000条)               │  │
│  │  双重校时: NTP(ntp.aliyun.com) + MQTT 服务器校时      │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         │ MQTT (4G SIM → seth_lte0)        │
│                         ▼                                   │
│             watch/{id}/vital (15s)                          │
│             watch/{id}/status (60s, retained + LWT)         │
│             watch/{id}/bind (按需)                          │
│                         │                                   │
│             订阅接收:  ◄─ watch/{id}/core-temp                │
│                        ◄─ watch/{id}/alert (振动+红底)       │
│                        ◄─ watch/{id}/time                    │
│                        ◄─ watch/{id}/bind/response           │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              中继服务器 (39.105.86.77)                      │
│  ┌──────────────┐    ┌──────────────────────────────┐      │
│  │   EMQX       │───▶│  Bridge (bridge-lite)        │      │
│  │   1883/8083  │    │  订阅 watch/{id}/vital        │      │
│  │   客户端:    │    │  → 调用模型API推算核心温度     │      │
│  │   手表       │    │  → 发布 core-temp/alert       │      │
│  │   Bridge    │    │  → 转发到 Dashboard API        │      │
│  │   Dashboard │    └──────────────┬─────────────────┘      │
│  │   模型服务   │                   │                        │
│  └──────────────┘                   │ HTTP POST              │
└────────────────────┬────────────────┼────────────────────────┘
                     │                │
                     ▼                ▼
┌─────────────────┐  ┌────────────────────────────────────────┐
│ 核心温度模型     │  │  大屏 Dashboard (101.201.29.99:8001)   │
│ FastAPI+Informer│  │  ┌────────────────────────────────┐    │
│ 20.205.12.160   │  │  │ Django 5.2 + ECharts + 高德地图 │    │
│ HR+SpO2 → 37°C  │  │  │ 实时体征面板 / 历史趋势 / 项目管理│   │
└─────────────────┘  │  │ 用户管理 / 设备注册 / 告警记录    │    │
                     │  └────────────────────────────────┘    │
                     │  ┌────────────────────────────────┐    │
                     │  │ MQTT Client (manage.py run_mqtt)│    │
                     │  │ 订阅全部主题 → 写入 PostgreSQL  │    │
                     │  │ 核心温度≥38°C → 自动创建Alert   │    │
                     │  │ 体征数据→HealthData表            │    │
                     │  └────────────────────────────────┘    │
                     └────────────────────────────────────────┘
```

---

## 组件部署

| 节点 | IP | 角色 | 技术栈 | 状态 |
|------|-----|------|--------|------|
| A80 手表 | 4G SIM | 人体体征采集 | Android 8.1 + hrs3918 | ✅ 生产运行 |
| 中继服务器 | 39.105.86.77 | MQTT Broker + 桥接 | EMQX + bridge-lite (Python) | ✅ 生产运行 |
| 模型服务器 | 20.205.12.160 | HR→核心温度推理 | FastAPI + PyTorch (Informer) | ✅ 就绪 |
| 大屏服务器 | 101.201.29.99 | 可视化+管理 | Django 5.2 / Gunicorn / PostgreSQL | ✅ 生产运行 |

---

## MQTT 主题

| 主题 | 方向 | 频率 | 说明 |
|------|------|:----:|------|
| `watch/{id}/vital` | 手表→中继→大屏 | 15s | 心率/血氧/血压/GPS/步数/电量/QoS1 |
| `watch/{id}/status` | 手表→中继→大屏 | 60s | 在线状态 + Last Will 遗嘱 |
| `watch/{id}/bind` | 手表→中继 | 按需 | 设备绑定请求 |
| `watch/{id}/alert` | 中继→手表&大屏 | 按需 | 热应激预警（含振动） |
| `watch/{id}/core-temp` | 中继→大屏 | 按需 | 模型推算的核心温度 |
| `watch/{id}/bind/response` | 中继→手表 | 按需 | 绑定结果回执 |
| `watch/{id}/time` | 中继→手表 | 上线时 | 服务器校时 |

---

## 文档入口

| 你想做什么 | 入口 |
|-----------|------|
| 📖 手表端详细文档（架构/编译/部署/关键参数） | [`watch-app/README.md`](watch-app/README.md) |
| 🚀 部署大屏 | [`frontend/docs/deploy-guide.md`](frontend/docs/deploy-guide.md) |
| 🔧 部署中继 | [`bridge/README.md`](bridge/README.md) |
| 🤖 模型部署 | [`model/DEPLOYMENT.md`](model/DEPLOYMENT.md) |
| 📋 测试报告 | [`docs/reports/REAL_DEVICE_TEST_REPORT.md`](docs/reports/REAL_DEVICE_TEST_REPORT.md) |
| 📡 MQTT 协议 | [`docs/api/mqtt-api.md`](docs/api/mqtt-api.md) |

---

## 当前状态

- ✅ **手表端**：采集/模拟fallback/离线队列/MQTT直连4G/警报接收振动/开机自启 — **全链路验证通过**
- ✅ **中继端**：MQTT ↔ 模型桥接/校时/告警检测 — **全链路验证通过**
- ✅ **大屏端**：实时体征面板/高德地图设备定位/项目管理/用户管理/告警记录 — **全链路验证通过**
- ✅ **核心温度**：手表→MQTT→桥接→模型→大屏API **CT=37.076°C 回显成功**
- ✅ **警报系统**：MQTT下发→手表振动+红底白字预警— **验证通过**
- ⏳ **模型 Docker**：容器化就绪，待正式接入生产环境
- ⏳ **平台签名**：系统应用 uid=1000，当前 debug key 运行正常

---

## 构建指南

### 手表端

```bash
cd watch-app
# 编译调试版（默认 EMQX 地址已内置）
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk

# 生产构建（可选平台签名）
export JUWEI_PLATFORM_STORE_FILE=/path/to/platform.jks
export JUWEI_PLATFORM_STORE_PASSWORD=*** JUWEI_PLATFORM_KEY_ALIAS=platform
export JUWEI_PLATFORM_KEY_PASSWORD=*** assembleRelease \
  -Pdevice_id=A80-PROD-001 \
  -Pmqtt_url=tcp://39.105.86.77:1883
```

详细参数见 [`watch-app/README.md`](watch-app/README.md)。

### 大屏端

**本地开发（端口 8000）**：
```bash
cd frontend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py import_regions --clear
export MQTT_BROKER=39.105.86.77
export MQTT_PORT=1883

# 终端1：Django Web
python manage.py runserver 0.0.0.0:8000
# 终端2：MQTT 客户端
python manage.py run_mqtt
```

**服务器部署（端口 8001）**：
```bash
cd frontend
bash deploy.sh 8001 <MQTT_BROKER_IP>
```

默认账号 **admin / admin123**。

### 中继端
```bash
cd bridge
pip install -r requirements.txt
BRIDGE_MQTT_BROKER=localhost BRIDGE_API_BASE=http://... python bridge.py
```

---

## 关键设计

### 传感器模拟退路

hrs3918 驱动算法对此硬件无法收敛出有效体征值（`hr_result=0`），连续 3 个采集周期无有效数据后自动启用模拟模式，产生微小变化的仿真体征（HR 72~78, SpO2 97~99, BP 116~123/76~80）以维持全链路验证。

### 离线续传

断网时数据暂存 SQLite 队列（`offline_queue` 表，最大 10,000 条），重连后批量发送（每次 100 条，带指数退避重试）。

### 时钟同步

双重校时：NTP（`ntp.aliyun.com`，6h/次）+ MQTT 服务器校时（上线时）。

### 心率传感器模式切换

聚伟系统属性 `persist.sys.heartrate_test_mode`：
- `1` = 心率模式：`values[0]`=HR, `[2]`=收缩压, `[3]`=舒张压
- `2` = 血氧模式：`values[1]`=SpO2
- `values[7]`=佩戴状态（`2`=正确佩戴）

---

## 硬件支持

| 设备 | 说明 |
|------|------|
| 聚伟 A80 | 320×380 方屏, Android 8.1, hrs3918 传感器, 4G LTE, GPS |
| USB-ADB | 开发和调试用，生产环境通过 4G SIM 直连 EMQX |
| 磁吸充电 | 触点充电，运行时保持佩戴 |

---

## License

Internal project — Heat Stress Warning System.

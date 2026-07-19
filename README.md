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
├── frontend/                  ← 大屏端（Django 5.2 实时监控面板）
│   ├── core/                  Django 主应用（models/views/admin）
│   ├── heatstress/            Django 项目配置
│   ├── templates/             4 个模板（dashboard/login/projects/users）
│   ├── static/                CSS/JS/图片
│   ├── data/gis/              行政区划 Shapefile
│   ├── docs/                  API接口文档 + 部署指南
│   └── deploy.sh              一键部署脚本
│
├── bridge/                    ← 中继服务器（MQTT ↔ HTTP 桥接）
│   ├── bridge.py              主程序（767 行 Python）
│   ├── test_bridge.py + test_bind.py  单元测试
│   ├── simulate_watch_mqtt.py 手表 MQTT 模拟器
│   └── heatstress-bridge.service  systemd 部署文件
│
├── model/                     ← 模型端（核心温度推算）
│   ├── deploy/                Docker Compose + 生产代码
│   ├── artifacts/             模型配置与 Scaler
│   └── pret/                  旧推理原型
│
├── docs/                      ← 统一文档索引
│   ├── README.md              文档总入口（按角色/模块分类）
│   ├── api/                   通信协议文档
│   │   ├── mqtt-api.md        大屏 ↔ MQTT 接口
│   │   └── bridge-http-api.md 中继 ↔ 后端 HTTP 接口
│   ├── product/               产品需求与硬件文档
│   └── reports/               测试报告
│
├── .github/workflows/         CI（三端构建 + 测试）
└── docs/README.md             点此开始阅读
```

## 数据流

```
A80 手表 ──MQTT──▶ EMQX (39.105.86.77)
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      中继服务器     大屏(WS)     手表(alert)
      (bridge)     Django 大屏    (订阅)
          │
      HTTP ▼
    模型服务 (20.205.12.160:8001)
```

| 链路 | 协议 | 说明 |
|------|------|------|
| 手表 → EMQX | MQTT TCP | 15s vital + 60s status + LWT 遗嘱 |
| 大屏 → EMQX | MQTT TCP | 订阅 bind/vital/status/alert |
| 中继 → EMQX | MQTT TCP | 订阅 vital/status，发布 alert/time |
| 中继 → 模型 | HTTP JSON | 20 分钟心率 → 核心温度推算 |

## 快速导航

| 你想做什么 | 入口 |
|-----------|------|
| 📖 阅读全部文档 | [`docs/README.md`](docs/README.md) |
| 🚀 部署大屏 | [`frontend/docs/deploy-guide.md`](frontend/docs/deploy-guide.md) |
| 🔧 部署中继 | [`bridge/README.md`](bridge/README.md) |
| 🤖 模型部署 | [`model/DEPLOYMENT.md`](model/DEPLOYMENT.md) |
| 📋 测试报告 | [`docs/reports/REAL_DEVICE_TEST_REPORT.md`](docs/reports/REAL_DEVICE_TEST_REPORT.md) |
| 📡 MQTT 协议 | [`docs/api/mqtt-api.md`](docs/api/mqtt-api.md) |
| 🔌 HTTP API | [`frontend/docs/watch-api.md`](frontend/docs/watch-api.md) |

## 当前状态

- ✅ 手表端：采集+MQTT+离线队列+告警接收+开机自启
- ✅ 中继端：MQTT↔HTTP 桥接+校时+告警轮询+ACK
- ✅ 大屏端：Django 实时面板+地图+项目管理+用户管理
- ✅ CI：GitHub Actions 三端自动化
- ⏳ 模型端：Docker 就绪，待生产接入
- ⏳ 手表：无独立网络（需配 Wi-Fi/SIM）
- ⏳ 后端：绑定/校时在校验中

## 构建

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
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### 中继端
```bash
cd bridge
pip install -r requirements.txt
BRIDGE_MQTT_BROKER=localhost BRIDGE_API_BASE=http://... python bridge.py
```

## 已知限制

- A80 无 Wi-Fi/SIM：MQTT 依赖 ADB reverse，脱离电脑断连
- 时钟不可信：冷启动回到 2012 年，依赖 MQTT 校时
- MQTT 无安全：匿名访问 + 明文
- 核心温度：手表不计算，模型 Docker 已就绪待生产接入

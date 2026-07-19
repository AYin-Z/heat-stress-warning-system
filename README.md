# 热应激预警系统 (Heat Stress Warning System)

PC 端大屏指挥中心，通过 **MQTT 直连 EMQX 中继服务器** 实时接收 A80 智能手表生理数据，结合核心温度推算进行热应激预警，预警信号自动分发到手表。

## 系统架构

```
A80 手表 ──MQTT(TCP)──▶ EMQX (中继)
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                  ▼
    中继(bridge.py)    大屏/后端(本项目)    手表(alert)
    校时+模型API       MQTT客户端订阅
                             │
                      预警检测 ──► MQTT发布 watch/{id}/alert
```

| 链路 | 协议 | 说明 |
|------|------|------|
| 手表 → EMQX | MQTT TCP | 15s vital + 60s status + LWT 遗嘱 |
| 后端 → EMQX | MQTT TCP | 订阅 bind/vital/status/alert，发布预警 |
| 中继 → EMQX | MQTT TCP | 校时 + 核心温度模型 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Django 5.2 + Gunicorn |
| MQTT | paho-mqtt 2.x |
| 前端 | 原生 HTML/CSS/JS + 高德地图 JS API 2.0 + ECharts 5.5 |
| 数据库 | SQLite |
| GIS | Shapely（行政区划点面匹配） |
| 部署 | Linux systemd × 2（Web + MQTT 客户端） |

## 核心功能

### 指挥大屏 `/dashboard/`
- 高德地图：设备位置、轨迹、辖区多边形
- 实时生命体征面板（心率/血氧/血压/核心温度）
- 热应激预警弹窗 + 侧边栏历史
- 8 项统计概览（在线/离线/监测中/数据不可用/从未上报/预警）
- MQTT 实时推送，10 秒轮询刷新

### 项目管理 `/projects/`
- 项目 CRUD + 唯一 recording 机制
- 省→市→县三级行政区划联动（含直辖市、省直辖县自动适配）
- 单区域强制（一个项目一个辖区）
- 辖区配色自定义 + CSV 健康数据导出

### 用户管理 `/users/`
- 左侧项目/设备树形目录
- 设备详情编辑（民警姓名/年龄/性别/标记样式）
- 离线时长显示（"离线 X天X小时"）
- 地理围栏过滤

### MQTT 数据接收
| 主题 | 频率 | 说明 |
|------|:---:|------|
| `watch/+/bind` | 按需 | 手表绑定 → 自动创建/激活 |
| `watch/+/vital` | 15s | 生理数据 |
| `watch/+/status` | 60s | 在线状态 + LWT |
| `watch/+/alert` | 按需 | 预警通知 |

### 关键机制

| 机制 | 说明 |
|------|------|
| **地理围栏** | 辖区几何 + 10km 缓冲，辖区外设备不显示（大屏/统计/用户管理均适用） |
| **离线超时** | 90 秒无上报 → 自动视为离线 |
| **自动发现** | 手表首次发数据 → 自动创建 + 激活 + 归入 recording 项目 |
| **项目切换** | 设备上报时自动归入 recording 项目，支持跨城市演示自动切换 |
| **坐标回退** | 当前坐标为 NULL → 取历史最后已知坐标 |
| **去重** | MQTT 创建 A80-* 设备时自动清理 HTTP 注册的 WATCH-* 虚设备 |
| **软编码** | 全国任意区县可用，辖区从项目 M2M 动态读取，无硬编码 |

### 手表端 API
| 端点 | 用途 | 鉴权 |
|------|------|:---:|
| `POST /api/watch/register/` | 注册 | 无 |
| `POST /api/watch/upload/` | 体征上传 | X-Device-ID |
| `POST /api/watch/heartbeat/` | 状态上报 | X-Device-ID |
| `GET /api/watch/alerts/` | 拉取预警 | X-Device-ID |

## 数据模型

```
Project ──< Device ──< HealthData
                    ├── DeviceLocation (轨迹)
                    └── Alert (预警)
Region (省/市/县三级，含 GeoJSON)
```

| 模型 | 说明 |
|------|------|
| **Project** | 项目/任务，M2M 关联辖区 Region |
| **Device** | 手表，绑定民警信息/在线状态/电量/GPS |
| **HealthData** | 生理数据（全部 nullable，中继未报= NULL） |
| **Alert** | 热应激预警（普通/高风险） |
| **DeviceLocation** | GPS 轨迹点 |
| **Region** | 行政区划（省/市/县，含 GeoJSON 边界） |

## 风险等级

| 等级 | 条件 | 颜色 |
|------|------|------|
| 正常 | coreTemp < 38℃ | 🟢 绿 |
| 普通预警 | 38℃ ≤ coreTemp < 39℃ | 🟠 橙 |
| 高风险预警 | coreTemp ≥ 39℃ | 🔴 红 |
| 监测中 | 有数据但缺 coreTemp | 🔵 蓝 |
| 数据不可用 | 未佩戴/无体征 | 灰蓝 |
| 离线 | 90s 无上报 | ⚫ 深灰 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 数据库 + 管理员
python manage.py migrate
python manage.py createsuperuser

# 导入行政区划
python manage.py import_regions --clear

# 启动 Web 服务
python manage.py runserver 0.0.0.0:8000

# 另一个终端启动 MQTT 客户端
python manage.py run_mqtt
```

设置环境变量：
```bash
export MQTT_BROKER=39.105.86.77
export MQTT_PORT=1883
export AMAP_KEY=你的高德Key
```

## 部署

详见 [`docs/deploy-guide.md`](docs/deploy-guide.md)。

```bash
bash deploy.sh 8001 <MQTT_BROKER_IP>
```

部署后两个 systemd 服务：
- `hotproject` — Django/Gunicorn
- `hotproject-mqtt` — MQTT 客户端

## 项目结构

```
.
├── core/                          # 主应用
│   ├── models.py                  # 数据模型 + 风险分类 + 在线判定
│   ├── views.py                   # 视图（大屏 + 项目 + 手表 API + 地理围栏）
│   ├── urls.py                    # 路由（30+ 端点）
│   ├── mqtt_client.py             # MQTT 客户端（直连 EMQX）
│   └── management/commands/
│       ├── import_regions.py      # 导入行政区划
│       └── run_mqtt.py            # 启动 MQTT 客户端
├── heatstress/                    # Django 配置
│   └── settings.py
├── templates/
│   ├── dashboard.html             # 指挥大屏
│   ├── projects.html              # 项目管理
│   ├── users.html                 # 用户管理
│   └── login.html
├── static/
│   ├── css/projects.css
│   └── js/projects.js
├── docs/
│   ├── watch-api.md               # API 接口文档
│   └── deploy-guide.md            # 部署指南
├── deploy.sh                      # 一键部署
├── manage.py
└── requirements.txt
```

## 文档

- [API 接口文档](docs/watch-api.md)
- [部署指南](docs/deploy-guide.md)

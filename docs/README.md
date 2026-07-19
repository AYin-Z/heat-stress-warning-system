# 📚 热应激预警系统 · 文档索引

> 全仓库文档统一入口。按角色/目标快速定位。

## 按模块

### 🖥 大屏后端（Django） — `frontend/`

| 文档 | 路径 | 说明 |
|------|------|------|
| 项目README | `frontend/README.md` | 架构、功能、快速开始、项目结构 |
| 部署指南 | `frontend/docs/deploy-guide.md` | 从零部署到 Linux 服务器 |
| API接口文档 | `frontend/docs/watch-api.md` | 手表端 API（注册/上传/心跳/预警/确认） |

### 🔧 中继服务器（Bridge） — `bridge/`

| 文档 | 路径 | 说明 |
|------|------|------|
| Bridge README | `bridge/README.md` | 行为说明、部署、环境变量 |
| Bridge ↔ 后端 HTTP API | `docs/api/bridge-http-api.md` | 中继调用后端的 6 个端点 |
| 依赖清单 | `bridge/requirements.txt` | Python 包依赖 |
| 单元测试 | `bridge/test_bridge.py` | 6 项行为契约测试 |
| 绑定测试 | `bridge/test_bind.py` | bind topic 功能测试 |
| 手表模拟器 | `bridge/simulate_watch_mqtt.py` | MQTT 仿真脚本 |
| 完整联测模拟器 | `bridge/simulate_comprehensive.py` | 5 场景多设备联动模拟 |

### 📱 手表端（A80 Android） — `watch-app/`

| 文档 | 路径 | 说明 |
|------|------|------|
| 签名信息 | `watch-app/keystore/签名信息.txt` | 平台签名证书信息 |

### 🤖 模型服务 — `model/`

| 文档 | 路径 | 说明 |
|------|------|------|
| 模型README | `model/README.md` | 核心温度预测服务概述、目录结构 |
| Docker部署 | `model/DEPLOYMENT.md` | 三种部署模式、首次启动、环境变量 |
| Docker构建与调试 | `model/deploy/DOCKER_BUILD_AND_DEBUG.md` | 凭据修复、构建、启动、验证、回滚 |
| Watch API集成 | `model/deploy/WATCH_API_INTEGRATION.md` | 20分钟心率窗口接口协议 |
| 推理协议 | `model/README-predict.md` | Kalman → Informer 推理链路说明 |
| 模型制品说明 | `model/artifacts/README.md` | 模型 checkpoint 与 Scaler 说明 |
| API接口文档 | `model/watch-api.md` | 手表 API v2.0（旧完整版） |
| 详细使用说明 | `model/使用说明.docx` | Word 格式完整说明 |
| 依赖清单 | `model/pret/requirements.txt` | 旧原型依赖 |
| 模型服务依赖 | `model/deploy/model-service/requirements.txt` | 生产环境依赖 |
| 旧原型说明 | `model/pret/README.md` | 旧版独立推理原型说明 |

### 📡 MQTT & 通信协议 — `docs/api/`

| 文档 | 路径 | 说明 |
|------|------|------|
| 大屏MQTT接口 | `docs/api/mqtt-api.md` | 大屏只需订阅 3 个主题即可工作 |
| Bridge HTTP API | `docs/api/bridge-http-api.md` | 中继 ↔ 后端 HTTP 接口（6端点） |

### 📦 产品需求与硬件 — `docs/product/`

| 文档 | 路径 | 说明 |
|------|------|------|
| 用户需求文档 | `doc_db521eb22613_需求文档_20260611.docx` | Word 版需求规格 |
| 界面设计 | `doc_b5769320d821_界面设计.pptx` | PPT 版界面原型 |
| 用户需求（理解版） | `doc_1cfe95e61881_用户需求260615（理解版）.pdf` | PDF 版需求解读 |
| A80 产品介绍 | `A80安卓系统二次开发智能手表产品介绍.pdf` | 硬件规格与参数 |
| A80 开发说明 | `聚伟AQ7和A80安卓系统开发说明.pdf` | 平台开发手册 |

### 📋 测试报告 — `docs/reports/`

| 文档 | 路径 | 说明 |
|------|------|------|
| 真实设备测试报告 | `REAL_DEVICE_TEST_REPORT.md` | A80 手表联调验收测试（2026-07-17） |
| 联动模拟报告 | `../../bridge/联测报告_20260719_215916.txt` | 5设备50轮完整联测结果 |

## 按角色阅读

| 角色 | 入口 |
|------|------|
| 🖥 **做大屏的同学** | [`docs/api/mqtt-api.md`](api/mqtt-api.md) — 只需连 MQTT WebSocket 收 3 个主题 |
| 🔧 **做后端的同学** | [`frontend/docs/watch-api.md`](../frontend/docs/watch-api.md) + [`docs/api/bridge-http-api.md`](api/bridge-http-api.md) |
| 🤖 **做模型的同学** | [`model/README.md`](../model/README.md) → [`model/deploy/DOCKER_BUILD_AND_DEBUG.md`](../model/deploy/DOCKER_BUILD_AND_DEBUG.md) |
| 📱 **做移动端的同学** | `watch-app/` 源码 + [`docs/reports/REAL_DEVICE_TEST_REPORT.md`](reports/REAL_DEVICE_TEST_REPORT.md) |
| 🚀 **部署运维** | [`frontend/docs/deploy-guide.md`](../frontend/docs/deploy-guide.md) + [`bridge/README.md`](../bridge/README.md) |

## 数据流全景

```
A80 手表 ──MQTT(TCP)──▶ EMQX (39.105.86.77)
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                   ▼
    中继(bridge.py)     大屏(ws)              手表(alert)
    校时+模型API        Django大屏             订阅
          │
     HTTP ▼
    模型服务 (20.205.12.160:8001)
```

## 架构概览

| 组件 | 技术栈 | 部署 |
|------|--------|------|
| 中继服务器 `bridge/` | Python + paho-mqtt | systemd → 中继服务器 |
| 大屏后端 `frontend/` | Django 5.2 + Gunicorn | systemd → 任意 Linux |
| 大屏前端 `frontend/templates/` | HTML/CSS/JS + 高德地图 + ECharts | Django 模板渲染 |
| 模型服务 `model/` | FastAPI + PyTorch (Informer) | Docker Compose |
| 手表应用 `watch-app/` | Kotlin + Android 8.1 | APK → A80 手表 |
| 消息中间件 | EMQX | systemd → 中继服务器 |

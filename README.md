# 热应激预警系统

## 架构概览

```
手表 (A80 Android) ──MQTT(1883)──▶ EMQX 中继 (39.105.86.77)
                                      │
                      WebSocket(8083)  │  HTTP API
                                      ▼
                              PC 大屏 (React)
```

## 目录结构

```
热应激预警系统/
├── docs/                          # 文档
│   ├── 需求文档_20260611.docx
│   ├── 用户需求260615（理解版）.pdf
│   └── 界面设计.pptx
├── frontend/                      # PC 端大屏 (React + Vite)
│   ├── src/
│   │   ├── components/
│   │   │   ├── TopStatusBar.tsx   # 顶部状态栏
│   │   │   ├── MapView.tsx        # 高德地图 + 标记
│   │   │   ├── RiskPieChart.tsx   # 风险饼图
│   │   │   ├── AlertSidebar.tsx   # 右侧预警历史
│   │   │   ├── AlertPopup.tsx     # 预警弹窗
│   │   │   └── OfficerDetail.tsx  # 二级详情弹窗
│   │   ├── services/
│   │   │   └── mqtt.ts           # MQTT WebSocket 服务
│   │   ├── store/
│   │   │   └── index.tsx         # 全局状态 (Context + Reducer)
│   │   ├── types/
│   │   │   └── index.ts          # TypeScript 类型
│   │   ├── App.tsx               # 主布局
│   │   └── main.tsx
│   └── package.json
├── A80安卓系统二次开发智能手表产品介绍.pdf
└── 聚伟AQ7和A80安卓系统开发说明.pdf
```

## 技术栈

| 层 | 技术 |
|----|------|
| 框架 | React 19 + TypeScript |
| 构建 | Vite 7 (Rolldown) |
| UI | Ant Design 5 |
| 地图 | 高德地图 JS API v2 |
| 图表 | ECharts 5 |
| 通信 | MQTT.js → EMQX WebSocket |

## 中继服务器

```
IP:   39.105.86.77 (阿里云 ECS)
OS:   Ubuntu 22.04
MQTT: EMQX (Docker)
  - 1883: MQTT (手表原生)
  - 8083: MQTT over WebSocket (前端)
  - 18083: Dashboard
```

## MQTT 主题约定

| 主题 | 方向 | 说明 |
|------|------|------|
| `watch/{deviceId}/vital` | 手表→Server | 生理数据上报 |
| `watch/{deviceId}/alert` | Server→PC | 预警触发推送 |
| `watch/{deviceId}/status` | 手表→Server | 设备在线/离线 |

## 开发

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
npm run build   # 输出到 dist/
```

## 部署到手表

### 方法：Platform 签名 + adb push (系统级权限)

A80 使用聚伟提供的 platform.jks 签名，安装到 `/system/priv-app/` 获得系统级权限。

```bash
# 1. 构建 APK
cd watch-app
./gradlew assembleRelease

# 2. 安装为系统应用
adb root
adb remount
adb push app/build/outputs/apk/release/app-release.apk /system/priv-app/heatstress/heatstress.apk
adb reboot
```

platform.jks 签名后，以下权限**无需用户确认**：
- RECEIVE_BOOT_COMPLETED（开机自启）
- BODY_SENSORS（心率/血氧）
- ACCESS_FINE_LOCATION（GPS）
- FOREGROUND_SERVICE（前台保活）
- SYSTEM_ALERT_WINDOW（覆盖层）

### Keystore 信息

```
文件:   keystore/platform.jks
别名:   android_platform
密码:   android (store + key)
SHA256: 53:04:91:5C:4B:B7:BA:CA:28:77:62:31:99:39:96:FD:...
```

- [x] 高德地图 API Key 已配置
- [ ] 手表端 Android 应用开发 → 手表上构建测试
- [ ] 后端预测模型 + 大模型接口
- [ ] 人员管理页面（项目管理/用户管理）
- [ ] 登录认证
- [ ] Nginx + Cloudflare Tunnel 公网访问

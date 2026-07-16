# React MQTT 大屏

这是直接订阅 EMQX WebSocket 的可选前端，不是当前部署在 `8001/dashboard/` 的
Django 大屏源码。

## 配置

在 `.env.local` 中提供：

```text
VITE_MQTT_BROKER_URL=ws://39.105.86.77:8083/mqtt
VITE_MQTT_USERNAME=
VITE_MQTT_PASSWORD=
VITE_AMAP_KEY=
```

不要把生产凭据和高德 Key 提交到仓库。

## 开发与构建

```bash
npm install
npm run dev
npm run build
```

前端接受可空的 HR、SpO2、血压和 GPS 字段；vital 数据也会刷新在线状态，
90 秒未收到 vital/status 时自动标记离线。设备在线但未佩戴、声明 `no_vitals`，
或没有有效核心温度时会单独显示为“数据不可用”，不会计入正常设备。

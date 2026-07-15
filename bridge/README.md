# HeatStress Bridge — 部署指南

MQTT ↔ HTTP 桥接服务，将 A80 手表的 MQTT 数据流转发到队友 HTTP API。

## 架构

```
A80 ──MQTT──▶ EMQX(1883) ──▶ bridge.py ──HTTP──▶ 队友API(8000)
                  ▲                                  │
                  │                                  │ 预警/alerts
                  │     ◀──── bridge.py ───HTTP──────┘
                  │
             大屏 ◀── WebSocket(8083)
```

## 部署（在 EMQX 服务器上）

```bash
# 1. 上传文件
scp bridge.py requirements.txt heatstress-bridge.service root@39.105.86.77:/opt/heatstress-bridge/

# 2. SSH 到服务器
ssh root@39.105.86.77

# 3. 创建虚拟环境
cd /opt/heatstress-bridge
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 4. 安装并启动 systemd 服务
cp heatstress-bridge.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now heatstress-bridge

# 5. 查看日志
journalctl -u heatstress-bridge -f
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BRIDGE_MQTT_BROKER` | localhost | EMQX 地址 |
| `BRIDGE_MQTT_PORT` | 1883 | MQTT 端口 |
| `BRIDGE_API_BASE` | http://101.201.29.99:8000 | 队友 API 地址 |
| `BRIDGE_LOG_LEVEL` | INFO | 日志级别 |
| `BRIDGE_ALERT_POLL_INTERVAL` | 10 | 拉取预警间隔(秒) |

## 数据流

1. A80 手表发布 `watch/{deviceId}/vital` → MQTT
2. bridge.py 收到消息 → 首次自动注册 → `POST /api/watch/upload/`
3. 队友 API 返回 alert → bridge.py 推回 MQTT `watch/{deviceId}/alert`
4. 大屏订阅 MQTT → 实时展示
5. 后台线程定期拉取未读预警 → 推送 + ack

## 本地测试

```bash
# 从本地连接远程 EMQX 和 API
export BRIDGE_MQTT_BROKER=39.105.86.77
export BRIDGE_API_BASE=http://101.201.29.99:8000
export BRIDGE_LOG_LEVEL=DEBUG
pip install -r requirements.txt
python bridge.py
```

## 模拟测试数据

在另一终端用 mosquitto_pub 模拟手表上报：

```bash
mosquitto_pub -h 39.105.86.77 -p 1883 \
  -t 'watch/A80-TEST01/vital' \
  -m '{"deviceId":"A80-TEST01","heartRate":88,"spo2":96.5,"bloodPressure":"128/82","latitude":30.572,"longitude":104.066,"timestamp":1700000000000}'
```

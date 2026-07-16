# HeatStress MQTT/HTTP Bridge

桥接服务订阅 A80 MQTT 数据，将完整有效的生理帧转发到实际 Django watch API，
并把 API 预警推回手表。

## 线上链路

```text
A80 -> EMQX localhost:1883 -> bridge.py
    -> http://101.201.29.99:8001/api/watch/*
    -> http://101.201.29.99:8001/dashboard/
```

API 基地址是 `8001`，不是旧文档中的 `8000`。

## 行为

- MQTT 回调只解析并放入有界队列，HTTP 请求由工作线程处理。
- 新设备通过 `/api/watch/register/` 幂等注册。
- 只在心率、血氧、收缩压、舒张压和核心温度均有效时调用 `/upload/`。
- 不再用 `75/98/120/80/37.0` 等默认值补齐缺失数据。
- 累计步数按相邻采样计算步频。
- `0/0` 定位、越界值和错误设备时间会被过滤。
- API alert 仅发布一次，成功进入 MQTT 后再 ack。
- 在线心跳会向 `watch/{deviceId}/time` 下发服务器时间，供无独立网络的 A80 校时。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `BRIDGE_MQTT_BROKER` | `localhost` | EMQX 地址 |
| `BRIDGE_MQTT_PORT` | `1883` | MQTT 端口 |
| `BRIDGE_MQTT_USERNAME` | 空 | MQTT 用户名 |
| `BRIDGE_MQTT_PASSWORD` | 空 | MQTT 密码 |
| `BRIDGE_API_BASE` | `http://101.201.29.99:8001` | Django API 基址 |
| `BRIDGE_API_TIMEOUT` | `6` | HTTP 超时秒数 |
| `BRIDGE_API_RETRY` | `1` | HTTP 重试次数 |
| `BRIDGE_WORKER_COUNT` | `4` | HTTP 工作线程数 |
| `BRIDGE_QUEUE_SIZE` | `2000` | MQTT 消息队列上限 |
| `BRIDGE_MQTT_PUBLISH_TIMEOUT` | `6` | QoS 1 预警发布确认超时秒数 |
| `BRIDGE_ALERT_POLL_INTERVAL` | `15` | 预警轮询秒数 |

## 部署

```bash
python3 -m venv /opt/heatstress-bridge/venv
/opt/heatstress-bridge/venv/bin/pip install -r requirements.txt
/opt/heatstress-bridge/venv/bin/python -m py_compile bridge.py

install -m 0644 bridge.py /opt/heatstress-bridge/bridge.py
install -m 0644 heatstress-bridge.service /etc/systemd/system/heatstress-bridge.service
systemctl daemon-reload
systemctl enable --now heatstress-bridge
systemctl status heatstress-bridge
```

更新线上文件前应创建带时间戳的备份，并在重启失败时回滚。

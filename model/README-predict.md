# 模型端口
  
  watch-api 每分钟请求一次
    → 每次携带最近20分钟的20个 heart_rate
    → 卡尔曼处理20个心率
    → 模型1立即推理
    → 返回当前 core_temperature

  经测试服务器上的模型返回核心温度延时在1s以内，远小于手表上传频率

## 新请求格式

  watch-api 请求：

  POST http://20.205.12.160:8001/v1/core-temperature/estimate
  Content-Type: application/json

  {
    "device_id": "WATCH-6B6D32BA",
      "samples": [
        {"heart_rate":82,  "timestamp":"2026-07-17T10:00:00+08:00"},
        {"heart_rate":83,  "timestamp":"2026-07-17T10:01:00+08:00"},
        {"heart_rate":85,  "timestamp":"2026-07-17T10:02:00+08:00"},
        {"heart_rate":84,  "timestamp":"2026-07-17T10:03:00+08:00"},
        {"heart_rate":86,  "timestamp":"2026-07-17T10:04:00+08:00"},
        {"heart_rate":88,  "timestamp":"2026-07-17T10:05:00+08:00"},
        {"heart_rate":90,  "timestamp":"2026-07-17T10:06:00+08:00"},
        {"heart_rate":91,  "timestamp":"2026-07-17T10:07:00+08:00"},
        {"heart_rate":93,  "timestamp":"2026-07-17T10:08:00+08:00"},
        {"heart_rate":92,  "timestamp":"2026-07-17T10:09:00+08:00"},
        {"heart_rate":94,  "timestamp":"2026-07-17T10:10:00+08:00"},
        {"heart_rate":95,  "timestamp":"2026-07-17T10:11:00+08:00"},
        {"heart_rate":96,  "timestamp":"2026-07-17T10:12:00+08:00"},
        {"heart_rate":98,  "timestamp":"2026-07-17T10:13:00+08:00"},
        {"heart_rate":97,  "timestamp":"2026-07-17T10:14:00+08:00"},
        {"heart_rate":99,  "timestamp":"2026-07-17T10:15:00+08:00"},
        {"heart_rate":101, "timestamp":"2026-07-17T10:16:00+08:00"},
        {"heart_rate":100, "timestamp":"2026-07-17T10:17:00+08:00"},
        {"heart_rate":102, "timestamp":"2026-07-17T10:18:00+08:00"},
        {"heart_rate":103, "timestamp":"2026-07-17T10:19:00+08:00"}
      ]
  }

  约定：

- heart_rates 必须正好20个。
- 顺序必须是最旧到最新。
- 每个值必须在 30～250 bpm。
- timestamp 是最后一个心率对应的时间。
- 服务端按一分钟间隔生成前19个时间点。

## 成功响应

  {
    "ok": true,
    "device_id": "WATCH-6B6D32BA",
    "core_temperature": 37.456,
    "source": "informer_model_1",
    "model_version": "core-estimator-kalman-hr-only-1.0.0",
    "window_size": 20,
    "timestamp": "2026-07-17T02:19:00Z"
  }

  watch-api 直接读取：

  core_temperature = response.json()["core_temperature"]

## 错误响应

  心率数量不是20个：

  HTTP/1.1 422 Unprocessable Entity

  心率超出范围：

  HTTP/1.1 422 Unprocessable Entity

  模型权重未成功加载：

  HTTP/1.1 503 Service Unavailable

  因此 watch-api 只能在HTTP 200且 ok=true 时保存核心温度。

## 在服务器更新 Docker

  将更新后的项目同步到 20.205.12.160，然后执行：

  cd '热应激项目'

  docker compose -f deploy/docker-compose.yml up -d \
    --build --force-recreate model-gateway

  必须带 --build，否则 Docker 可能继续使用旧镜像。

  查看构建及启动日志：

  docker compose -f deploy/docker-compose.yml logs \
    -f --tail=200 model-gateway

  确认模型状态：

  curl -s http://127.0.0.1:8001/readyz

  应包含：

  {
    "estimator": {
      "enabled": true,
      "ready": true,
      "version": "core-estimator-kalman-hr-only-1.0.0",
      "error": null
    },
    "forecaster": {
      "enabled": false,
      "ready": false
    }
  }


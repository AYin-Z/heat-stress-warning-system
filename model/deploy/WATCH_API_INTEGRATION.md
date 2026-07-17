# Watch API → 模型1：20分钟心率窗口接口

Docker构建、凭据修复和运行排障参见 [`DOCKER_BUILD_AND_DEBUG.md`](./DOCKER_BUILD_AND_DEBUG.md)。

watch-api 每分钟调用一次模型服务。每次都传入该设备最近20分钟的完整心率窗口，顺序必须为最旧到最新。服务不再等待Redis累计窗口，而是立即完成卡尔曼预处理和模型1推理。

## 请求

```http
POST /v1/core-temperature/estimate
Content-Type: application/json
```

```json
{
  "device_id": "WATCH-6B6D32BA",
  "heart_rates": [82, 83, 85, 84, 86, 88, 90, 91, 93, 92, 94, 95, 96, 98, 97, 99, 101, 100, 102, 103],
  "timestamp": "2026-07-17T10:19:00+08:00"
}
```

`timestamp` 是数组最后一个心率的采集时间。服务按一分钟间隔向前生成其余19个时间点。`heart_rates` 必须恰好20个，每个值必须在30至250 bpm之间。

## 成功响应

```json
{
  "ok": true,
  "device_id": "WATCH-6B6D32BA",
  "core_temperature": 37.456,
  "source": "informer_model_1",
  "model_version": "core-estimator-kalman-hr-only-1.0.0",
  "window_size": 20,
  "timestamp": "2026-07-17T02:19:00Z"
}
```

- `200`：推理成功；
- `422`：数组不是20个、心率越界或请求格式错误；
- `503`：模型1未启用、权重加载失败或推理结果无效。

旧的逐样本接口保留在 `/v1/core-temperature/estimate-samples`，仅用于兼容，不建议新系统使用。

## curl

```bash
curl -i --max-time 20 \
  -X POST http://20.205.12.160:8001/v1/core-temperature/estimate \
  -H 'Content-Type: application/json' \
  -d '{
    "device_id":"WATCH-6B6D32BA",
    "heart_rates":[82,83,85,84,86,88,90,91,93,92,94,95,96,98,97,99,101,100,102,103],
    "timestamp":"2026-07-17T10:19:00+08:00"
  }'
```

本架构是 watch-api 主动调用模型，因此 `deploy/.env` 应保持 `FORWARD_UPLOAD=false`，避免模型服务再次转发回watch-api形成环路。

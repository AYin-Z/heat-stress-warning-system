# 热应激核心温度预测服务

本项目通过手表上传的心率估算当前核心温度。当前生产链路为：

```text
20 个每分钟心率
  → 卡尔曼滤波生成 Kalman_Result
  → Informer 模型1推理
  → 返回当前 core_temperature
```

模型网关使用 FastAPI，Redis 保存每台设备的滑动窗口状态。当前模型1已启用，模型2和 TDgpt 默认关闭。

## 目录结构

```text
.
├── README.md                    # 项目简要使用说明
├── DEPLOYMENT.md                # Docker 部署、接入模式与运维说明
├── 项目详细使用与文件说明.md   # 完整文件盘点与清理建议
├── artifacts/                   # 可部署的模型配置和 Scaler
│   ├── core-estimator/          # 模型1配置及归一化参数
│   └── core-forecaster/         # 模型2预留配置，当前未启用
├── deploy/                      # 当前生产部署工程
│   ├── .env                     # 当前运行参数
│   ├── .env.example             # 环境变量模板
│   ├── docker-compose.yml        # 网关、Redis 和可选 TDgpt 编排
│   ├── model-service/            # FastAPI 接口与模型推理代码
│   ├── tests/                    # 单元测试和冒烟测试
│   ├── tools/                    # Scaler 导出工具
│   └── tdgpt/                    # 可选 TDgpt 算法适配
├── pret/                        # 旧的独立推理与手表模拟原型
└── 模型1/                       # Informer 研究代码、权重和实验结果
    ├── checkpoint/               # 模型权重
    ├── models/                   # Informer 网络结构
    ├── utils/                    # 时间特征、mask、Scaler 等工具
    ├── data/                     # 训练数据加载逻辑
    ├── exp/                      # 训练和评估流程
    ├── estimate/                 # 研究评估表格与图片
```

## 快速启动

环境需求：Docker 和 Docker Compose。

```bash
docker compose -f deploy/docker-compose.yml up -d --build model-gateway redis
docker compose -f deploy/docker-compose.yml ps
```

检查服务：

```bash
curl http://127.0.0.1:8001/healthz
curl http://127.0.0.1:8001/readyz
```

- `/healthz` 返回成功：Web 进程存活。
- `/readyz` 中 `models.estimator.ready=true`：权重、配置和 Scaler 均已加载。

## 调用模型

### 一次提交 20 分钟心率

```bash
curl -X POST http://127.0.0.1:8001/v1/core-temperature/estimate \
  -H 'Content-Type: application/json' \
  -d '{
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
    }'
```

约束：

- `heart_rates` 必须恰好包含 20 个整数；
- 心率必须按从旧到新排列，范围为 30–250 bpm；
- `timestamp` 是最后一个心率对应的时间；
- 请求参数错误返回 HTTP 422，模型未就绪返回 HTTP 503。

成功响应示例：

```json
{
  "ok": true,
  "device_id": "WATCH-TEST-001",
  "core_temperature": 37.456,
  "source": "informer_model_1",
  "model_version": "core-estimator-kalman-hr-only-1.0.0",
  "window_size": 20,
  "timestamp": "2026-07-17T02:19:00Z"
}
```

### 手表每分钟上传

```bash
curl -X POST http://127.0.0.1:8001/api/watch/upload/ \
  -H 'Content-Type: application/json' \
  -H 'X-Device-ID: WATCH-TEST-001' \
  -d '{"heart_rate":88,"timestamp":"2026-07-17T10:00:00+08:00"}'
```

网关会按设备累积分钟数据。累积不足 20 个有效分钟点时使用卡尔曼结果；满 20 个点后使用 Informer 模型1。缺少 `X-Device-ID` 会返回 HTTP 401。

## 当前使用的模型文件

生产必需：

- `模型1/checkpoint/informer_checkpoints_Core/model_Kalman/.../checkpoint.pth`；
- `artifacts/core-estimator/model_config.json`；
- `artifacts/core-estimator/scaler_x.json`；
- `artifacts/core-estimator/scaler_y.json`；
- `模型1/models/` 和 `模型1/utils/`。

`model_Kalman_fold1` 至 `model_Kalman_fold5` 是交叉验证权重，当前服务不会加载它们。

## 测试

```bash
PYTHONPATH=deploy/model-service \
  python3 -m unittest discover -s deploy/tests -p 'test_*.py'
```

## 运维命令

```bash
# 查看日志
docker compose -f deploy/docker-compose.yml logs -f --tail=200 model-gateway

# 重启网关
docker compose -f deploy/docker-compose.yml restart model-gateway

# 停止服务
docker compose -f deploy/docker-compose.yml down
```

生产环境不要随意使用 `docker compose down -v`，该命令会同时删除 Redis 数据卷。

更详细的逐文件说明见 [项目详细使用与文件说明.md](项目详细使用与文件说明.md)。

## API（已上线）

```
POST http://20.205.12.160:8001/v1/core-temperature/estimate
```

详见 [`watch-api.md`](watch-api.md) 或 [Bridge API 文档](../docs/api/bridge-http-api.md#6-核心温度推算独立模型服务)。

## 更新部署

```bash
cd model
docker compose -f deploy/docker-compose.yml up -d --build --force-recreate model-gateway
```

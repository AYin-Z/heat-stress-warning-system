# 模型端 — 核心温度推算与预测

## 目录结构

```
model/
├── pret/                  ← 预训练代码（Kalman + Informer 训练管线）
│   ├── kalman.py          卡尔曼滤波器实现
│   ├── informer_runtime.py Informer 推理引擎
│   ├── pipeline.py         训练/评估管线
│   ├── simulate_watch.py   模拟手表数据生成
│   └── test_pipeline.py    管线测试
│
├── artifacts/             ← 模型权重与配置
│   ├── core-estimator/    核心温度估计器（Kalman + Informer）
│   └── core-forecaster/   核心温度预测器（未来趋势）
│
├── deploy/                ← 部署配置
│   ├── docker-compose.yml 容器编排
│   ├── model-service/     API 服务（FastAPI）
│   ├── tdgpt/             时序预测模块
│   └── tests/             冒烟测试
│
├── watch-api.md           ← 提供给 Bridge 的 API 规格
├── DEPLOYMENT.md          部署指南
├── 使用说明.docx          使用文档
└── README-predict.md      原始 README
```

## API（已上线）

```
POST http://20.205.12.160:8001/v1/core-temperature/estimate
```

详见 [`watch-api.md`](watch-api.md) 或 [Bridge API 文档](../docs/api/bridge-http-api.md#6-核心温度推算独立模型服务)。

## 健康检查

```bash
curl http://20.205.12.160:8001/readyz
```

## 更新部署

```bash
cd model
docker compose -f deploy/docker-compose.yml up -d --build --force-recreate model-gateway
```

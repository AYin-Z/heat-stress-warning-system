# 模型制品目录

Docker 服务只读挂载本目录。当前模型1已切换为只需要心率的 `model_Kalman` checkpoint，并已从训练参考集重建 Scaler；`deploy/.env` 默认启用模型1、关闭不再适用的模型2。

## 模型1

模型1配置和Scaler位于 `core-estimator/`，checkpoint由 Compose 从原研究目录只读挂载到 `/checkpoints/core-estimator/checkpoint.pth`：

```text
core-estimator/
├── model_config.json
├── scaler_x.json
└── scaler_y.json
```

`scaler_x.json`、`scaler_y.json` 格式：

```json
{"mean": [0.0], "std": [1.0]}
```

数组顺序必须与 `model_config.json.features` 完全一致。禁止使用线上数据重新拟合。

## 模型2

将制品放到 `core-forecaster/`：

```text
core-forecaster/
├── checkpoint.pth
├── model_config.json
├── scaler_x.json
└── scaler_y.json
```

模型2依赖核心温度历史，可在未来确实需要预测功能并完成独立验收后再启用；本次“HR → 当前核心温度”部署保持关闭。

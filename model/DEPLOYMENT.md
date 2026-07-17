# 热应激模型 Docker 部署

这套部署在不修改对方 watch-api 源码的前提下，提供一个协议兼容的模型网关：

- `POST /api/watch/upload/`：先按设备聚合数据并计算核心温度，再可选转发给对方接口；
- `/api/watch/*` 其他路由：透明转发给对方服务；
- `POST /v1/core-temperature/estimate`：供后端直接调用的内部接口；
- `GET /healthz`：进程健康检查；
- `GET /readyz`：Redis、模型1和模型2的真实就绪状态。

## 1. 部署模式

### 模式A：模型网关和对方服务不在同一台机器

网关监听本机 `8001`，上游为文档提供的地址：

```env
PUBLIC_PORT=8001
UPSTREAM_WATCH_API=http://101.201.29.99:8001
FORWARD_UPLOAD=true
```

手表请求地址改成模型网关地址。网关完成推理后再把原始上传转发给对方服务器。

### 模式B：部署在对方服务器上

不能让网关和原服务同时占用 `8001`。推荐把原服务改为仅本机监听 `8000`：

```env
PUBLIC_PORT=8001
UPSTREAM_WATCH_API=http://host.docker.internal:8000
FORWARD_UPLOAD=true
```

Linux 下若使用 `host.docker.internal`，给 `model-gateway` 增加：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

严禁将 `UPSTREAM_WATCH_API` 指向网关自身，否则形成无限转发。

### 模式C：由对方后端直接调用模型

保持 `FORWARD_UPLOAD=false`，对方服务调用：

```text
POST http://model-gateway:8001/v1/core-temperature/estimate
```

这是长期最推荐的方式，但需要对方修改后端源码。

## 2. 首次启动

```bash
cd deploy
cp .env.example .env
```

首次联调先设置：

```env
FORWARD_UPLOAD=false
MODEL1_ENABLED=false
MODEL2_ENABLED=false
```

启动基础服务：

```bash
docker compose build model-gateway
docker compose up -d model-gateway redis
docker compose ps
```

`model-gateway` 明确安装 PyTorch CPU wheel，不会下载 CUDA 运行库；生产服务器无需 GPU。

若只联调接口和卡尔曼降级，可临时设置 `INSTALL_TORCH=false` 加速构建；启用任一 Informer 前必须恢复为 `true` 并重新构建。

查看状态：

```bash
curl http://127.0.0.1:8001/healthz
curl http://127.0.0.1:8001/readyz
```

测试上传：

```bash
curl -X POST http://127.0.0.1:8001/api/watch/upload/ \
  -H 'Content-Type: application/json' \
  -H 'X-Device-ID: WATCH-TEST-001' \
  -d '{
    "heart_rate": 88,
    "skin_temperature": 35.2,
    "timestamp": "2026-07-15T10:30:00+08:00"
  }'
```

Scaler 未配置时响应会明确显示：

```json
{
  "thermal": {
    "status": "warming_up",
    "current_source": "kalman_fallback",
    "forecast": null
  }
}
```

## 3. 启用 Informer

研究工程的 checkpoint 没有保存 Scaler，因此不能仅复制 `checkpoint.pth` 就启用模型。按照 [artifacts/README.md](artifacts/README.md) 准备完整模型制品。

模型1建议先确认 `model_7` 的特征合同，再复制权重：

```bash
cp 模型1/checkpoint/informer_checkpoints_Core/model_7/informer_multiple_ftMNS_sl20_ll0_pl2_tgCore_dm512_nh8_el2_dl1_df2048_atprob_fc5_ebtimeF_dtTrue_mxTrue_exp/checkpoint.pth \
  artifacts/core-estimator/checkpoint.pth
cp artifacts/core-estimator/model_config.example.json artifacts/core-estimator/model_config.json
```

模型2群体预训练权重：

```bash
cp 模型2/checkpoint/informer_checkpoints_field/General/pre_train_model/informer_multiple_ftS_sl15_ll5_pl10_tgTcrChest_dm512_nh8_el2_dl1_df2048_atprob_fc5_ebtimeF_dtTrue_mxTrue_exp/checkpoint.pth \
  artifacts/core-forecaster/checkpoint.pth
cp artifacts/core-forecaster/model_config.example.json artifacts/core-forecaster/model_config.json
```

补齐对应 Scaler 后修改：

```env
MODEL1_ENABLED=true
MODEL2_ENABLED=true
```

如果取得了原始训练目录，可按训练时的精确列顺序导出 Scaler。例如：

```bash
python3 deploy/tools/export_scalers.py \
  --train-dir /path/to/original/train_7 \
  --features Head,Chest,Forearm,Hand,Thigh,Calf,Foot,HR \
  --target Core \
  --output-dir artifacts/core-estimator
```

这个工具采用与项目 `StandardScaler` 相同的总体标准差（`ddof=0`）。必须使用训练时原目录，不能用测试集或线上数据替代。

然后重启并检查 `/readyz`：

```bash
docker compose up -d --build model-gateway
curl http://127.0.0.1:8001/readyz
```

只有 `ready: true` 才表示 checkpoint、结构和 Scaler 均成功加载。

## 4. TDgpt 二开部署

TDgpt 固定使用 `tdengine/tdgpt:3.4.1.9`，避免 `latest` 升级改变插件接口。自定义算法名为 `coretemp`，适配代码位于 `deploy/tdgpt/core_temperature_forecast.py`。

启动可选 profile：

```bash
docker compose --profile tdgpt build tdgpt
docker compose --profile tdgpt up -d tdgpt
docker compose logs -f tdgpt
```

TDgpt 容器内部使用 `6035`；Compose 没有映射到宿主机公网。需要调试时可临时增加：

```yaml
ports:
  - "127.0.0.1:6035:6035"
```

TDgpt 的 SQL 调用还要求把 anode 注册到 TDengine TSDB。注册完成后使用类似：

```sql
SELECT FORECAST(core_temperature, 'algo=coretemp,rows=10')
FROM heatstress.device_minute
WHERE device_id = 'WATCH-TEST-001';
```

实际 SQL 参数以所部署 TDengine 3.4.1.9 的 `FORECAST` 语法为准。模型网关本身不依赖 TDgpt profile，TDgpt 故障不会中断手表上传。

## 5. 接口兼容行为

- 缺少 `X-Device-ID`：返回文档规定的 `401/MISSING_DEVICE_ID`；
- 上游返回设备未激活、禁用等错误：保持其 HTTP 状态和 JSON 不变；
- 上游成功：在原响应上增加 `thermal`；
- 上游不可达：返回 `502`，不会假装数据已保存；
- `core_temperature` 有真实值时优先使用真实值；
- 没有真实值时使用 Informer 模型1，模型未就绪则使用卡尔曼降级；
- 满足15个一分钟核心温度点且模型2就绪后，返回未来10分钟预测。

## 6. 运维

```bash
docker compose logs -f model-gateway
docker compose restart model-gateway
docker compose down
docker compose down -v  # 会删除Redis状态，生产环境慎用
```

升级模型时使用新版本目录并保留旧制品，先通过 `/readyz` 和影子流量验证，再切换挂载。所有预警记录应保存模型版本及数据来源。

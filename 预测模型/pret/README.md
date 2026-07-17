# Watch心率 → Kalman → 模型1 核心温度测试

当前实际硬件模式只上传 `heart_rate`。部署使用模型1已有的 `model_Kalman` 单变量 checkpoint：先从心率生成 `Kalman_Result`，累计20个分钟样本后由 Informer 输出当前核心温度。API 返回字段为 `core_temperature`。

本目录只读取现有 checkpoint，不会修改、覆盖或重新训练模型。

## 已确认的真实链路

```text
watch-api分钟数据
  ├─ HR ──> Kalman_Result
  ├─ 7个皮温点 ─────────────┐
  └─ HR + Kalman_Result ────┤
                            ↓
                  模型1（9变量→Core）
                            ↓
               Core历史 + 原始皮温历史
                            ↓
             模型2的4个单变量Informer
       ├─ TcrChest：模型1生成的Core
       ├─ TskLArm：Forearm
       ├─ TskLThigh：Thigh
       └─ TskMean：加权平均皮温
```

模型1的指定实地权重编码器输入维度为9。模型2的每个 checkpoint 编码器输入维度为1，所以模型2是4次独立推理，不是把 Core 和皮温拼成一个多变量张量。

原始数据加载器使用 `r_begin = s_end - label_len - 1`，因此模型2的10个输出对齐为当前时刻至未来9分钟，即 `horizon_minutes=0..9`。

## 文件

- `simulate_watch.py`：把实验CSV转换成 watch-api JSONL，或逐条POST到已部署网关；
- `pipeline.py`：直接加载现有权重执行完整两级模型；
- `kalman.py`：严格复刻 `卡尔曼数据处理.ipynb`；
- `informer_runtime.py`：与原Notebook一致的Informer推理封装；
- `config.json`：只读checkpoint路径、目标映射和参考数据配置；
- `test_pipeline.py`：不依赖checkpoint的基础逻辑测试。

## 1. 模拟 watch-api 输入

生成JSONL，不发网络请求：

```bash
python3 pret/simulate_watch.py \
  --csv '数据/环境舱-黄/高温实验_test/test/9_34重度警服12-13_3.csv' \
  --output /tmp/watch-input.jsonl
```

默认每条记录严格只包含实际硬件可用的心率和时间：

```json
{"heart_rate": 98, "timestamp": "2026-07-15T10:00:00+08:00"}
```

旧的7点皮温实验模拟仍可通过 `--include-skin` 显式启用：

```json
{
  "heart_rate": 98,
  "skin_temperature": 35.1,
  "skin_temperatures": {
    "head": 35.5,
    "chest": 35.0,
    "forearm": 35.2,
    "hand": 35.1,
    "thigh": 34.8,
    "calf": 34.9,
    "foot": 35.0
  },
  "timestamp": "2026-07-15T10:00:00+08:00"
}
```

发送时设备号严格放在 `X-Device-ID` 请求头，不放在JSON正文。

发送到已经部署的模型网关：

```bash
python3 pret/simulate_watch.py \
  --csv '数据/环境舱-黄/高温实验_test/test/9_34重度警服12-13_3.csv' \
  --url http://127.0.0.1:8001/api/watch/upload/ \
  --device-id WATCH-PRET-001 \
  --interval 0.1
```

## 2. 直接联合测试已有模型

需要已安装CPU版PyTorch：

```bash
python3 pret/pipeline.py \
  --input '数据/环境舱-黄/高温实验_test/test/9_34重度警服12-13_3.csv' \
  --output pret/output/predictions.csv
```

为了复现 Notebook 中使用真实首个Core初始化卡尔曼的测试方式：

```bash
python3 pret/pipeline.py \
  --input '数据/环境舱-黄/高温实验_test/test/9_34重度警服12-13_3.csv' \
  --output pret/output/predictions.csv \
  --use-ground-truth-initial-core
```

生产模拟默认使用 `37.0℃` 初始化，因为真实设备接口并不提供首个食管/胸部核心温度。

## Scaler说明

- 模型1：从 `config.json.model1.scaler_reference_dir` 指定的训练CSV重建，特征顺序固定为9维；
- 模型2：当前交付中缺少Notebook引用的 `JOS-3/FFT` 原训练目录，所以默认使用当前输入窗口标准化，并在结果中标记 `model2_scaler=window`；
- 获得模型2原训练目录后，把各目标的 `scaler_reference_dir` 配入 `config.json`，即可严格复现训练Scaler。

`informer_checkpoints_test` 当前没有 checkpoint 文件，因此测试默认只读使用 `informer_checkpoints_field`。代码不会写入该目录。

## Docker联合测试

构建并运行（checkpoint和数据均以只读卷挂载）：

```bash
docker compose -f pret/docker-compose.yml build
docker compose -f pret/docker-compose.yml run --rm pret-test
```

结果写入 `pret/output/predictions.csv`。首次构建需要下载CPU版PyTorch，镜像不包含也不复制现有checkpoint。

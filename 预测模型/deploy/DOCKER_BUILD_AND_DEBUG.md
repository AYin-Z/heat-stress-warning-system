# 模型1 Docker 构建、部署与联调手册

本文适用于部署服务器 `20.205.12.160`。当前接口约定是 watch-api 每分钟发送一次请求，每次携带最近20分钟的心率，模型立即返回当前核心温度。

## 1. 当前报错：Docker凭据助手失败

报错：

```text
failed to solve: error getting credentials - err: exit status 1
```

这发生在拉取 `python:3.10-slim-bookworm` 元数据时，尚未执行模型项目的构建步骤。通常是远程Linux服务器的 `~/.docker/config.json` 引用了只存在于Docker Desktop中的凭据助手。

先检查：

```bash
cat ~/.docker/config.json 2>/dev/null || true
```

如果看到以下任一配置，即与问题吻合：

```json
{"credsStore":"desktop"}
```

```json
{"credsStore":"desktop.exe"}
```

```json
{"credHelpers":{"docker.io":"desktop"}}
```

### 推荐修复：为服务器创建独立Docker配置

此方法不删除原配置：

```bash
mkdir -p "$HOME/.docker-server"
chmod 700 "$HOME/.docker-server"
printf '%s\n' '{"auths":{}}' > "$HOME/.docker-server/config.json"
chmod 600 "$HOME/.docker-server/config.json"
```

验证匿名拉取：

```bash
DOCKER_CONFIG="$HOME/.docker-server" \
docker pull python:3.10-slim-bookworm
```

如果Docker Hub提示限流，再使用服务器专用配置登录：

```bash
DOCKER_CONFIG="$HOME/.docker-server" docker login docker.io
```

不要把密码直接写进命令或项目文件。

## 2. 构建模型镜像

进入项目根目录，即能看到 `deploy/`、`模型1/` 和 `artifacts/` 的目录：

```bash
cd '/实际路径/热应激项目'
```

检查关键文件：

```bash
test -f deploy/docker-compose.yml
test -f deploy/model-service.Dockerfile
test -f artifacts/core-estimator/model_config.json
test -f artifacts/core-estimator/scaler_x.json
test -f artifacts/core-estimator/scaler_y.json
test -f '模型1/checkpoint/informer_checkpoints_Core/model_Kalman/informer_multiple_ftMNS_sl20_ll0_pl2_tgCore_dm512_nh8_el2_dl1_df2048_atprob_fc5_ebtimeF_dtTrue_mxTrue_exp/checkpoint.pth'
```

解析Compose配置：

```bash
DOCKER_CONFIG="$HOME/.docker-server" \
docker compose -f deploy/docker-compose.yml config --quiet
```

使用详细输出构建：

```bash
DOCKER_CONFIG="$HOME/.docker-server" \
BUILDKIT_PROGRESS=plain \
docker compose -f deploy/docker-compose.yml build model-gateway
```

首次构建会下载约179MB的CPU版PyTorch，网络较慢时需要数分钟。不要在下载期间反复重新执行构建。

构建成功后检查镜像：

```bash
docker image inspect heatstress/model-gateway:1.0.0 \
  --format '{{.Id}} {{.Created}} {{.Size}}'
```

## 3. 启动服务

```bash
DOCKER_CONFIG="$HOME/.docker-server" \
docker compose -f deploy/docker-compose.yml up -d --force-recreate
```

查看状态：

```bash
docker compose -f deploy/docker-compose.yml ps
```

预期：

```text
model-gateway  Up ... (healthy)  0.0.0.0:8001->8001/tcp
redis          Up ... (healthy)
```

构建失败不会自动更新现有容器。应通过以下命令确认当前运行镜像的创建时间：

```bash
docker inspect heatstress-model-gateway-1 \
  --format 'image={{.Image}} started={{.State.StartedAt}} status={{.State.Status}}'
docker image inspect heatstress/model-gateway:1.0.0 \
  --format 'created={{.Created}} id={{.Id}}'
```

## 4. 健康与模型检查

```bash
curl -fsS http://127.0.0.1:8001/healthz
curl -fsS http://127.0.0.1:8001/readyz
```

`readyz`必须包含：

```json
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
```

若模型 `ready=false`：

```bash
docker compose -f deploy/docker-compose.yml logs --no-color --tail=200 model-gateway
docker compose -f deploy/docker-compose.yml exec model-gateway \
  sh -c 'ls -lh /checkpoints/core-estimator/checkpoint.pth /models/core-estimator/*.json'
```

## 5. 验证20心率窗口接口

```bash
curl -i --max-time 30 \
  -X POST http://127.0.0.1:8001/v1/core-temperature/estimate \
  -H 'Content-Type: application/json' \
  -d '{
    "device_id":"WATCH-6B6D32BA",
    "heart_rates":[82,83,85,84,86,88,90,91,93,92,94,95,96,98,97,99,101,100,102,103],
    "timestamp":"2026-07-17T10:19:00+08:00"
  }'
```

成功响应必须为HTTP 200，并直接包含：

```json
{
  "ok": true,
  "device_id": "WATCH-6B6D32BA",
  "core_temperature": 37.456,
  "source": "informer_model_1",
  "model_version": "core-estimator-kalman-hr-only-1.0.0",
  "window_size": 20
}
```

如果响应仍包含 `warming_up` 或 `thermal`，说明运行的仍是旧镜像，需要重新构建并创建容器。

## 6. Watch API远程调用

watch-api服务器调用：

```text
POST http://20.205.12.160:8001/v1/core-temperature/estimate
```

先从watch-api服务器检查网络：

```bash
curl -i --connect-timeout 5 --max-time 15 \
  http://20.205.12.160:8001/readyz
```

只应在云安全组和服务器防火墙中允许watch-api服务器IP访问TCP 8001，不应向整个互联网开放。

## 7. 日志调试

持续查看模型网关：

```bash
docker compose -f deploy/docker-compose.yml logs -f --tail=200 model-gateway
```

查看全部服务：

```bash
docker compose -f deploy/docker-compose.yml logs --no-color --tail=300
```

查看最近退出原因：

```bash
docker inspect heatstress-model-gateway-1 \
  --format 'status={{.State.Status}} exit={{.State.ExitCode}} error={{.State.Error}}'
```

进入容器：

```bash
docker compose -f deploy/docker-compose.yml exec model-gateway sh
```

## 8. 常见构建问题

### Docker守护进程权限不足

```text
permission denied while trying to connect to the Docker daemon
```

检查：

```bash
id
ls -l /var/run/docker.sock
```

由管理员把部署用户加入docker组，然后重新登录：

```bash
sudo usermod -aG docker "$USER"
```

不要混用普通用户和 `sudo docker`，否则Docker配置会分别落在用户目录和 `/root`。

### Docker Hub DNS或网络失败

```bash
curl -I --max-time 15 https://registry-1.docker.io/v2/
getent hosts registry-1.docker.io
docker info
```

Registry返回HTTP 401是正常现象，表示网络已连通但匿名请求需要认证流程。

### 磁盘不足

```bash
df -h
docker system df
```

不要在未确认用途的生产服务器上直接执行 `docker system prune -a`。

### 端口被占用

```bash
sudo ss -lntp | grep ':8001'
```

如需更换公网端口，修改 `deploy/.env`：

```dotenv
PUBLIC_PORT=8002
```

容器内部仍使用8001。

## 9. 更新与回滚

更新代码后：

```bash
DOCKER_CONFIG="$HOME/.docker-server" \
BUILDKIT_PROGRESS=plain \
docker compose -f deploy/docker-compose.yml build model-gateway

docker compose -f deploy/docker-compose.yml up -d \
  --force-recreate model-gateway
```

更新后必须重新执行 `readyz` 和20心率窗口请求。生产环境建议为每次镜像使用唯一版本标签，不要长期只使用 `1.0.0`。


# 热应激预警系统 — 部署指南

> 从零开始在任意 Linux 服务器上部署，无需修改代码。

## 环境要求

| 项目 | 最低版本 |
|------|---------|
| 操作系统 | Ubuntu 20.04+ / Debian 11+ |
| Python | 3.10+ |
| 内存 | 512MB+ |
| 磁盘 | 500MB+ |
| 网络 | 可访问 EMQX 中继服务器 |

---

## 一、上传项目

```bash
# 打包本地上传
tar -czf hot_project.tar.gz --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='data_cache' .
scp hot_project.tar.gz root@<服务器IP>:/var/www/
ssh root@<服务器IP>
cd /var/www && tar -xzf hot_project.tar.gz -C hot_project
```

---

## 二、配置环境变量

所有可配置项通过环境变量覆盖，无需改代码：

```bash
# MQTT 连接（必须配置）
export MQTT_BROKER=39.105.86.77    # EMQX 地址
export MQTT_PORT=1883               # MQTT TCP 端口
export MQTT_USERNAME=''             # MQTT 用户名（可选）
export MQTT_PASSWORD=''             # MQTT 密码（可选）

# MQTT 客户端
export MQTT_WORKER_COUNT=2          # Worker 线程数
export MQTT_QUEUE_SIZE=2000         # 消息队列大小
```

变量可写入 `/etc/environment` 或 systemd service 的 `Environment=` 中。

---

## 三、安装依赖

```bash
cd /var/www/hot_project

python3 -m venv venv
source venv/bin/activate

pip install django==5.2 gunicorn paho-mqtt shapely requests
```

---

## 四、初始化

```bash
# 数据库迁移
python manage.py migrate --noinput

# 创建管理员
python manage.py createsuperuser

# 导入行政区划数据（约3000条记录，需要几秒）
python manage.py import_regions --clear

# 收集静态文件
python manage.py collectstatic --noinput
```

---

## 五、创建 Systemd 服务

### 5.1 Django Web 服务

```bash
cat > /etc/systemd/system/hotproject.service << 'EOF'
[Unit]
Description=热应激预警系统
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/hot_project
ExecStart=/var/www/hot_project/venv/bin/gunicorn heatstress.wsgi:application -b 0.0.0.0:8001
Restart=always
RestartSec=3
Environment=MQTT_BROKER=39.105.86.77
Environment=MQTT_PORT=1883

[Install]
WantedBy=multi-user.target
EOF
```

### 5.2 MQTT 客户端服务

```bash
cat > /etc/systemd/system/hotproject-mqtt.service << 'EOF'
[Unit]
Description=热应激预警系统 MQTT 客户端
After=network.target hotproject.service
Wants=network.target

[Service]
User=root
WorkingDirectory=/var/www/hot_project
ExecStart=/var/www/hot_project/venv/bin/python /var/www/hot_project/manage.py run_mqtt
Restart=always
RestartSec=10
Environment=MQTT_BROKER=39.105.86.77
Environment=MQTT_PORT=1883

[Install]
WantedBy=multi-user.target
EOF
```

### 5.3 启动

```bash
systemctl daemon-reload
systemctl enable hotproject hotproject-mqtt
systemctl start hotproject hotproject-mqtt

# 确认两个服务都 running
systemctl is-active hotproject hotproject-mqtt
```

---

## 六、防火墙

```bash
# 云控制台安全组开放目标端口
# 服务器防火墙
ufw allow 8001/tcp
```

---

## 七、验证

```bash
# 服务状态
systemctl status hotproject hotproject-mqtt

# Django 日志
journalctl -u hotproject -f

# MQTT 日志
journalctl -u hotproject-mqtt -f

# 浏览器访问
# http://<服务器IP>:8001/dashboard/
```

默认账号：**admin** / **admin123**

---

## 八、高德地图配置

在 `heatstress/settings.py` 中配置高德 Key：

```python
AMAP_KEY = '你的高德 Key'
AMAP_SECRET = '你的高德密钥'
```

通过环境变量：

```bash
export AMAP_KEY=xxx
export AMAP_SECRET=xxx
```

---

## 九、日常管理

```bash
# 重启服务
systemctl restart hotproject hotproject-mqtt

# 更新代码后
cd /var/www/hot_project
# 上传新文件覆盖
python manage.py migrate --noinput      # 如有数据库变更
python manage.py collectstatic --noinput
systemctl restart hotproject hotproject-mqtt
```

---

## 十、部署脚本（一键）

项目自带 `deploy.sh`，从源码目录执行：

```bash
bash deploy.sh 8001 <服务器IP>
```

脚本自动完成：虚拟环境 → 依赖 → 迁移 → systemd → 启动。

---

## 十一、多项目/多端口部署

不同项目换端口和 service 名即可：

```bash
# 项目 A: /var/www/hot_project → :8001 → hotproject
# 项目 B: /var/www/hot_project_b → :8002 → hotproject-b
```

---

## 十二、常见问题

### 依赖安装失败
```bash
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip
pip install django==5.2 gunicorn paho-mqtt shapely requests
```

### 端口占用
```bash
fuser -k 8001/tcp
```

### MQTT 连接不上
```bash
# 检查网络可达性
telnet <MQTT_BROKER> 1883

# 查看 MQTT 日志
journalctl -u hotproject-mqtt -n 30
```

### 行政区划数据未导入
```bash
python manage.py import_regions --clear
```

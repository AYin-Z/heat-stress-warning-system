# 热应激预警系统 — 部署指南

> 从零部署到任意 Linux 服务器。高德 Key 已内置，无需额外配置。

## 一键部署

```bash
cd /var/www/hot_project
bash deploy.sh 8001 <MQTT_BROKER_IP>
```

脚本自动完成：虚拟环境 → 依赖 → 迁移 → systemd 双服务 → 启动。

部署后访问 `http://<服务器IP>:8001/dashboard/`，默认账号 **admin / admin123**。

---

## 手动部署（如果一键脚本失败）

### 1. 上传

```bash
tar -czf hot_project.tar.gz --exclude='venv' --exclude='__pycache__' .
scp hot_project.tar.gz root@<IP>:/var/www/
ssh root@<IP>
cd /var/www && tar -xzf hot_project.tar.gz -C hot_project
```

### 2. 环境变量

```bash
export MQTT_BROKER=39.105.86.77    # EMQX 地址，必配
export MQTT_PORT=1883
```

### 3. 安装 + 初始化

```bash
cd /var/www/hot_project
python3 -m venv venv && source venv/bin/activate
pip install django==5.2 gunicorn paho-mqtt shapely requests

python manage.py migrate --noinput
python manage.py createsuperuser
python manage.py import_regions --clear      # 导入行政区划
python manage.py collectstatic --noinput
```

### 4. Systemd 双服务

```bash
# Web 服务
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

# MQTT 服务
cat > /etc/systemd/system/hotproject-mqtt.service << 'EOF'
[Unit]
Description=热应激预警系统 MQTT 客户端
After=network.target hotproject.service
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

systemctl daemon-reload
systemctl enable hotproject hotproject-mqtt
systemctl start hotproject hotproject-mqtt
```

---

## 防火墙

```bash
ufw allow 8001/tcp
```

云控制台安全组同步开放对应端口。

---

## 高德地图

Key 已内置在 `heatstress/settings.py`，无需手动配置。如需更换：

```python
AMAP_KEY = '你的 Key'
AMAP_SECRET = '你的密钥'
```

---

## 日常管理

```bash
systemctl restart hotproject hotproject-mqtt    # 重启
journalctl -u hotproject -f                     # Web 日志
journalctl -u hotproject-mqtt -f                # MQTT 日志
```

更新代码后：

```bash
cd /var/www/hot_project
# 上传覆盖文件
python manage.py migrate --noinput
python manage.py collectstatic --noinput
systemctl restart hotproject hotproject-mqtt
```

---

## 常见问题

| 问题 | 解决 |
|------|------|
| 依赖安装失败 | `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt` |
| 端口占用 | `fuser -k 8001/tcp` |
| MQTT 连不上 | `telnet <MQTT_BROKER> 1883`；`journalctl -u hotproject-mqtt -n 30` |
| 区划数据缺失 | `python manage.py import_regions --clear` |

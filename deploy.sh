#!/bin/bash
# 热应激预警系统 - 一键部署脚本
# 用法: bash deploy.sh [端口] [MQTT Broker IP] [服务器IP]
# 示例: bash deploy.sh 8001 39.105.86.77 101.201.29.99
set -e

PORT=${1:-8001}
MQTT_BROKER=${2:-39.105.86.77}
MQTT_PORT=${3:-1883}
APP_DIR="/var/www/hot_project"

echo "=========================================="
echo "  热应激预警系统 - 一键部署"
echo "  Web端口: $PORT  MQTT: $MQTT_BROKER:$MQTT_PORT"
echo "=========================================="

# 检查 Python
if ! python3 --version &>/dev/null; then
    echo "ERROR: 需要 Python 3.10+"
    exit 1
fi

# 创建目录
echo "[1/7] 创建应用目录..."
mkdir -p $APP_DIR

# 复制代码
echo "[2/7] 复制代码..."
cp -r core heatstress templates static data manage.py requirements.txt $APP_DIR/

# 虚拟环境
echo "[3/7] 创建虚拟环境..."
cd $APP_DIR
python3 -m venv venv
source venv/bin/activate

# 安装依赖
echo "[4/7] 安装依赖..."
pip install -q django==5.2 gunicorn paho-mqtt shapely requests

# 数据库迁移
echo "[5/7] 数据库迁移..."
python manage.py migrate --noinput

# 创建 systemd Web 服务
echo "[6/7] 注册 systemd 服务..."
cat > /etc/systemd/system/hotproject.service << SYSTEMDEOF
[Unit]
Description=热应激预警系统
After=network.target

[Service]
User=root
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/gunicorn heatstress.wsgi:application -b 0.0.0.0:$PORT
Restart=always
RestartSec=3
Environment=MQTT_BROKER=$MQTT_BROKER
Environment=MQTT_PORT=$MQTT_PORT

[Install]
WantedBy=multi-user.target
SYSTEMDEOF

# 创建 systemd MQTT 客户端服务
cat > /etc/systemd/system/hotproject-mqtt.service << SYSTEMDEOF
[Unit]
Description=热应激预警系统 MQTT 客户端
After=network.target hotproject.service
Wants=network.target

[Service]
User=root
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/manage.py run_mqtt
Restart=always
RestartSec=10
Environment=MQTT_BROKER=$MQTT_BROKER
Environment=MQTT_PORT=$MQTT_PORT

[Install]
WantedBy=multi-user.target
SYSTEMDEOF

systemctl daemon-reload
systemctl enable hotproject hotproject-mqtt
systemctl restart hotproject hotproject-mqtt

# 收集静态文件
echo "[7/7] 收集静态文件..."
python manage.py collectstatic --noinput

echo ""
echo "=========================================="
echo "  部署完成！"
echo "  大屏: http://<服务器IP>:$PORT/dashboard/"
echo "  账号: admin / admin123"
echo "=========================================="
echo ""
echo "  管理命令:"
echo "  systemctl status hotproject       查看Web状态"
echo "  systemctl status hotproject-mqtt  查看MQTT状态"
echo "  systemctl restart hotproject hotproject-mqtt  重启全部"
echo "  journalctl -u hotproject -f       查看Web日志"
echo "  journalctl -u hotproject-mqtt -f  查看MQTT日志"

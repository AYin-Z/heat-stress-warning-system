"""
Django 管理命令: 运行 MQTT 客户端，连接 EMQX 中继服务器。

用法:
    python manage.py run_mqtt

环境变量 / Django settings 可配置项:
    MQTT_BROKER   — EMQX 地址 (默认 39.105.86.77)
    MQTT_PORT     — MQTT TCP 端口 (默认 1883)
    MQTT_USERNAME — MQTT 用户名 (默认 空)
    MQTT_PASSWORD — MQTT 密码 (默认 空)
"""

import os
import signal
import sys
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = '启动 MQTT 客户端，连接 EMQX 中继服务器收发手表数据和预警'

    def handle(self, **options):
        # 延迟导入，确保 Django 先 setup
        import core.mqtt_client as mqtt

        self.stdout.write(self.style.NOTICE('[MQTT] 正在启动 MQTT 客户端...'))
        sys.stdout.flush()

        client = mqtt.start_mqtt()

        shutdown_requested = False

        def _shutdown(signum, frame):
            nonlocal shutdown_requested
            if shutdown_requested:
                return
            shutdown_requested = True
            self.stdout.write(self.style.WARNING(
                f'[MQTT] 收到信号 {signal.Signals(signum).name}，正在关闭...'
            ))
            sys.stdout.flush()
            mqtt.stop_mqtt()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        self.stdout.write(self.style.SUCCESS(
            f'[MQTT] MQTT 客户端已启动 (PID={os.getpid()})，等待消息...'
        ))
        sys.stdout.flush()

        # 主循环：用短 sleep 确保信号及时处理
        try:
            while mqtt.running and not shutdown_requested:
                time.sleep(0.5)
            # 等待 worker 清空队列（最多 5 秒）
            if shutdown_requested:
                deadline = time.time() + 5
                while time.time() < deadline:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            mqtt.stop_mqtt()
            self.stdout.write(self.style.SUCCESS('[MQTT] MQTT 客户端已停止'))
            sys.stdout.flush()

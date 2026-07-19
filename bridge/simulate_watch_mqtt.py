#!/usr/bin/env python3
"""
手表 MQTT 模拟器 — 模拟 A80 手表向 EMQX 发送数据。
用于联测手表→EMQX→Bridge→模型→前端 全链路。

用法:
  python simulate_watch_mqtt.py                  # 默认参数
  python simulate_watch_mqtt.py --device-id A80-TEST-001 --broker 39.105.86.77
  python simulate_watch_mqtt.py --bind-only --stress             # 仅压测绑定
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sim")

# ============================================================
# 参数
# ============================================================

DEFAULT_BROKER = "39.105.86.77"
DEFAULT_PORT = 1883
DEFAULT_DEVICE_ID = "A80-SIM-001"
VITAL_INTERVAL = 15       # 秒
STATUS_INTERVAL = 60      # 秒
STEP_INCREMENT = 5        # 每步增加步数

# ============================================================
# 手表状态
# ============================================================

class WatchState:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.heart_rate = 72
        self.spo2 = 97
        self.systolic = 118
        self.diastolic = 78
        self.steps = 0
        self.battery = 85
        self.worn = True
        self.latitude = 39.90923 + random.uniform(-0.01, 0.01)
        self.longitude = 116.397428 + random.uniform(-0.01, 0.01)

    def jitter_vitals(self):
        """模拟生理数据波动。"""
        self.heart_rate = max(60, min(180, self.heart_rate + random.randint(-5, 5)))
        self.spo2 = max(92, min(100, self.spo2 + random.randint(-1, 1)))
        self.systolic = max(95, min(160, self.systolic + random.randint(-3, 3)))
        self.diastolic = max(60, min(100, self.diastolic + random.randint(-2, 2)))
        self.steps += STEP_INCREMENT + random.randint(0, 10)
        self.battery = max(1, self.battery - random.randint(0, 1))
        self.latitude += random.uniform(-0.0005, 0.0005)
        self.longitude += random.uniform(-0.0005, 0.0005)
        # 偶尔模拟短时高强度
        if random.random() < 0.05:
            self.heart_rate += 30
            self.heart_rate = min(180, self.heart_rate)

    def vital_payload(self) -> dict:
        return {
            "deviceId": self.device_id,
            "timestamp": int(time.time() * 1000),
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "gpsAccuracy": 8.0,
            "heartRate": self.heart_rate,
            "spo2": self.spo2,
            "bloodPressure": f"{self.systolic}/{self.diastolic}",
            "steps": self.steps,
            "batteryLevel": self.battery,
            "worn": self.worn,
            "dataQuality": "complete",
            "firmwareVersion": "1.1.0-a80",
        }

    def status_payload(self) -> dict:
        return {
            "status": "online",
            "timestamp": int(time.time() * 1000),
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "batteryLevel": self.battery,
        }

    def bind_payload(self) -> dict:
        return {
            "deviceId": self.device_id,
            "mac": "8c:7e:f1:39:8b:1d",
            "timestamp": int(time.time() * 1000),
            "action": "bind",
        }


# ============================================================
# MQTT 客户端
# ============================================================

class SimulatedWatch:
    def __init__(self, state: WatchState, broker: str, port: int, mqtt_user: str = "", mqtt_pass: str = ""):
        self.state = state
        self.device_id = state.device_id
        self._running = True
        self._connected = False

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"sim-{self.device_id}-{random.randint(1000,9999)}",
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        if mqtt_user:
            self._client.username_pw_set(mqtt_user, mqtt_pass)

        self._broker = broker
        self._port = port

        # 订阅下行主题
        self._alert_topic = f"watch/{self.device_id}/alert"
        self._time_topic = f"watch/{self.device_id}/time"
        self._bind_resp_topic = f"watch/{self.device_id}/bind/response"

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self._connected = True
            log.info("[%s] ✅ 已连接 EMQX %s:%d", self.device_id, self._broker, self._port)
            client.subscribe([(self._alert_topic, 1), (self._time_topic, 1), (self._bind_resp_topic, 1)])
        else:
            log.error("[%s] ❌ 连接失败: rc=%s", self.device_id, reason_code)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self._connected = False
        if self._running:
            log.warning("[%s] 连接断开, 将自动重连", self.device_id)

    def _on_message(self, client, userdata, message):
        try:
            payload = message.payload.decode("utf-8")
            log.info("[%s] ⬇ 收到消息 [%s]: %s", self.device_id, message.topic, payload)
        except Exception as e:
            log.warning("[%s] 消息解析失败: %s", self.device_id, e)

    def connect(self):
        log.info("[%s] 正在连接 %s:%d ...", self.device_id, self._broker, self._port)
        self._client.connect_async(self._broker, self._port, keepalive=60)
        self._client.loop_start()

    def publish(self, topic: str, payload: dict, label: str = ""):
        if not self._connected:
            log.warning("[%s] 未连接，跳过 %s", self.device_id, label or topic)
            return False
        body = json.dumps(payload, ensure_ascii=False)
        info = self._client.publish(topic, body, qos=1)
        if info.rc == mqtt.MQTT_ERR_SUCCESS:
            log.info("[%s] ⬆ %s: HR=%s SPO2=%s BP=%s", self.device_id,
                     label or topic, payload.get("heartRate", "?"), payload.get("spo2", "?"),
                     payload.get("bloodPressure", "?"))
            return True
        else:
            log.warning("[%s] ⬆ %s 发布失败: rc=%s", self.device_id, label or topic, info.rc)
            return False

    def send_bind(self):
        return self.publish(f"watch/{self.device_id}/bind", self.state.bind_payload(), "BIND")

    def send_vital(self):
        self.state.jitter_vitals()
        return self.publish(f"watch/{self.device_id}/vital", self.state.vital_payload(), "VITAL")

    def send_status(self):
        return self.publish(f"watch/{self.device_id}/status", self.state.status_payload(), "STATUS")

    def stop(self):
        self._running = False
        self._client.loop_stop()
        self._client.disconnect()
        log.info("[%s] 已停止", self.device_id)


# ============================================================
# 主循环
# ============================================================

def run_device(watch: SimulatedWatch, bind_only: bool = False, stress: int = 0):
    watch.connect()
    time.sleep(1)

    # 发送绑定
    watch.send_bind()
    time.sleep(0.5)
    watch.send_status()
    time.sleep(0.5)

    if bind_only:
        log.info("[%s] 绑定完成，--bind-only 模式退出", watch.device_id)
        return

    # 压力测试模式
    if stress > 0:
        log.info("[%s] 🔥 压力模式: %d 条之后退出", watch.device_id, stress)
        count = 0
        while watch._running and count < stress:
            watch.send_vital()
            count += 1
            if count % 4 == 0:
                watch.send_status()
            time.sleep(1)
        return

    # 正常循环
    last_status = time.time()
    log.info("[%s] 🔄 进入实时循环 (vital=%ds, status=%ds)", watch.device_id, VITAL_INTERVAL, STATUS_INTERVAL)

    while watch._running:
        watch.send_vital()
        now = time.time()
        if now - last_status >= STATUS_INTERVAL:
            watch.send_status()
            last_status = now
        # 等待到下一个 vital 周期
        time.sleep(VITAL_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="A80 手表 MQTT 模拟器")
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID, help="设备ID")
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT Broker 地址")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT 端口")
    parser.add_argument("--bind-only", action="store_true", help="仅发送绑定请求后退出")
    parser.add_argument("--stress", type=int, default=0, help="压力模式：发送 N 条后退出（每秒1条）")
    parser.add_argument("--multi", type=int, default=0, help="模拟 N 个手表同时在线")
    parser.add_argument("--mqtt-user", default="", help="MQTT 用户名")
    parser.add_argument("--mqtt-pass", default="", help="MQTT 密码")
    args = parser.parse_args()

    devices: list[SimulatedWatch] = []
    threads: list[threading.Thread] = []

    # 创建模拟设备
    if args.multi > 0:
        ids = [f"A80-SIM-{i+1:03d}" for i in range(args.multi)]
    else:
        ids = [args.device_id]

    for dev_id in ids:
        state = WatchState(dev_id)
        watch = SimulatedWatch(state, args.broker, args.port, args.mqtt_user, args.mqtt_pass)
        devices.append(watch)

    def shutdown(signum, frame):
        log.info("收到信号 %s, 正在停止所有模拟设备...", signum)
        for w in devices:
            w.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 启动每个设备（单设备走主线程，多设备走线程池）
    if len(devices) == 1:
        run_device(devices[0], args.bind_only, args.stress)
    else:
        for w in devices:
            t = threading.Thread(target=run_device, args=(w, args.bind_only, args.stress), daemon=True)
            t.start()
            threads.append(t)
            time.sleep(0.3)  # 错开连接时间

        try:
            while any(t.is_alive() for t in threads):
                time.sleep(1)
        except KeyboardInterrupt:
            for w in devices:
                w.stop()

    log.info("模拟结束")


if __name__ == "__main__":
    main()

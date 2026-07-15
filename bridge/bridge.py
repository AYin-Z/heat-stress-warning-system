#!/usr/bin/env python3
"""
热应激预警系统 — MQTT ↔ HTTP 桥接服务

作用：连接 EMQX MQTT 和队友 HTTP API，实现双通道数据同步。

数据流向：
  A80 手表 ──MQTT(vital)──▶ EMQX ──▶ 本桥接 ──HTTP(upload)──▶ 队友 API (101.201.29.99:8000)
                                         │
  A80 手表 ◀──MQTT(alert)── EMQX ◀── 本桥接 ◀──HTTP(alerts)── 队友 API

=== 队友 API 接口对照 ===
  注册:    POST /api/watch/register/          (hardware_serial → device_id)
  心跳:    POST /api/watch/heartbeat/          (X-Device-ID)
  上传:    POST /api/watch/upload/             (X-Device-ID, 生理数据+GPS)
  拉预警:  GET  /api/watch/alerts/?limit=10    (X-Device-ID)
  确认:    POST /api/watch/alerts/{id}/ack/    (X-Device-ID)
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin

import paho.mqtt.client as mqtt
import requests

# ============================================================
# 配置
# ============================================================

# --- MQTT ---
MQTT_BROKER = os.environ.get("BRIDGE_MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("BRIDGE_MQTT_PORT", "1883"))
MQTT_TOPIC_VITAL = os.environ.get("BRIDGE_MQTT_TOPIC_VITAL", "watch/+/vital")
MQTT_TOPIC_STATUS = os.environ.get("BRIDGE_MQTT_TOPIC_STATUS", "watch/+/status")
MQTT_ALERT_TOPIC_TPL = "watch/{device_id}/alert"  # 反向推送预警到 MQTT

# --- HTTP API ---
API_BASE = os.environ.get("BRIDGE_API_BASE", "http://101.201.29.99:8001")
API_TIMEOUT = int(os.environ.get("BRIDGE_API_TIMEOUT", "10"))
API_RETRY = int(os.environ.get("BRIDGE_API_RETRY", "2"))

# --- 行为 ---
LOG_LEVEL = os.environ.get("BRIDGE_LOG_LEVEL", "INFO")
ALERT_POLL_INTERVAL = int(os.environ.get("BRIDGE_ALERT_POLL_INTERVAL", "10"))  # 拉预警间隔(秒)

# ============================================================
# 日志
# ============================================================

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bridge")

# ============================================================
# 设备状态追踪
# ============================================================

@dataclass
class DeviceState:
    mqtt_id: str             # MQTT topic 中的 deviceId (hardware_serial)
    api_device_id: str = ""  # API 注册返回的 device_id (WATCH-XXXXXXXX)
    bind_status: str = "unknown"
    registered: bool = False
    last_upload: float = 0.0
    last_heartbeat: float = 0.0
    last_alert_check: float = 0.0


class DeviceRegistry:
    """线程安全的设备注册表"""

    def __init__(self):
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceState] = {}

    def get_or_create(self, mqtt_id: str) -> DeviceState:
        with self._lock:
            if mqtt_id not in self._devices:
                self._devices[mqtt_id] = DeviceState(mqtt_id=mqtt_id)
            return self._devices[mqtt_id]

    def update(self, mqtt_id: str, **kwargs):
        with self._lock:
            if mqtt_id in self._devices:
                for k, v in kwargs.items():
                    setattr(self._devices[mqtt_id], k, v)

    def list_active(self) -> list[DeviceState]:
        with self._lock:
            return [d for d in self._devices.values() if d.bind_status == "active"]

    def list_all(self) -> list[DeviceState]:
        with self._lock:
            return list(self._devices.values())


registry = DeviceRegistry()

# ============================================================
# HTTP API 客户端
# ============================================================

class ApiClient:
    """队友 API HTTP 客户端，含重试和错误处理"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _post(self, path: str, json_data: dict, device_id: str | None = None) -> dict:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        headers = {}
        if device_id:
            headers["X-Device-ID"] = device_id

        for attempt in range(1 + API_RETRY):
            try:
                resp = self.session.post(
                    url, json=json_data, headers=headers, timeout=API_TIMEOUT
                )
                # 非 JSON 响应（如 404 HTML）不抛异常，返回 status-based dict
                try:
                    data = resp.json()
                except (json.JSONDecodeError, ValueError):
                    log.warning(
                        "API %s → %s (non-JSON response, %d bytes)",
                        path, resp.status_code, len(resp.text)
                    )
                    return {"ok": False, "error": f"non-json-{resp.status_code}"}
                if resp.status_code in (200, 201):
                    return data
                log.warning(
                    "API %s → %s %s (attempt %d/%d)",
                    path, resp.status_code, data.get("error", ""), attempt, 1 + API_RETRY
                )
                if resp.status_code in (400, 401, 403, 404):
                    return data  # 客户端错误不重试
            except (requests.ConnectionError, requests.Timeout) as e:
                log.warning("API %s request failed (attempt %d/%d): %s", path, attempt, 1 + API_RETRY, e)
                if attempt == API_RETRY:
                    return {"ok": False, "error": str(e)}
                time.sleep(2 ** attempt)
        return {"ok": False, "error": "max_retries"}

    def _get(self, path: str, device_id: str, params: dict | None = None) -> dict:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        headers = {"X-Device-ID": device_id}
        for attempt in range(1 + API_RETRY):
            try:
                resp = self.session.get(
                    url, headers=headers, params=params, timeout=API_TIMEOUT
                )
                try:
                    return resp.json()
                except (json.JSONDecodeError, ValueError):
                    log.warning(
                        "API %s → %s (non-JSON response)",
                        path, resp.status_code
                    )
                    return {"ok": False, "error": f"non-json-{resp.status_code}"}
            except (requests.ConnectionError, requests.Timeout) as e:
                log.warning("API %s request failed (attempt %d/%d): %s", path, attempt, 1 + API_RETRY, e)
                if attempt == API_RETRY:
                    return {"ok": False, "error": str(e)}
                time.sleep(2 ** attempt)
        return {"ok": False, "error": "max_retries"}

    # --- 业务方法 ---

    def register_device(self, device_id: str) -> dict:
        """注册设备，幂等：新设备返回 201, 已激活返回 200"""
        return self._post(
            "/api/watch/register/",
            {"hardware_serial": device_id, "firmware_version": "A80-bridge/v1.0"},
            device_id=device_id,
        )

    def send_heartbeat(self, device_id: str, lat: float | None = None, lng: float | None = None) -> dict:
        body = {}
        if lat is not None and lng is not None:
            body["latitude"] = lat
            body["longitude"] = lng
        return self._post("/api/watch/heartbeat/", body, device_id=device_id)

    def upload_data(
        self,
        device_id: str,
        *,
        heart_rate: int = 75,
        blood_oxygen: float = 98.0,
        blood_pressure_sys: int = 120,
        blood_pressure_dia: int = 80,
        step_frequency: int = 0,
        core_temperature: float = 37.0,
        latitude: float | None = None,
        longitude: float | None = None,
        timestamp: str | None = None,
    ) -> dict:
        body = {
            "heart_rate": heart_rate,
            "blood_oxygen": blood_oxygen,
            "blood_pressure_sys": blood_pressure_sys,
            "blood_pressure_dia": blood_pressure_dia,
            "step_frequency": step_frequency,
            "core_temperature": core_temperature,
        }
        if latitude is not None:
            body["latitude"] = latitude
        if longitude is not None:
            body["longitude"] = longitude
        if timestamp:
            body["timestamp"] = timestamp
        return self._post("/api/watch/upload/", body, device_id=device_id)

    def fetch_alerts(self, device_id: str, limit: int = 10) -> list[dict]:
        data = self._get(f"/api/watch/alerts/", device_id, params={"limit": limit})
        return data.get("alerts", []) if data.get("ok") or "alerts" in data else []

    def ack_alert(self, device_id: str, alert_id: int) -> dict:
        return self._post(f"/api/watch/alerts/{alert_id}/ack/", {}, device_id=device_id)


api = ApiClient(API_BASE)

# ============================================================
# 核心桥接逻辑
# ============================================================

def parse_blood_pressure(bp_str: str) -> tuple[int, int]:
    """解析 "120/80" → (120, 80)，异常时返回默认值"""
    try:
        parts = bp_str.split("/")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        pass
    log.debug("Failed to parse blood pressure: %s, using defaults", bp_str)
    return 120, 80


def ts_to_iso(ts_ms: int) -> str:
    """Unix 毫秒 → ISO 8601 字符串"""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    # 转北京时间
    from datetime import timedelta
    bj = dt + timedelta(hours=8)
    return bj.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def ensure_registered(mqtt_id: str) -> bool:
    """确保设备已注册，返回是否处于可用状态。如已注册返回 api_device_id 存在。"""
    state = registry.get_or_create(mqtt_id)
    if state.api_device_id and state.bind_status == "active":
        return state.bind_status == "active"

    log.info("[%s] Registering device...", mqtt_id)
    resp = api.register_device(mqtt_id)

    if resp.get("ok"):
        api_id = resp.get("device_id", "")
        bind_status = resp.get("bind_status", "unknown")
        registry.update(mqtt_id, registered=True, api_device_id=api_id, bind_status=bind_status)
        log.info("[%s] Registered → api_id=%s bind_status=%s", mqtt_id, api_id, bind_status)
        return bind_status == "active"
    else:
        log.error("[%s] Registration failed: %s", mqtt_id, resp)
        return False


def forward_vital(mqtt_id: str, payload: dict):
    """将 MQTT vital 消息转发到队友 API upload"""
    state = registry.get_or_create(mqtt_id)
    api_id = state.api_device_id
    if not api_id:
        log.warning("[%s] No api_device_id, skipping upload", mqtt_id)
        return

    # 解析血压
    bp_sys, bp_dia = parse_blood_pressure(payload.get("bloodPressure", "120/80"))

    # 构造时间戳
    ts_ms = payload.get("timestamp", int(time.time() * 1000))
    ts_iso = ts_to_iso(ts_ms)

    resp = api.upload_data(
        device_id=api_id,
        heart_rate=int(payload.get("heartRate", 75)),
        blood_oxygen=float(payload.get("spo2", 98.0)),
        blood_pressure_sys=bp_sys,
        blood_pressure_dia=bp_dia,
        step_frequency=0,
        core_temperature=float(payload.get("coreTemp", 37.0)),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
        timestamp=ts_iso,
    )

    registry.update(mqtt_id, last_upload=time.time())

    # 检查 upload 响应中的预警
    alert = resp.get("alert")
    if alert:
        log.warning("[%s] ALERT from API: type=%s risk=%s advice=%s",
                     mqtt_id, alert.get("type"), alert.get("risk_level"),
                     alert.get("advice", "")[:50])
        publish_alert_to_mqtt(mqtt_id, alert)


def forward_status(mqtt_id: str, payload: dict):
    """将 MQTT status 消息转为心跳"""
    online = payload.get("status") == "online"
    if not online:
        return

    state = registry.get_or_create(mqtt_id)
    api_id = state.api_device_id
    if not api_id:
        return

    lat = payload.get("latitude")
    lng = payload.get("longitude")

    resp = api.send_heartbeat(api_id, lat=lat, lng=lng)
    registry.update(mqtt_id, last_heartbeat=time.time())

    # 心跳响应中的 bind_status 变化
    new_status = resp.get("bind_status")
    if new_status:
        state = registry.get_or_create(mqtt_id)
        if state.bind_status != new_status:
            log.info("[%s] bind_status changed: %s → %s", mqtt_id, state.bind_status, new_status)
            registry.update(mqtt_id, bind_status=new_status)


def publish_alert_to_mqtt(mqtt_id: str, alert: dict):
    """将队友 API 的预警推送到 MQTT，大屏和手表都能收到"""
    topic = MQTT_ALERT_TOPIC_TPL.format(device_id=mqtt_id)
    payload = json.dumps({
        "deviceId": mqtt_id,
        "alertType": "高风险预警" if alert.get("risk_level") == "high_risk" else "普通预警",
        "coreTemp": alert.get("core_temperature", 0),
        "officerName": mqtt_id,
        "advice": alert.get("advice", ""),
    }, ensure_ascii=False)
    mqtt_client.publish(topic, payload, qos=1)
    log.info("[%s] Alert published to MQTT topic %s", mqtt_id, topic)


def poll_alerts():
    """定期拉取各设备的未读预警，推送 ack 并转发到 MQTT"""
    for state in registry.list_active():
        now = time.time()
        if now - state.last_alert_check < ALERT_POLL_INTERVAL:
            continue
        if not state.api_device_id:
            continue

        try:
            alerts = api.fetch_alerts(state.api_device_id, limit=5)
            registry.update(state.mqtt_id, last_alert_check=now)

            for alert in alerts:
                alert_id = alert.get("id")
                if alert_id:
                    publish_alert_to_mqtt(state.mqtt_id, alert)
                    api.ack_alert(state.api_device_id, alert_id)
                    log.info("[%s] Acked alert #%s", state.mqtt_id, alert_id)
        except Exception:
            log.exception("[%s] Failed to poll alerts", state.mqtt_id)


# ============================================================
# MQTT 客户端
# ============================================================

mqtt_client = mqtt.Client(client_id="heatstress-bridge")


def extract_device_id(topic: str) -> str:
    """从 topic 'watch/{deviceId}/vital' 提取 deviceId"""
    parts = topic.split("/")
    return parts[1] if len(parts) >= 2 else "unknown"


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info("MQTT connected to %s:%d", MQTT_BROKER, MQTT_PORT)
        client.subscribe([(MQTT_TOPIC_VITAL, 1), (MQTT_TOPIC_STATUS, 1)])
        log.info("Subscribed: %s, %s", MQTT_TOPIC_VITAL, MQTT_TOPIC_STATUS)
    else:
        log.error("MQTT connection failed: rc=%d", rc)


def on_message(client, userdata, msg):
    try:
        device_id = extract_device_id(msg.topic)
        payload = json.loads(msg.payload.decode("utf-8"))

        if msg.topic.endswith("/vital"):
            # 首次上报前确保注册
            if ensure_registered(device_id):
                forward_vital(device_id, payload)
        elif msg.topic.endswith("/status"):
            if ensure_registered(device_id):
                forward_status(device_id, payload)

    except json.JSONDecodeError:
        log.warning("Invalid JSON from %s: %s", msg.topic, msg.payload[:100])
    except Exception:
        log.exception("Error handling message from %s", msg.topic)


mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# ============================================================
# 主循环
# ============================================================

running = True


def signal_handler(sig, frame):
    global running
    log.info("Received signal %s, shutting down...", sig)
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def alert_poll_loop():
    """后台线程：定期轮询各设备预警"""
    while running:
        try:
            poll_alerts()
        except Exception:
            log.exception("Alert poll error")
        time.sleep(ALERT_POLL_INTERVAL)


def main():
    log.info("=== HeatStress Bridge Starting ===")
    log.info("MQTT: %s:%d", MQTT_BROKER, MQTT_PORT)
    log.info("API:  %s", API_BASE)

    # 启动预警轮询线程
    poll_thread = threading.Thread(target=alert_poll_loop, daemon=True)
    poll_thread.start()

    # 连接 MQTT
    mqtt_client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()

    # 主循环保活
    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    log.info("Stopping MQTT loop...")
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    log.info("=== Bridge Stopped ===")


if __name__ == "__main__":
    main()

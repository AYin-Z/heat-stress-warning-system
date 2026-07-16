#!/usr/bin/env python3
"""A80 MQTT to dashboard API bridge."""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin

import paho.mqtt.client as mqtt
import requests
from requests.adapters import HTTPAdapter


MQTT_BROKER = os.environ.get("BRIDGE_MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("BRIDGE_MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("BRIDGE_MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("BRIDGE_MQTT_PASSWORD", "")
MQTT_TOPIC_VITAL = os.environ.get("BRIDGE_MQTT_TOPIC_VITAL", "watch/+/vital")
MQTT_TOPIC_STATUS = os.environ.get("BRIDGE_MQTT_TOPIC_STATUS", "watch/+/status")
MQTT_ALERT_TOPIC_TPL = "watch/{device_id}/alert"
MQTT_TIME_TOPIC_TPL = "watch/{device_id}/time"

API_BASE = os.environ.get("BRIDGE_API_BASE", "http://101.201.29.99:8001")
API_TIMEOUT = float(os.environ.get("BRIDGE_API_TIMEOUT", "6"))
API_RETRY = int(os.environ.get("BRIDGE_API_RETRY", "1"))
ALERT_POLL_INTERVAL = int(os.environ.get("BRIDGE_ALERT_POLL_INTERVAL", "15"))
WORKER_COUNT = int(os.environ.get("BRIDGE_WORKER_COUNT", "4"))
QUEUE_SIZE = int(os.environ.get("BRIDGE_QUEUE_SIZE", "2000"))
MQTT_PUBLISH_TIMEOUT = float(os.environ.get("BRIDGE_MQTT_PUBLISH_TIMEOUT", "6"))

logging.basicConfig(
    level=getattr(logging, os.environ.get("BRIDGE_LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bridge")


@dataclass
class DeviceState:
    mqtt_id: str
    api_device_id: str = ""
    bind_status: str = "unknown"
    registered: bool = False
    last_upload: float = 0.0
    last_heartbeat: float = 0.0
    last_alert_check: float = 0.0
    last_steps: Optional[int] = None
    last_steps_at: float = 0.0
    in_flight_alert_ids: set[int] = field(default_factory=set)
    published_alert_ids: set[int] = field(default_factory=set)
    acknowledged_alert_ids: set[int] = field(default_factory=set)


class DeviceRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: dict[str, DeviceState] = {}

    def get_or_create(self, mqtt_id: str) -> DeviceState:
        with self._lock:
            return self._devices.setdefault(mqtt_id, DeviceState(mqtt_id=mqtt_id))

    def update(self, mqtt_id: str, **values: Any) -> None:
        with self._lock:
            state = self._devices.setdefault(mqtt_id, DeviceState(mqtt_id=mqtt_id))
            for key, value in values.items():
                setattr(state, key, value)

    def active_snapshot(self) -> list[DeviceState]:
        with self._lock:
            return [
                DeviceState(
                    mqtt_id=item.mqtt_id,
                    api_device_id=item.api_device_id,
                    bind_status=item.bind_status,
                    registered=item.registered,
                    last_upload=item.last_upload,
                    last_heartbeat=item.last_heartbeat,
                    last_alert_check=item.last_alert_check,
                )
                for item in self._devices.values()
                if item.bind_status == "active"
            ]

    def step_frequency(self, mqtt_id: str, steps: Optional[int], sample_time: float) -> Optional[int]:
        if steps is None or steps < 0:
            return None
        with self._lock:
            state = self._devices.setdefault(mqtt_id, DeviceState(mqtt_id=mqtt_id))
            previous_steps = state.last_steps
            previous_time = state.last_steps_at
            state.last_steps = steps
            state.last_steps_at = sample_time
            if previous_steps is None or previous_time <= 0 or steps < previous_steps:
                return None
            elapsed = sample_time - previous_time
            if elapsed < 1:
                return None
            return round(min(300.0, max(0.0, (steps - previous_steps) * 60.0 / elapsed)))

    def begin_alert_delivery(self, mqtt_id: str, alert_id: Optional[int]) -> Optional[bool]:
        if alert_id is None:
            return False
        with self._lock:
            state = self._devices.setdefault(mqtt_id, DeviceState(mqtt_id=mqtt_id))
            if alert_id in state.acknowledged_alert_ids or alert_id in state.in_flight_alert_ids:
                return None
            state.in_flight_alert_ids.add(alert_id)
            return alert_id in state.published_alert_ids

    def complete_alert_delivery(
        self,
        mqtt_id: str,
        alert_id: Optional[int],
        *,
        published: bool,
        acknowledged: bool,
    ) -> None:
        if alert_id is None:
            return
        with self._lock:
            state = self._devices.setdefault(mqtt_id, DeviceState(mqtt_id=mqtt_id))
            state.in_flight_alert_ids.discard(alert_id)
            if published:
                state.published_alert_ids.add(alert_id)
            if acknowledged:
                state.acknowledged_alert_ids.add(alert_id)
            if len(state.acknowledged_alert_ids) >= 500:
                state.published_alert_ids.intersection_update(state.in_flight_alert_ids)
                state.acknowledged_alert_ids.clear()


registry = DeviceRegistry()
registration_lock = threading.Lock()


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        adapter = HTTPAdapter(pool_connections=WORKER_COUNT + 2, pool_maxsize=WORKER_COUNT + 2)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        device_id: Optional[str] = None,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        headers = {"X-Device-ID": device_id} if device_id else {}
        for attempt in range(API_RETRY + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    json=body,
                    params=params,
                    headers=headers,
                    timeout=API_TIMEOUT,
                )
                try:
                    data = response.json()
                except ValueError:
                    log.warning("API %s returned HTTP %s with non-JSON body", path, response.status_code)
                    return {"ok": False, "error": f"non-json-{response.status_code}"}
                if 200 <= response.status_code < 300:
                    return data
                log.warning("API %s returned HTTP %s: %s", path, response.status_code, data)
                if response.status_code < 500:
                    return data
            except (requests.ConnectionError, requests.Timeout) as exc:
                log.warning(
                    "API %s failed (%d/%d): %s",
                    path,
                    attempt + 1,
                    API_RETRY + 1,
                    exc,
                )
            if attempt < API_RETRY:
                time.sleep(2**attempt)
        return {"ok": False, "error": "request-failed"}

    def register_device(self, hardware_serial: str) -> dict[str, Any]:
        return self.request_json(
            "POST",
            "/api/watch/register/",
            device_id=hardware_serial,
            body={"hardware_serial": hardware_serial, "firmware_version": "A80-bridge/v1.1"},
        )

    def heartbeat(
        self, device_id: str, latitude: Optional[float], longitude: Optional[float]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if latitude is not None and longitude is not None:
            body.update(latitude=latitude, longitude=longitude)
        return self.request_json("POST", "/api/watch/heartbeat/", device_id=device_id, body=body)

    def upload(self, device_id: str, **values: Any) -> dict[str, Any]:
        body = {key: value for key, value in values.items() if value is not None}
        return self.request_json("POST", "/api/watch/upload/", device_id=device_id, body=body)

    def alerts(self, device_id: str, limit: int = 5) -> list[dict[str, Any]]:
        response = self.request_json(
            "GET", "/api/watch/alerts/", device_id=device_id, params={"limit": limit}
        )
        alerts = response.get("alerts", [])
        return alerts if isinstance(alerts, list) else []

    def acknowledge(self, device_id: str, alert_id: int) -> dict[str, Any]:
        return self.request_json(
            "POST", f"/api/watch/alerts/{alert_id}/ack/", device_id=device_id, body={}
        )


api = ApiClient(API_BASE)


def optional_int(payload: dict[str, Any], key: str, low: int, high: int) -> Optional[int]:
    try:
        value = payload.get(key)
        if value is None or isinstance(value, bool):
            return None
        parsed = int(value)
        return parsed if low <= parsed <= high else None
    except (TypeError, ValueError):
        return None


def optional_float(payload: dict[str, Any], key: str, low: float, high: float) -> Optional[float]:
    try:
        value = payload.get(key)
        if value is None or isinstance(value, bool):
            return None
        parsed = float(value)
        return parsed if low <= parsed <= high else None
    except (TypeError, ValueError):
        return None


def parse_blood_pressure(value: Any) -> tuple[Optional[int], Optional[int]]:
    if not isinstance(value, str):
        return None, None
    try:
        systolic_text, diastolic_text = value.split("/", 1)
        systolic = int(systolic_text)
        diastolic = int(diastolic_text)
        if 70 <= systolic <= 230 and 40 <= diastolic <= 160:
            return systolic, diastolic
    except (TypeError, ValueError):
        pass
    return None, None


def valid_coordinates(payload: dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    latitude = optional_float(payload, "latitude", -90, 90)
    longitude = optional_float(payload, "longitude", -180, 180)
    if latitude is None or longitude is None or (latitude == 0 and longitude == 0):
        return None, None
    return latitude, longitude


def sample_time(payload: dict[str, Any]) -> float:
    try:
        timestamp = int(payload.get("timestamp")) / 1000.0
        if datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() <= timestamp <= time.time() + 86400:
            return timestamp
    except (TypeError, ValueError):
        pass
    return time.time()


def iso_timestamp(payload: dict[str, Any]) -> Optional[str]:
    timestamp = sample_time(payload)
    try:
        original = int(payload.get("timestamp")) / 1000.0
    except (TypeError, ValueError):
        return None
    if abs(timestamp - original) > 1:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_registered(mqtt_id: str) -> bool:
    state = registry.get_or_create(mqtt_id)
    if state.api_device_id and state.bind_status == "active":
        return True
    with registration_lock:
        state = registry.get_or_create(mqtt_id)
        if state.api_device_id and state.bind_status == "active":
            return True
        response = api.register_device(mqtt_id)
        if not response.get("ok"):
            log.error("[%s] Registration failed: %s", mqtt_id, response)
            return False
        registry.update(
            mqtt_id,
            registered=True,
            api_device_id=response.get("device_id", ""),
            bind_status=response.get("bind_status", "unknown"),
        )
        log.info(
            "[%s] Registered as %s (%s)",
            mqtt_id,
            response.get("device_id", ""),
            response.get("bind_status", "unknown"),
        )
        return response.get("bind_status") == "active"


def forward_vital(mqtt_id: str, payload: dict[str, Any]) -> None:
    state = registry.get_or_create(mqtt_id)
    if not state.api_device_id:
        return
    heart_rate = optional_int(payload, "heartRate", 30, 250)
    blood_oxygen = optional_float(payload, "spo2", 70, 100)
    systolic, diastolic = parse_blood_pressure(payload.get("bloodPressure"))
    steps = optional_int(payload, "steps", 0, 10_000_000)
    taken_at = sample_time(payload)
    step_frequency = registry.step_frequency(mqtt_id, steps, taken_at)
    core_temperature = optional_float(payload, "coreTemp", 30, 45)
    latitude, longitude = valid_coordinates(payload)

    complete_vitals = (
        heart_rate is not None
        and blood_oxygen is not None
        and systolic is not None
        and diastolic is not None
        and core_temperature is not None
    )
    if not complete_vitals:
        log.debug("[%s] Incomplete vital frame ignored (quality=%s)", mqtt_id, payload.get("dataQuality"))
        return

    response = api.upload(
        state.api_device_id,
        heart_rate=heart_rate,
        blood_oxygen=blood_oxygen,
        blood_pressure_sys=systolic,
        blood_pressure_dia=diastolic,
        step_frequency=step_frequency,
        core_temperature=core_temperature,
        latitude=latitude,
        longitude=longitude,
        timestamp=iso_timestamp(payload),
    )
    if response.get("ok"):
        registry.update(mqtt_id, last_upload=time.time())
    else:
        log.warning("[%s] Upload rejected: %s", mqtt_id, response)

    alert = response.get("alert")
    if isinstance(alert, dict):
        deliver_alert(mqtt_id, state.api_device_id, alert)


def forward_status(mqtt_id: str, payload: dict[str, Any]) -> None:
    if payload.get("status") != "online":
        return
    state = registry.get_or_create(mqtt_id)
    if not state.api_device_id:
        return
    latitude, longitude = valid_coordinates(payload)
    response = api.heartbeat(state.api_device_id, latitude, longitude)
    if response.get("ok"):
        registry.update(mqtt_id, last_heartbeat=time.time())
    bind_status = response.get("bind_status")
    if bind_status:
        registry.update(mqtt_id, bind_status=bind_status)


def publish_time_sync(mqtt_id: str) -> bool:
    topic = MQTT_TIME_TOPIC_TPL.format(device_id=mqtt_id)
    payload = json.dumps(
        {
            "timestamp": int(time.time() * 1000),
            "source": "heatstress-bridge",
        }
    )
    info = mqtt_client.publish(topic, payload, qos=1, retain=False)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        log.warning("[%s] Time sync MQTT publish failed: rc=%s", mqtt_id, info.rc)
        return False
    try:
        info.wait_for_publish(timeout=MQTT_PUBLISH_TIMEOUT)
    except (RuntimeError, ValueError) as exc:
        log.warning("[%s] Time sync MQTT confirmation failed: %s", mqtt_id, exc)
        return False
    if not info.is_published():
        log.warning("[%s] Time sync MQTT confirmation timed out", mqtt_id)
        return False
    return True


def alert_id(alert: dict[str, Any]) -> Optional[int]:
    try:
        return int(alert["id"]) if alert.get("id") is not None else None
    except (TypeError, ValueError):
        return None


def publish_alert(mqtt_id: str, alert: dict[str, Any]) -> bool:
    topic = MQTT_ALERT_TOPIC_TPL.format(device_id=mqtt_id)
    risk_level = alert.get("risk_level")
    payload = json.dumps(
        {
            "deviceId": mqtt_id,
            "alertId": alert_id(alert),
            "alertType": "高风险预警" if risk_level == "high_risk" else "普通预警",
            "riskLevel": risk_level,
            "coreTemp": alert.get("core_temperature"),
            "officerName": alert.get("officer_name") or mqtt_id,
            "advice": alert.get("advice", ""),
            "timestamp": int(time.time() * 1000),
        },
        ensure_ascii=False,
    )
    info = mqtt_client.publish(topic, payload, qos=1, retain=False)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        log.warning("[%s] Alert MQTT publish failed: rc=%s", mqtt_id, info.rc)
        return False
    try:
        info.wait_for_publish(timeout=MQTT_PUBLISH_TIMEOUT)
    except (RuntimeError, ValueError) as exc:
        log.warning("[%s] Alert MQTT confirmation failed: %s", mqtt_id, exc)
        return False
    if not info.is_published():
        log.warning("[%s] Alert MQTT confirmation timed out", mqtt_id)
        return False
    log.warning("[%s] Alert published: risk=%s", mqtt_id, risk_level)
    return True


def deliver_alert(mqtt_id: str, api_device_id: str, alert: dict[str, Any]) -> None:
    current_alert_id = alert_id(alert)
    already_published = registry.begin_alert_delivery(mqtt_id, current_alert_id)
    if already_published is None:
        return
    published = already_published
    acknowledged = False
    try:
        if not published:
            published = publish_alert(mqtt_id, alert)
        if published and current_alert_id is not None:
            response = api.acknowledge(api_device_id, current_alert_id)
            acknowledged = response.get("ok") is True
            if not acknowledged:
                log.warning("[%s] Alert acknowledgement failed: %s", mqtt_id, response)
    finally:
        registry.complete_alert_delivery(
            mqtt_id,
            current_alert_id,
            published=published,
            acknowledged=acknowledged,
        )


def poll_alerts() -> None:
    for state in registry.active_snapshot():
        now = time.time()
        if now - state.last_alert_check < ALERT_POLL_INTERVAL or not state.api_device_id:
            continue
        registry.update(state.mqtt_id, last_alert_check=now)
        for alert in api.alerts(state.api_device_id):
            if isinstance(alert, dict):
                deliver_alert(state.mqtt_id, state.api_device_id, alert)


message_queue: queue.Queue[tuple[str, str, dict[str, Any]]] = queue.Queue(maxsize=QUEUE_SIZE)
running = True


def process_message(kind: str, device_id: str, payload: dict[str, Any]) -> None:
    if kind == "status" and payload.get("status") == "online":
        publish_time_sync(device_id)
    if not ensure_registered(device_id):
        return
    if kind == "vital":
        forward_vital(device_id, payload)
    elif kind == "status":
        forward_status(device_id, payload)


def worker_loop() -> None:
    while running or not message_queue.empty():
        try:
            item = message_queue.get(timeout=1)
        except queue.Empty:
            continue
        try:
            process_message(*item)
        except Exception:
            log.exception("Message processing failed for %s", item[1])
        finally:
            message_queue.task_done()


def extract_device_id(topic: str) -> Optional[str]:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "watch" or not parts[1]:
        return None
    return parts[1]


def on_connect(client, userdata, flags, reason_code, properties) -> None:
    if reason_code == 0:
        client.subscribe([(MQTT_TOPIC_VITAL, 1), (MQTT_TOPIC_STATUS, 1)])
        log.info("MQTT connected to %s:%d", MQTT_BROKER, MQTT_PORT)
    else:
        log.error("MQTT connection failed: %s", reason_code)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties) -> None:
    if running:
        log.warning("MQTT disconnected: %s", reason_code)


def on_message(client, userdata, message) -> None:
    device_id = extract_device_id(message.topic)
    if device_id is None:
        log.warning("Ignoring malformed topic: %s", message.topic)
        return
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        kind = "vital" if message.topic.endswith("/vital") else "status"
        message_queue.put_nowait((kind, device_id, payload))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        log.warning("Invalid payload from %s: %s", message.topic, exc)
    except queue.Full:
        log.error("Bridge queue full; dropping newest message from %s", device_id)


mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="heatstress-bridge-v2")
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message
if MQTT_USERNAME:
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)


def signal_handler(signum, frame) -> None:
    global running
    log.info("Received signal %s", signum)
    running = False


def alert_poll_loop() -> None:
    while running:
        try:
            poll_alerts()
        except Exception:
            log.exception("Alert polling failed")
        time.sleep(ALERT_POLL_INTERVAL)


def main() -> None:
    log.info("HeatStress bridge starting: MQTT=%s:%d API=%s", MQTT_BROKER, MQTT_PORT, API_BASE)
    for index in range(max(1, WORKER_COUNT)):
        threading.Thread(target=worker_loop, name=f"bridge-worker-{index}", daemon=True).start()
    threading.Thread(target=alert_poll_loop, name="alert-poller", daemon=True).start()

    mqtt_client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()
    try:
        while running:
            time.sleep(1)
    finally:
        mqtt_client.loop_stop()
        try:
            mqtt_client.disconnect()
        except Exception:
            pass
        log.info("HeatStress bridge stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    main()

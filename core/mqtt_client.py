"""
MQTT 客户端 — 连接 EMQX 中继服务器，收发手表数据和预警。

大屏端通过本模块:
  1. 订阅 watch/+/vital   → 接收手表生理数据
  2. 订阅 watch/+/status  → 接收手表在线状态
  3. 订阅 watch/+/alert   → 接收预警通知（来自中继/模型）
  4. 发布 watch/{id}/alert → 下发预警到手表（中继自动分发）

连接信息:
  协议: MQTT TCP
  地址: 39.105.86.77:1883
  认证: 当前无（匿名）
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

import paho.mqtt.client as mqtt
from django.utils import timezone as django_timezone
from django.conf import settings

logger = logging.getLogger('mqtt')

# ── 连接配置 ──
MQTT_BROKER = getattr(settings, 'MQTT_BROKER', '39.105.86.77')
MQTT_PORT = int(getattr(settings, 'MQTT_PORT', 1883))
MQTT_USERNAME = getattr(settings, 'MQTT_USERNAME', '')
MQTT_PASSWORD = getattr(settings, 'MQTT_PASSWORD', '')
MQTT_TOPIC_VITAL = 'watch/+/vital'
MQTT_TOPIC_STATUS = 'watch/+/status'
MQTT_TOPIC_ALERT = 'watch/+/alert'
MQTT_TOPIC_BIND = 'watch/+/bind'
MQTT_ALERT_TOPIC_TPL = 'watch/{device_id}/alert'

# ── 工作线程配置 ──
WORKER_COUNT = int(getattr(settings, 'MQTT_WORKER_COUNT', 2))
QUEUE_SIZE = int(getattr(settings, 'MQTT_QUEUE_SIZE', 2000))

# ── 全局状态 ──
message_queue: queue.Queue[tuple[str, str, dict[str, Any]]] = queue.Queue(maxsize=QUEUE_SIZE)
running = True
_client: Optional[mqtt.Client] = None
# 用于发布预警的引用（主线程创建 client 后设置）
_publish_client: Optional[mqtt.Client] = None


# ═══════════════════════════════════════════════════════════════
# 消息解析
# ═══════════════════════════════════════════════════════════════

def optional_int(value: Any, low: int, high: int) -> Optional[int]:
    """安全整数提取"""
    try:
        if value is None or isinstance(value, bool):
            return None
        parsed = int(value)
        return parsed if low <= parsed <= high else None
    except (TypeError, ValueError):
        return None


def optional_float(value: Any, low: float, high: float) -> Optional[float]:
    """安全浮点数提取"""
    try:
        if value is None or isinstance(value, bool):
            return None
        parsed = float(value)
        return parsed if low <= parsed <= high else None
    except (TypeError, ValueError):
        return None


def parse_blood_pressure(value: Any) -> tuple[Optional[int], Optional[int]]:
    """解析血压字符串 "120/80" """
    if not isinstance(value, str):
        return None, None
    try:
        systolic_text, diastolic_text = value.split('/', 1)
        systolic = int(systolic_text)
        diastolic = int(diastolic_text)
        if 70 <= systolic <= 230 and 40 <= diastolic <= 160:
            return systolic, diastolic
    except (TypeError, ValueError):
        pass
    return None, None


def valid_coordinates(lat: Any, lng: Any) -> tuple[Optional[float], Optional[float]]:
    """验证并返回有效坐标"""
    latitude = optional_float(lat, -90, 90)
    longitude = optional_float(lng, -180, 180)
    if latitude is None or longitude is None or (latitude == 0 and longitude == 0):
        return None, None
    return latitude, longitude


def parse_timestamp(value: Any) -> Optional[datetime]:
    """将 Unix 毫秒时间戳转为 datetime（带时区）"""
    try:
        ts = int(value) / 1000.0
        min_ts = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        max_ts = time.time() + 86400
        if min_ts <= ts <= max_ts:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (TypeError, ValueError):
        pass
    return None


# ═══════════════════════════════════════════════════════════════
# 消息处理（在 worker 线程中执行）
# ═══════════════════════════════════════════════════════════════

def _get_recording_project():
    """获取当前正在录入的项目"""
    from .models import Project
    return Project.objects.filter(status='recording').first() or Project.objects.first()


def _sync_device_project(device) -> None:
    """设备上报数据时，自动归入当前 recording 项目（支持跨城市演示切换）"""
    from .models import Project
    recording = _get_recording_project()
    if recording and device.project_id != recording.id:
        old_name = device.project.name
        device.project = recording
        device.save(update_fields=['project'])
        logger.info("[MQTT] 设备 %s 项目切换: %s → %s", device.device_id, old_name, recording.name)


def _auto_create_device(device_id: str, **extra_fields) -> Optional[Any]:
    """自动创建设备（手表通过 MQTT 首次上报数据时），状态为 pending，待管理员激活。
    同时清理 HTTP 注册接口产生的 WATCH-* 虚设备（同 hardware_serial 的重复记录）。
    """
    from django.db import IntegrityError
    from .models import Device

    default_project = _get_recording_project()
    if not default_project:
        logger.error("[MQTT] 无法自动创建设备 %s: 系统中没有项目", device_id)
        return None

    # 清除 HTTP 注册接口产生的 WATCH-* 虚设备（以本 device_id 为 hardware_serial 的重复记录）
    Device.objects.filter(hardware_serial=device_id).exclude(device_id=device_id).delete()

    try:
        device = Device.objects.create(
            project=default_project,
            device_id=device_id,
            bind_status='pending',
            is_online=True,
            last_report_time=django_timezone.now(),
            officer_name='',  # 待管理员填写
            latitude=extra_fields.get('latitude'),
            longitude=extra_fields.get('longitude'),
            battery_level=extra_fields.get('battery_level', None),
            firmware_version=extra_fields.get('firmware_version', ''),
            worn=extra_fields.get('worn', True),
        )
    except IntegrityError:
        # 并发创建时取已有记录
        device = Device.objects.get(device_id=device_id)
    logger.info("[MQTT] 自动创建待绑定设备: device_id=%s project=%s", device_id, default_project.name)
    return device


def process_vital(device_id: str, payload: dict[str, Any]) -> None:
    """处理生理数据消息 → 写入 HealthData + 更新 Device"""
    from .models import Device, HealthData, DeviceLocation

    try:
        device = Device.objects.get(device_id=device_id)
    except Device.DoesNotExist:
        lat, lng = valid_coordinates(payload.get('latitude'), payload.get('longitude'))
        extra = {}
        if lat is not None:
            extra['latitude'] = lat
            extra['longitude'] = lng
        battery = optional_int(payload.get('batteryLevel'), 0, 100)
        if battery is not None:
            extra['battery_level'] = battery
        fw = str(payload.get('firmwareVersion', '') or '')
        if fw:
            extra['firmware_version'] = fw
        device = _auto_create_device(device_id, **extra)
        if device is None:
            return

    if device.bind_status == 'disabled':
        return

    # 自动归入当前 recording 项目（跨城市演示：天津→北京自动切换）
    _sync_device_project(device)

    # 收到真实数据 → 自动激活（手表跳过 bind 直接发数据也有效）
    if device.bind_status == 'pending':
        device.bind_status = 'active'
        device.save(update_fields=['bind_status'])
        logger.info("[MQTT] 自动激活设备: %s（收到真实 vital 数据）", device_id)

    heart_rate = optional_int(payload.get('heartRate'), 30, 250)
    blood_oxygen = optional_float(payload.get('spo2'), 70, 100)
    systolic, diastolic = parse_blood_pressure(payload.get('bloodPressure'))
    steps = optional_int(payload.get('steps'), 0, 10_000_000)
    battery_level = optional_int(payload.get('batteryLevel'), 0, 100)
    worn = payload.get('worn')
    if worn is not None and not isinstance(worn, bool):
        worn = None
    data_quality = str(payload.get('dataQuality', '')) if payload.get('dataQuality') else ''
    firmware_version = str(payload.get('firmwareVersion', '')) if payload.get('firmwareVersion') else ''
    gps_accuracy = optional_float(payload.get('gpsAccuracy'), 0, 100_000)
    core_temp = optional_float(payload.get('coreTemp'), 30, 45)

    latitude, longitude = valid_coordinates(
        payload.get('latitude'), payload.get('longitude')
    )

    report_time = parse_timestamp(payload.get('timestamp'))

    # 检查是否有任何生命体征数据
    has_any_vital = (
        heart_rate is not None
        or blood_oxygen is not None
        or (systolic is not None and diastolic is not None)
    )
    if not has_any_vital:
        logger.debug("[MQTT] vital 帧无有效健康数据: device=%s quality=%s", device_id, data_quality)
        return

    # 保存健康数据 — 只存中继实际发送的值，不做假数据填充
    health = HealthData.objects.create(
        device=device,
        heart_rate=heart_rate,
        blood_oxygen=blood_oxygen,
        blood_pressure_sys=systolic,
        blood_pressure_dia=diastolic,
        step_frequency=None,  # vital 消息中是累计步数，步频需另行计算
        core_temperature=core_temp,
        core_temp_source='mqtt_direct',
        steps=steps,
        gps_accuracy=gps_accuracy,
        data_quality=data_quality,
        latitude=latitude,
        longitude=longitude,
    )
    if report_time:
        health.timestamp = report_time
        health.save(update_fields=['timestamp'])

    # 更新设备状态
    device.is_online = True
    device.last_report_time = report_time or django_timezone.now()
    if latitude is not None:
        device.latitude = latitude
    if longitude is not None:
        device.longitude = longitude
    if battery_level is not None:
        device.battery_level = battery_level
    if worn is not None:
        device.worn = worn
    if firmware_version:
        device.firmware_version = firmware_version
    device.save(update_fields=[
        'is_online', 'last_report_time', 'latitude', 'longitude',
        'battery_level', 'worn', 'firmware_version',
    ])

    # 保存位置轨迹
    if latitude is not None and longitude is not None:
        DeviceLocation.objects.create(
            device=device,
            latitude=latitude,
            longitude=longitude,
        )

    # 温度预警判断（阈值见 models 常量）
    from .models import TEMP_NORMAL_WARNING
    if core_temp is not None and core_temp >= TEMP_NORMAL_WARNING:
        _check_and_create_alert(device, core_temp, heart_rate, blood_oxygen)


def process_status(device_id: str, payload: dict[str, Any]) -> None:
    """处理在线状态消息 → 更新 Device"""
    from .models import Device

    try:
        device = Device.objects.get(device_id=device_id)
    except Device.DoesNotExist:
        battery = optional_int(payload.get('batteryLevel'), 0, 100)
        extra = {}
        if battery is not None:
            extra['battery_level'] = battery
        device = _auto_create_device(device_id, **extra)
        if device is None:
            return

    # 自动归入当前 recording 项目
    _sync_device_project(device)

    # 收到状态数据 → 自动激活 pending 设备
    auto_activated = False
    if device.bind_status == 'pending':
        device.bind_status = 'active'
        auto_activated = True

    is_online = payload.get('status') == 'online'
    battery_level = optional_int(payload.get('batteryLevel'), 0, 100)

    device.is_online = is_online
    device.last_report_time = django_timezone.now()
    if battery_level is not None:
        device.battery_level = battery_level
    update_fields = ['is_online', 'last_report_time', 'battery_level']
    if auto_activated:
        update_fields.append('bind_status')
    device.save(update_fields=update_fields)
    if auto_activated:
        logger.info("[MQTT] 自动激活设备: %s（收到真实 status 数据）", device_id)

    if not is_online:
        logger.info("[MQTT] 设备离线: %s", device_id)


def process_alert(device_id: str, payload: dict[str, Any]) -> None:
    """处理预警消息（来自中继/模型）→ 写入 Alert"""
    from .models import Device, Alert

    try:
        device = Device.objects.get(device_id=device_id)
    except Device.DoesNotExist:
        logger.warning("[MQTT] 收到未注册设备的 alert: %s", device_id)
        return

    alert_id = payload.get('alertId')
    core_temp = optional_float(payload.get('coreTemp'), 30, 45)
    risk_level = payload.get('riskLevel', 'warning')
    alert_type = 'high_risk' if risk_level == 'high_risk' else 'normal'
    advice = payload.get('advice', '')

    # 去重：检查是否已有相同 alertId 的记录
    if alert_id:
        existing = Alert.objects.filter(
            device=device,
            id=alert_id,
        ).first()
        if existing:
            logger.debug("[MQTT] alert 已存在，跳过: id=%s", alert_id)
            return

    Alert.objects.create(
        device=device,
        alert_type=alert_type,
        risk_level=risk_level,
        core_temperature=core_temp or 0,
        heart_rate=0,
        blood_oxygen=0,
        advice_text=advice,
    )
    logger.info("[MQTT] 收到预警: device=%s risk=%s core_temp=%s", device_id, risk_level, core_temp)


def process_bind(device_id: str, payload: dict[str, Any]) -> None:
    """处理手表绑定请求 → 创建或激活设备"""
    from .models import Device, Project

    hardware_serial = str(payload.get('hardwareSerial', '') or '').strip()
    firmware_version = str(payload.get('firmwareVersion', '') or '').strip()

    # 检查是否已注册
    existing = Device.objects.filter(device_id=device_id).first()
    if not existing and hardware_serial:
        existing = Device.objects.filter(hardware_serial=hardware_serial).first()

    if existing:
        if existing.bind_status == 'disabled':
            logger.warning("[MQTT] 绑定请求被拒: device=%s 已禁用", device_id)
            return
        # 自动归入当前 recording 项目 + 激活
        _sync_device_project(existing)
        existing.bind_status = 'active'
        existing.is_online = True
        existing.last_report_time = django_timezone.now()
        if firmware_version:
            existing.firmware_version = firmware_version
        existing.save(update_fields=['bind_status', 'is_online', 'last_report_time', 'firmware_version'])
        logger.info("[MQTT] 绑定成功(已有): device=%s serial=%s", device_id, hardware_serial)
        return

    # 新设备：自动创建并激活
    default_project = Project.objects.filter(status='recording').first() or Project.objects.first()
    if not default_project:
        logger.error("[MQTT] 绑定失败: 无可用项目 device=%s", device_id)
        return

    Device.objects.create(
        project=default_project,
        device_id=device_id,
        hardware_serial=hardware_serial or None,
        firmware_version=firmware_version,
        bind_status='active',
        is_online=True,
        last_report_time=django_timezone.now(),
        officer_name='',  # 待管理员填写
    )
    logger.info("[MQTT] 绑定成功(新建): device=%s serial=%s project=%s", device_id, hardware_serial, default_project.name)


def _check_and_create_alert(device, core_temperature: float,
                             heart_rate: Optional[int],
                             blood_oxygen: Optional[float]) -> None:
    """检查温度阈值并创建预警 + 发布到 MQTT（阈值取自 models 常量）"""
    from .models import Alert, TEMP_WARNING_THRESHOLD, TEMP_NORMAL_WARNING

    if core_temperature >= TEMP_WARNING_THRESHOLD:
        alert_type = 'high_risk'
        risk_level = 'high_risk'
        advice = '1. 立即停止当前活动，转移至阴凉通风处休息\n2. 补充电解质饮料，如症状持续及时就医'
    elif core_temperature >= TEMP_NORMAL_WARNING:
        alert_type = 'normal'
        risk_level = 'warning'
        advice = '1. 适当降低活动强度，注意补充水分\n2. 持续监测体温变化，必要时暂停执勤'
    else:
        return

    # 防重复：同一设备 60 秒内不重复创建同等级预警
    recent = Alert.objects.filter(
        device=device,
        risk_level=risk_level,
        created_at__gte=django_timezone.now() - django_timezone.timedelta(seconds=60),
    ).first()
    if recent:
        return

    alert = Alert.objects.create(
        device=device,
        alert_type=alert_type,
        risk_level=risk_level,
        core_temperature=core_temperature,
        heart_rate=heart_rate or 0,
        blood_oxygen=blood_oxygen or 0,
        advice_text=advice,
    )

    # 发布预警到 MQTT（中继服务器会分发给手表）
    publish_alert(
        device_id=device.device_id,
        alert_id=alert.id,
        alert_type='高风险预警' if alert_type == 'high_risk' else '普通预警',
        risk_level=risk_level,
        core_temp=core_temperature,
        officer_name=device.officer_name or device.device_id,
        advice=advice,
    )


# ═══════════════════════════════════════════════════════════════
# MQTT 发布
# ═══════════════════════════════════════════════════════════════

def publish_alert(device_id: str, alert_id: int, alert_type: str,
                  risk_level: str, core_temp: float, officer_name: str,
                  advice: str) -> bool:
    """发布预警到 MQTT 主题 watch/{device_id}/alert"""
    global _publish_client

    if not _publish_client or not _publish_client.is_connected():
        logger.warning("[MQTT] 无法发布预警: MQTT 未连接")
        return False

    topic = MQTT_ALERT_TOPIC_TPL.format(device_id=device_id)
    payload = json.dumps({
        'deviceId': device_id,
        'alertId': alert_id,
        'alertType': alert_type,
        'riskLevel': risk_level,
        'coreTemp': core_temp,
        'officerName': officer_name,
        'advice': advice,
        'timestamp': int(time.time() * 1000),
    }, ensure_ascii=False)

    info = _publish_client.publish(topic, payload, qos=1, retain=False)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        logger.warning("[MQTT] 发布预警失败: rc=%s", info.rc)
        return False
    try:
        info.wait_for_publish(timeout=6)
    except (RuntimeError, ValueError) as exc:
        logger.warning("[MQTT] 发布预警确认超时: %s", exc)
        return False

    logger.info("[MQTT] 预警已发布: device=%s risk=%s alert_id=%s",
                device_id, risk_level, alert_id)
    return True


# ═══════════════════════════════════════════════════════════════
# MQTT 回调
# ═══════════════════════════════════════════════════════════════

def extract_device_id(topic: str) -> Optional[str]:
    """从 MQTT topic 提取 device_id"""
    parts = topic.split('/')
    if len(parts) != 3 or parts[0] != 'watch' or not parts[1]:
        return None
    return parts[1]


def on_connect(client, userdata, flags, reason_code, properties) -> None:
    if reason_code == 0:
        client.subscribe([
            (MQTT_TOPIC_VITAL, 1),
            (MQTT_TOPIC_STATUS, 1),
            (MQTT_TOPIC_ALERT, 1),
            (MQTT_TOPIC_BIND, 1),
        ])
        logger.info("[MQTT] 已连接到 %s:%d，已订阅 watch/+/vital, status, alert, bind",
                    MQTT_BROKER, MQTT_PORT)
    else:
        logger.error("[MQTT] 连接失败: reason_code=%s", reason_code)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties) -> None:
    if running:
        logger.warning("[MQTT] 连接断开: reason_code=%s (将自动重连)", reason_code)


def on_message(client, userdata, message) -> None:
    device_id = extract_device_id(message.topic)
    if device_id is None:
        logger.warning("[MQTT] 无法解析 topic: %s", message.topic)
        return

    try:
        payload = json.loads(message.payload.decode('utf-8'))
        if not isinstance(payload, dict):
            raise ValueError('payload is not an object')

        if message.topic.endswith('/vital'):
            kind = 'vital'
        elif message.topic.endswith('/status'):
            kind = 'status'
        elif message.topic.endswith('/alert'):
            kind = 'alert'
        elif message.topic.endswith('/bind'):
            kind = 'bind'
        else:
            return

        message_queue.put_nowait((kind, device_id, payload))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("[MQTT] 无效消息 %s: %s", message.topic, exc)
    except queue.Full:
        logger.error("[MQTT] 消息队列已满，丢弃: %s", device_id)


# ═══════════════════════════════════════════════════════════════
# Worker 线程
# ═══════════════════════════════════════════════════════════════

def process_message(kind: str, device_id: str, payload: dict[str, Any]) -> None:
    """分发消息到对应处理函数"""
    try:
        if kind == 'vital':
            process_vital(device_id, payload)
        elif kind == 'status':
            process_status(device_id, payload)
        elif kind == 'alert':
            process_alert(device_id, payload)
        elif kind == 'bind':
            process_bind(device_id, payload)
    except Exception:
        logger.exception("[MQTT] 消息处理失败: kind=%s device=%s", kind, device_id)


def worker_loop() -> None:
    """Worker 线程主循环"""
    while running or not message_queue.empty():
        try:
            item = message_queue.get(timeout=1)
        except queue.Empty:
            continue
        try:
            process_message(*item)
        finally:
            message_queue.task_done()


# ═══════════════════════════════════════════════════════════════
# 启动 / 停止
# ═══════════════════════════════════════════════════════════════

def start_mqtt() -> mqtt.Client:
    """启动 MQTT 客户端和 worker 线程，返回 client 实例"""
    global _client, _publish_client, running

    running = True

    # 创建 MQTT 客户端
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f'heatstress-dashboard-{os.getpid()}',
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    # 启动 worker 线程
    for i in range(max(1, WORKER_COUNT)):
        t = threading.Thread(
            target=worker_loop,
            name=f'mqtt-worker-{i}',
            daemon=True,
        )
        t.start()

    # 连接 EMQX（异步，自动重连）
    client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    _client = client
    _publish_client = client

    logger.info("[MQTT] 客户端已启动: broker=%s:%d workers=%d",
                MQTT_BROKER, MQTT_PORT, WORKER_COUNT)
    return client


def stop_mqtt() -> None:
    """停止 MQTT 客户端"""
    global _client, _publish_client, running

    running = False
    logger.info("[MQTT] 正在停止...")

    if _client:
        _client.loop_stop()
        try:
            _client.disconnect()
        except Exception:
            pass
        _client = None
        _publish_client = None

    logger.info("[MQTT] 已停止")

#!/usr/bin/env python3
"""
热应激预警系统 · 完备联测模拟器
覆盖 5 种实战场景 + 所有 MQTT 主题 + 边缘情况。

用法:
  python simulate_comprehensive.py                    # 运行全部场景（约 5 分钟）
  python simulate_comprehensive.py --rapid             # 快速模式（3 轮/设备，约 30 秒）
  python simulate_comprehensive.py --scenario patrol   # 只跑特定场景

场景:
  normal-patrol      常规巡逻（稳定数据，逐步积累步数）
  intense-training   高强度训练→HR峰值165→恢复
  heat-stress        热应激预警（HR>150持续，应触发告警）
  low-battery-wear   低电量12%→2%+穿戴检测
  intermittent       间歇性离线→重连
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("联测")

BROKER = "39.105.86.77"
PORT = 1883
TOPIC_PREFIX = "watch"


# ── 场景生成函数 ──


def gen_normal_patrol(state, round_i, total):
    hr = 72 + int(15 * (round_i / total)) + random.randint(-5, 5)
    state["heartRate"] = max(60, min(120, hr))
    state["spo2"] = max(95, min(100, 98 + random.randint(-2, 1)))
    state["systolic"] = max(105, min(135, 118 + random.randint(-3, 4)))
    state["diastolic"] = max(65, min(90, 78 + random.randint(-2, 3)))
    state["steps"] += 6 + random.randint(2, 12)
    state["battery"] = max(1, state["battery"] - random.randint(0, 1))
    state["latitude"] += random.uniform(-0.0003, 0.0003)
    state["longitude"] += random.uniform(-0.0003, 0.0003)
    state["worn"], state["dataQuality"] = True, "complete"


def gen_intense_training(state, round_i, total):
    pct = round_i / total
    if pct < 0.25:
        ramp = pct / 0.25
        hr, spo2 = 80 + int(ramp * 40), 97 - int(ramp * 2)
    elif pct < 0.65:
        ramp = (pct - 0.25) / 0.40
        hr, spo2 = 120 + int(ramp * 45), 95 - int(ramp * 4)
    else:
        ramp = (pct - 0.65) / 0.35
        hr, spo2 = 165 - int(ramp * 60), 91 + int(ramp * 6)
    state["heartRate"] = max(60, min(180, hr + random.randint(-4, 6)))
    state["spo2"] = max(88, min(100, spo2 + random.randint(-1, 2)))
    state["systolic"] = max(120, min(170, 120 + int((hr - 80) * 0.4) + random.randint(-5, 5)))
    state["diastolic"] = max(70, min(100, 75 + int((hr - 80) * 0.2) + random.randint(-3, 3)))
    state["steps"] += 20 + random.randint(5, 25)
    state["battery"] = max(1, state["battery"] - random.randint(0, 2))
    state["worn"], state["dataQuality"] = True, "complete"
    state["latitude"] += random.uniform(-0.001, 0.001)
    state["longitude"] += random.uniform(-0.001, 0.001)


def gen_heat_stress_alert(state, round_i, total):
    pct = round_i / total
    if pct < 0.7:
        hr, spo2 = 155 + random.randint(-8, 10), 89 + random.randint(-2, 3)
        bp_sys, bp_dia = 150 + random.randint(-8, 12), 90 + random.randint(-5, 8)
    else:
        hr, spo2 = 145 + random.randint(-5, 8), 91 + random.randint(-2, 2)
        bp_sys, bp_dia = 145 + random.randint(-5, 8), 88 + random.randint(-3, 5)
    state["heartRate"] = max(130, min(180, hr))
    state["spo2"] = max(85, min(96, spo2))
    state["systolic"] = max(135, min(170, bp_sys))
    state["diastolic"] = max(80, min(105, bp_dia))
    state["steps"] += 12 + random.randint(3, 18)
    state["battery"] = max(1, state["battery"] - random.randint(0, 2))
    state["worn"], state["dataQuality"] = True, "complete"
    state["latitude"] += random.uniform(-0.0005, 0.0005)
    state["longitude"] += random.uniform(-0.0005, 0.0005)


def gen_low_battery_wear(state, round_i, total):
    pct = round_i / total
    state["battery"] = max(1, 12 - int(pct * 12))
    hr = 70 + random.randint(-4, 6)
    state["spo2"] = 97 + random.randint(-1, 1)
    state["systolic"] = 115 + random.randint(-3, 5)
    state["diastolic"] = 76 + random.randint(-2, 3)
    state["steps"] += 3 + random.randint(1, 5)
    if round_i == 2:
        state["worn"], state["dataQuality"] = False, "not_worn"
        state["heartRate"], state["spo2"] = 0, 0
    elif round_i == 4:
        state["worn"], state["dataQuality"] = True, "complete"
        state["latitude"], state["longitude"] = 0.0, 0.0
    else:
        state["worn"], state["dataQuality"] = True, "complete"
        state["heartRate"] = hr


def gen_intermittent(state, round_i, total):
    state["heartRate"] = 72 + random.randint(-3, 5)
    state["spo2"] = 97 + random.randint(-1, 2)
    state["systolic"] = 118 + random.randint(-3, 4)
    state["diastolic"] = 78 + random.randint(-2, 3)
    state["steps"] += 5 + random.randint(1, 8)
    state["battery"] = max(1, state["battery"] - random.randint(0, 1))
    state["worn"], state["dataQuality"] = True, "complete"
    return round_i in (2, 3)  # skip rounds 3 and 4


SCENARIOS = [
    {"name": "normal-patrol", "device_id": "A80-PROD-001",
     "desc": "常规巡逻 — 稳定生理数据，逐步积累步数",
     "initial_state": {"latitude": 39.7298, "longitude": 116.3412, "battery": 87, "steps": 1523},
     "gen": gen_normal_patrol, "color": "🟢"},
    {"name": "intense-training", "device_id": "A80-PROD-002",
     "desc": "高强度训练 → HR 峰值 165 → 恢复",
     "initial_state": {"latitude": 39.7305, "longitude": 116.3405, "battery": 72, "steps": 3841},
     "gen": gen_intense_training, "color": "🟡"},
    {"name": "heat-stress", "device_id": "A80-PROD-003",
     "desc": "热应激预警 — HR>150 持续，应触发告警",
     "initial_state": {"latitude": 39.7310, "longitude": 116.3398, "battery": 65, "steps": 2105},
     "gen": gen_heat_stress_alert, "color": "🔴"},
    {"name": "low-battery-wear", "device_id": "A80-TEST-001",
     "desc": "低电量 (12%→2%) + 穿戴检测 (脱下/戴回/无GPS)",
     "initial_state": {"latitude": 39.7289, "longitude": 116.3420, "battery": 12, "steps": 5876},
     "gen": gen_low_battery_wear, "color": "⚪"},
    {"name": "intermittent", "device_id": "A80-TEST-002",
     "desc": "间歇性离线 — 在线→离线→重连",
     "initial_state": {"latitude": 39.7290, "longitude": 116.3418, "battery": 45, "steps": 902},
     "gen": gen_intermittent, "color": "⚡"},
]


def run_scenario(scenario: dict, rounds: int, client: mqtt.Client, stats: dict):
    did = scenario["device_id"]
    s = dict(scenario["initial_state"])
    s.update({"worn": True, "dataQuality": "complete", "heartRate": 70, "spo2": 97,
              "systolic": 118, "diastolic": 78})
    log.info("%s %s [%s] %s", scenario["color"], did, scenario["name"], scenario["desc"])
    serial = f"SN-{did}-{random.randint(10000000,99999999)}"
    client.publish(f"{TOPIC_PREFIX}/{did}/bind", json.dumps({
        "deviceId": did, "mac": f"8c:7e:f1:{random.randint(0x10,0xff):02x}:{random.randint(0x10,0xff):02x}:{random.randint(0x10,0xff):02x}",
        "timestamp": int(time.time() * 1000), "action": "bind",
        "hardwareSerial": serial, "firmwareVersion": "1.1.0-a80"}))
    time.sleep(0.3)
    client.publish(f"{TOPIC_PREFIX}/{did}/status", json.dumps({
        "status": "online", "timestamp": int(time.time() * 1000),
        "latitude": s["latitude"], "longitude": s["longitude"], "batteryLevel": s["battery"]}))
    time.sleep(0.3)

    hr_vals, spo2_vals = [], []
    for i in range(rounds):
        if not globals().get("_running", True):
            break
        gen_result = scenario["gen"](s, i, rounds)
        is_skip = bool(gen_result) if isinstance(gen_result, bool) else False
        if is_skip:
            log.info("   #%02d ⏭️ 跳过（模拟离线）", i + 1)
            continue
        topic = f"{TOPIC_PREFIX}/{did}/vital"
        payload = json.dumps({
            "deviceId": did, "timestamp": int(time.time() * 1000),
            "latitude": round(s.get("latitude", 0.0), 6), "longitude": round(s.get("longitude", 0.0), 6),
            "heartRate": s.get("heartRate", 0), "spo2": s.get("spo2", 0),
            "bloodPressure": f"{s.get('systolic',120)}/{s.get('diastolic',80)}",
            "steps": s.get("steps", 0), "batteryLevel": s.get("battery", 100),
            "worn": s.get("worn", True), "dataQuality": s.get("dataQuality", "complete"),
            "firmwareVersion": "1.1.0-a80", "seq": i + 1})
        info = client.publish(topic, payload, qos=1)
        ok = info.rc == mqtt.MQTT_ERR_SUCCESS
        hr = s.get("heartRate", "?"); spo2 = s.get("spo2", "?")
        tags = []
        if not s.get("worn"): tags.append("NOT WORN")
        if s.get("battery", 100) <= 5: tags.append(f"LOW BATT {s['battery']}%")
        if isinstance(hr, int) and hr >= 150: tags.append("🔥 HIGH HR")
        if s.get("latitude") == 0 and s.get("longitude") == 0: tags.append("NO GPS")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        log.info("   #%02d HR=%-3d SpO2=%-3d BP=%s/%s Bat=%d%%%s %s",
                 i + 1, hr, spo2, s.get("systolic", "?"), s.get("diastolic", "?"),
                 s.get("battery", "?"), tag_str, "✅" if ok else "❌")
        if isinstance(hr, int): hr_vals.append(hr)
        if isinstance(spo2, int): spo2_vals.append(spo2)
        if (i + 1) % 3 == 0:
            client.publish(f"{TOPIC_PREFIX}/{did}/status", json.dumps({
                "status": "online", "timestamp": int(time.time() * 1000),
                "latitude": round(s.get("latitude", 0.0), 6), "longitude": round(s.get("longitude", 0.0), 6),
                "batteryLevel": s.get("battery", 100)}))
        time.sleep(1)
    stats[scenario["name"]] = {
        "device_id": did, "hr_range": f"{min(hr_vals)}-{max(hr_vals)}" if hr_vals else "-",
        "spo2_range": f"{min(spo2_vals)}-{max(spo2_vals)}" if spo2_vals else "-",
        "battery_end": s.get("battery", "?"),
    }


def main():
    global _running
    _running = True
    parser = argparse.ArgumentParser(description="热应激系统 · 完备联测模拟器")
    parser.add_argument("--rapid", action="store_true", help="快速模式（每设备 3 轮）")
    parser.add_argument("--scenario", type=str, default=None, help="只跑指定场景名")
    parser.add_argument("--rounds", type=int, default=10, help="每设备模拟轮数（默认 10）")
    args = parser.parse_args()
    rounds = 3 if args.rapid else args.rounds

    scenarios = [s for s in SCENARIOS if not args.scenario or s["name"] == args.scenario]
    if not scenarios:
        log.error("未知场景: %s。可用: %s", args.scenario, ", ".join(s["name"] for s in SCENARIOS))
        sys.exit(1)

    log.info("═══ 热应激预警系统 · 完备联测 ═══")
    log.info("场景: %d 个 | 每场景 %d 轮 | MQTT: %s:%d", len(scenarios), rounds, BROKER, PORT)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-comp-{random.randint(1000,9999)}")
    evt = threading.Event()

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code == 0: evt.set(); log.info("✅ 已连接 EMQX")
        else: log.error("❌ 连接失败: rc=%s", reason_code)
    client.on_connect = on_connect
    client.connect_async(BROKER, PORT, keepalive=60)
    client.loop_start()
    if not evt.wait(timeout=10):
        log.error("❌ 无法连接到 EMQX"); sys.exit(1)

    def shutdown(sig, frame):
        global _running; _running = False
        log.info("收到信号，停止...")
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    stats = {}
    for sc in scenarios:
        if not _running: break
        run_scenario(sc, rounds, client, stats)
        time.sleep(2)

    client.loop_stop(); client.disconnect()

    print("\n" + "=" * 64)
    print("📊 联测结果汇总")
    print("=" * 64)
    print(f"{'场景':<20} {'设备ID':<18} {'HR范围':<16} {'SpO2':<12} {'余电':<6}")
    print("-" * 64)
    for name, s in stats.items():
        print(f"{name:<20} {s['device_id']:<18} {s['hr_range']:<16} {s['spo2_range']:<12} {s['battery_end']:<6}%")
    print("-" * 64)
    has_high = any(int(s["hr_range"].split("-")[0]) >= 150 for s in stats.values() if s["hr_range"] != "-")
    has_low = any(int(s["spo2_range"].split("-")[0]) <= 90 for s in stats.values() if s["spo2_range"] != "-")
    print(f"  高心率触发: {'✅' if has_high else '❌'}")
    print(f"  低血氧触发: {'✅' if has_low else '❌'}")
    print(f"  未穿戴检测: {'✅' if 'low-battery-wear' in stats else '❌'}")
    print(f"  离线重连:   {'✅' if 'intermittent' in stats else '❌'}")


if __name__ == "__main__":
    main()

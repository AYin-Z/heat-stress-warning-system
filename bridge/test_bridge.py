import time
import unittest

import bridge


class BridgeContractTest(unittest.TestCase):
    def setUp(self):
        bridge.registry = bridge.DeviceRegistry()
        bridge.registry.update(
            "UNIT-A80",
            api_device_id="WATCH-UNIT",
            bind_status="active",
        )
        self.calls = []
        self.original_upload = bridge.api.upload
        self.original_acknowledge = bridge.api.acknowledge
        self.original_publish_alert = bridge.publish_alert
        self.original_mqtt_publish = bridge.mqtt_client.publish
        bridge.api.upload = self.capture_upload

    def tearDown(self):
        bridge.api.upload = self.original_upload
        bridge.api.acknowledge = self.original_acknowledge
        bridge.publish_alert = self.original_publish_alert
        bridge.mqtt_client.publish = self.original_mqtt_publish

    def capture_upload(self, device_id, **values):
        self.calls.append((device_id, values))
        return {"ok": True}

    def test_missing_values_are_not_replaced_with_defaults(self):
        bridge.forward_vital(
            "UNIT-A80",
            {"steps": 10, "dataQuality": "not_worn"},
        )
        self.assertEqual([], self.calls)

    def test_complete_valid_frame_is_forwarded(self):
        bridge.forward_vital(
            "UNIT-A80",
            {
                "heartRate": 88,
                "spo2": 97,
                "bloodPressure": "126/82",
                "coreTemp": 37.2,
                "steps": 12,
                "timestamp": int(time.time() * 1000),
            },
        )
        self.assertEqual(1, len(self.calls))
        _, values = self.calls[0]
        self.assertEqual(88, values["heart_rate"])
        self.assertEqual(37.2, values["core_temperature"])
        self.assertIsNone(values["latitude"])

    def test_invalid_sentinels_are_filtered(self):
        self.assertEqual((None, None), bridge.parse_blood_pressure(None))
        self.assertEqual((120, 80), bridge.parse_blood_pressure("120/80"))
        self.assertIsNone(bridge.optional_int({"heartRate": 0}, "heartRate", 30, 250))
        self.assertEqual(
            (None, None),
            bridge.valid_coordinates({"latitude": 0, "longitude": 0}),
        )
        self.assertIsNone(bridge.iso_timestamp({"timestamp": 1325376000000}))

    def test_failed_alert_publish_is_retried(self):
        publish_results = iter([False, True])
        publish_calls = []
        acknowledge_calls = []
        bridge.publish_alert = lambda mqtt_id, alert: (
            publish_calls.append(alert["id"]) or next(publish_results)
        )
        bridge.api.acknowledge = lambda device_id, alert_id: (
            acknowledge_calls.append(alert_id) or {"ok": True}
        )
        alert = {"id": 41, "risk_level": "high_risk"}

        bridge.deliver_alert("UNIT-A80", "WATCH-UNIT", alert)
        bridge.deliver_alert("UNIT-A80", "WATCH-UNIT", alert)
        bridge.deliver_alert("UNIT-A80", "WATCH-UNIT", alert)

        self.assertEqual([41, 41], publish_calls)
        self.assertEqual([41], acknowledge_calls)

    def test_acknowledgement_retry_does_not_duplicate_publish(self):
        publish_calls = []
        acknowledge_results = iter([{"ok": False}, {"ok": True}])
        acknowledge_calls = []
        bridge.publish_alert = lambda mqtt_id, alert: publish_calls.append(alert["id"]) or True
        bridge.api.acknowledge = lambda device_id, alert_id: (
            acknowledge_calls.append(alert_id) or next(acknowledge_results)
        )
        alert = {"id": 42, "risk_level": "high_risk"}

        bridge.deliver_alert("UNIT-A80", "WATCH-UNIT", alert)
        bridge.deliver_alert("UNIT-A80", "WATCH-UNIT", alert)
        bridge.deliver_alert("UNIT-A80", "WATCH-UNIT", alert)

        self.assertEqual([42], publish_calls)
        self.assertEqual([42, 42], acknowledge_calls)

    def test_time_sync_uses_qos_one_and_current_server_time(self):
        calls = []

        class PublishResult:
            rc = bridge.mqtt.MQTT_ERR_SUCCESS

            def wait_for_publish(self, timeout):
                self.timeout = timeout

            def is_published(self):
                return True

        bridge.mqtt_client.publish = lambda topic, payload, qos, retain: (
            calls.append((topic, payload, qos, retain)) or PublishResult()
        )
        before = int(time.time() * 1000)

        self.assertTrue(bridge.publish_time_sync("UNIT-A80"))

        after = int(time.time() * 1000)
        topic, payload_text, qos, retain = calls[0]
        payload = __import__("json").loads(payload_text)
        self.assertEqual("watch/UNIT-A80/time", topic)
        self.assertEqual("heatstress-bridge", payload["source"])
        self.assertTrue(before <= payload["timestamp"] <= after)
        self.assertEqual(1, qos)
        self.assertFalse(retain)


if __name__ == "__main__":
    unittest.main()

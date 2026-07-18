"""bind topic 新增功能的单元测试。"""
import json
import unittest

import bridge


class BindTopicTest(unittest.TestCase):
    def setUp(self):
        bridge.registry = bridge.DeviceRegistry()
        self.register_calls = []
        self.original_register = bridge.api.register_device
        bridge.api.register_device = self.capture_register

    def tearDown(self):
        bridge.api.register_device = self.original_register

    def capture_register(self, hardware_serial, firmware_version=""):
        self.register_calls.append((hardware_serial, firmware_version))
        return {"ok": True, "device_id": "WATCH-TEST-01", "bind_status": "active"}

    # ── forward_bind ──
    def test_bind_creates_device_with_hardware_serial(self):
        bridge.forward_bind("A80-abc123", {
            "deviceId": "A80-abc123",
            "hardwareSerial": "SN-A80-82432237337554",
            "firmwareVersion": "1.1.0-a80",
        })
        self.assertEqual(1, len(self.register_calls))
        hw, fw = self.register_calls[0]
        self.assertEqual("SN-A80-82432237337554", hw)
        self.assertEqual("1.1.0-a80", fw)

        state = bridge.registry.get_or_create("A80-abc123")
        self.assertEqual("WATCH-TEST-01", state.api_device_id)
        self.assertEqual("active", state.bind_status)
        self.assertTrue(state.registered)

    def test_bind_falls_back_to_device_id_when_no_hardware_serial(self):
        bridge.forward_bind("A80-no-hw", {
            "deviceId": "A80-no-hw",
        })
        self.assertEqual(1, len(self.register_calls))
        hw, fw = self.register_calls[0]
        self.assertEqual("A80-no-hw", hw)  # fallback to deviceId
        self.assertEqual("", fw)

    def test_bind_skip_if_already_bound(self):
        bridge.registry.update("A80-bound", api_device_id="WATCH-EXIST", bind_status="active")
        bridge.forward_bind("A80-bound", {
            "deviceId": "A80-bound",
            "hardwareSerial": "SN-DUPLICATE",
        })
        self.assertEqual(0, len(self.register_calls))

    # ── on_message 路由 ──
    def test_on_message_routes_bind_topic(self):
        """模拟 MQTT bind 消息的 topic 路由。"""
        # 构造一个 fake message 对象
        class FakeMessage:
            topic = "watch/A80-bind-test/bind"
            payload = json.dumps({
                "deviceId": "A80-bind-test",
                "hardwareSerial": "SN-ROUTE-TEST",
            }).encode()

        bridge.on_message(None, None, FakeMessage())
        # 消息应进入队列并被 process_message 处理
        # 我们 drain 队列来看 forward_bind 是否被调用
        from queue import Empty
        processed = False
        while not bridge.message_queue.empty():
            try:
                kind, device_id, payload = bridge.message_queue.get_nowait()
                bridge.process_message(kind, device_id, payload)
                processed = True
            except Empty:
                break
        self.assertTrue(processed)
        self.assertEqual(1, len(self.register_calls))
        hw, _ = self.register_calls[0]
        self.assertEqual("SN-ROUTE-TEST", hw)

    # ── process_message 不阻塞 bind 后的正常流 ──
    def test_bind_then_vital_flows(self):
        """绑定后 vital 数据正常流转。"""
        bridge.forward_bind("A80-flow", {
            "deviceId": "A80-flow",
            "hardwareSerial": "SN-FLOW",
        })
        # 模拟 register API 已返回 device_id
        self.assertEqual("WATCH-TEST-01", bridge.registry.get_or_create("A80-flow").api_device_id)

        # 替换 upload 来验证 vital 被转发
        upload_calls = []
        saved_upload = bridge.api.upload
        bridge.api.upload = lambda device_id, **kw: upload_calls.append((device_id, kw)) or {"ok": True}

        bridge.forward_vital("A80-flow", {
            "heartRate": 80,
            "timestamp": 1784266823680,
        })
        self.assertEqual(1, len(upload_calls))

        bridge.api.upload = saved_upload


if __name__ == "__main__":
    unittest.main()

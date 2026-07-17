from datetime import datetime, timezone
import unittest

try:
    from app.service import ThermalService
except ModuleNotFoundError as exc:
    if exc.name != "redis":
        raise
    ThermalService = None


class FakeModel:
    ready = True
    error = None
    version = "test-model1"
    config = {"seq_len": 20}

    def __init__(self):
        self.values = None
        self.timestamps = None

    def predict(self, values, timestamps):
        self.values = values
        self.timestamps = timestamps
        return [37.456, 37.5]


class WindowServiceTests(unittest.TestCase):
    @unittest.skipIf(ThermalService is None, "redis client is installed in the Docker image")
    def test_complete_window_runs_model1_immediately(self):
        service = ThermalService.__new__(ThermalService)
        service.model1 = FakeModel()
        result = service.estimate_hr_window(
            [80 + index for index in range(20)],
            datetime(2026, 7, 17, 10, 19, 45, tzinfo=timezone.utc),
        )
        self.assertEqual(result["core_temperature"], 37.456)
        self.assertEqual(result["source"], "informer_model_1")
        self.assertEqual(result["window_size"], 20)
        self.assertEqual(service.model1.values.shape, (20, 1))
        self.assertEqual(service.model1.timestamps[0].minute, 0)
        self.assertEqual(service.model1.timestamps[-1].minute, 19)


if __name__ == "__main__":
    unittest.main()

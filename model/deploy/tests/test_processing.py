from datetime import datetime, timezone
import unittest

from app.processing import append_raw_and_aggregate, aggregate_minute, kalman_step, to_sample
from app.schemas import HeartRateWindowRequest, WatchUpload


class ProcessingTests(unittest.TestCase):
    def test_same_minute_is_aggregated(self):
        first = to_sample(WatchUpload(timestamp=datetime(2026, 7, 15, 10, 0, 5, tzinfo=timezone.utc), heart_rate=80))
        second = to_sample(WatchUpload(timestamp=datetime(2026, 7, 15, 10, 0, 45, tzinfo=timezone.utc), heart_rate=100))
        values = aggregate_minute([], first)
        values = aggregate_minute(values, second)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0].heart_rate, 90)

    def test_skin_alias(self):
        sample = to_sample(WatchUpload(skin_temperatures={"wrist": 35.2, "chest": 34.8}))
        self.assertEqual(sample.skin_temperatures, {"Hand": 35.2, "Chest": 34.8})

    def test_three_raw_values_have_true_median(self):
        raw = []
        minutes = []
        for second, heart_rate in ((5, 80), (25, 100), (45, 120)):
            sample = to_sample(WatchUpload(
                timestamp=datetime(2026, 7, 15, 10, 0, second, tzinfo=timezone.utc),
                heart_rate=heart_rate,
            ))
            raw, minutes = append_raw_and_aggregate(raw, sample)
        self.assertEqual(minutes[0].heart_rate, 100)

    def test_kalman_stays_in_physical_range(self):
        value, variance = kalman_step(90, 37.0, 0.0)
        self.assertGreaterEqual(value, 35)
        self.assertLessEqual(value, 43)
        self.assertGreaterEqual(variance, 0)

    def test_window_requires_exactly_twenty_values(self):
        with self.assertRaises(ValueError):
            HeartRateWindowRequest(
                device_id="WATCH-TEST",
                heart_rates=[90] * 19,
                timestamp=datetime(2026, 7, 17, tzinfo=timezone.utc),
            )

    def test_window_rejects_invalid_heart_rate(self):
        with self.assertRaises(ValueError):
            HeartRateWindowRequest(
                device_id="WATCH-TEST",
                heart_rates=[90] * 19 + [300],
                timestamp=datetime(2026, 7, 17, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from data import SKIN_COLUMNS, mean_skin, watch_payload
from kalman import KalmanCoreEstimator, kalman_filter


class PipelineBasicsTest(unittest.TestCase):
    def test_mean_skin_weights(self):
        row = {key: 35.0 for key in SKIN_COLUMNS}
        self.assertAlmostEqual(mean_skin(row), 35.0)

    def test_kalman_batch_matches_stream(self):
        heart_rates = [80.0, 81.0, 85.0]
        stream = KalmanCoreEstimator(temperature=37.0)
        self.assertEqual(kalman_filter(heart_rates, 37.0), [stream.update(x) for x in heart_rates])

    def test_watch_payload_has_model_inputs(self):
        row = {key: 35.0 for key in SKIN_COLUMNS}
        row.update(HR=90.0, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
        payload = watch_payload(row)
        self.assertEqual(payload["heart_rate"], 90)
        self.assertNotIn("skin_temperatures", payload)
        extended = watch_payload(row, include_skin=True)
        self.assertEqual(set(extended["skin_temperatures"]), {x.lower() for x in SKIN_COLUMNS})

    def test_config_checkpoint_layout(self):
        config = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
        self.assertTrue((ROOT / config["model1"]["checkpoint"]).is_file())
        for target in config["model2"]["targets"]:
            matches = list((ROOT / config["model2"]["checkpoint_root"]).glob(f"*tg{target}_*/checkpoint.pth"))
            self.assertEqual(len(matches), 1, (target, matches))


if __name__ == "__main__":
    unittest.main()

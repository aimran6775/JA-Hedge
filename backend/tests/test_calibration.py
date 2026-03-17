"""
Tests for CalibrationTracker — calibration math, ECE, serialization.
"""

import pytest
import numpy as np

from app.ai.models import CalibrationTracker


class TestCalibrationTracker:
    """Core CalibrationTracker unit tests."""

    def test_not_ready_until_min_samples(self, calibration_tracker: CalibrationTracker):
        for i in range(29):
            calibration_tracker.record(0.5, i % 2)
        assert not calibration_tracker.is_ready
        calibration_tracker.record(0.5, 1)
        assert calibration_tracker.is_ready

    def test_calibrate_returns_raw_when_not_ready(self, calibration_tracker: CalibrationTracker):
        calibration_tracker.record(0.7, 1)  # only 1 sample
        assert calibration_tracker.calibrate(0.7) == 0.7

    def test_calibrate_blends_toward_actual_rate(self, calibration_tracker_ready: CalibrationTracker):
        ct = calibration_tracker_ready
        # Bin 7 (0.7-0.8): 20 samples, 70% positive (actual_rate = 0.70)
        result = ct.calibrate(0.72)
        # adjusted = 0.72 + blend * (0.70 - 0.72)
        # blend = min(20/40, 0.7) = 0.5
        # adjusted = 0.72 + 0.5 * (-0.02) = 0.71
        assert abs(result - 0.71) < 0.01

    def test_calibrate_does_not_use_bin_center(self, calibration_tracker_ready: CalibrationTracker):
        ct = calibration_tracker_ready
        # If the bug returned, it would blend toward (actual_rate - bin_center)
        # bin_center for 7 = 0.75, actual_rate = 0.70
        # BAD: 0.72 + 0.5 * (0.70 - 0.75) = 0.72 - 0.025 = 0.695
        # GOOD: 0.72 + 0.5 * (0.70 - 0.72) = 0.72 - 0.01 = 0.71
        result = ct.calibrate(0.72)
        assert result > 0.70, f"calibrate used bin_center not prob: {result}"

    def test_ece_uses_avg_prediction_not_bin_center(self):
        ct = CalibrationTracker()
        for _ in range(30):
            ct.record(0.60, 1)  # all YES in bin 6
        ct._recompute_ece()
        # avg_pred = 0.60, actual_rate = 1.0 → ECE = |1.0 - 0.60| = 0.40
        # (bug would use bin_center 0.65 → ECE = 0.35)
        assert abs(ct.expected_calibration_error - 0.40) < 0.01

    def test_expected_error_uses_avg_prediction(self, calibration_tracker_ready: CalibrationTracker):
        ct = calibration_tracker_ready
        err = ct.expected_error(0.75)
        # Bin 7: avg_pred ~= 0.75, actual_rate = 0.70
        # error = |0.70 - 0.75| = 0.05
        assert abs(err - 0.05) < 0.02

    def test_bin_pred_sum_serialization(self, calibration_tracker_ready: CalibrationTracker):
        ct = calibration_tracker_ready
        d = ct.to_dict()
        assert "bin_pred_sum" in d
        ct2 = CalibrationTracker.from_dict(d)
        assert ct2._total_samples == ct._total_samples
        np.testing.assert_array_almost_equal(ct2._bin_pred_sum, ct._bin_pred_sum)
        np.testing.assert_array_equal(ct2._bin_counts, ct._bin_counts)

    def test_calibrate_clamps_output(self):
        ct = CalibrationTracker()
        # Fill a bin to make it ready with extreme actual_rate
        for _ in range(40):
            ct.record(0.95, 1)  # bin 9, 100% positive
        result = ct.calibrate(0.95)
        assert 0.01 <= result <= 0.99

    def test_summary_returns_expected_keys(self, calibration_tracker_ready: CalibrationTracker):
        summary = calibration_tracker_ready.summary()
        assert "total_samples" in summary
        assert "bins_populated" in summary
        assert "ece" in summary
        assert "is_ready" in summary
        assert "bin_details" in summary
        assert len(summary["bin_details"]) == 10

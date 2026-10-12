"""Detector tests on SIMULATED data.

These check the detector logic (calibration, threshold, hysteresis). They say nothing about how
well it works on real CSI: that has to be measured on the ESP32 hardware.
"""
import numpy as np

from csi_motion.csi import lltf_amplitude
from csi_motion.detector import MotionDetector, pearson
from csi_motion.source import SimulatedSource


def run(sim, detector):
    out = []
    for p in sim.packets():
        t = p.id / sim.rate_hz
        out.append((t, detector.update(lltf_amplitude(p), p.timestamp_us)))
    return out


def test_pearson():
    a = np.array([1.0, 2.0, 3.0, 4.0])
    assert abs(pearson(a, a * 2 + 5) - 1.0) < 1e-6
    assert abs(pearson(a, -a) + 1.0) < 1e-6
    assert pearson(np.ones(4), a) == 1.0  # constant vector: treated as "no change"


def test_calibration_then_detection():
    sim = SimulatedSource(realtime=False, max_packets=3600)  # 36 s = 3 x (8 s still + 4 s moving)
    results = run(sim, MotionDetector(baseline_seconds=5.0))

    assert all(r.calibrating and not r.moving for t, r in results if t < 4.5)
    assert all(r.threshold is not None for t, r in results if t > 6.0)

    def in_transition(t):
        phase = t % 12.0
        return phase < 1.5 or 8.0 <= phase < 9.0  # settle time after each boundary

    still = [r for t, r in results if t > 6.0 and sim.is_moving(t) is False and not in_transition(t)]
    moving = [r for t, r in results if t > 6.0 and sim.is_moving(t) and not in_transition(t)]
    assert len(still) > 500 and len(moving) > 300
    assert sum(r.moving for r in still) / len(still) < 0.02  # false alarms
    assert sum(r.moving for r in moving) / len(moving) > 0.9  # detections


def test_restart_calibration_clears_state():
    sim = SimulatedSource(realtime=False, max_packets=1000)
    det = MotionDetector(baseline_seconds=2.0)
    run(sim, det)
    assert not det.calibrating
    det.restart_calibration()
    assert det.calibrating


def test_timestamp_wraparound_does_not_break_calibration_timer():
    det = MotionDetector(baseline_seconds=1.0, window=10, lag=2)
    rng = np.random.default_rng(0)
    base = np.linspace(10, 30, 51)
    t = 2**32 - 300_000  # wraps after 0.3 s
    for i in range(300):
        det.update(base + rng.normal(0, 0.1, 51), (t + i * 10_000) & 0xFFFFFFFF)
    assert not det.calibrating

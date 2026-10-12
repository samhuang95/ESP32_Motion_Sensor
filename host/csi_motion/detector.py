"""Motion detector based on how fast the CSI amplitude pattern changes.

Per packet the amplitude vector over the used subcarriers is normalised (see csi.normalize).
The change score of a packet is 1 - Pearson correlation with the packet `lag` samples earlier.
The motion score is the mean change score over the last `window` packets.

When nobody moves the pattern is stable and the score stays near the receiver-noise floor.
A person moving inside the sensing area makes the reflections change, which lowers the
correlation and raises the score.

The threshold is learned during a calibration phase while the area is still:
threshold = mean + k * std of the scores seen while calibrating. Calibration length is measured
with the receiver's own packet timestamps, so it does not depend on the PC's timing.

This detects *movement*. A person standing perfectly still is not reported as motion.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

import numpy as np

from .csi import normalize


@dataclass(frozen=True)
class MotionResult:
    score: float
    threshold: Optional[float]  # None while calibrating
    moving: bool
    calibrating: bool
    calibration_progress: float  # 0..1


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-9:
        return 1.0
    return float(np.dot(a, b) / denom)


class MotionDetector:
    def __init__(
        self,
        window: int = 50,
        lag: int = 5,
        baseline_seconds: float = 5.0,
        k: float = 6.0,
        hold_packets: int = 50,
    ) -> None:
        self.window = window
        self.lag = lag
        self.baseline_us = int(baseline_seconds * 1e6)
        self.k = k
        self.hold_packets = hold_packets
        self.restart_calibration()

    def restart_calibration(self) -> None:
        self._vectors: Deque[np.ndarray] = deque(maxlen=self.lag + 1)
        self._changes: Deque[float] = deque(maxlen=self.window)
        self._calib_scores: List[float] = []
        self._elapsed_us = 0
        self._last_ts: Optional[int] = None
        self._baseline: Optional[Tuple[float, float]] = None  # (threshold_on, threshold_off)
        self._moving = False
        self._quiet_count = 0

    @property
    def calibrating(self) -> bool:
        return self._baseline is None

    def update(self, amplitude: np.ndarray, timestamp_us: int) -> MotionResult:
        if self._last_ts is not None:
            dt = (timestamp_us - self._last_ts) & 0xFFFFFFFF
            if dt < 1_000_000:  # ignore gaps (sender restart, wrap-around glitches)
                self._elapsed_us += dt
        self._last_ts = timestamp_us

        vec = normalize(amplitude)
        if len(self._vectors) == self._vectors.maxlen:
            self._changes.append(1.0 - pearson(vec, self._vectors[0]))
        self._vectors.append(vec)

        score = float(np.mean(self._changes)) if self._changes else 0.0
        window_full = len(self._changes) == self.window

        if self._baseline is None:
            if window_full:
                self._calib_scores.append(score)
            if self._elapsed_us >= self.baseline_us and len(self._calib_scores) >= self.window:
                self._finish_calibration()
            progress = min(1.0, self._elapsed_us / max(1, self.baseline_us))
            if self._baseline is None:
                return MotionResult(score, None, False, True, progress)

        thr_on, thr_off = self._baseline
        if score > thr_on:
            self._moving = True
            self._quiet_count = 0
        elif self._moving:
            self._quiet_count = self._quiet_count + 1 if score < thr_off else 0
            if self._quiet_count >= self.hold_packets:
                self._moving = False
                self._quiet_count = 0
        return MotionResult(score, thr_on, self._moving, False, 1.0)

    def _finish_calibration(self) -> None:
        scores = np.asarray(self._calib_scores)
        mean, std = float(scores.mean()), float(scores.std())
        margin = self.k * max(std, 0.1 * mean, 1e-4)
        self._baseline = (mean + margin, mean + 0.5 * margin)

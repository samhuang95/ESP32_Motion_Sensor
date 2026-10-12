"""Live matplotlib view: amplitude heatmap + motion score."""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional

import numpy as np

from .csi import N_USED, lltf_amplitude, normalize
from .detector import MotionDetector, MotionResult
from .protocol import CsiPacket

HEATMAP_COLUMNS = 300
SCORE_COLUMNS = 600


class LiveView:
    """Feeds packets through the detector and draws the result.

    Plot text is English on purpose: matplotlib's default font has no CJK glyphs.
    """

    def __init__(self, detector: MotionDetector, title: str) -> None:
        import matplotlib.pyplot as plt

        self.detector = detector
        self.fig, (self.ax_map, self.ax_score) = plt.subplots(
            2, 1, figsize=(10, 7), gridspec_kw={"height_ratios": [3, 2]}
        )
        self.fig.suptitle(title)

        self._vectors: Deque[np.ndarray] = deque(maxlen=HEATMAP_COLUMNS)
        self._scores: Deque[float] = deque(maxlen=SCORE_COLUMNS)
        self._thresholds: Deque[float] = deque(maxlen=SCORE_COLUMNS)
        self.last_result: Optional[MotionResult] = None
        self.packets_seen = 0

        self.image = self.ax_map.imshow(
            np.zeros((N_USED, HEATMAP_COLUMNS)),
            aspect="auto",
            origin="lower",
            cmap="coolwarm",
            vmin=-0.3,
            vmax=0.3,
            interpolation="nearest",
        )
        self.ax_map.set_ylabel("subcarrier (index in used set)")
        self.ax_map.set_title("Normalised amplitude minus its median (static background removed)")
        self.score_line, = self.ax_score.plot([], [], lw=1.5, label="motion score")
        self.threshold_line, = self.ax_score.plot([], [], "--", lw=1, label="threshold")
        self.ax_score.set_xlim(0, SCORE_COLUMNS)
        self.ax_score.set_ylabel("score")
        self.ax_score.set_xlabel("packets (newest on the right)")
        self.ax_score.legend(loc="upper right")
        self.status = self.ax_score.text(
            0.02, 0.88, "", transform=self.ax_score.transAxes, fontsize=16, weight="bold"
        )
        self.fig.tight_layout()

    def process(self, packet: CsiPacket) -> None:
        amplitude = lltf_amplitude(packet)
        if amplitude is None:
            return
        result = self.detector.update(amplitude, packet.timestamp_us)
        self._vectors.append(normalize(amplitude))
        self._scores.append(result.score)
        self._thresholds.append(result.threshold if result.threshold is not None else np.nan)
        self.last_result = result
        self.packets_seen += 1

    def restart_calibration(self) -> None:
        self.detector.restart_calibration()

    def render(self) -> None:
        if not self._vectors:
            return
        data = np.array(self._vectors).T  # (subcarriers, time)
        data = data - np.median(data, axis=1, keepdims=True)
        padded = np.zeros((N_USED, HEATMAP_COLUMNS))
        padded[:, HEATMAP_COLUMNS - data.shape[1]:] = data
        self.image.set_data(padded)

        scores = np.array(self._scores)
        thresholds = np.array(self._thresholds)
        x = np.arange(SCORE_COLUMNS - len(scores), SCORE_COLUMNS)
        self.score_line.set_data(x, scores)
        self.threshold_line.set_data(x, thresholds)
        top = max(float(scores.max()), float(np.nanmax(thresholds)) if np.isfinite(thresholds).any() else 0.0)
        self.ax_score.set_ylim(0, max(top * 1.2, 1e-3))

        result = self.last_result
        if result is None:
            return
        if result.calibrating:
            self.status.set_text(f"CALIBRATING {result.calibration_progress * 100:.0f}% - stay out of the area")
            self.status.set_color("tab:orange")
        elif result.moving:
            self.status.set_text("MOTION")
            self.status.set_color("tab:red")
        else:
            self.status.set_text("IDLE")
            self.status.set_color("tab:green")

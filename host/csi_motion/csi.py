"""CSI amplitude extraction.

The firmware captures the legacy long training field (LLTF) of 20 MHz packets: 64 subcarriers,
stored as (imaginary, real) int8 pairs in the order 0..31, -32..-1 (ESP-IDF Wi-Fi guide,
"Wi-Fi Channel State Information"). Only subcarriers -26..-1 and 1..26 carry signal.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .protocol import CsiPacket

LLTF_VALUES = 128  # 64 subcarriers x (imag, real)
SUBCARRIER_INDEX = np.r_[0:32, -32:0]

# Used subcarriers: -26..-1 and 2..26. Subcarrier 0 is the DC null; subcarrier 1 is dropped
# as well because the ESP32 marks the first 4 CSI bytes (subcarriers 0 and 1) as invalid.
USED = (np.abs(SUBCARRIER_INDEX) <= 26) & (SUBCARRIER_INDEX != 0) & (SUBCARRIER_INDEX != 1)
USED_INDEX = SUBCARRIER_INDEX[USED]
N_USED = int(USED.sum())


def lltf_amplitude(packet: CsiPacket) -> Optional[np.ndarray]:
    """Amplitude of the used LLTF subcarriers, or None if the packet is unusable."""
    if packet.bandwidth != 0 or packet.raw.size < LLTF_VALUES:
        return None
    pairs = packet.raw[:LLTF_VALUES].astype(np.float32).reshape(-1, 2)  # [imag, real]
    amplitude = np.hypot(pairs[:, 0], pairs[:, 1])[USED]
    return amplitude


def normalize(amplitude: np.ndarray) -> np.ndarray:
    """Divide by the mean so that receiver gain (AGC) changes cancel out.

    The original ESP32 has no CSI gain compensation, so absolute amplitude jumps when the
    automatic gain control changes; the *shape* across subcarriers is what stays comparable.
    """
    return amplitude / (float(amplitude.mean()) + 1e-6)

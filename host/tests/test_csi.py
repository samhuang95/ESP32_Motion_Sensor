import numpy as np

from csi_motion.csi import N_USED, USED_INDEX, lltf_amplitude, normalize
from csi_motion.protocol import CsiPacket


def make_packet(raw, bandwidth=0):
    return CsiPacket(0, "1a:00:00:00:00:00", -50, -95, 11, bandwidth, 0, True, np.asarray(raw, dtype=np.int8))


def raw_with(**subcarriers):
    """subcarriers: {'s10': (imag, real)} in ESP32 order 0..31, -32..-1."""
    raw = np.zeros(128, dtype=np.int8)
    for name, (imag, real) in subcarriers.items():
        index = int(name[1:].replace("m", "-"))
        pos = index if index >= 0 else 64 + index
        raw[2 * pos], raw[2 * pos + 1] = imag, real
    return raw


def amp_at(amplitude, index):
    return amplitude[list(USED_INDEX).index(index)]


def test_used_subcarrier_set():
    assert N_USED == 51
    assert 0 not in USED_INDEX and 1 not in USED_INDEX
    assert 26 in USED_INDEX and 27 not in USED_INDEX
    assert -26 in USED_INDEX and -27 not in USED_INDEX


def test_amplitude_uses_imag_then_real_and_esp32_subcarrier_order():
    a = lltf_amplitude(make_packet(raw_with(s10=(3, 4), sm1=(6, 8))))
    assert a.shape == (N_USED,)
    assert amp_at(a, 10) == 5.0  # hypot(imag=3, real=4)
    assert amp_at(a, -1) == 10.0  # last array position is subcarrier -1
    assert np.count_nonzero(a) == 2


def test_unused_subcarriers_are_dropped():
    a = lltf_amplitude(make_packet(raw_with(s1=(9, 9), s27=(9, 9), sm27=(9, 9), s0=(9, 9))))
    assert np.count_nonzero(a) == 0


def test_rejects_ht40_and_short_packets():
    assert lltf_amplitude(make_packet(raw_with(s5=(1, 1)), bandwidth=1)) is None
    assert lltf_amplitude(make_packet(np.zeros(100))) is None


def test_ht_ltf_appended_after_lltf_is_ignored():
    raw = np.concatenate([raw_with(s10=(3, 4)), np.full(128, 100, dtype=np.int8)])
    a = lltf_amplitude(make_packet(raw))
    assert amp_at(a, 10) == 5.0 and np.count_nonzero(a) == 1


def test_normalize_cancels_gain():
    a = np.array([10.0, 20.0, 30.0])
    assert np.allclose(normalize(a), normalize(a * 3.7), atol=1e-4)
    assert np.all(np.isfinite(normalize(np.zeros(5))))

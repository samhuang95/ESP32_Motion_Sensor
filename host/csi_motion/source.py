"""Line sources: a real serial port, a recorded file, or a simulator."""
from __future__ import annotations

import time
from typing import Callable, Iterator, Optional

import numpy as np

from .csi import SUBCARRIER_INDEX
from .protocol import CsiPacket, format_line

StopFn = Callable[[], bool]


class SerialSource:
    """Reads text lines from the ESP32 receiver's USB serial port."""

    def __init__(self, port: str, baud: int = 921600) -> None:
        import serial  # imported here so the other modules work without pyserial

        # Open without toggling DTR/RTS where the OS allows it: on most dev boards these lines
        # reset the ESP32, which would restart the receiver every time this tool starts.
        self._ser = serial.Serial()
        self._ser.port = port
        self._ser.baudrate = baud
        self._ser.timeout = 0.2
        self._ser.dtr = False
        self._ser.rts = False
        self._ser.open()

    def lines(self, stop: Optional[StopFn] = None) -> Iterator[str]:
        buf = bytearray()
        while not (stop and stop()):
            chunk = self._ser.read(max(1, self._ser.in_waiting))
            if not chunk:
                continue
            buf += chunk
            while True:
                i = buf.find(b"\n")
                if i < 0:
                    break
                line = bytes(buf[:i]).decode("ascii", errors="replace").strip()
                del buf[: i + 1]
                if line:
                    yield line
            if len(buf) > 65536:  # no newline for a long time: garbage, resynchronise
                buf.clear()

    def close(self) -> None:
        self._ser.close()


class FileSource:
    """Replays a file recorded with `csi-motion record`."""

    def __init__(self, path: str, pace_hz: Optional[float] = None) -> None:
        self.path = path
        self.pace_hz = pace_hz

    def lines(self, stop: Optional[StopFn] = None) -> Iterator[str]:
        with open(self.path, "r", encoding="ascii", errors="replace") as f:
            for line in f:
                if stop and stop():
                    return
                line = line.strip()
                if not line:
                    continue
                yield line
                if self.pace_hz and line.startswith("CSI_DATA"):
                    time.sleep(1.0 / self.pace_hz)

    def close(self) -> None:
        pass


class SimulatedSource:
    """Synthetic CSI-like packets for exercising the tools without hardware.

    NOT real CSI. A fixed random "room" (static complex channel) plus receiver noise and gain
    jitter; every `still_s + moving_s` seconds there is a stretch of `moving_s` seconds in which
    a time-varying component is added. It only exists to test the software pipeline.
    """

    def __init__(
        self,
        rate_hz: float = 100.0,
        still_s: float = 8.0,
        moving_s: float = 4.0,
        seed: int = 1,
        realtime: bool = True,
        max_packets: Optional[int] = None,
    ) -> None:
        self.rate_hz = rate_hz
        self.still_s = still_s
        self.moving_s = moving_s
        self.realtime = realtime
        self.max_packets = max_packets
        self._rng = np.random.default_rng(seed)
        used = (np.abs(SUBCARRIER_INDEX) <= 26) & (SUBCARRIER_INDEX != 0)
        self._used = used
        k = np.arange(64)
        base_amp = 25 + 8 * np.sin(k / 9.0) + self._rng.normal(0, 2, 64)
        self._static = base_amp * np.exp(1j * self._rng.uniform(-np.pi, np.pi, 64))
        self._phi = self._rng.uniform(-np.pi, np.pi, (3, 64))

    def is_moving(self, t: float) -> bool:
        return (t % (self.still_s + self.moving_s)) >= self.still_s

    def packets(self) -> Iterator[CsiPacket]:
        n = 0
        t0 = time.monotonic()
        while self.max_packets is None or n < self.max_packets:
            t = n / self.rate_hz
            h = self._static.copy()
            if self.is_moving(t):
                for p, f in enumerate((0.7, 1.3, 2.1)):
                    h += 6.0 * np.exp(1j * (2 * np.pi * f * t + self._phi[p]))
            h = h * (1.0 + self._rng.normal(0, 0.02))  # AGC-like gain jitter
            h = h + self._rng.normal(0, 0.4, 64) + 1j * self._rng.normal(0, 0.4, 64)
            h = np.where(self._used, h, 0)
            raw = np.empty(128, dtype=np.int8)
            raw[0::2] = np.clip(np.round(h.imag), -128, 127)
            raw[1::2] = np.clip(np.round(h.real), -128, 127)
            yield CsiPacket(
                id=n,
                mac="1a:00:00:00:00:00",
                rssi=-45,
                noise_floor=-95,
                channel=11,
                bandwidth=0,
                timestamp_us=int(t * 1e6) & 0xFFFFFFFF,
                first_word_invalid=True,
                raw=raw,
            )
            n += 1
            if self.realtime:
                delay = t0 + n / self.rate_hz - time.monotonic()
                if delay > 0:
                    time.sleep(delay)

    def lines(self, stop: Optional[StopFn] = None) -> Iterator[str]:
        per_second = max(1, int(self.rate_hz))
        for packet in self.packets():
            if stop and stop():
                return
            yield format_line(packet)
            if (packet.id + 1) % per_second == 0:  # the real receiver prints CSI_STAT once per second
                yield f"CSI_STAT,{(packet.id + 1) * 1000 // per_second},{packet.id + 1},0"

    def close(self) -> None:
        pass

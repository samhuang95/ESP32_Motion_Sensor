"""Serial link / CSI stream health statistics (used by `csi-motion check`)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .protocol import ID_UNKNOWN, CsiPacket, CsiStat


@dataclass
class LinkStats:
    packets: int = 0
    lost: int = 0  # missing sender counters (lost over the air or dropped in the receiver)
    id_resets: int = 0  # sender restarted / counter jumped
    bad_lines: int = 0
    other_lines: int = 0
    unusable: int = 0  # packets that are not 20 MHz LLTF
    first_ts: Optional[int] = None
    elapsed_us: int = 0
    rssi: List[int] = field(default_factory=list)
    noise_floor: List[int] = field(default_factory=list)
    channels: set = field(default_factory=set)
    lengths: set = field(default_factory=set)
    last_stat: Optional[CsiStat] = None
    _last_id: Optional[int] = None
    _last_ts: Optional[int] = None

    def add_packet(self, p: CsiPacket) -> None:
        self.packets += 1
        self.rssi.append(p.rssi)
        self.noise_floor.append(p.noise_floor)
        self.channels.add(p.channel)
        self.lengths.add(int(p.raw.size))

        if self._last_ts is not None:
            dt = (p.timestamp_us - self._last_ts) & 0xFFFFFFFF
            if dt < 1_000_000:
                self.elapsed_us += dt
        self._last_ts = p.timestamp_us

        if p.id != ID_UNKNOWN:
            if self._last_id is not None:
                gap = (p.id - self._last_id) & 0xFFFFFFFF
                if 1 <= gap < 1000:
                    self.lost += gap - 1
                else:
                    self.id_resets += 1
            self._last_id = p.id

    @property
    def rate_hz(self) -> float:
        """Packet rate measured on the receiver's clock."""
        if self.elapsed_us <= 0 or self.packets < 2:
            return 0.0
        return (self.packets - 1) / (self.elapsed_us / 1e6)

    @property
    def loss_percent(self) -> float:
        total = self.packets + self.lost
        return 100.0 * self.lost / total if total else 0.0

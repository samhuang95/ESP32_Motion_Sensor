"""Serial link / CSI stream health statistics (used by `csi-motion check`)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .protocol import ID_UNKNOWN, CsiPacket, CsiStat


@dataclass
class LinkStats:
    packets: int = 0
    lost: int = 0  # missing sender counters (lost over the air or dropped in the receiver)
    id_resets: int = 0  # sender restarted / counter jumped
    rx_resets: int = 0  # receiver restarted (its uptime in CSI_STAT went backwards)
    dropped_in_window: int = 0  # packets the receiver dropped (serial too slow) while we were listening
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

    def add_stat(self, stat: CsiStat) -> None:
        # CSI_STAT counters are cumulative since the receiver booted: only count what happened
        # while we were listening, and treat a reboot (uptime going backwards) as a fresh counter.
        if self.last_stat is not None:
            if stat.device_ms < self.last_stat.device_ms:
                self.rx_resets += 1
                self.dropped_in_window += stat.dropped
            else:
                self.dropped_in_window += max(0, stat.dropped - self.last_stat.dropped)
        self.last_stat = stat

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

    def ac1(self, expect_rate_hz: float = 100.0) -> Tuple[bool, List[str]]:
        """Acceptance criterion AC-1 of specs/phase1.md (section 7): is the CSI stream healthy?"""
        if self.packets == 0:
            return False, ["沒有收到任何 CSI_DATA"]
        reasons: List[str] = []
        min_rate = 0.9 * expect_rate_hz
        if self.rate_hz < min_rate:
            reasons.append(f"取樣率 {self.rate_hz:.1f} Hz 低於 {min_rate:.0f} Hz")
        if self.loss_percent > 5:
            reasons.append(f"遺失率 {self.loss_percent:.1f}% 超過 5%")
        if self.last_stat is None:
            reasons.append("沒有收到 CSI_STAT，無法判定接收端丟包")
        elif self.dropped_in_window > 0:
            reasons.append(f"接收端丟包 {self.dropped_in_window} 個")
        mean_rssi = sum(self.rssi) / len(self.rssi)
        if mean_rssi < -75:
            reasons.append(f"平均 RSSI {mean_rssi:.0f} dBm 低於 -75 dBm")
        return not reasons, reasons

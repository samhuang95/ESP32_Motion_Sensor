"""Parsing and formatting of the serial lines printed by firmware/csi_recv.

CSI_DATA,<id>,<mac>,<rssi>,<rate>,<sig_mode>,<mcs>,<bandwidth>,<smoothing>,<not_sounding>,
         <aggregation>,<stbc>,<fec_coding>,<sgi>,<noise_floor>,<ampdu_cnt>,<channel>,
         <secondary_channel>,<local_timestamp>,<ant>,<sig_len>,<rx_format>,<len>,<first_word>,"[...]"
CSI_STAT,<device_ms>,<rx_total>,<dropped>

The CSI_DATA layout is the same as in Espressif's esp-csi examples.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Optional, Union

import numpy as np

CSI_FIELDS = (
    "type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,"
    "fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,"
    "sig_len,rx_format,len,first_word,data"
)
N_FIELDS = len(CSI_FIELDS.split(","))
ID_UNKNOWN = 0xFFFFFFFF  # the receiver could not read the sender's counter


@dataclass(frozen=True)
class CsiPacket:
    id: int  # sender packet counter (ID_UNKNOWN if unavailable)
    mac: str
    rssi: int
    noise_floor: int
    channel: int
    bandwidth: int  # rx_ctrl.cwb: 0 = 20 MHz, 1 = 40 MHz
    timestamp_us: int  # receiver's local clock, wraps at 2**32
    first_word_invalid: bool
    raw: np.ndarray  # int8: [imag0, real0, imag1, real1, ...]


@dataclass(frozen=True)
class CsiStat:
    device_ms: int
    rx_total: int  # CSI packets seen by the receiver since boot
    dropped: int  # packets dropped inside the receiver because the serial link was too slow


Event = Union[CsiPacket, CsiStat]


def parse_line(line: str) -> Optional[Event]:
    """Parse one serial line.

    Returns None for lines that are not CSI output (boot messages, logs, the header).
    Raises ValueError for CSI_DATA / CSI_STAT lines that are damaged (e.g. truncated by a
    serial overrun), so callers can count them.
    """
    line = line.strip()
    if line.startswith("CSI_STAT,"):
        parts = line.split(",")
        if len(parts) != 4:
            raise ValueError(f"bad CSI_STAT line: {line!r}")
        try:
            return CsiStat(int(parts[1]), int(parts[2]), int(parts[3]))
        except ValueError as exc:
            raise ValueError(f"bad CSI_STAT line: {line!r}") from exc

    if not line.startswith("CSI_DATA,"):
        return None

    try:
        fields = next(csv.reader([line]))
    except (csv.Error, StopIteration) as exc:
        raise ValueError(f"unparsable CSI_DATA line: {line[:80]!r}") from exc
    if len(fields) != N_FIELDS:
        raise ValueError(f"CSI_DATA has {len(fields)} fields, expected {N_FIELDS}")

    data = fields[-1].strip()
    if not (data.startswith("[") and data.endswith("]")):
        raise ValueError("CSI data array is not enclosed in [...]")
    try:
        values = np.array(data[1:-1].split(","), dtype=np.int16)
        declared_len = int(fields[22])
        if values.size != declared_len:
            raise ValueError(f"CSI length {values.size} != declared {declared_len}")
        if values.min() < -128 or values.max() > 127:
            raise ValueError("CSI value outside int8 range")
        return CsiPacket(
            id=int(fields[1]),
            mac=fields[2],
            rssi=int(fields[3]),
            noise_floor=int(fields[14]),
            channel=int(fields[16]),
            bandwidth=int(fields[7]),
            timestamp_us=int(fields[18]) & 0xFFFFFFFF,
            first_word_invalid=fields[23].strip() == "1",
            raw=values.astype(np.int8),
        )
    except (ValueError, IndexError) as exc:
        raise ValueError(f"bad CSI_DATA line: {exc}") from exc


def format_line(packet: CsiPacket) -> str:
    """Inverse of parse_line (fields the host does not use are written as 0)."""
    body = ",".join(str(int(v)) for v in packet.raw)
    return (
        f"CSI_DATA,{packet.id},{packet.mac},{packet.rssi},0,0,0,{packet.bandwidth},0,0,0,0,0,0,"
        f"{packet.noise_floor},0,{packet.channel},0,{packet.timestamp_us},0,0,0,"
        f'{packet.raw.size},{int(packet.first_word_invalid)},"[{body}]"'
    )

import numpy as np
import pytest

from csi_motion.protocol import CSI_FIELDS, ID_UNKNOWN, CsiPacket, CsiStat, format_line, parse_line

# A real line from the Espressif esp-csi get-started README (same 25-column layout).
OFFICIAL_SAMPLE = (
    "CSI_DATA,0,94:d9:b3:80:8c:81,-30,11,1,6,1,0,1,0,1,0,0,-93,0,13,2,2751923,0,67,0,128,1,"
    '"[67,48,4,0,0,0,0,0,0,0,5,0,20,1,20,1,19,0,17,1,16,2,15,2,14,1,12,0,12,-1,12,-3,12,-4,13,-6,'
    "15,-7,16,-8,16,-8,16,-8,16,-6,15,-5,15,-4,14,-4,13,-4,12,-4,11,-4,10,-4,9,-5,8,-6,4,-4,8,-9,"
    "9,-10,9,-10,10,-11,11,-10,11,-10,12,-9,11,-8,11,-7,10,-6,9,-6,7,-6,6,-7,5,-7,5,-8,5,-9,5,-10,"
    '5,-11,5,-11,6,-11,7,-11,8,-11,9,-10,9,-9,8,-8,8,-7,1,-2,0,0,0,0,0,0,0,0]"'
)


def test_header_has_25_columns():
    assert len(CSI_FIELDS.split(",")) == 25


def test_parses_official_sample():
    p = parse_line(OFFICIAL_SAMPLE)
    assert isinstance(p, CsiPacket)
    assert p.id == 0
    assert p.mac == "94:d9:b3:80:8c:81"
    assert p.rssi == -30
    assert p.noise_floor == -93
    assert p.channel == 13
    assert p.bandwidth == 1
    assert p.timestamp_us == 2751923
    assert p.first_word_invalid is True
    assert p.raw.dtype == np.int8
    assert p.raw.size == 128
    assert list(p.raw[:4]) == [67, 48, 4, 0]


def test_round_trip():
    raw = np.arange(-64, 64, dtype=np.int8)
    p = CsiPacket(7, "1a:00:00:00:00:00", -50, -95, 11, 0, 123456, True, raw)
    q = parse_line(format_line(p))
    assert q.id == 7 and q.rssi == -50 and q.channel == 11 and q.timestamp_us == 123456
    assert np.array_equal(q.raw, raw)


def test_stat_line():
    assert parse_line("CSI_STAT,1000,98,2") == CsiStat(1000, 98, 2)


@pytest.mark.parametrize(
    "line",
    [
        "CSI_STAT,1000,98",  # truncated
        "CSI_STAT,a,b,c",
        OFFICIAL_SAMPLE[:-20],  # cut by a serial overrun
        OFFICIAL_SAMPLE.replace(",128,1,", ",127,1,"),  # declared length != actual
        OFFICIAL_SAMPLE.replace("[67,", "[1000,"),  # not an int8
        "CSI_DATA,1,2,3",
    ],
)
def test_damaged_lines_raise(line):
    with pytest.raises(ValueError):
        parse_line(line)


@pytest.mark.parametrize("line", ["", "I (123) wifi: boot", "ets Jun  8 2016", "type,id,mac,rssi", "\x00\xff garbage"])
def test_unrelated_lines_are_ignored(line):
    assert parse_line(line) is None


def test_id_unknown_constant_matches_firmware():
    assert ID_UNKNOWN == 0xFFFFFFFF


def test_negative_timestamp_from_firmware_int_cast():
    # The firmware prints the 32-bit timestamp through (int): after ~35 min uptime it is negative.
    line = OFFICIAL_SAMPLE.replace(",2751923,", ",-5,")
    assert parse_line(line).timestamp_us == 2**32 - 5

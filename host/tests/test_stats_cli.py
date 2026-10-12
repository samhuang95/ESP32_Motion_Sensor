import json
import os

import numpy as np
import pytest

from csi_motion import cli
from csi_motion.protocol import ID_UNKNOWN, CsiPacket, CsiStat
from csi_motion.stats import LinkStats


def pkt(i, ts_us, rssi=-50, id_=None):
    return CsiPacket(i if id_ is None else id_, "1a:00:00:00:00:00", rssi, -95, 11, 0, ts_us, True, np.zeros(128, np.int8))


def test_loss_and_rate():
    s = LinkStats()
    for i in (0, 1, 2, 5, 6):  # 3 and 4 missing
        s.add_packet(pkt(i, i * 10_000))
    assert s.packets == 5 and s.lost == 2
    assert s.loss_percent == pytest.approx(100 * 2 / 7)
    assert s.rate_hz == pytest.approx(4 / 0.06)


def test_sender_restart_is_not_counted_as_loss():
    s = LinkStats()
    for i, id_ in enumerate((10, 11, 12, 0, 1, 2)):
        s.add_packet(pkt(i, i * 10_000, id_=id_))
    assert s.lost == 0 and s.id_resets == 1


def test_unknown_ids_are_ignored():
    s = LinkStats()
    for i in range(5):
        s.add_packet(pkt(i, i * 10_000, id_=ID_UNKNOWN))
    assert s.lost == 0 and s.id_resets == 0


def test_check_simulated(capsys):
    assert cli.main(["check", "--simulate", "--seconds", "1.5"]) == 0
    out = capsys.readouterr().out
    assert "收到封包數" in out and "AC-1" in out and "通過" in out


def test_check_without_data_fails(tmp_path, capsys):
    empty = tmp_path / "empty.csv"
    empty.write_text("I (1) boot: nothing here\n")
    assert cli.main(["check", "--file", str(empty), "--seconds", "1"]) == 1
    assert "沒有收到任何 CSI_DATA" in capsys.readouterr().out


def test_record_then_replay(tmp_path, capsys):
    out_dir = tmp_path / "data"
    rc = cli.main(["record", "--simulate", "--label", "idle", "--seconds", "1.2", "--countdown", "0", "--out", str(out_dir)])
    assert rc == 0
    files = sorted(os.listdir(out_dir))
    assert [f.split(".")[-1] for f in files] == ["csv", "json"]
    meta = json.loads((out_dir / files[1]).read_text(encoding="utf-8"))
    assert meta["label"] == "idle" and meta["simulated"] is True and meta["packets"] > 50

    capsys.readouterr()
    assert cli.main(["check", "--file", str(out_dir / files[0]), "--seconds", "5", "--pace", "10000"]) == 0
    assert f"收到封包數     : {meta['packets']}" in capsys.readouterr().out


def test_record_rejects_bad_label(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["record", "--simulate", "--label", "../evil", "--seconds", "1", "--out", str(tmp_path)])


def test_receiver_restart_detected_from_uptime_going_backwards():
    s = LinkStats()
    for ms in (1000, 2000, 3000, 500, 1500):  # reboot between 3000 and 500
        s.add_stat(CsiStat(ms, 100, 0))
    assert s.rx_resets == 1 and s.last_stat.device_ms == 1500


def test_check_warns_below_50_hz(tmp_path, capsys):
    from csi_motion.protocol import format_line

    f = tmp_path / "slow.csv"
    f.write_text("\n".join(format_line(pkt(i, i * 40_000)) for i in range(60)) + "\n")  # 25 Hz
    assert cli.main(["check", "--file", str(f), "--seconds", "5", "--pace", "10000"]) == 0
    out = capsys.readouterr().out
    assert "低於 50 Hz" in out


def test_dropped_counted_only_inside_window_and_across_reboot():
    s = LinkStats()
    s.add_stat(CsiStat(1000, 100, 5))  # baseline: 5 were dropped before we started listening
    s.add_stat(CsiStat(2000, 200, 7))
    assert s.dropped_in_window == 2
    s.add_stat(CsiStat(500, 50, 3))  # receiver rebooted: counters restart from 0
    assert s.rx_resets == 1 and s.dropped_in_window == 5


def test_check_json_simulated_passes_ac1(capsys):
    assert cli.main(["check", "--simulate", "--seconds", "2.2", "--json", "--strict"]) == 0
    out = json.loads(capsys.readouterr().out)  # stdout must be pure JSON
    assert out["ac1"]["pass"] is True and out["ac1"]["reasons"] == []
    assert out["rate_hz"] == pytest.approx(100.0, abs=0.5)
    assert out["receiver_stat_seen"] is True and out["receiver_dropped_in_window"] == 0
    assert out["csi_lengths"] == [128] and out["channels"] == [11]


def test_check_strict_fails_ac1_with_reasons(tmp_path, capsys):
    from csi_motion.protocol import format_line

    f = tmp_path / "slow.csv"
    f.write_text("\n".join(format_line(pkt(i, i * 40_000)) for i in range(60)) + "\n")  # 25 Hz, no CSI_STAT
    rc = cli.main(["check", "--file", str(f), "--seconds", "5", "--pace", "10000", "--json", "--strict"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["ac1"]["pass"] is False
    joined = " ".join(out["ac1"]["reasons"])
    assert "取樣率" in joined and "CSI_STAT" in joined
    # without --strict the same data is only reported, not an error exit
    assert cli.main(["check", "--file", str(f), "--seconds", "5", "--pace", "10000", "--json"]) == 0
    capsys.readouterr()


def test_check_expect_rate_scales_threshold(capsys):
    # simulated stream is 100 Hz: fine for expect 100, not for expect 200 (needs >= 180 Hz)
    assert cli.main(["check", "--simulate", "--seconds", "2.2", "--json", "--strict", "--expect-rate", "200"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert any("取樣率" in r for r in out["ac1"]["reasons"])


def test_recording_keeps_csi_stat_lines(tmp_path):
    out_dir = tmp_path / "d"
    cli.main(["record", "--simulate", "--label", "idle", "--seconds", "2.2", "--countdown", "0", "--out", str(out_dir)])
    csv_file = next(out_dir.glob("*.csv"))
    assert any(line.startswith("CSI_STAT,") for line in csv_file.read_text().splitlines())
    assert json.loads(next(out_dir.glob("*.json")).read_text(encoding="utf-8"))["receiver_dropped"] == 0

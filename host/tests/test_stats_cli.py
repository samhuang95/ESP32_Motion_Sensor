import json
import os

import numpy as np
import pytest

from csi_motion import cli
from csi_motion.protocol import ID_UNKNOWN, CsiPacket
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
    assert "收到封包數" in out and "正常" in out


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

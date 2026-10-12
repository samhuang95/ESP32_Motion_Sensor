import matplotlib

matplotlib.use("Agg")

from csi_motion.detector import MotionDetector  # noqa: E402
from csi_motion.live import LiveView  # noqa: E402
from csi_motion.source import SimulatedSource  # noqa: E402


def test_live_view_renders(tmp_path):
    view = LiveView(MotionDetector(baseline_seconds=2.0), "[SIMULATED DATA - not real CSI]")
    for p in SimulatedSource(realtime=False, max_packets=1200).packets():
        view.process(p)
    view.render()
    out = tmp_path / "live.png"
    view.fig.savefig(out)
    assert out.stat().st_size > 10_000
    assert view.packets_seen == 1200
    assert view.status.get_text() in {"MOTION", "IDLE"}

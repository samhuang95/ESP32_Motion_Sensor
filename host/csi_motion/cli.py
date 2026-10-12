"""Command line interface: csi-motion {ports,check,record,live}."""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime
from typing import List, Optional

import numpy as np

from .csi import lltf_amplitude
from .protocol import CSI_FIELDS, CsiPacket, CsiStat, parse_line
from .source import FileSource, SerialSource, SimulatedSource
from .stats import LinkStats


def _add_source_args(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--port", help="接收端 ESP32 的序列埠，例如 COM3 或 /dev/ttyUSB0")
    g.add_argument("--file", help="重播 `record` 錄下來的檔案")
    g.add_argument("--simulate", action="store_true", help="使用模擬資料(非真實 CSI)，只用來測試軟體流程")
    p.add_argument("--baud", type=int, default=921600, help="序列埠速率 (預設 921600，需與韌體一致)")
    p.add_argument("--pace", type=float, default=100.0, help="--file 重播速度 (封包/秒，預設 100)")


def _make_source(args):
    if args.simulate:
        print("*** 模擬資料模式：這不是真實的 Wi-Fi CSI ***", file=sys.stderr)
        return SimulatedSource()
    if args.file:
        return FileSource(args.file, pace_hz=args.pace)
    if args.port:
        try:
            return SerialSource(args.port, args.baud)
        except Exception as exc:  # serial.SerialException, PermissionError, ...
            raise SystemExit(f"無法開啟序列埠 {args.port}: {exc}\n(用 `csi-motion ports` 列出可用的序列埠)")
    raise SystemExit("請指定 --port、--file 或 --simulate (用 `csi-motion ports` 列出序列埠)")


def _events(lines, stats: Optional[LinkStats] = None):
    """Parse lines into events, counting damaged / unrelated lines in `stats`."""
    for line in lines:
        try:
            event = parse_line(line)
        except ValueError:
            if stats:
                stats.bad_lines += 1
            continue
        if event is None:
            if stats:
                stats.other_lines += 1
            continue
        yield event


def cmd_ports(args) -> int:
    from serial.tools import list_ports

    ports = list(list_ports.comports())
    if not ports:
        print("找不到任何序列埠。請確認 USB 線是「資料線」(不是只能充電)，以及已安裝 CP210x / CH340 驅動。")
        return 1
    for p in ports:
        print(f"{p.device}\t{p.description}")
    return 0


def cmd_check(args) -> int:
    source = _make_source(args)
    stats = LinkStats()
    deadline = time.monotonic() + args.seconds
    print(f"收集 {args.seconds:.0f} 秒的資料…")
    try:
        for event in _events(source.lines(stop=lambda: time.monotonic() > deadline), stats):
            if isinstance(event, CsiStat):
                stats.add_stat(event)
            else:
                stats.add_packet(event)
                if lltf_amplitude(event) is None:
                    stats.unusable += 1
    finally:
        source.close()
    return _print_check_report(stats)


def _print_check_report(stats: LinkStats) -> int:
    print("\n=== CSI 連線檢查 ===")
    if stats.packets == 0:
        print("沒有收到任何 CSI_DATA。可能原因:")
        print("  1. 發送端沒通電，或沒有燒錄 csi_send")
        print("  2. 兩塊板子的 Wi-Fi 通道不同 (CONFIG_CSI_CHANNEL 要一致)")
        print("  3. 序列埠速率不對 (接收端預設 921600)，或選錯了埠 (--port)")
        print("  4. 接收端剛重啟，等 1~2 秒再試")
        print(f"(收到 {stats.other_lines} 行非 CSI 文字，{stats.bad_lines} 行損毀的 CSI 行)")
        return 1

    warnings: List[str] = []
    print(f"收到封包數     : {stats.packets}")
    print(f"取樣率         : {stats.rate_hz:.1f} Hz (以接收端時鐘計算)")
    print(f"遺失率         : {stats.loss_percent:.1f} % (依發送端計數器，{stats.lost} 個)")
    print(f"RSSI           : 平均 {np.mean(stats.rssi):.0f} dBm (最小 {min(stats.rssi)}, 最大 {max(stats.rssi)})")
    print(f"底噪           : 平均 {np.mean(stats.noise_floor):.0f} dBm")
    print(f"通道           : {sorted(stats.channels)}")
    print(f"每包 CSI 長度  : {sorted(stats.lengths)} (128 = 只含 LLTF)")
    if stats.last_stat is not None:
        print(f"接收端丟包     : {stats.last_stat.dropped} (序列埠來不及輸出而丟棄)")
    print(f"損毀/無關行數  : {stats.bad_lines} / {stats.other_lines}")
    print(f"重啟/跳變      : 發送端計數器跳變 {stats.id_resets} 次 / 接收端重啟 {stats.rx_resets} 次")

    if stats.rate_hz < 50:
        warnings.append("取樣率低於 50 Hz (規格最低要求 50 Hz，預設 100 Hz)；檢查發送端 CONFIG_CSI_SEND_PERIOD_MS 與接收端丟包。")
    if stats.loss_percent > 5:
        warnings.append("遺失率超過 5%。兩板距離、遮蔽或 2.4 GHz 干擾都可能造成。")
    if stats.last_stat is not None and stats.last_stat.dropped > 0:
        warnings.append("接收端因序列埠太慢而丟包：降低發送頻率，或提高序列埠速率 (需韌體與 --baud 同步調整)。")
    if float(np.mean(stats.rssi)) < -75:
        warnings.append("訊號偏弱 (RSSI < -75 dBm)：拉近兩板，或改用外接天線。")
    if stats.unusable:
        warnings.append(f"{stats.unusable} 個封包不是 20 MHz LLTF，已被忽略。")
    if stats.rx_resets:
        warnings.append(f"接收端在量測期間重啟了 {stats.rx_resets} 次 (供電不穩、USB 線接觸不良，或程式當機)。")
    if stats.id_resets > 1:
        warnings.append("發送端計數器多次跳變，發送端可能在重啟 (供電不穩?)。")

    print()
    if warnings:
        for w in warnings:
            print("警告:", w)
    else:
        print("結果: 正常。可以用 `csi-motion live` 觀察動作偵測。")
    return 0


_LABEL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def cmd_record(args) -> int:
    if not _LABEL_RE.match(args.label):
        raise SystemExit("--label 只能使用英數字、底線與連字號")
    source = _make_source(args)
    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(args.out, f"{args.label}_{stamp}")

    for i in range(args.countdown, 0, -1):
        print(f"{i}…", end=" ", flush=True)
        time.sleep(1)
    print(f"開始錄製「{args.label}」{args.seconds:.0f} 秒")

    stats = LinkStats()
    started = time.monotonic()
    deadline = started + args.seconds
    next_report = started + 1
    try:
        with open(base + ".csv", "w", encoding="ascii") as out:
            out.write(CSI_FIELDS + "\n")
            for line in source.lines(stop=lambda: time.monotonic() > deadline):
                try:
                    event = parse_line(line)
                except ValueError:
                    stats.bad_lines += 1
                    continue
                if isinstance(event, CsiPacket):
                    stats.add_packet(event)
                    out.write(line + "\n")
                elif isinstance(event, CsiStat):
                    stats.add_stat(event)
                if time.monotonic() >= next_report:
                    next_report += 1
                    print(f"\r  {stats.packets} 封包 ({stats.rate_hz:.0f} Hz)", end="", flush=True)
    except KeyboardInterrupt:
        print("\n中斷，已儲存目前的資料。")
    finally:
        source.close()

    meta = {
        "label": args.label,
        "started_at": stamp,
        "seconds_requested": args.seconds,
        "packets": stats.packets,
        "rate_hz": round(stats.rate_hz, 2),
        "loss_percent": round(stats.loss_percent, 2),
        "simulated": bool(args.simulate),
        "source": args.file or args.port or "simulate",
    }
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"\n已存到 {base}.csv ({stats.packets} 封包，{stats.rate_hz:.0f} Hz，遺失 {stats.loss_percent:.1f}%)")
    return 0 if stats.packets else 1


def cmd_live(args) -> int:
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    from .detector import MotionDetector
    from .live import LiveView

    source = _make_source(args)
    packets: "queue.Queue[CsiPacket]" = queue.Queue(maxsize=20000)
    stop = threading.Event()

    def reader() -> None:
        for event in _events(source.lines(stop=stop.is_set)):
            if isinstance(event, CsiPacket):
                try:
                    packets.put_nowait(event)
                except queue.Full:
                    pass

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    title = "[SIMULATED DATA - not real CSI]" if args.simulate else "ESP32 Wi-Fi CSI motion"
    view = LiveView(MotionDetector(baseline_seconds=args.baseline_seconds), title)

    def on_frame(_):
        for _i in range(2000):
            try:
                view.process(packets.get_nowait())
            except queue.Empty:
                break
        view.render()

    def on_key(event) -> None:
        if event.key == "c":
            view.restart_calibration()

    view.fig.canvas.mpl_connect("key_press_event", on_key)
    print("按 c 重新校準 (校準時請讓感測區保持無人/靜止)。關閉視窗結束。")
    _anim = FuncAnimation(view.fig, on_frame, interval=100, cache_frame_data=False)
    try:
        plt.show()
    finally:
        stop.set()
        thread.join(timeout=1.0)
        source.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="csi-motion", description="ESP32 Wi-Fi CSI 動作感測 PC 端工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ports", help="列出序列埠")
    p.set_defaults(func=cmd_ports)

    p = sub.add_parser("check", help="檢查 CSI 串流是否健康 (取樣率、遺失率、訊號強度)")
    _add_source_args(p)
    p.add_argument("--seconds", type=float, default=10.0)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("record", help="錄製帶標籤的 CSI 資料 (之後訓練分類器用)")
    _add_source_args(p)
    p.add_argument("--label", required=True, help="動作標籤，例如 idle / jump / spin / arm_wave")
    p.add_argument("--seconds", type=float, default=30.0)
    p.add_argument("--countdown", type=int, default=3, help="開始前倒數秒數，讓你走到位置")
    p.add_argument("--out", default="data", help="輸出資料夾 (預設 ./data)")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("live", help="即時視圖與動作偵測")
    _add_source_args(p)
    p.add_argument("--baseline-seconds", type=float, default=5.0, help="開頭用來校準靜止基準的秒數")
    p.set_defaults(func=cmd_live)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

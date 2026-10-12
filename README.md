# ESP32 Motion Sensor

用兩塊 **ESP32 (ESP-WROOM-32)** 的 Wi-Fi CSI（通道狀態資訊）做「無接觸動作偵測」。規格見 [`specs/phase1.md`](specs/phase1.md)。

```
 發送端 ESP32                接收端 ESP32                 PC
 csi_send  ──ESP-NOW 100Hz──▶ csi_recv ──USB 序列埠 921600──▶ csi-motion
 (固定頻率發封包)             (擷取每個封包的 CSI)           (檢查 / 偵測 / 錄製)
```

## 目前狀態（請先讀這段）

| 項目 | 狀態 |
|---|---|
| 韌體 `csi_send` / `csi_recv` | 已用 ESP-IDF v5.5.1 以 `esp32` 目標編譯通過（0 警告），**尚未在實體板子上跑過** |
| PC 端 `csi-motion` | 42 個自動測試通過（解析器用 Espressif 官方範例的真實資料行；偵測器只用**模擬資料**測試） |
| 動作偵測參數 | **尚未用真實資料調校**。門檻值是開機時用靜止狀態自動學的，但 `window` / `lag` / `k` 需要你實測後調整 |
| 真實火柴人 / 骨架追蹤 | **不做**。兩塊 ESP32 = 一條鏈路，無法重建人體關節。已決定**不使用相機**，Phase 2 會做「由動作分類結果驅動的火柴人示意動畫」（見下方） |

這一階段的目標：**讓 CSI 資料穩定流進 PC，並確認動作偵測在你的房間有效**，再開始錄資料做分類。

## 為什麼沒有火柴人

WiFi 骨架重建（WiPose、DensePose From WiFi、Person-in-WiFi 3D）是真實的研究，但都用多天線研究級網卡、多個接收端、GPU 模型，並且在**同一個房間訓練與測試**。

兩塊 ESP32 只有一條 1×1 的鏈路，回答得了「有沒有人在動、動作像哪一類」，回答不了「手肘在哪裡」。
與 ESP32 相關的開源專案 [ruvnet/RuView](https://github.com/ruvnet/RuView) 自己承認單顆 ESP32 的即時 17 關節模型只有 PCK@20 ≈ 3%，網路上看到的火柴人展示請小心，可能是模擬資料或預錄動畫（見其 [issue #509](https://github.com/ruvnet/RuView/issues/509)）。

所以本專案的定位是「動作事件偵測／分類」，不做骨架追蹤（見 [`specs/phase1.md`](specs/phase1.md) 第 1.2 節）。

**你在電腦上看到的火柴人會是這樣**（Phase 2，決策 D1）：你做動作，系統判斷「這是跳／轉圈／揮手／靜止」，畫面上的火柴人播放對應的預製動畫，並標示「分類結果」與信心值。你可以靠自己做的動作驗證它對不對。它**不會**跟著你的手肘、膝蓋即時動，也不會對沒訓練過的動作有反應。

## 硬體與擺放（詳見 [`specs/phase1.md`](specs/phase1.md) 第 4 節）

- 2 × ESP-WROOM-32 開發板，各自用 USB 供電（發送端可接行動電源）。接收端要接 PC。
- 兩板相距 **2 m**、高度 **1.0 ~ 1.2 m**（腰到胸），固定在腳架上，天線方向一致。
- 感測區內不要有其他人走動、風扇、移動的大型物體。校準與錄製期間尤其重要。
- ESP-WROOM-32 是板載 PCB 天線（有指向性）。效果不好時可考慮換帶 IPEX 接頭的 ESP32-WROOM-32U + 外接天線。
- 原版 ESP32 **沒有 CSI 增益補償**（S3 / C 系列才有），絕對振幅會因 AGC 跳動。偵測器因此先把每個封包的振幅正規化，並用封包間的相關係數而不是原始振幅變化。

## Windows 11 環境安裝（只需做一次）

1. **Python 3.11 以上**（我測試用的是 3.13；專案宣告支援 3.9 以上）：從 [python.org](https://www.python.org/downloads/windows/) 安裝，安裝時勾選「Add python.exe to PATH」。用 `py --version` 確認。
2. **USB 驅動**：看板子 USB 孔旁邊的小方形晶片型號。`CP2102` 裝 Silicon Labs 的 CP210x 驅動；`CH340` / `CH343` 裝 WCH 的驅動（CH343 可能與 CH340 不同，請依晶片型號選）。裝完重新開機。
3. **ESP-IDF 5.5.x**：照官方的 [Windows 安裝指南](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/get-started/windows-setup.html)，用 ESP-IDF Tools 安裝程式，或較新的 [ESP-IDF Installation Manager](https://docs.espressif.com/projects/idf-im-ui/en/latest/)。選 5.5.x（我驗證過的是 5.5.1）。裝完從開始選單開「**ESP-IDF PowerShell**」，輸入 `idf.py --version` 確認。（我沒有在 Windows 上驗證過安裝程式，請以官方文件為準。）
4. **接上兩塊板子**：用**資料線**（不是只能充電的線），直接插電腦，不要經過 USB hub。到「裝置管理員 → 連接埠 (COM 和 LPT)」應該各出現一個 `COMx`。

## 建置與燒錄韌體

在「**ESP-IDF PowerShell**」裡執行（韌體 5.5.1 編譯通過）：

```powershell
# 接收端（之後要接電腦的那塊）
cd firmware\csi_recv
idf.py set-target esp32
idf.py -p COM3 flash

# 發送端
cd ..\csi_send
idf.py set-target esp32
idf.py -p COM4 flash
```

- 不確定哪個 COM 是哪塊板子：先只插一塊，看裝置管理員出現哪個，燒完再插另一塊。發送端燒完後只要供電即可，可以接行動電源。
- 燒錄失敗（`Failed to connect`）：燒錄開始時按住板子上的 BOOT 鍵。
- macOS / Linux 指令相同，埠名類似 `/dev/ttyUSB0`（我只在 Linux 上做過編譯，沒有實際燒錄）。
- 設定：`idf.py menuconfig` → **CSI Motion Sensor (common)**（Wi-Fi 通道、發送功率；**兩塊板子通道必須相同**）、**CSI Sender**（發封包間隔，預設 10 ms = 100 Hz）、**CSI Receiver**。
- 預設只擷取 LLTF（每包 128 個數值）。序列埠 921600 baud 上限約 92 KB/s；以官方範例的真實資料行估算，100 Hz 下 LLTF 約 44 KB/s，加上 HT-LTF 約 76 KB/s（餘裕很薄，真實數值字元更多時可能超過）。開啟 HT-LTF 時建議把發送頻率降到 50 Hz。是否丟包以 `csi-motion check` 的「接收端丟包」為準。
- 不要同時開 `idf.py monitor` 和 PC 端工具，序列埠只能被一個程式佔用。

## PC 端工具

請在**一般的 PowerShell 視窗**執行（不要在 ESP-IDF PowerShell 裡，兩者各有自己的 Python 環境）：

```powershell
cd host
py -m venv .venv
.\.venv\Scripts\Activate.ps1        # 若被「執行原則」擋下：Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e ".[dev]"

csi-motion ports                     # 列出序列埠，找出接收端
csi-motion check --port COM3         # ① 先確認串流健康
csi-motion live  --port COM3         # ② 即時視圖 + 動作偵測
csi-motion record --port COM3 --label idle --seconds 30   # ③ 錄製帶標籤資料
pytest                               # 跑測試（測試目前只在 Linux 上跑過）
```

1. **`check`**：收集 10 秒，回報取樣率、遺失率、RSSI、接收端丟包，並判定 AC-1（串流健康）是否通過。**先把這一步調到通過再往下。** 自動化用法：`csi-motion check --seconds 60 --json --strict`（只輸出 JSON；結束碼 0 = 通過、2 = 未通過、1 = 沒有資料）。
2. **`live`**：開頭 5 秒是校準（請讓感測區保持無人／靜止），之後顯示 `IDLE` / `MOTION`。上圖是扣除背景後的振幅熱圖，下圖是動作分數與門檻。按 `c` 重新校準。偵測的是**移動**，站著不動不會被偵測到。
3. **`record`**：存成 `data/<label>_<時間>.csv`（原始 CSI 行，格式與 Espressif esp-csi 範例相同）與 `.json`（標籤與品質資訊）。`--file` 可重播。`data/` 已被 git 忽略。

沒有硬體時可加 `--simulate` 看軟體流程，畫面標題會註明 **SIMULATED**，那不是真實 CSI。

## 疑難排解

| 現象 | 檢查 |
|---|---|
| `check` 沒收到任何 CSI_DATA | 發送端有沒有通電；兩板 `CSI_CHANNEL` 是否相同；`--port` 是否選對；USB 線是否為資料線 |
| 取樣率遠低於 100 Hz | 看 `接收端丟包`：有值代表序列埠太慢；沒有值代表空中遺失（距離、干擾） |
| 一直誤報 MOTION | 校準時是否有人在區內；按 `c` 重新校準；換較乾淨的 Wi-Fi 通道 |
| 動作偵測不靈敏 | 兩板距離與高度是否照規格第 4 節；降低 `MotionDetector(k=…)` 或縮短 `lag`（`host/csi_motion/detector.py`） |
| 裝置管理員沒有 COM 埠 | 換資料線、直插電腦；確認驅動（看板上晶片型號）並重新開機 |
| `Activate.ps1` 無法執行 | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| 開啟序列埠後板子重啟 | 部分板子的 DTR/RTS 會觸發重置，等 1~2 秒再看資料 |

## 專案結構

```
firmware/
  components/csi_common/   兩邊共用的 Wi-Fi / ESP-NOW 初始化
  csi_send/                發送端
  csi_recv/                接收端（CSI → queue → 序列埠）
host/
  csi_motion/              protocol 解析、csi 振幅、detector 偵測、stats 檢查、source、live、cli
  tests/
```

韌體由 Espressif [esp-csi](https://github.com/espressif/esp-csi) 的 get-started 範例（Apache-2.0 / CC0）改寫：改成只用 HT20、把序列埠輸出移出 Wi-Fi 回呼（依 ESP-IDF 文件建議用 queue）、`esp_wifi_set_mac` 放在 `esp_wifi_start` 之前（API 文件要求介面停用時才能呼叫）。

## 下一步

1. 照上面的 Windows 11 步驟安裝、燒錄，跑 `csi-motion check`。
2. 之後電腦連線讓 Claude 直接測試：`check --json --strict` 能自動判讀 AC-1 / AC-5；動作偵測的統計（AC-2、AC-3）會再做一個 `csi-motion trial` 指令，依提示做動作並自動統計。
3. 依 [`specs/phase1.md`](specs/phase1.md) 第 8 節的四類動作（idle / jump / spin / arm_wave）各錄多段資料，再進入 Phase 2（分類器與火柴人示意動畫）。

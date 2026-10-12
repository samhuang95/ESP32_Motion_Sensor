# 規格書：Phase 1 — Wi-Fi CSI 資料管線與動作偵測

| 項目 | 內容 |
|---|---|
| 文件版本 | V2.0-phase1（草案） |
| 日期 | 2026-10-12 |
| 取代範圍 | 取代 [`spec.pdf`](../spec.pdf)（V1.0，2026-06-25）中屬於第一階段的部分；`spec.pdf` 其餘內容（舞蹈分類、MIDI/特效）移到 Phase 2 |
| 狀態 | 韌體已編譯、PC 端已測試；**尚未在實體 ESP32 上驗證**。第 7 節的驗收數字是我提出的初始目標，需要你確認，並在第一輪實測後修訂 |

---

## 1. 目的與範圍

### 1.1 目標

用兩塊 **ESP32 (ESP-WROOM-32)** 取得穩定的 Wi-Fi CSI 資料流，傳到 PC，並在 PC 上即時判斷感測區內**是否有人在移動**。同時建立可重複使用的資料錄製流程，為 Phase 2 的動作分類準備資料。

Phase 1 只回答一個問題：**這套硬體在你的房間裡，能不能可靠地看見「有人在動」？**

### 1.2 非目標（Phase 1 不做）

| 項目 | 原因 |
|---|---|
| 火柴人 / 人體骨架 / DensePose | 兩塊 ESP32 只有一條 1×1 的鏈路，無法重建關節（見第 2 節） |
| 舞蹈動作分類（Idle / Jump / Spin / Arm_Wave） | 需要 Phase 1 錄到的真實資料才能訓練與評估 |
| MIDI、視覺特效 | 依賴分類器 |
| 靜止人體偵測、呼吸、心率 | 動作偵測器只對「移動」有反應 |
| 多人、穿牆、跨房間泛化 | 超出兩塊 ESP32 的能力，且研究顯示跨環境會明顯退化 |
| 在 ESP32 上跑推論（Edge Impulse） | 先在 PC 上確認有資料可學，再決定是否部署 |

### 1.3 與 spec.pdf V1.0 的差異

| 項目 | spec.pdf V1.0 | Phase 1 | 原因 |
|---|---|---|---|
| 晶片 | ESP32-S3 | **原版 ESP32 (ESP-WROOM-32)** | 你手上的板子。Espressif 官方範例對原版 ESP32 可用，但沒有 CSI 增益補償 |
| 取樣率 | 50 ~ 100 Hz | 預設 100 Hz，最低接受 50 Hz | 同 spec |
| 系統延遲 | < 100 ms | **不承諾**（見 R-5） | 偵測器用滑動視窗，放開延遲設計上約 1 s |
| 推論位置 | Edge Impulse 在 ESP32 或 PC | Phase 1 只在 PC | 先有資料再決定 |
| 序列埠速率 | ≥ 115200 | **921600** | 100 Hz 的 CSI 約 44 KB/s，115200 baud 只有約 11.5 KB/s，無法承載 |

---

## 2. 背景：為什麼 Phase 1 不做火柴人

已查證的事實（2026-10-11 ~ 12）：

- WiPose、DensePose From WiFi、Person-in-WiFi 3D 是真實的研究，但使用多天線研究級網卡（3×3 MIMO）、多個接收端、電腦端 GPU 模型，並且主要在**同一個環境**訓練與測試。
- 與 ESP32 相關的開源專案 [ruvnet/RuView](https://github.com/ruvnet/RuView) 的 README 自述：單顆 ESP32 空間解析度有限；即時單 ESP32 17 關節模型為「first-cut」，PCK@20 約 3.0%；其 82.69% 是公開資料集 MM-Fi 的離線結果，「不是即時單顆 ESP32 的數字」。其 [issue #509](https://github.com/ruvnet/RuView/issues/509) 中維護者承認原先的 UI 骨架由訊號門檻驅動，且沒有可出貨的 17 關節模型。
- 跨環境泛化：模型換房間或換佈局後會明顯退化（[Exposing the CSI](https://arxiv.org/pdf/2302.00992)、[RePos](https://arxiv.org/pdf/2607.02986)，後者為 2026 年 preprint，未確認是否通過同行審查）。

結論：兩塊 ESP32 能做「有沒有動、動作像哪一類」，做不到「手肘在哪裡」。若 Phase 2 之後仍要火柴人，只有兩種誠實的做法：(a) 攝影機 + MediaPipe；(b) 示意動畫，由分類結果觸發，**並明確標示不是真實姿態**。

---

## 3. 系統架構

```
 發送端 ESP32               接收端 ESP32                    PC
 csi_send  ──ESP-NOW 廣播──▶ csi_recv ──USB 序列埠──▶ csi-motion
 (固定間隔發封包)            (擷取 CSI → queue → 輸出)   check / live / record
```

### 3.1 韌體

| 元件 | 路徑 | 職責 |
|---|---|---|
| `csi_common` | `firmware/components/csi_common` | Wi-Fi STA、HT20、固定通道、關閉省電；ESP-NOW 廣播 peer（HT20 / MCS0 / long GI） |
| `csi_send` | `firmware/csi_send` | 以固定間隔廣播 4 位元組計數器；固定 MAC `1a:00:00:00:00:00` |
| `csi_recv` | `firmware/csi_recv` | CSI 回呼只做搬運進 queue，低優先任務格式化並輸出；每秒輸出 `CSI_STAT` |

設計約束（來自 ESP-IDF 文件）：CSI 回呼在 Wi-Fi 任務內執行，不可做耗時工作；`esp_wifi_set_mac` 只能在介面停用時呼叫（放在 `esp_wifi_start` 之前）。

### 3.2 PC 端（`host/`，Python ≥ 3.9）

| 模組 | 職責 |
|---|---|
| `protocol` | 解析 `CSI_DATA` / `CSI_STAT`；損毀行丟出 `ValueError` 供計數 |
| `csi` | 取 LLTF 振幅；正規化以抵銷增益變動 |
| `detector` | 校準 + 動作偵測 |
| `stats` | 取樣率、遺失率、RSSI 等串流品質 |
| `source` | 序列埠 / 檔案重播 / 模擬資料三種來源 |
| `live`、`cli` | 即時視圖與指令 `ports` `check` `record` `live` |

### 3.3 介面契約：序列埠格式（921600 baud，8N1，文字行）

```
CSI_INFO,channel=<n>,send_ltf=<lltf|lltf+htltf>          開機時一行
type,id,mac,rssi,...,first_word,data                      標頭行（25 欄）
CSI_DATA,<id>,<mac>,<rssi>,<rate>,<sig_mode>,<mcs>,<bandwidth>,<smoothing>,<not_sounding>,
         <aggregation>,<stbc>,<fec_coding>,<sgi>,<noise_floor>,<ampdu_cnt>,<channel>,
         <secondary_channel>,<local_timestamp>,<ant>,<sig_len>,<rx_format>,<len>,<first_word>,"[...]"
CSI_STAT,<device_ms>,<rx_total>,<dropped>                  每秒一行
```

- `CSI_DATA` 與 Espressif esp-csi 範例的欄位相同（共 25 欄）。`id` 為發送端計數器，讀不到時為 `4294967295`。
- `data` 是 int8 陣列，每個子載波依序為 `[虛部, 實部]`；LLTF 共 64 個子載波，順序 `0..31, -32..-1`，因此 `len = 128`。
- `local_timestamp` 為接收端 32 位元微秒時鐘，韌體以有號整數印出，**約 35 分鐘後會變成負數**，PC 端須以 `& 0xFFFFFFFF` 還原。
- `first_word = 1` 表示前 4 位元組（子載波 0 與 1）硬體上無效。
- PC 端使用 51 個子載波：`-26..-1` 與 `2..26`（排除 DC 0、無效的 1，以及保護頻帶）。
- 非 `CSI_` 開頭的行（開機訊息、亂碼）一律忽略。

---

## 4. 硬體與擺放

### 4.1 設備

| 項目 | 規格 | 數量 |
|---|---|---|
| 接收端 | ESP-WROOM-32 開發板，接 PC，USB **資料線** | 1 |
| 發送端 | ESP-WROOM-32 開發板，USB 供電（電腦或行動電源） | 1 |
| 固定支架 | 相機腳架或燈架，高度可調至 1.0 ~ 1.2 m | 2 |
| PC | Windows / macOS / Linux，Python ≥ 3.9，ESP-IDF v5.5.x（驗證版本 5.5.1） | 1 |

成本目標沿用 spec.pdf（新台幣 1,000 元內）；Phase 1 不新增硬體。

### 4.2 擺放（沿用 spec.pdf 第 3 節，並加入官方建議）

- 兩板直線距離 **2.0 m**（官方範例建議 > 1 m）；高度 **1.0 ~ 1.2 m**（約成人腰到胸）；天線朝向一致。
- 感測區內不可有其他人走動，也不要有風扇、窗簾等會動的物體。校準與錄製期間尤其重要。
- ESP-WROOM-32 為板載 PCB 天線，具指向性；Espressif 建議外接天線效果較好。若實測不足，備案是改用帶 IPEX 接頭的 ESP32-WROOM-32U。
- Wi-Fi 通道預設 11，兩板必須相同；用手機的 Wi-Fi 分析器挑最空的通道。

---

## 5. 功能需求

狀態欄：**編譯** = 韌體已通過 ESP-IDF 5.5.1 編譯；**測試** = 有自動測試；**待實測** = 需要實體板子才能驗證。

### 5.1 發送端 `csi_send`

| ID | 需求 | 狀態 |
|---|---|---|
| FR-S1 | 以 `CONFIG_CSI_SEND_PERIOD_MS`（2 ~ 1000 ms，預設 10）的固定間隔廣播 ESP-NOW 封包，內容為遞增的 32 位元計數器 | 編譯 / 待實測 |
| FR-S2 | 固定 MAC `1a:00:00:00:00:00`，使用 HT20、MCS0、long GI，通道由 `CONFIG_CSI_CHANNEL`（1 ~ 13，預設 11）決定 | 編譯 / 待實測 |
| FR-S3 | 發射功率由 `CONFIG_CSI_TX_POWER_QDBM` 設定（單位 0.25 dBm，8 ~ 84，預設 40 = 10 dBm） | 編譯 / 待實測 |
| FR-S4 | 每 5 秒記錄已送出數與送出失敗數；間隔短於一個 FreeRTOS tick 時編譯期報錯 | 編譯 |

### 5.2 接收端 `csi_recv`

| ID | 需求 | 狀態 |
|---|---|---|
| FR-R1 | 啟用 CSI，僅接受來自固定發送 MAC 的封包 | 編譯 / 待實測 |
| FR-R2 | 預設只擷取 LLTF（128 個數值）；`CONFIG_CSI_USE_HTLTF` 可附加 HT-LTF | 編譯（兩種都過） |
| FR-R3 | CSI 回呼只複製資料進 queue（`CONFIG_CSI_QUEUE_LEN`，預設 32）；格式化與輸出在固定於核心 1 的低優先任務 | 編譯 / 待實測 |
| FR-R4 | queue 滿時丟棄並計數，不得阻塞 Wi-Fi 任務；每輸出 8 筆讓出一個 tick，避免餓死 idle task | 編譯 / 待實測 |
| FR-R5 | 每秒輸出 `CSI_STAT,<device_ms>,<rx_total>,<dropped>` | 編譯 / 待實測 |
| FR-R6 | 輸出格式符合 3.3 節，共 25 欄 | 測試（欄數與欄位順序已與解析器對照） |

### 5.3 PC 端 `csi-motion`

| ID | 需求 | 狀態 |
|---|---|---|
| FR-P1 | `ports`：列出序列埠 | 待實測 |
| FR-P2 | `check`：收集指定秒數（預設 10），回報封包數、取樣率（以接收端時鐘計）、遺失率（依計數器）、RSSI、底噪、通道、CSI 長度、接收端丟包、損毀行數、發送端計數器跳變與接收端重啟次數，並給出警告 | 測試 |
| FR-P3 | `check` 的警告條件：取樣率 < 50 Hz、遺失率 > 5%、接收端丟包 > 0、RSSI 平均 < -75 dBm、含非 20 MHz LLTF 封包、發送端計數器跳變多於 1 次、接收端重啟（`CSI_STAT.device_ms` 倒退）；完全沒資料時列出原因並以非零碼結束 | 測試 |
| FR-P4 | `live`：開頭校準（預設 5 秒，以接收端時間戳計），之後顯示 `IDLE` / `MOTION`；上圖為扣除背景的振幅熱圖，下圖為動作分數與門檻；按 `c` 重新校準 | 測試（渲染）/ 待實測 |
| FR-P5 | `record`：`--label`（僅 `[A-Za-z0-9_-]`）、`--seconds`（預設 30）、`--countdown`（預設 3）；輸出 `data/<label>_<時間>.csv`（原始 `CSI_DATA` 行，含標頭）與 `.json`（標籤、封包數、取樣率、遺失率、是否模擬） | 測試 |
| FR-P6 | `--file` 重播錄製檔、`--simulate` 使用模擬資料；模擬模式必須在終端機與圖表標題明確標示非真實 CSI | 測試 |
| FR-P7 | 開啟序列埠時不主動拉動 DTR/RTS，避免重置板子（部分系統仍可能重置） | 待實測 |

### 5.4 動作偵測演算法（FR-P4 的細節）

1. 取 51 個子載波的振幅，除以其平均值（抵銷增益變動）。
2. 變化分數 = `1 − Pearson(目前封包, 往前 lag 個封包)`，`lag` 預設 5。
3. 動作分數 = 最近 `window` 個變化分數的平均，`window` 預設 50。
4. 校準期間記錄分數：`門檻 = 平均 + k × max(標準差, 0.1 × 平均, 1e-4)`，`k` 預設 6；解除門檻 = 平均 + 0.5 × 邊界。
5. 分數超過門檻 → `MOTION`；分數連續 `hold_packets`（預設 50）個封包低於解除門檻 → 回到 `IDLE`。
6. 校準時間以封包的接收端時間戳累計，不受 PC 時間影響；間隔 ≥ 1 s 的跳變不計入。

---

## 6. 非功能需求

| ID | 需求 |
|---|---|
| NFR-1 | 取樣率：預設 100 Hz；低於 50 Hz 視為不合格 |
| NFR-2 | 序列埠頻寬：LLTF 約 44 KB/s（以官方範例的真實資料行 437 位元組估算），HT-LTF 約 76 KB/s，上限約 92 KB/s。開 HT-LTF 時發送頻率不得高於 50 Hz，並以 `dropped` 為準 |
| NFR-3 | 韌體以 ESP-IDF v5.5.x 編譯，`esp32` 目標，無警告 |
| NFR-4 | PC 端在 Windows、macOS、Linux 皆可執行；依賴僅 numpy、pyserial、matplotlib |
| NFR-5 | 隱私：不使用攝影機與麥克風；錄製資料只存在本機 `host/data/`，已被 git 忽略 |
| NFR-6 | 可重現：韌體設定集中在 `sdkconfig.defaults` 與 Kconfig；測試不需要硬體 |

---

## 7. 驗收標準

> 以下數字是**我提出的初始目標**，不是量測結果。請確認或調整；第一輪實測後我會依實際數據修訂。「方法」欄是量測方式。

| ID | 驗收項目 | 通過條件 | 方法 |
|---|---|---|---|
| AC-1 | 串流健康 | 預設 100 Hz 設定下，`check --seconds 60`：取樣率 ≥ 90 Hz、遺失率 ≤ 5%、接收端丟包 = 0、平均 RSSI ≥ -75 dBm | 兩板依第 4 節擺放，無人在區內 |
| AC-2 | 靜止誤報 | 校準後空場 10 分鐘，處於 `MOTION` 狀態的時間 ≤ 2%，且觸發次數 ≤ 2 次 | `live` 持續執行；人離開感測區 |
| AC-3 | 偵測率 | 在兩板連線區內各做 20 次：揮手、原地走動、原地跳，每種至少 18 次（90%）被判為 `MOTION` | 每次動作 3 秒，間隔 ≥ 5 秒靜止，人工記錄 |
| AC-4 | 起始延遲 | 動作開始到顯示 `MOTION` 的中位數 ≤ 300 ms | 手機 240 fps 慢動作同時拍人與螢幕，逐格估算 |
| AC-5 | 長時間穩定 | 連續 30 分鐘：接收端重啟 = 0 次、發送端計數器跳變 ≤ 1 次，且取樣率與遺失率仍符合 AC-1 | `check --seconds 1800`，看「重啟/跳變」那一行 |
| AC-6 | 錄製可用 | 錄 4 種標籤各 1 段 30 秒，用 `check --file` 重播，封包數與 `.json` 一致，損毀行 = 0 | 見 8 節 |
| AC-7 | 軟體品質 | `pytest` 全數通過；兩個韌體專案編譯無警告 | CI 或本機 |

放開延遲（`MOTION` → `IDLE`）不列入驗收：設計上約 1 s（`hold_packets` = 0.5 s + 分數視窗衰減約 0.5 s），在模擬資料上實測為 1.04 s。

---

## 8. 資料收集協定（為 Phase 2 準備）

目的：避免模型只記住「這個房間、這個人、這個站位」。已知跨環境會明顯退化，所以變因要在**同一環境內**盡量涵蓋。

- 標籤：`idle`、`jump`、`spin`、`arm_wave`（沿用 spec.pdf）。
- 每個標籤至少錄 **10 段 × 30 秒**。
- 變因：至少 3 個站位（連線中央、偏左 0.5 m、偏右 0.5 m）；至少 2 個不同日期或時段；有衣著或持物變化時在 `.json` 備註。
- 每次錄製前先跑 `check`，不合格（AC-1 條件）的資料不收。
- 訓練 / 驗證切分以**錄製場次**為單位，不可把同一段錄音切到兩邊（否則評估會虛高）。

---

## 9. 風險與限制

| ID | 風險 | 影響 | 對策 |
|---|---|---|---|
| R-1 | 原版 ESP32 沒有 CSI 增益補償（S3 / C 系列才有） | 絕對振幅受 AGC 影響而跳動 | 偵測器用正規化 + 相關係數；若仍不穩，備案是換 ESP32-S3 或 C6 |
| R-2 | PCB 天線有指向性且易受主板干擾 | 靈敏度與擺放高度、角度相關 | 固定天線朝向；備案 ESP32-WROOM-32U + 外接天線 |
| R-3 | 2.4 GHz 環境干擾（路由器、藍牙、微波爐） | 遺失率與誤報上升 | 選最空的通道；降低發射功率縮小感知範圍 |
| R-4 | 偵測器只對「移動」有反應 | 站著不動不會被偵測到 | 已寫入非目標；靜止偵測不在 Phase 1 |
| R-5 | spec.pdf 的 < 100 ms 延遲目標 | 滑動視窗與放開保持使放開延遲約 1 s；起始延遲待實測。舞蹈節奏觸發特效可能需要更短反應 | Phase 1 不承諾；Phase 2 分類器需另做視窗設計並重新評估 |
| R-6 | 序列埠頻寬餘裕有限（尤其開 HT-LTF） | 接收端丟包 | `CSI_STAT.dropped` 可觀測；降頻或提高 baud（韌體與 `--baud` 同步） |
| R-7 | 封包計數器的讀取位置（payload 偏移 15）沿用官方範例，未在實體板子上驗證 | 遺失率統計可能無意義 | `check` 會顯示計數器跳變；若異常，只影響統計，不影響偵測 |
| R-8 | 偵測器參數（`window`、`lag`、`k`）未用真實資料調校；單元測試只用模擬資料 | 真實環境的誤報 / 漏報未知 | 第一輪實測後依 AC-2、AC-3 調整 |
| R-9 | 跨環境、跨人退化 | 換房間或換人後需重新校準 / 重錄 | 已知限制；第 8 節的收集協定降低同環境過擬合 |
| R-10 | 部分開發板開啟序列埠會觸發重置 | 啟動後前 1 ~ 2 秒沒有資料 | 文件已說明；`check` 在無資料時列出此可能 |

---

## 10. 開放決策（需要你回答）

1. **火柴人路線**：
   - A. 只做動作分類，火柴人僅作為分類結果的示意動畫（誠實標示）。
   - B. 同步用攝影機 + MediaPipe 錄骨架，作為研究實驗，檢驗 CSI → 骨架是否可行（預期結果不佳）。
   - C. 兩者並行（我的建議：A 為主，B 只做資料收集）。
2. **驗收數字**（第 7 節）是否接受，或要放寬 / 加嚴。
3. **晶片備案**：實測效果不足時，是否願意購入 ESP32-S3 或 ESP32-C6（官方範例列為最佳 RF 晶片）。
4. **分類器部署位置**（Phase 2）：PC 端 scikit-learn / 1D-CNN，或 Edge Impulse 部署回 ESP32。

---

## 11. 里程碑

| 階段 | 內容 | 完成條件 |
|---|---|---|
| M1（已完成） | 韌體、PC 端工具、測試 | 編譯通過、測試通過（現為 37 個）；初版 commit `be240d7` |
| M2 | 實體驗證與調參 | AC-1 ~ AC-5 通過（或依數據修訂標準） |
| M3 | 資料收集 | AC-6，並依第 8 節收齊資料 |
| Phase 2 | 動作分類、MIDI / 特效、（選）示意動畫 | 另立規格 `specs/phase2.md` |

---

## 附錄 A：設定參數

**韌體（`idf.py menuconfig`）**

| 選項 | 位置 | 範圍 | 預設 |
|---|---|---|---|
| `CSI_CHANNEL` | CSI Motion Sensor (common) | 1 ~ 13 | 11 |
| `CSI_TX_POWER_QDBM` | CSI Motion Sensor (common)（僅發送端） | 8 ~ 84 | 40（10 dBm） |
| `CSI_SEND_PERIOD_MS` | CSI Sender | 2 ~ 1000 | 10（100 Hz） |
| `CSI_USE_HTLTF` | CSI Receiver | 開 / 關 | 關 |
| `CSI_QUEUE_LEN` | CSI Receiver | 4 ~ 256 | 32 |
| 序列埠速率 | `sdkconfig.defaults` | — | 921600 |

**PC 端**

| 參數 | 指令 | 預設 |
|---|---|---|
| `--port` / `--file` / `--simulate` | 全部 | 三擇一 |
| `--baud` | 全部 | 921600 |
| `--seconds` | `check`、`record` | 10、30 |
| `--baseline-seconds` | `live` | 5 |
| `--label`、`--countdown`、`--out` | `record` | 必填、3、`data` |
| `--pace` | `--file` 重播 | 100 封包/秒 |
| 偵測器 `window`、`lag`、`k`、`hold_packets` | `host/csi_motion/detector.py` | 50、5、6.0、50 |

## 附錄 B：參考資料

- [Espressif esp-csi](https://github.com/espressif/esp-csi)（get-started 範例，Apache-2.0 / CC0）
- ESP-IDF Wi-Fi 指南「Wi-Fi Channel State Information」（子載波順序、位元組數、`first_word_invalid`）
- [ruvnet/RuView](https://github.com/ruvnet/RuView) 與 [issue #509](https://github.com/ruvnet/RuView/issues/509)
- [Exposing the CSI](https://arxiv.org/pdf/2302.00992)、[RePos](https://arxiv.org/pdf/2607.02986)

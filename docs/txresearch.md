# 微型臺指期貨 TMF 多空研究與紙上交易系統規格

**文件版本：** 1.1.0
**專案代號：** `tmf-research-agent`
**行情來源：** 永豐 Shioaji API
**執行模式：** Research Only
**實際下單：** 永久禁止
**主要研究目標：** 建立具樣本外穩定性的多空機率模型，而非追求回測最大獲利

---

# 1. 專案目標

建立一套針對微型臺指期貨近月契約的研究系統，完成：

1. 接收 Shioaji 即時 Tick。
2. 接收 Shioaji 即時 BidAsk。
3. 取得歷史 Tick 與分鐘 K 棒。
4. 保存不可修改的原始行情。
5. 建立 1 秒、1 分鐘、5 分鐘、15 分鐘及 60 分鐘資料。
6. 計算價格、成交量、成交流、五檔、基差、波動率及市場結構特徵。
7. 建立 `LONG`、`SHORT`、`NO_TRADE` 標記。
8. 建立 Logistic Regression 基準模型。
9. 使用 Purged Walk-Forward Validation 驗證模型。
10. 建立歷史事件重播。
11. 建立即時推論。
12. 執行紙上交易。
13. 輸出模型機率、資料品質、訊號理由及樣本外績效。
14. 建立完整的過擬合、資料洩漏及研究偏誤檢查。
15. 永久禁止實際委託、改單與刪單。

本系統不得以「精確預測下一個價格」作為目標。

主要輸出固定為：

```text
LONG
SHORT
NO_TRADE
```

每次輸出必須同時包含：

```text
P(LONG)
P(SHORT)
P(NO_TRADE)
市場狀態
資料品質
模型版本
特徵版本
預期移動點數
估計交易成本
訊號成立理由
不交易理由
```

---

# 2. 研究標的

研究商品固定為：

```text
商品：微型臺指期貨
代碼：TMF
連續近月別名：TMFR1
每點價值：新臺幣 10 元
```

微型臺指期貨契約價值為指數乘上新臺幣 10 元，一般交易時段為 08:45–13:45，盤後交易時段為 15:00–次日 05:00；到期月份最後交易日的一般交易時段提早於 13:30 結束，且沒有盤後交易。

Shioaji 行情介面支援期貨 Tick 與 BidAsk 訂閱，歷史行情介面支援 Tick 與分鐘 K 棒查詢。

系統使用連續近月別名取得目前近月商品，但所有資料必須同時保存實際契約代碼：

```text
alias_code
target_code
delivery_month
delivery_date
resolved_at
```

不得只保存 `TMFR1`。

---

# 3. 專案範圍

## 3.1 第一階段包含

第一階段只研究 TMF 自身資料：

```text
TMF Tick
TMF BidAsk
TMF underlying price
TMF 歷史 Tick
TMF 歷史 K 棒
日盤
夜盤
近月換月
紙上交易
```

第一階段不加入：

```text
TXF
MTX
臺指選擇權
Put/Call Ratio
三大法人
外資未平倉量
美股期貨
匯率
新聞
社群情緒
大型語言模型方向判斷
深度學習
強化學習
```

外部因子只能在 TMF 單商品基準完成後，以獨立實驗加入。

## 3.2 永久排除

永久禁止：

```text
實際下單
模擬交易環境下單
改單
刪單
預約單
觸價單
帳務查詢
持倉查詢
保證金查詢
CA 憑證啟用
交易帳號操作
建立委託物件
呼叫委託端點
自動交易
半自動交易
一鍵轉送委託
```

Shioaji 的期貨委託流程包含 CA 啟用、`FuturesOrder` 與 `place_order`；本專案禁止實作或呼叫這些功能。

---

# 4. 唯讀安全架構

## 4.1 原始 API 隔離

只有以下基礎設施模組可以持有原始 Shioaji API 物件：

```text
src/tmf_research/infrastructure/shioaji_market_data.py
```

其他模組只能依賴：

```python
class MarketDataGateway(Protocol):
    def resolve_near_contract(self) -> ContractInfo: ...
    def subscribe_tick(self, contract: ContractInfo) -> None: ...
    def subscribe_bidask(self, contract: ContractInfo) -> None: ...
    def unsubscribe_tick(self, contract: ContractInfo) -> None: ...
    def unsubscribe_bidask(self, contract: ContractInfo) -> None: ...
    def fetch_ticks(self, contract: ContractInfo, date: str) -> TickBatch: ...
    def fetch_kbars(
        self,
        contract: ContractInfo,
        start: str,
        end: str,
    ) -> KbarBatch: ...
```

策略、模型、紙上交易及服務層不得取得原始 Shioaji API 物件。

## 4.2 禁止符號

`src/` 中禁止出現：

```text
activate_ca
place_order
update_order
update_price
update_qty
cancel_order
FuturesOrder
StockOrder
ReserveOrder
TouchPrice
OrderExecutor
LiveBroker
ShioajiBroker
```

若第三方套件型別定義或測試 fixture 必須提及禁止字串，必須：

1. 放在安全掃描程式的 allowlist。
2. 註明存在理由。
3. 不得形成可執行呼叫路徑。

## 4.3 安全掃描

建立：

```text
src/tmf_research/security/readonly_verifier.py
tests/security/test_readonly_boundary.py
```

檢查方式同時包含：

```text
AST 掃描
import graph 掃描
字串掃描
Protocol 邊界測試
依賴方向測試
```

CI 第一個步驟固定執行：

```bash
tmf verify-readonly
```

失敗時停止全部測試。

## 4.4 紙上交易隔離

唯一允許的交易類別：

```python
class PaperBroker:
    ...
```

不得建立：

```text
Broker
ExecutionBroker
LiveExecution
OrderGateway
RealBroker
```

`PaperBroker` 不得：

```text
接收 Shioaji API 物件
接收交易帳號
接收 CA
發送網路請求
呼叫任何券商方法
```

---

# 5. 系統架構

```text
Shioaji Market Data
        │
        ▼
ReadOnly MarketDataGateway
        │
        ├── Contract Resolver
        ├── Tick Subscriber
        ├── BidAsk Subscriber
        └── Historical Downloader
        │
        ▼
Bounded Event Queue
        │
        ├── Raw Tick Writer
        ├── Raw BidAsk Writer
        └── Connection Event Writer
        │
        ▼
Append-only Raw Storage
        │
        ▼
Session Resolver
        │
        ▼
Aggregation Pipeline
        │
        ├── 1-second State
        ├── 1-minute Bars
        ├── 5-minute Bars
        ├── 15-minute Bars
        └── 60-minute Bars
        │
        ▼
Feature Pipeline
        │
        ▼
Label Pipeline
        │
        ▼
Research Dataset
        │
        ▼
Nested Walk-Forward Validation
        │
        ├── Baseline Models
        ├── Logistic Regression
        ├── Calibration
        ├── Stability Analysis
        └── Overfitting Diagnostics
        │
        ▼
Locked Model Registry
        │
        ├── Historical Replay
        └── Live Research Inference
                │
                ▼
PaperBroker
```

---

# 6. 專案目錄

```text
tmf-research-agent/
├── README.md
├── SPEC.md
├── AGENTS.md
├── pyproject.toml
├── data/
│   ├── raw/
│   ├── normalized/
│   ├── bars/
│   ├── features/
│   ├── labels/
│   ├── datasets/
│   ├── predictions/
│   ├── paper_trades/
│   ├── experiments/
│   ├── reports/
│   └── registry/
├── src/
│   └── tmf_research/
│       ├── cli.py
│       ├── domain/
│       │   ├── contracts.py
│       │   ├── events.py
│       │   ├── predictions.py
│       │   ├── sessions.py
│       │   └── paper_trades.py
│       ├── infrastructure/
│       │   ├── shioaji_market_data.py
│       │   ├── readonly_gateway.py
│       │   ├── contract_resolver.py
│       │   ├── reconnect_manager.py
│       │   ├── raw_store.py
│       │   └── data_catalog.py
│       ├── collection/
│       │   ├── live_collector.py
│       │   ├── historical_downloader.py
│       │   ├── event_queue.py
│       │   └── raw_writer.py
│       ├── processing/
│       │   ├── normalize.py
│       │   ├── session_resolver.py
│       │   ├── quote_joiner.py
│       │   ├── one_second.py
│       │   └── bars.py
│       ├── features/
│       │   ├── definitions.py
│       │   ├── price.py
│       │   ├── volume.py
│       │   ├── orderflow.py
│       │   ├── orderbook.py
│       │   ├── basis.py
│       │   ├── volatility.py
│       │   ├── structure.py
│       │   ├── time_features.py
│       │   └── pipeline.py
│       ├── labeling/
│       │   ├── executable_prices.py
│       │   ├── triple_barrier.py
│       │   └── pipeline.py
│       ├── models/
│       │   ├── baselines.py
│       │   ├── scaler.py
│       │   ├── logistic.py
│       │   ├── calibration.py
│       │   ├── inference.py
│       │   └── serialization.py
│       ├── validation/
│       │   ├── folds.py
│       │   ├── purging.py
│       │   ├── nested_walk_forward.py
│       │   ├── metrics.py
│       │   ├── stability.py
│       │   ├── overfitting.py
│       │   ├── ablation.py
│       │   └── report.py
│       ├── experiments/
│       │   ├── registry.py
│       │   ├── search_budget.py
│       │   └── comparison.py
│       ├── paper/
│       │   ├── broker.py
│       │   ├── fill_model.py
│       │   ├── risk.py
│       │   └── replay.py
│       ├── runtime/
│       │   ├── feature_state.py
│       │   ├── live_research.py
│       │   └── health.py
│       └── security/
│           └── readonly_verifier.py
└── tests/
    ├── unit/
    ├── integration/
    ├── regression/
    ├── leakage/
    ├── overfitting/
    ├── replay/
    ├── security/
    └── fixtures/
```

既有登入、連線、憑證、套件及執行環境設定沿用目前專案，不列入本規格。

---

# 7. 契約解析與換月

## 7.1 近月解析

系統啟動時解析：

```text
TMFR1
```

並保存：

```text
alias_code
target_code
symbol
category
delivery_month
delivery_date
resolved_at
resolver_version
```

## 7.2 禁止做法

不得：

```text
將實際月份寫死
依商品代碼字尾猜月份
只保存 TMFR1
以當日收盤後資料回頭決定盤中契約
把換月價格跳空視為真實報酬
把不同月份契約直接無調整串接
```

## 7.3 換月事件

發現以下變化時建立事件：

```text
old_target_code != new_target_code
OR
old_delivery_month != new_delivery_month
```

事件包含：

```text
detected_at
effective_from
old_target_code
new_target_code
old_delivery_month
new_delivery_month
resolver_version
```

換月狀態未確認時：

```text
signal = NO_TRADE
allow_paper_trade = false
```

---

# 8. 即時行情處理

Callback 中只允許：

1. 接收資料。
2. 解析最小必要欄位。
3. 加入本機接收時間。
4. 放入 bounded queue。
5. 立即返回。

Callback 中禁止：

```text
訓練模型
執行模型推論
計算完整指標
寫入大型檔案
查詢歷史資料
呼叫外部服務
執行紙上交易
等待鎖
sleep
```

官方 Shioaji 文件也提供將 Tick/BidAsk 放入 queue 的行情綁定模式；本系統採用 queue 隔離行情接收與後續處理。

## 8.1 Queue 行為

Queue 滿載時：

1. 不得阻塞行情 callback。
2. 增加 `dropped_event_count`。
3. 建立 `QUEUE_BACKPRESSURE` 事件。
4. 將資料品質標記為失效。
5. 停止產生紙上交易訊號。
6. 不得靜默丟棄。

---

# 9. 原始資料

## 9.1 TickEvent

```text
event_id
schema_version
received_at
exchange_datetime
latency_ms
alias_code
target_code
delivery_month
trading_date
session
code
open
high
low
close
avg_price
underlying_price
amount
total_amount
volume
total_volume
tick_type
price_chg
pct_chg
bid_side_total_volume
ask_side_total_volume
simtrade
raw_payload
```

## 9.2 BidAskEvent

```text
event_id
schema_version
received_at
exchange_datetime
latency_ms
alias_code
target_code
delivery_month
trading_date
session
code
bid_price_1
bid_price_2
bid_price_3
bid_price_4
bid_price_5
bid_volume_1
bid_volume_2
bid_volume_3
bid_volume_4
bid_volume_5
ask_price_1
ask_price_2
ask_price_3
ask_price_4
ask_price_5
ask_volume_1
ask_volume_2
ask_volume_3
ask_volume_4
ask_volume_5
diff_bid_volume_1
diff_bid_volume_2
diff_bid_volume_3
diff_bid_volume_4
diff_bid_volume_5
diff_ask_volume_1
diff_ask_volume_2
diff_ask_volume_3
diff_ask_volume_4
diff_ask_volume_5
underlying_price
simtrade
raw_payload
```

## 9.3 ConnectionEvent

```text
event_id
occurred_at
event_type
connection_status
attempt_number
reason
last_tick_at
last_bidask_at
queue_size
dropped_event_count
```

## 9.4 Raw Data 原則

Raw Data 必須：

```text
append-only
不可覆寫
不可事後修改
保留原始 payload
具 checksum
具 schema version
具 writer version
具時間範圍
```

修正資料處理邏輯時，建立新的 dataset version，不修改舊資料。

---

# 10. 時段與交易日

## 10.1 Session

```text
DAY
NIGHT
CLOSED
```

## 10.2 Trading Date

不得以日曆日期直接當作交易日。

夜盤交易日必須依交易所行事曆解析：

```text
15:00–23:59：歸屬下一個有效交易日
00:00–05:00：歸屬當前有效交易日
```

週末、國定假日、颱風休市及臨時休市不得使用簡單加一天處理。

## 10.3 K 棒對齊

日盤 K 棒以：

```text
08:45
```

為 session 起點。

夜盤 K 棒以：

```text
15:00
```

為 session 起點。

不得使用 Unix 整點直接切割 5 分鐘、15 分鐘及 60 分鐘 K 棒。

---

# 11. Tick 與 BidAsk 對齊

每個 Tick 只能匹配該 Tick 發生時間以前最近的一筆 BidAsk：

```text
bidask.exchange_datetime <= tick.exchange_datetime
```

使用：

```text
backward as-of join
```

禁止：

```text
nearest join
forward join
使用未來 BidAsk
```

保存：

```text
matched_bidask_at
quote_age_ms
bidask_available
```

BidAsk 過期時：

```text
bidask_available = false
```

不得用於：

```text
Spread 特徵
五檔特徵
可成交價格標記
紙上進場
紙上出場
```

---

# 12. 聚合資料

## 12.1 一秒狀態

每秒輸出：

```text
second
open
high
low
close
volume
trade_count
buy_volume
sell_volume
unknown_volume
last_bid
last_ask
spread
midpoint
microprice
level1_imbalance
level3_imbalance
level5_imbalance
underlying_price
basis
last_tick_age_ms
last_bidask_age_ms
```

空秒不得製造虛假成交。

可 forward-fill：

```text
last bid
last ask
midpoint
order book
underlying price
```

不得 forward-fill：

```text
volume
trade count
buy volume
sell volume
```

## 12.2 K 棒

建立：

```text
1m
5m
15m
60m
```

欄位：

```text
bar_start
bar_end
open
high
low
close
volume
trade_count
buy_volume
sell_volume
unknown_volume
vwap
bidask_coverage_ratio
tick_coverage_ratio
is_complete
```

不完整 K 棒不得直接進入訓練。

---

# 13. 資料品質

每個交易日與 Session 產生：

```text
tick_count
bidask_count
duplicate_count
out_of_order_count
invalid_price_count
invalid_depth_count
stale_tick_count
stale_bidask_count
simtrade_count
queue_drop_count
connection_drop_count
maximum_gap_seconds
tick_coverage_ratio
bidask_coverage_ratio
quality_status
```

以下資料不得進入正式研究集：

```text
simtrade=true
價格 <= 0
ask_price_1 < bid_price_1
成交量 < 0
時間無法解析
無法確認 target_code
資料重複
超出有效交易時段
BidAsk 過期
Session 不完整
Queue 發生未處理資料遺失
```

不得靜默刪除，必須保存 rejection reason。

---

# 14. 特徵時間規則

每個特徵必須包含：

```text
feature_time
decision_time
evidence_available_at
feature_version
```

硬性條件：

```text
evidence_available_at <= decision_time
```

不符合時視為資料洩漏，整個實驗失效。

所有 rolling 特徵只允許使用：

```text
timestamp <= decision_time
```

禁止：

```text
centered rolling window
backward fill
全資料正規化
全資料分位數
使用未來 K 棒確認現在訊號
```

---

# 15. 第一版特徵

第一版限制特徵數量，避免在樣本不足時建立高維模型。

初始候選特徵不得超過：

```text
40 個主要數值特徵
10 個 missing indicator
```

正式候選模型使用的主要數值特徵不得超過：

```text
30 個
```

增加特徵必須先完成：

```text
單因子檢查
相關性檢查
跨 Fold 穩定性檢查
Ablation Test
樣本外增益檢查
```

## 15.1 價格與趨勢

```text
return_30s
return_1m
return_3m
return_5m
return_15m
return_30m
return_60m
ema_distance_5
ema_distance_20
ema_slope_5m
ema_slope_15m
ema_slope_60m
consecutive_up_bars
consecutive_down_bars
body_to_range_ratio
upper_wick_ratio
lower_wick_ratio
```

## 15.2 VWAP

```text
session_vwap
rolling_vwap_5m
rolling_vwap_15m
price_to_session_vwap_atr
vwap_slope_5m
vwap_slope_15m
vwap_cross_count_15m
```

日盤與夜盤 VWAP 分開計算。

## 15.3 成交流

```text
aggressive_buy_volume_10s
aggressive_sell_volume_10s
aggressive_buy_volume_1m
aggressive_sell_volume_1m
trade_imbalance_10s
trade_imbalance_30s
trade_imbalance_1m
trade_imbalance_5m
unknown_trade_ratio
volume_acceleration
ticks_per_second
large_trade_ratio
```

Trade imbalance：

```text
(buy_volume - sell_volume)
/
max(buy_volume + sell_volume, epsilon)
```

大單門檻只能使用 Train Fold 的成交量分位數決定。

## 15.4 五檔

```text
spread_points
spread_to_atr
midpoint
microprice
microprice_minus_midpoint
level1_book_imbalance
level3_book_imbalance
level5_book_imbalance
book_imbalance_change_5s
book_imbalance_change_30s
bid_depth_change
ask_depth_change
bid_cancel_pressure
ask_cancel_pressure
quote_update_rate
```

Book imbalance：

```text
(sum_bid_volume - sum_ask_volume)
/
max(sum_bid_volume + sum_ask_volume, epsilon)
```

Microprice：

```text
(
  ask_price_1 * bid_volume_1
  + bid_price_1 * ask_volume_1
)
/
max(bid_volume_1 + ask_volume_1, epsilon)
```

五檔量可撤單，不得將單一五檔特徵直接解讀為方向結論。

## 15.5 基差

```text
basis_points
basis_change_10s
basis_change_1m
basis_change_5m
basis_zscore_30m
price_basis_divergence
```

```text
basis_points = TMF price - underlying_price
```

`underlying_price` 缺失時標記 missing，不得填零。

## 15.6 波動率

```text
true_range_1m
atr_5m
atr_15m
atr_60m
realized_vol_5m
realized_vol_15m
realized_vol_60m
range_expansion_ratio
volatility_percentile
```

分位數只能使用當時以前的資料，或 Train Fold 建立的轉換器。

## 15.7 市場結構

```text
distance_previous_day_high_atr
distance_previous_day_low_atr
distance_previous_close_atr
distance_night_high_atr
distance_night_low_atr
distance_opening_range_high_atr
distance_opening_range_low_atr
break_previous_high
break_previous_low
false_breakout_high
false_breakout_low
```

Swing 類特徵若需要右側 K 棒確認，`evidence_available_at` 必須設定為右側確認完成時間。

## 15.8 時間與契約

```text
session_day
session_night
minutes_from_session_open
minutes_to_session_close
is_first_15m
is_first_30m
is_last_30m
day_of_week
days_to_expiry
is_expiry_week
is_rollover_day
```

---

# 16. 特徵冗餘控制

高度相關特徵不得全部保留。

在每個 Train Fold 中：

1. 計算特徵相關矩陣。
2. 對絕對相關係數高於 `0.90` 的特徵建立群組。
3. 每組優先保留：

   * 資料完整度較高者。
   * 定義較簡單者。
   * 跨 Fold 穩定度較高者。
4. 移除結果只作用於該 Fold。
5. 不得使用 Validation 或 Test 決定保留欄位。

禁止將大量不同週期但高度重複的指標同時放入模型，例如：

```text
EMA 5、6、7、8、9、10
RSI 12、13、14、15、16
ATR 10、11、12、13、14
```

特徵新增必須具明確市場機制，不得只因回測改善而加入。

---

# 17. 標記設計

## 17.1 預測期限

分別建立：

```text
5 分鐘
15 分鐘
60 分鐘
```

第一版主要模型：

```text
15 分鐘
```

三個期限必須使用不同模型與不同標記資料，不得混合。

## 17.2 決策頻率

每一根完整 1 分鐘 K 棒收盤後建立一個候選決策點。

同一時間不得重複建立候選。

## 17.3 可成交價格

多單：

```text
entry = ask_price_1 + entry_slippage
exit = bid_price_1 - exit_slippage
```

空單：

```text
entry = bid_price_1 - entry_slippage
exit = ask_price_1 + exit_slippage
```

不得只用 Close 建立進出場價格。

## 17.4 Triple Barrier

每個候選建立：

```text
upper_barrier
lower_barrier
vertical_barrier
```

目標與停損：

```text
target_points = max(
    target_atr_multiplier * atr,
    minimum_target_points
)

stop_points = max(
    stop_atr_multiplier * atr,
    minimum_stop_points
)
```

所有參數只允許使用 Train 與 Inner Validation 選擇。

## 17.5 標記

```text
先碰上方目標：LONG
先碰下方停損：SHORT
期限內未碰：NO_TRADE
無法判定先後：AMBIGUOUS
```

`AMBIGUOUS` 不進入模型訓練，但必須統計比例。

## 17.6 標記欄位

```text
candidate_id
decision_time
evidence_available_at
outcome_time
horizon
entry_bid
entry_ask
entry_spread
atr_at_entry
upper_barrier
lower_barrier
vertical_barrier
label
first_touch
maximum_favorable_excursion
maximum_adverse_excursion
estimated_cost
label_version
```

---

# 18. 基準模型

任何複雜模型都必須與基準模型比較。

必要基準：

```text
Baseline 0：永遠 NO_TRADE
Baseline 1：前一分鐘方向延續
Baseline 2：價格高於 VWAP 偏多，低於 VWAP 偏空
Baseline 3：EMA slope 規則
Baseline 4：僅使用價格報酬的 Logistic Regression
```

模型只有在多數外層 Walk-Forward Fold 中穩定優於基準，才可進入候選模型。

不得只比較全期間總損益。

---

# 19. 正式模型

第一版正式模型固定為：

```text
Logistic Regression
```

採兩階段架構。

## 19.1 模型 A：是否交易

目標：

```text
TRADE vs NO_TRADE
```

其中：

```text
TRADE = LONG 或 SHORT
```

輸出：

```text
p_trade
p_no_trade
```

## 19.2 模型 B：方向

只使用 Train Fold 中標記為 `LONG` 或 `SHORT` 的樣本。

目標：

```text
LONG vs SHORT
```

輸出：

```text
p_long_given_trade
p_short_given_trade
```

## 19.3 最終機率

```text
p_long = p_trade * p_long_given_trade
p_short = p_trade * p_short_given_trade
p_no_trade = 1 - p_trade
```

驗證：

```text
0 <= probability <= 1
p_long + p_short + p_no_trade = 1
```

## 19.4 複雜度限制

Logistic Regression 必須包含：

```text
L2 正則化
特徵標準化
類別權重
固定收斂條件
固定最大迭代次數
完整訓練紀錄
穩定模型序列化
```

不得使用：

```text
高階多項式自動展開
任意特徵交互作用生成
未受限制的特徵選擇
逐筆人工挑選最佳回測結果
```

第一版交互作用特徵最多：

```text
5 個
```

每個交互作用都必須具明確定義及 ablation 證據。

---

# 20. 過擬合控制原則

過擬合控制為本專案核心要求。

模型不得以以下結果判定成功：

```text
Train Accuracy 高
單一 Test 區間獲利
全資料回測獲利
某個月份特別獲利
最佳參數組獲利
最佳特徵組獲利
```

成功判定必須來自：

```text
多個互不重疊的外層 Test Fold
跨市場狀態穩定性
扣除成本後的樣本外期望值
機率校準
特徵係數穩定性
模型對參數變化不敏感
```

---

# 21. Nested Walk-Forward Validation

使用雙層 Walk-Forward。

## 21.1 外層 Fold

外層只負責最終樣本外評估：

```text
Outer Train
Outer Test
```

Outer Test 不得參與：

```text
特徵選擇
參數選擇
門檻選擇
標記參數選擇
模型選擇
校準器選擇
```

## 21.2 內層 Fold

Outer Train 內再切分：

```text
Inner Train
Inner Validation
```

Inner Validation 用於選擇：

```text
L2 強度
Learning rate
Iteration limit
Trade probability threshold
Direction threshold
Triple Barrier 參數
Calibration method
Feature subset
```

## 21.3 時間切分

禁止：

```text
Random Split
Shuffle
KFold
Stratified Random Split
```

Fold 必須保持時間順序。

## 21.4 Purge

若 Train 樣本的：

```text
outcome_time >= validation_start
```

則從 Train 移除。

若 Validation 樣本的：

```text
outcome_time >= test_start
```

則從 Validation 移除。

## 21.5 Embargo

每個 Validation 與 Test 邊界加入 embargo。

Embargo 長度不得小於：

```text
該模型最大預測期限
```

若模型期限為 60 分鐘，embargo 不得短於 60 分鐘。

---

# 22. 最終鎖定測試集

除了外層 Walk-Forward，必須保留一段完全鎖定資料。

Locked Holdout 必須：

```text
位於全部資料最後方
在模型開發期間不可查看績效
不可用於決定特徵
不可用於決定參數
不可用於選擇門檻
不可重複執行後再調整模型
```

Locked Holdout 長度採：

```text
至少 40 個有效交易日
或全部資料的最後 15%
取較大者
```

若資料不足以同時建立：

```text
Nested Walk-Forward
Locked Holdout
```

則系統只能輸出：

```text
RESEARCH_INSUFFICIENT_DATA
```

不得宣稱模型已驗證。

Locked Holdout 只允許在候選模型、特徵集、參數及決策規則完全凍結後執行一次。

若執行後修改模型，原 Locked Holdout 即視為已污染，必須取得新的未使用資料。

---

# 23. 研究搜尋預算

避免因大量試驗挑中偶然最佳模型。

每個正式研究版本限制：

```text
模型家族：最多 2 種
主要特徵集合：最多 8 組
超參數組合：最多 30 組
Triple Barrier 組合：最多 12 組
訊號門檻組合：最多 12 組
校準方法：最多 3 種
```

每個實驗必須先登記：

```text
experiment_id
hypothesis
feature_set
label_version
parameter_space
evaluation_metric
created_at
```

實驗開始後不得擴大搜尋空間。

禁止：

```text
看到結果後追加附近參數
反覆調整到 Test 獲利
只保存最佳實驗
刪除失敗實驗
```

所有實驗結果必須保存，包括失敗結果。

---

# 24. 模型選擇標準

模型不得因單一指標最佳而勝出。

候選模型必須同時符合：

1. 多數 Outer Test Fold 的淨期望值大於基準。
2. 多數 Outer Test Fold 的 Brier Score 不劣於基準。
3. 多數 Outer Test Fold 的 Log Loss 不劣於基準。
4. 扣成本後仍具有正期望值。
5. 不依賴單一月份。
6. 不依賴單一方向。
7. 不依賴單一高波動事件。
8. Train 與 Test 落差未超過限制。
9. 特徵係數方向具穩定性。
10. 參數鄰近區域結果不崩潰。

最低穩定性門檻：

```text
至少 70% Outer Test Fold 的淨期望值不為負
至少 70% Outer Test Fold 優於主要基準
任何單一 Fold 不得貢獻超過總樣本外淨利的 40%
LONG 或 SHORT 任一方向不得貢獻超過總樣本外淨利的 85%
單一月份不得貢獻超過總樣本外淨利的 30%
```

以上為專案驗收門檻，不代表市場統計定律。

若不符合，模型狀態：

```text
REJECTED_OVERFIT_RISK
```

---

# 25. Train/Test Gap

每個 Fold 比較：

```text
Train Log Loss vs Test Log Loss
Train Brier Score vs Test Brier Score
Train EV vs Test EV
Train Profit Factor vs Test Profit Factor
Train Trade Frequency vs Test Trade Frequency
```

建立：

```text
generalization_gap
```

若發生以下任一情況，標記高風險：

```text
Train 正期望值但多數 Test Fold 為負
Train Profit Factor 顯著高於 Test
Train Calibration 明顯優於 Test
Train 交易數遠高於 Test
Train 準確率提升但 Test 淨期望值下降
```

不得以更換評估指標掩蓋落差。

---

# 26. 特徵係數穩定性

對每個 Logistic Regression 特徵保存每個 Fold 的：

```text
coefficient
coefficient_sign
standardized_magnitude
rank
```

正式模型中的重要特徵需符合：

```text
係數方向在至少 70% Outer Fold 一致
中位數係數不接近 0
移除後樣本外績效不得更好
```

若特徵係數在不同 Fold 頻繁正負翻轉：

```text
unstable_feature = true
```

該特徵原則上移除。

不得因其在全資料模型中的係數很大而保留。

---

# 27. Ablation Test

每個特徵群組執行移除實驗：

```text
移除價格特徵
移除 VWAP 特徵
移除成交流特徵
移除五檔特徵
移除基差特徵
移除波動率特徵
移除市場結構特徵
移除時間特徵
```

對每個群組比較：

```text
Outer Test Log Loss
Outer Test Brier Score
Outer Test Net EV
Trade Count
Maximum Drawdown
Fold Stability
```

特徵群組只有在多數 Outer Fold 提供穩定增益時保留。

不得因全期間總獲利增加而保留。

---

# 28. 參數穩健性

最佳參數附近必須具有穩定結果。

例如選出的 L2 為 `λ`，必須同時測試鄰近值：

```text
0.5λ
λ
2λ
```

選出的機率門檻為 `t`，必須檢查：

```text
t - 0.05
t
t + 0.05
```

選出的 ATR multiplier 為 `m`，必須檢查：

```text
m - 0.25
m
m + 0.25
```

若只有單一精確參數點獲利，而鄰近參數全面失效：

```text
parameter_fragility = true
model_status = REJECTED_OVERFIT_RISK
```

不得使用極窄參數峰值作為正式模型。

---

# 29. 機率校準

比較：

```text
未校準
Platt Scaling
Isotonic Regression
```

校準器只能使用 Inner Validation。

Outer Test 不得參與校準。

選擇校準器時優先順序：

```text
Brier Score
Log Loss
Calibration Error
交易期望值
```

不得只因交易損益最高而選擇校準器。

輸出校準表：

```text
預測機率區間
樣本數
預測平均機率
實際發生比例
平均淨損益
```

樣本過少的機率區間不得視為有效證據。

---

# 30. 樣本數限制

每個正式 Fold 必須具有足夠樣本。

最低要求：

```text
Outer Train 至少 5,000 個候選決策點
Outer Test 至少 500 個候選決策點
Outer Test 至少 30 筆紙上交易
LONG 至少 10 筆
SHORT 至少 10 筆
```

若未達標：

```text
fold_status = INSUFFICIENT_SAMPLE
```

不足 Fold 不得用來宣稱穩定。

若有效 Outer Fold 少於 5 個：

```text
model_status = RESEARCH_INSUFFICIENT_DATA
```

---

# 31. 市場狀態穩定性

樣本外績效必須分組檢查：

```text
日盤
夜盤
高波動
中波動
低波動
趨勢盤
盤整盤
到期週
非到期週
開盤 30 分鐘
一般盤中
收盤前 30 分鐘
LONG
SHORT
不同月份
不同 target_code
```

不得為每個小分組各自訓練模型，除非：

1. 該分組樣本數足夠。
2. 有明確事前假設。
3. 通過獨立 Nested Walk-Forward。
4. 明確優於共享模型。

禁止為了改善回測，將資料切成大量市場狀態後各自挑選最佳模型。

---

# 32. 標準化與缺失值

每個 Fold：

1. 只使用 Inner Train 計算 mean、std。
2. 只使用 Inner Train 計算 median。
3. 只使用 Inner Train 決定異常值門檻。
4. 將相同轉換器套用到 Validation 與 Test。
5. 保存 feature order。
6. 保存 scaler。
7. 保存 imputer。
8. 保存轉換器 hash。

必要特徵缺失：

```text
signal = NO_TRADE
```

可選特徵缺失：

```text
使用 Train median
增加 missing indicator
```

禁止：

```text
全資料 median
全資料 mean
全資料 std
backward fill
從未來取得最後有效值
```

---

# 33. 異常值處理

異常值門檻只能在 Train Fold 建立。

可使用：

```text
Train Fold 分位數截尾
Robust Scaler
明確市場合理範圍
```

不得：

```text
查看 Test 後修改異常值門檻
刪除虧損交易附近異常資料
刪除重大行情
只保留正常市場
```

重大行情必須保留並單獨標記。

---

# 34. 紙上交易

紙上交易固定：

```text
一口
同時最多一個部位
不得加碼
不得攤平
不得反手
不得跨 Session 持有
```

## 34.1 進場

多單：

```text
fill = ask_price_1 + entry_slippage
```

空單：

```text
fill = bid_price_1 - entry_slippage
```

以下情況拒絕：

```text
BidAsk 缺失
BidAsk stale
Spread 超過限制
資料品質失效
模型不相容
特徵缺失
已有紙上部位
正在換月
Session 結束
成本設定不完整
```

## 34.2 出場

依序判斷：

1. Stop loss。
2. Profit target。
3. Vertical barrier。
4. Session 結束。
5. 資料 stale。
6. Rollover。

若停利與停損在相同 K 棒均可能被觸及，且 Tick 無法確認先後：

```text
採停損先發生
```

## 34.3 損益

```text
gross_pnl_ntd = gross_pnl_points * 10
```

```text
net_pnl_ntd =
gross_pnl_ntd
- entry_fee
- exit_fee
- tax
- slippage_cost
```

成本資料不完整時：

```text
允許計算 gross
禁止輸出 net
禁止宣稱策略獲利
```

---

# 35. 即時推論

每根完整 1 分鐘 K 棒完成後：

1. 驗證連線。
2. 驗證 target code。
3. 驗證換月狀態。
4. 驗證 Tick freshness。
5. 驗證 BidAsk freshness。
6. 驗證資料品質。
7. 計算特徵。
8. 驗證 feature version。
9. 驗證 model checksum。
10. 計算機率。
11. 套用固定門檻。
12. 產生 prediction。
13. 交由 PaperBroker。
14. 保存結果。

模型上線後禁止即時自動調整：

```text
特徵
係數
scaler
機率門檻
停損
停利
持有時間
```

重新訓練必須形成新的 model version。

---

# 36. 即時輸出

```json
{
  "schemaVersion": "1.1.0",
  "predictionId": "",
  "decisionTime": "",
  "evidenceAvailableAt": "",
  "instrument": {
    "category": "TMF",
    "aliasCode": "TMFR1",
    "targetCode": "",
    "deliveryMonth": "",
    "deliveryDate": "",
    "pointValueNtd": 10
  },
  "session": {
    "type": "DAY",
    "tradingDate": "",
    "minutesFromOpen": 0,
    "minutesToClose": 0
  },
  "market": {
    "lastPrice": 0.0,
    "bidPrice1": 0.0,
    "askPrice1": 0.0,
    "spreadPoints": 0.0,
    "underlyingPrice": null,
    "basisPoints": null,
    "sessionVwap": 0.0,
    "atr15m": 0.0
  },
  "probability": {
    "long": 0.0,
    "short": 0.0,
    "noTrade": 1.0
  },
  "signal": "NO_TRADE",
  "paperPlan": {
    "enabled": false,
    "direction": null,
    "quantity": 0,
    "entryPrice": null,
    "stopPrice": null,
    "targetPrice": null,
    "maximumHoldingMinutes": 0
  },
  "quality": {
    "tickAgeMs": 0,
    "bidAskAgeMs": 0,
    "dataStale": false,
    "rollover": false,
    "completeFeatures": false,
    "allowPaperTrade": false
  },
  "model": {
    "modelId": "",
    "modelVersion": "",
    "featureVersion": "",
    "labelVersion": "",
    "trainingEnd": "",
    "calibrationMethod": ""
  },
  "reasons": [],
  "missingFeatures": [],
  "warnings": []
}
```

---

# 37. 模型註冊

每個模型保存：

```text
metadata.json
feature_names.json
feature_manifest.json
scaler.json
imputer.json
trade_model.json
direction_model.json
calibrator.json
fold_metrics.json
stability_report.json
ablation_report.json
overfitting_report.json
checksum.sha256
```

Metadata：

```text
model_id
model_version
created_at
training_start
training_end
instrument
session
horizon
feature_version
label_version
code_commit
random_seed
training_data_hash
experiment_id
outer_fold_count
locked_holdout_status
```

推論時下列任一不一致：

```text
feature version
feature order
instrument
session
horizon
schema version
model checksum
scaler dimension
imputer dimension
```

強制：

```text
NO_TRADE
```

---

# 38. 實驗註冊

每次研究建立：

```text
experiment_id
created_at
hypothesis
feature_set_id
label_version
model_family
parameter_space
search_budget
primary_metric
secondary_metrics
train_period
locked_holdout_status
result
```

所有實驗必須保存。

禁止只保存最佳模型。

實驗比較必須使用相同：

```text
資料版本
Outer Fold
成本假設
標記版本
評估期間
```

不同條件不得直接比較總損益。

---

# 39. 評估指標

## 39.1 分類

```text
Log Loss
Brier Score
ROC AUC
Precision
Recall
F1
Confusion Matrix
Expected Calibration Error
Calibration Table
```

不得只使用 Accuracy。

## 39.2 交易

```text
Trade Count
Long Count
Short Count
Win Rate
Average Win
Average Loss
Average Net Points
Gross PnL
Net PnL
Profit Factor
Maximum Drawdown
Longest Losing Streak
Expected Value Per Trade
Expected Value Per Day
Average Holding Time
Exposure Ratio
Turnover
```

## 39.3 穩定性

```text
Positive Fold Ratio
Baseline Outperformance Ratio
Coefficient Sign Stability
Feature Rank Stability
Parameter Sensitivity
Monthly Contribution Concentration
Directional Contribution Concentration
Fold Profit Concentration
Train/Test Gap
```

---

# 40. 回測結果呈現規則

報告必須同時顯示：

```text
全部 Fold
每個 Fold
平均值
中位數
最差 Fold
最好 Fold
標準差
四分位距
```

禁止只顯示：

```text
累積損益曲線
最佳 Fold
最佳月份
最佳參數
全期間平均
```

累積損益圖必須標出：

```text
Train
Validation
Outer Test
Locked Holdout
```

---

# 41. 測試需求

## 41.1 Unit Tests

```text
Session 解析
Trading Date 解析
到期日特殊時段
Contract rollover
Tick normalization
BidAsk normalization
As-of join
VWAP
ATR
Trade imbalance
Book imbalance
Microprice
Basis
Triple Barrier
可成交價格
紙上損益
Logistic Regression
Scaler
Imputer
Calibration
Probability sum
Model checksum
```

## 41.2 Leakage Tests

必須證明：

```text
feature evidenceAvailableAt <= decisionTime
as-of join 不使用未來 BidAsk
scaler 只使用 Train
imputer 只使用 Train
outlier threshold 只使用 Train
calibrator 只使用 Validation
Test 不參與參數選擇
Test 不參與門檻選擇
swing feature 不提前出現
previous day feature 不使用當日收盤
```

## 41.3 Overfitting Tests

必須檢查：

```text
Nested Walk-Forward 正確切分
Locked Holdout 未被訓練讀取
搜尋預算未超限
失敗實驗未被刪除
特徵數未超限
高度相關特徵已處理
參數鄰近區域已測試
Ablation 已完成
Fold 貢獻集中度
月份貢獻集中度
方向貢獻集中度
Train/Test Gap
係數方向穩定度
```

## 41.4 Replay Tests

相同：

```text
Raw Data
Dataset Version
Feature Version
Label Version
Model Version
Seed
```

必須產生相同：

```text
特徵
標記
機率
訊號
紙上成交
紙上損益
報告 checksum
```

## 41.5 Security Tests

必須證明：

```text
沒有 CA
沒有 FuturesOrder
沒有 place_order
沒有 update_order
沒有 cancel_order
策略無法取得原始 API
PaperBroker 不發送網路請求
所有交易均標記 PAPER
```

---

# 42. 模型狀態

模型狀態固定使用：

```text
DRAFT
VALIDATING
REJECTED_LEAKAGE
REJECTED_INSUFFICIENT_DATA
REJECTED_OVERFIT_RISK
REJECTED_UNSTABLE
CANDIDATE
LOCKED_TEST_PENDING
LOCKED_TEST_FAILED
APPROVED_FOR_PAPER
RETIRED
```

只有：

```text
APPROVED_FOR_PAPER
```

可進入即時紙上交易。

任何模型不得進入實際交易狀態。

---

# 43. 驗收標準

## 43.1 安全

```text
Readonly verifier 通過
無下單 API
無委託物件
無 CA
無 LiveBroker
PaperBroker 完全隔離
```

## 43.2 資料

```text
能解析 TMFR1
能保存 target_code
能接收 Tick
能接收 BidAsk
能偵測 stale data
能偵測換月
能正確切分日夜盤
Raw Data append-only
資料轉換可重現
```

## 43.3 模型

```text
至少 5 個有效 Outer Test Fold
完成 Nested Walk-Forward
完成 Purge 與 Embargo
完成 Locked Holdout
完成 Calibration
完成 Ablation
完成參數穩健性測試
完成係數穩定性報告
完成過擬合報告
完成 Train/Test Gap 報告
```

## 43.4 過擬合

模型要核准為 `APPROVED_FOR_PAPER`，必須：

```text
至少 70% Outer Test Fold 淨期望值不為負
至少 70% Outer Test Fold 優於主要基準
單一 Fold 貢獻不超過總樣本外淨利 40%
單一月份貢獻不超過總樣本外淨利 30%
單一方向貢獻不超過總樣本外淨利 85%
重要特徵係數方向至少 70% Fold 一致
鄰近參數沒有全面失效
Locked Holdout 未失敗
```

若未通過：

```text
不得修改驗收門檻
不得重新定義指標
不得刪除虧損期間
不得切換 Test 範圍
不得宣稱模型有效
```

---

# 44. 開發階段

## Phase 0：唯讀安全

完成：

```text
MarketDataGateway
原始 API 隔離
Readonly verifier
安全測試
PaperBroker 邊界
```

## Phase 1：資料收集

完成：

```text
Contract Resolver
Tick Subscription
BidAsk Subscription
Event Queue
Raw Writer
Reconnect
Data Quality
```

## Phase 2：資料處理

完成：

```text
Session Resolver
Trading Date
Tick/BidAsk Join
1 秒狀態
多時間框架 K 棒
資料品質報告
```

## Phase 3：特徵與標記

完成：

```text
第一版特徵
Feature Manifest
Triple Barrier
Executable Price
Leakage Tests
Label Manifest
```

## Phase 4：模型基準

完成：

```text
Baseline 0–4
Logistic Regression
Scaler
Imputer
L2
Class Weight
Serialization
```

## Phase 5：過擬合控制

完成：

```text
Nested Walk-Forward
Purge
Embargo
Search Budget
Feature Correlation Control
Ablation
Coefficient Stability
Parameter Sensitivity
Train/Test Gap
Locked Holdout
```

Phase 5 未完成前不得開發即時紙上交易。

## Phase 6：紙上交易

完成：

```text
Historical Replay
Live Inference
PaperBroker
Paper Ledger
Prediction JSON
風險過濾
```

## Phase 7：模型擴充

只有基準模型通過全部樣本外驗收後，才允許研究：

```text
Gradient Boosting
TXF 領先特徵
現貨指數
選擇權
法人籌碼
海外市場
```

每次只新增一組因子，必須執行獨立 ablation。

---

# 45. Codex 開發規則

Codex 必須：

1. 逐 Phase 開發。
2. 不跳過 Phase 0。
3. 不產生下單程式碼。
4. 不建立 LiveBroker。
5. 不在 Callback 執行重工作。
6. 不修改 Raw Data。
7. 不使用 Random Split。
8. 不使用未來資料。
9. 不使用 Test 選參數。
10. 不使用 Test 選門檻。
11. 不超過研究搜尋預算。
12. 不刪除失敗實驗。
13. 不只保存最佳模型。
14. 每個特徵保存 `evidence_available_at`。
15. 每個模型保存資料與程式版本。
16. 每個公開函式加入型別。
17. 每個 Phase 建立測試。
18. 相同輸入必須產生相同輸出。
19. 發現欄位與文件不符時保存實際 payload。
20. 不因回測改善而任意增加特徵。
21. 不因回測失敗而改變 Test 區間。
22. 不因 Locked Holdout 失敗而重新調參。
23. 不將單一最佳參數視為有效模型。
24. 不宣稱紙上績效等同實際交易績效。

---

# 46. Definition of Done

專案完成必須同時符合：

```text
完全唯讀
無任何下單能力
TMF 行情可穩定收集
target_code 可追蹤
日夜盤正確解析
換月可辨識
Raw Data 不可修改
特徵無未來資訊
標記使用可成交價
Nested Walk-Forward 可重現
Locked Holdout 未污染
模型通過過擬合控制
模型通過參數穩健性測試
模型通過 Ablation
模型通過係數穩定性檢查
紙上交易可完整重播
成本假設透明
所有 prediction 可追溯
```

最終系統只能是：

```text
行情資料系統
量化研究系統
機率推論系統
歷史重播系統
紙上交易系統
```

不得成為：

```text
實際交易系統
自動下單系統
半自動下單系統
委託轉送系統
```

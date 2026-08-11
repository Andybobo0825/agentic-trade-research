# Pre-registration: Phase 3 過濾機制驗證(2026-08-11)

**目的**:`phase3_stability` 的七個 frozen hard gates 至今沒有跑過本 repo 自訂的證據標準。本研究驗證它作為「過濾器」的宣稱——不是驗證它是可獲利策略。過濾器的宣稱是:**eligible 名單優於公平基準,被 anti-chase gate 剔除的名單劣於基準**。

**紀律**:本文件凍結後,gate 參數與通過標準不得再改。跑出什麼就報什麼([[binding-belongs-to-the-holdout]] 規則)。失敗不得回頭調 gate 重跑;要調 gate 需另立新 pre-registration。

## 受測物(凍結,不得調整)

`src/phase3-filter.js` 現行 frozen gates,原碼直接引用,不得用重新實作的副本:

```text
HMA9 slope > 0
HMA20 slope >= 0
close >= HMA9
maxHmaDistancePct = 6
minimumAverageTurnover = 20,000,000
maximumMomentum5Pct = 18
maximumClosePosition = 0.72
```

## 資料與宇宙

- 資料:FinMind `TaiwanStockPrice` 日線(免費層可回溯),token 用 `.env` 的 `FINMIND_API_TOKEN`。快取到 `.omx/research/phase3-validation/cache/`(gitignored),可斷點續抓。
- 宇宙:TWSE + TPEx 普通股(排除 ETF、權證、存託憑證;以 `TaiwanStockInfo` 分類過濾)。每個交易日 D 的宇宙 = 當日有成交資料且過去 20 日均成交金額 ≥ 20,000,000 的股票(= Phase 3 自己的流動性底線)。這使得測試問題是:「在可交易股票中,其餘六個 gate 是否有選擇力?」
- 生存者偏差:宇宙逐日由當日實際存在的資料構成(point-in-time);FinMind 對已下市股票覆蓋不完整之處必須在報告中量化(對照 TWSE 下市清單抽樣)。

## 視窗(凍結)

- **Development**:2023-01-01 ~ 2024-12-31
- **Confirmation(封存)**:2025-01-01 ~ 2026-06-30。dev 未全數通過前不得計算;開封只有一次。

## 程序

對每個交易日 D(僅用 ≤D 的資料):

1. `E_D` = 通過全部 hard gates 的 eligible 集合。
2. `B_D` = 僅通過流動性底線的基準集合(含 E_D)。
3. `C_D` = 因 `maximumMomentum5Pct` 或 `maximumClosePosition` 被剔除(其餘 gate 通過)的「追高被擋」集合。
4. 前向報酬:D+1 開盤買入 → D+5 收盤、D+10 收盤(股票停牌/漲跌停無量以次一可成交日開盤替代並記錄次數);另記錄視窗內最大回撤。
5. 每日組內等權平均,再跨日平均;統計推論一律用「以日為叢集」的 bootstrap(10,000 次)。

## 通過標準(凍結)

Development 四項全過才算 dev 通過:

1. **選擇力**:`mean(E) − mean(B)` 的 5 日超額 > 0,且日叢集 bootstrap 95% CI 不含 0。
2. **擋垃圾力**:`mean(C) − mean(B)` 的 5 日超額 < 0,且 95% CI 不含 0;且 C 組 10 日最大回撤分布的第 10 百分位劣於 E 組(左尾更深)。
3. **穩定性**:把 dev 依時間對半切,兩半的 E−B 超額皆 > 0。
4. **非空洞性**:E_D 的每日中位數 ≥ 3 檔,且 E 佔 B 比例的中位數 ≤ 40%(過濾器必須真的在過濾)。

Dev 全過 → 開封 confirmation,跑一次,通過標準 = 上述 1 與 3(同參數)。Confirmation 過 = Phase 3 取得「合格過濾器」地位;不過 = 記錄為負面結果,gate 重設需新 pre-registration。

## 明確排除在範圍外

- 軟性排序因子(soft score)的 rank-IC 檢定——另案。
- 任何成本後可獲利性宣稱——過濾器比較是相對比較,成本在組間近似抵銷,但本研究不支持「照名單買會賺」的結論。
- 任何 gate 參數搜尋。

## 產出

`.omx/research/phase3-validation/report.md`:各標準的數字、CI、通過/失敗判定、資料覆蓋率與生存者偏差量化、可重跑指令。程式碼放 `.omx/research/phase3-validation/`(不進 git 主樹)。

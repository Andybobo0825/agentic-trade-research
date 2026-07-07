# 台股盤前 30 分鐘 Workflow（啟動 prompt：盤前流程）

來源邊界：本 workflow 依使用者提供的 `/Users/chentingwei/Downloads/台股盤前30分鐘拆解流程.md` 建立。它只產生盤前觀察、風險分類與執行限制；不得生成無條件下單指令。

## 啟動方式

LINE / Codex prompt：

```text
盤前流程
```

帶觀察股：

```text
盤前流程：觀察 2330,2454,2317,2308,00631L
```

CLI：

```bash
node src/cli.js preopen-brief --format markdown
```

若 data agent 已抓到盤前資料，可直接注入：

```bash
node src/cli.js preopen-brief \
  --date 2026-07-02 \
  --fx-prev-close 29.60 \
  --fx-current 29.49 \
  --future-close 47160 \
  --future-change 140 \
  --future-volume 100000 \
  --previous-spot-close 47018.99 \
  --us-moves 'dow=0.3,sp500=0.5,nasdaq=0.9,sox=1.2' \
  --branch-file .omx/data/preopen-branches.json \
  --auction-file .omx/data/preopen-auctions.json \
  --format markdown
```

## 必要順序

Agent 必須照以下順序整合，不得跳步：

```text
匯率
→ 台指期夜盤
→ 美股與台指期相對強弱
→ 個股最近 5 日分點
→ 8:58～9:00 試撮
→ 正式開盤確認
```

## Data agent 輸入契約

### 匯率

CLI 欄位：

- `--fx-prev-close`：前一交易日新台幣兌美元下午收盤價。
- `--fx-current`：當日早盤新台幣兌美元報價。

判斷：

- 今日報價比前日收盤低 0.1 元以上：新台幣明顯升值，偏多。
- 今日報價比前日收盤高 0.1 元以上：新台幣明顯貶值，偏空。
- 其餘：中性。

### 台指期夜盤與期現貨價差

CLI 欄位：

- `--future-close`：台指期夜盤收盤點位。
- `--future-change`：台指期夜盤漲跌點數。
- `--future-volume`：台指期夜盤成交量。
- `--previous-spot-close`：前一交易日台股現貨加權指數收盤。

若未提供 `--previous-spot-close` 且未加 `--no-fetch`，工具會 best-effort 用 Fugle `IX0001` 歷史日線補前一日現貨收盤；失敗則標示資料不足。

判斷：

- 正價差超過 100 點：偏多。
- 逆價差超過 100 點：偏空。
- 6～8 月逆價差 100～300 點：標記可能受除息影響，不單獨判偏空。

### 美股與台股相對強弱

CLI 欄位：

- `--us-moves 'dow=0.3,sp500=0.5,nasdaq=0.9,sox=1.2'`

規則：

- 美股明顯上漲但台指期不偏多：台股弱於美股，禁止開盤直接追高。
- 美股明顯下跌但台指期未偏空：只標記台股相對抗跌，不推導買訊。

### 個股關鍵分點

CLI 欄位：

- `--branch-data '<json-array>'`
- 或 `--branch-file <path>`

JSON row 格式：

```json
{
  "ticker": "2330",
  "name": "台積電",
  "branch": "凱基-台北",
  "dailyNetLots": [120, 180, 260, 330, 410]
}
```

處理：

- 最近 5 日連續買超、買超逐日增加、未轉賣：觀察。
- 轉賣、連續賣超、最近賣超：排除或降低優先。
- 少於 5 日：資料不足。

限制：分點只視為券商分點成交紀錄，不得直接斷定背後交易者身分。

### 8:58～9:00 集合競價

CLI 欄位：

- `--auction-data '<json-array>'`
- 或 `--auction-file <path>`

JSON row 格式：

```json
{
  "ticker": "2330",
  "price858": 2500,
  "price859": 2504,
  "open": 2506
}
```

預設最後一分鐘拉高 / 壓低門檻為 `0.5%`，可用 `--auction-threshold-pct` 調整。

處理：

- 最後一分鐘突然拉高：標記開高回落風險，禁止追第一波。
- 最後一分鐘壓低但開盤未延續下跌：標記下方承接跡象。
- 缺資料：資料不足，不補造。

## 輸出邊界

輸出只包含：

- 今日盤前市場傾向。
- 今日風險程度。
- 權值股是否適合追價。
- 個股觀察名單。
- 應避開或降低優先個股。
- 開盤後執行限制。
- 每項判斷使用的原始數據。
- Agent 依流程做出的 research 建議。

不得輸出：

- 保證獲利、必漲、必中。
- 無條件買進 / 賣出。
- 資料不足時的補造數值。
- 把單一匯率、期貨價差、分點或試撮訊號當作獨立交易依據。

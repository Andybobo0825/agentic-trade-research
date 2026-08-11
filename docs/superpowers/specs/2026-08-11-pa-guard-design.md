# PA-guard 設計規格(2026-08-11)

把 PA_Agent(AGPL,僅移植設計概念,禁止複製其程式碼與 prompt 文字)的「程式驗證 LLM」架構整合進 trade repo。三個新模組 + CLI/MCP 註冊。全部 ESM、零新依賴、風格比照現有 src/*.js。

## 模組 1:`src/market-facts.js` — 確定性事實表 + regime 分類

### `computeMarketFacts(rows, options)`

- `rows`:日線陣列,FinMind 形狀(`{date, open, max, min, close, Trading_money}`;同時接受 `high/low/turnover` 別名)。舊到新或新到舊都要能吃(內部按 date 排序,舊→新)。
- `options`:`{ ticker, windows = { background: 60, structure: 20, immediate: 5 } }`。
- 回傳:

```js
{
  ticker, asOf,                 // asOf = 最後一根的 date
  factTableVersion: 1,
  windows: {                    // 視窗宣告(硬切分 + 角色)
    background: { bars: 60, role: 'risk-context' },   // 只作風險脈絡,不得否決 structure 方向
    structure:  { bars: 20, role: 'direction' },      // 決定 regime 與方向
    immediate:  { bars: 5,  role: 'signal-quality' }, // 訊號品質/逐棒
  },
  facts: [ { id, key, window, value, desc } ],  // id 格式 F1, F2, ...(穩定:同輸入同 id)
  regime: { label, alternative, direction, evidence: [factIds], confidence },  // confidence 整數 10–95
  playbook: { regime, guidance, refs },  // refs = repo 內文件路徑陣列
}
```

### Facts 清單(全部確定性算術;資料不足的 fact 省略並在 facts 加一筆 `key:'insufficient', desc` 說明)

- `close`、`prevClose`、`changePct`
- `ma5`/`ma10`/`ma20`/`ma60` 數值 + `closeVsMa20`/`closeVsMa60`(`above|below`)
- `turnover`(當日)、`avgTurnover20`、`turnoverRatio`(當日/20日均)、`avgTurnover5over20`(5日均/20日均)
- `swingHigh60`/`swingLow60`(數值 + 日期)、`retracementPct`(close 在 low→high 的位置 %)、`drawdownFromHighPct`
- `trendBarRun`:最近連續同方向實體 K 數 + 方向(實體 <10% 全距視為中性、中斷計數)
- `avgBodyOverlap5`:最近 5 根相鄰實體重疊比平均(0–1)
- `pullbackDepthPct`:structure 視窗內主波段的最大回撤深度 %(相對該視窗 swing 幅度)
- `lastBars`:最近 5 根,每根 `{date, dir(阳/阴/平 用 up/down/flat), bodyRatio, upperWickRatio, lowerWickRatio}`

### Regime 裁決樹(唯一入口,依序首個命中;每步記 evidence fact ids)

枚舉:`spike | tight_channel | normal_channel | trading_range | insufficient_data`。

1. rows(有效)< 25 → `insufficient_data`(direction=neutral, confidence=10)。
2. `spike`:最近 5 根內有 ≥3 連續同向實體 K,且該串 `avgBodyOverlap < 0.3`、平均 bodyRatio > 0.5 → direction = 該串方向。
3. `tight_channel`:(多)ma5>ma20 且 close>ma20 且 `pullbackDepthPct < 30`;(空)鏡像 → direction = up/down 對應 bullish/bearish。
4. `normal_channel`:同 3 的方向條件但 `pullbackDepthPct` 30–50。
5. 其餘 → `trading_range`(direction=neutral;但若 closeVsMa20 與 closeVsMa60 同側,direction 可為該側 weak 判定 → 仍輸出 bullish/bearish,evidence 註明)。

`alternative`:`pullbackDepthPct` 距 30 或 50 邊界 ±5pp 內 → 鄰態;spike 判定差一根 → tight_channel。否則 null。

`confidence`(確定性計分):基準 80;邊界 ±5pp 內 −15;immediate 視窗最近 5 根方向與 structure 方向衝突 −10;資料 < background 視窗 −20;下限 10 上限 95。

`playbook` 對照表(guidance 為 1–2 句繁中,自行撰寫,不抄 PA_Agent;refs 指向 repo 文件):
- spike → 不追、等第一次回檔;refs: docs/standard-workflow-v1.md
- tight_channel → 順向、回測均線觀察;refs 同上
- normal_channel → 順向但等較深回測;refs 同上
- trading_range → 邊界才有意義、中間不動作;refs 同上
- insufficient_data → 不判讀;refs 同上

### CLI/工具

`market-diagnosis`:參數 `{ticker, startDate?, provider?}` → 內部用現有 `getTaiwanPrice`(auto-history)抓日線(至少 90 天)→ `computeMarketFacts` → `format` 支援 compact-json/json/markdown。markdown renderer:事實表(id/key/value)+ regime 區塊 + windows 宣告 + playbook。

## 模組 2:`src/judgment-guard.js` — LLM 判讀驗證器

### 判讀 JSON schema(兩階段)

```js
{
  stage: 'diagnosis' | 'decision-included',
  diagnosis: {
    regime,                    // 枚舉,同上
    alternative_regime,        // 枚舉或 null
    direction: 'bullish'|'bearish'|'neutral',
    confidence,                // 整數 0–100(拒收字串)
    gate_result: 'proceed'|'wait',
    gate_trace: [ { node, question, branch, facts: [factId] } ],
    cited_facts: { F3: 45120.72, ... },   // LLM 引用的事實值
  },
  decision: null | {
    stance: 'enter'|'wait'|'avoid',
    prices: { activeEntryLimit, patientEntryPrice, takeProfitPrice, stopLossPrice },  // 各為 number|null
    conditions: [string], risks: [string],
  },
}
```

### `validateJudgment(judgment, factTable)` → `{ ok, errors: [{code, path, message}] }`

規則(每條都要有測試):
1. 枚舉與型別:regime/direction/gate_result/stance 合法;confidence 整數。
2. 必經節點:gate_trace 需含 node `D1`(資料是否足夠)、`D2`(regime 裁決)、`D3`(方向)、`D4`(gate 判定);`gate_result='proceed'` 時缺一即錯。
3. 路徑一致性:D2 的 branch 必須等於 `diagnosis.regime` 或 `alternative_regime`;D3 branch == direction。
4. 證據存在:每個 trace item 的 facts 至少 1 個且全部存在於 factTable;`cited_facts` 每個 id 存在且值與 factTable 相對誤差 ≤ 0.5%。
5. 兩階段 gate:`gate_result='wait'` 時 `decision.prices` 四價必須全 null(stance 只能 wait/avoid);`decision` 含非 null 價格 ⇒ 必須 `gate_result='proceed'`。
6. RR 重算(程式權威):stance='enter' 且四價齊 → 多方 `(takeProfit−activeEntry)/(activeEntry−stopLoss) ≥ 1.0`,且 stopLoss < activeEntry < takeProfit;direction=bearish 鏡像。違反即錯(不自動修,只報錯)。
7. 價格可追溯:decision.prices 每個非 null 值需落在 factTable 任一 fact 值 ±3% 內(參考價必須錨在事實上,不得憑空)。

### `validateReportNumbers(markdownText, factTable, judgment)` → errors

從報告文字抽出 ≥1000 的數字(去千分位逗號),每個需與(a)任一 fact 值或(b)judgment 四價,相對誤差 ≤ 0.5% 匹配;不匹配 → `UNTRACEABLE_NUMBER` 錯誤(附該數字)。<1000 的數字跳過(百分比/家數雜訊)。此為幻覺攔截器,測試需含「真實引用通過/編造點位攔截」兩向。

### `scanForbiddenContent(markdownText)` → errors

禁令正則(繁中):倉位比例(如 `\d+%.{0,4}倉`)、手數、加碼、減碼、移動停損、移止損、保證、穩賺、一定漲、一定跌、all-in、梭哈。命中 → `FORBIDDEN_CONTENT`。

### `buildRetryFeedback(errors)` → `{ categories, message, forbiddenFixes }`

- categories:錯誤分四類 `schema | missing | inconsistency | untraceable`。
- message:繁中,逐條列錯 + 指示。
- forbiddenFixes(固定):「不得為通過驗證而更改 regime、direction、gate_result 或 stance;必須回到事實表重新對照」「不得刪除 cited_facts 來規避比對;必須修正數值或改引用正確 fact」。

### CLI/工具

`judgment-validate`:`{judgmentFile 或 judgment(JSON字串), factsFile 或 facts, reportFile?}` → 跑上述三個驗證,markdown/json 輸出;失敗時輸出 retry feedback。

## 模組 3:`src/experience-store.js` — 經驗庫

- `recordExperience(rootDir, { regime, date, ticker, judgment, note? })` → 寫 `.omx/experience/<regime>/<date>-<ticker>.json`(mkdir -p;同名覆寫)。
- `recallExperience(rootDir, { regime, limit = 5 })` → 依檔名日期新→舊取前 limit,回傳解析後陣列;目錄不存在回 `[]`。
- 嚴格唯讀/唯寫分離;不掃其他 regime。
- CLI:`experience-log`(從參數或 stdin JSON 寫入)、`experience-recall`(`{regime, limit}`)。

## 註冊

- `src/tools.js`:新增 `market-diagnosis`、`judgment-validate`、`experience-log`、`experience-recall`(比照現有工具結構、輸入 schema、renderer)。
- `src/cli.js`、`src/mcp-server.js`:同步註冊(比照既有模式)。

## 測試(先寫測試;檔名)

- `tests/market-facts.test.js`:合成 K 線 fixtures 各觸發 5 個 regime;alternative 邊界案例;confidence 計分;insufficient_data;facts 數值抽查(手算對照);rows 順序不變性(舊→新 vs 新→舊同輸出)。
- `tests/judgment-guard.test.js`:規則 1–7 各至少一過一錯;validateReportNumbers 真引用過/編造攔截;scanForbiddenContent 命中與不命中;buildRetryFeedback 內容含 forbiddenFixes。
- `tests/experience-store.test.js`:寫入/讀回/排序/limit/空目錄。
- CLI 註冊煙霧測試併入既有 tests/tools.test.js 模式(新增最小 case,不重構既有測試)。

## 邊界

- 不改 `src/phase3-*.js`、`src/taiwan-agent-team.js`、既有測試。
- 不引用 PA_Agent 任何原文或程式碼(AGPL)。
- 機率錨點:不得寫入任何未經本 repo 驗證的機率數字(playbook guidance 用條件語言即可)。
- 全程 read-only,不碰下單。

# Trade Repo Standard Workflow 1.4

本文件是目前 repo 的標準執行流程來源。若舊對話、舊 backtest、舊策略名稱、臨時 LINE 對話結論或研究 sidecar 與本文件衝突，以 Standard Workflow 1.4 為準。

## 0. Version Lock / Change Control

標準流程不可因單次對話或單次選股結果靜默漂移。任何升版都必須留下：問題定義、新規則、影響範圍、可驗證方式與對既有策略的處理。

硬性規則：

1. 一般互動只能套用 Standard Workflow 1.4。
2. 單次選股失誤只能先記為 `failure_case`，不得直接覆蓋標準流程。
3. 外部新聞、法說、財報、股癌逐字稿只作信心加權與題材背景，不作技術合格條件。
4. 所有 Phase 3 流程都是 `read_only`；不得觸發真實下單 API。
5. 後續回答若提到流程，必須引用 Standard Workflow 1.4。

## 1. Active Main Strategy

唯一有效主策略：`phase3_stability`

唯一正式主流程入口：

```bash
node src/cli.js taiwan-agent-team --mode auto --format markdown
```

`taiwan-agent-team` 是確定性 orchestrator，不是第二套策略或預測模型。它有兩種公開模式：

- `screen`：使用者要求選股、篩選或候選名單時，才執行 `phase3-dataset` 與唯一技術篩選入口 `phase3-screen`。只有 eligible 候選可以進入外部研究與 DOM；零 eligible 候選就停止後續逐檔研究。
- `analyze`：使用者指定 ticker 要求分析時，不執行 Phase 3，必須標示 `phase3Eligibility: not_evaluated`，再執行市場 context、外部信心、DOM 與四個價格。

主策略定位：

1. Phase 3 是確定性技術篩選器，不訓練模型、不輸出機率，也不用未來行情產生當下訊號。
2. 候選只使用 decision time 當時已公開的市場與法人資料。
3. 外部資訊只在技術候選出現後加權投資信心；新聞、法說、財報、股癌及產業敘事不得把不合格技術訊號硬推成買進。
4. 市場 breadth、外資連續性及量能只作有上限的排序加減分，不能覆蓋硬性技術失敗；IC.TPEX 目前只在候選成立後提供產業分類與外部信心背景，不進入 Phase 3 soft score。
5. 歷史收益、成本、回撤與命中率必須在訊號凍結後另行評估，不能回寫訊號。
6. 主流程沒有自動下單功能；使用者仍手動決定是否交易。

`screen` 候選成立後的完整執行順序固定為：

```text
phase3-dataset → phase3-screen → company/industry/ETF research → gooaye-topic-research → phase3-dom-confidence → manual decision
```

`phase3-dom-confidence` 是外部研究完成後才執行的獨立信心層。DOM 不進入 Phase 3 資料、soft score 或候選資格（eligibility），也不能把 rejected ticker 改成 eligible。它只讀取永豐 Shioaji 五檔委買賣，預設在約 10 秒內取樣三次（0、5、10 秒），提供當下買賣壓力與人工決策參考。

只要至少一筆 DOM 樣本有效，就必須交付：`activeEntryLimit`、`patientEntryPrice`、`takeProfitPrice`、`stopLossPrice`。即使結論是等待或不追價，仍須交付全部四個價格；若全部取樣失敗，欄位保留但值為 `null`，不得捏造價位。此工具完全 read-only，不包含下單 API。

Frozen Phase 3 hard gates：

```text
HMA9 slope > 0
HMA20 slope >= 0
close >= HMA9
maxHmaDistancePct = 6
minimumAverageTurnover = 20000000
maximumMomentum5Pct = 18
maximumClosePosition = 0.72
```

軟性排序因子：

- volume ratio
- relative 3-day momentum
- market breadth
- foreign buy streak
- foreign three-day intensity

舊短線 MVP 已降為歷史稽核紀錄，不是 baseline layer，也不得與 Phase 3 疊加交易。舊模型、fold、方向 sidecar 與 promotion workflow 已移除，不是可用策略。

## 1A. Large-Cap / Core Holding Analysis Gate

權值股、核心資產、長期持有標的不得直接套用短線題材股進出場結論。

適用範圍：

- 台積電 2330。
- 主要權值半導體、金融、大型 ETF 成分核心股。
- 使用者明確表示「長期持有 / 買低點 / 核心配置」的標的。

硬性規則：

1. 權值股分析順序：大盤位置與風險胃納 → 權值族群同步性 → 個股長期均線 / 估值 / 基本面 / 法人籌碼 → Phase 3 短線訊號。
2. 權值股買點以分批配置、低點區間、風險報酬為主，不以短線熱門股追價為主。
3. 回覆必須區分：短線不追、長期可分批、更佳低接區間、趨勢修復確認價。
4. 若使用者問台積電，必須至少同時看加權指數、電子/半導體指數或大盤 breadth。

## 2. Taiwan Market Data Source Order

台股價格、量價、K 棒、成交量、即時 snapshot、ticks/orderbook：

1. Primary：SinoPac Shioaji local server / API。
2. Shioaji failure gate：若 Shioaji 連線、health、quote、snapshot、kbars 失敗，必須先處理 API server / session 問題，再繼續研究。
3. Fallback：FinMind / Fugle / TWSE / TPEx only when Shioaji lacks the dataset or is externally unavailable after repair attempt。
4. 若使用 fallback，回答中必須標示資料限制與 Shioaji 修復狀態。

Shioaji failure gate 標準處理：

1. 不得在 Shioaji 失敗後直接往下做實盤研究或選股。
2. 先判斷失敗類型：`fetch failed` / 8080 refused、`NotReady` / `SessionNotEstablished`、500 response。
3. 最小修復順序：檢查 pid / listener / health / log，只重啟 Shioaji server，不重啟 LINE bridge / tunnel / Codex agent。
4. 修復後驗證：health endpoint healthy；必要時跑 `shioaji-quote` 或目標 ticker quote / snapshot。
5. fallback 後若 Shioaji 恢復，後續研究必須回到 Shioaji 第一順位。

指定股票分析主流程（`analyze`）：

1. 執行 `taiwan-agent-team --mode analyze --tickers <TICKER>`；不執行 Phase 3，也不宣稱 ticker 通過技術篩選。
2. 讀取大盤、個股 snapshot、盤前與產業鏈 context，並標示 `phase3Eligibility: not_evaluated`。
3. 補公司、新聞 / 法說 / 財報、營收、估值及 ETF 等外部信心因子。
4. 全部目標的公司／產業／ETF 研究完成後，執行一次 `gooaye-topic-research --date <AS_OF_DATE> --tickers <TICKERS>`；先以官方 RSS 確認當時最新集數，再只取不晚於 as-of date 的研究 artifact。
5. 股癌題材 context 已記錄後，才逐檔執行 `phase3-dom-confidence --ticker <TICKER>`，取得獨立 DOM 信心分數及四個價格參考。
5. `daily-decision-study`、`signal-study`、`chip-study` 僅供歷史診斷，不得形成第二套策略。

選股主流程（`screen`）：

1. 更新 point-in-time evidence，再執行唯一技術篩選入口 `phase3-screen`。
2. 只對 eligible 候選補即時 quote、產業鏈與外部信心因子；rejected ticker 不得進入 downstream research 或 DOM。
3. 零 eligible 候選時停止外部研究與 DOM，不得製造替代候選。

資料建置 / 候選池工具：

```bash
node src/cli.js phase3-dataset --evidence-root .omx/evidence/phase3 --format markdown
node src/cli.js phase3-screen --evidence-root .omx/evidence/phase3 --format markdown
node src/cli.js phase3-dom-confidence --ticker <TICKER> --format markdown
```

`phase3-dataset` 只建立與稽核 point-in-time 證據；`phase3-screen` 是唯一策略入口。

## 3. Gooaye / News / 法說 Topic Research Workflow

外部資訊只作題材熱度與信心加權，不作價格資料、策略認證或單獨買賣依據。

Source order:

1. 新聞 / 法說 / 財報 / 股癌只在技術候選成立後使用。
2. 主流程的 `gooaye-topic-research` 一律先查官方 SoundOn RSS 作為集數權威，再取不晚於 as-of date 的公開研究 artifact，避免前視偏誤。
3. 若需要股癌逐字稿，依 `docs/gooaye-transcript-agent-handoff.md` 的獨立研究流程取得；主策略文件不啟動外部 sidecar。
4. 題材結論必須回到 Shioaji 量價、IC.TPEX 產業鏈、同族群同步性與 Phase 3 技術訊號。

## 4. IC.TPEX 產業鏈 Mapping Workflow

`https://ic.tpex.org.tw/` 是 TPEx/TWSE 產業價值鏈資訊平台；用於把題材關鍵字映射到官方產業鏈與同族群公司，不作價格資料或單獨買賣依據。

使用位置：

1. Gooaye / 新聞 / 使用者題材抽出關鍵字後，先到 IC.TPEX 對應產業鏈。
2. 建立同產業鏈 candidate universe，例如被動元件、半導體、連接器、PCB、電腦週邊、AI / 雲端運算等。
3. 檢查同族群同步性：同鏈股票是否一起量增、價動、收高。
4. IC.TPEX 只作產業鏈分類與 peer group；成交量、K 棒、流動性與交易判斷仍回 Shioaji + Phase 3。
5. 若 IC.TPEX 公司面資料與市場資料衝突，以 Shioaji 量價資料決定是否進入交易觀察。

## 4A. Xiaoyu ETF Holding Lens

`https://xiaoyu-etf.pages.dev/` 是公開台股 ETF 持股追蹤與 ETF 推估買賣資料來源；用於補強 ETF/投信籌碼視角，不作價格、量價或單獨買賣依據。

使用位置：

```bash
node src/cli.js xiaoyu-etf --mode stock --ticker <TICKER> --format markdown
node src/cli.js xiaoyu-etf --mode etf --etf <ETF_CODE> --format markdown
node src/cli.js xiaoyu-etf --mode rank --scope active --window d1 --direction buy --format markdown
```

規則：Xiaoyu ETF 只作 ETF 持股 / 主動式 ETF 是否加減碼 / ETF 推估買賣排行；價量與交易判斷以 Shioaji / 交易所為準。

## 5. Taiwan Industry Code Guard

產業分類是選股品質的核心輸入，不能用臨時猜測改寫。

硬性規則：

1. 台股產業代碼 `28` = `電子零組件`，包含被動元件與電子零組件熱度候選，絕對不可排除。
2. 預設排除產業只包含 `17` = `金融保險`；除非使用者明確要求，不得新增其他產業碼到排除清單。
3. 全市場篩選、hotScore、產業熱度、同族群同步性研究都必須保留 `28`。
4. 若研究腳本嘗試把 `28` 放入 `excludedIndustries`，`src/hot-stock-filter.js` 必須直接丟錯。
5. 題材分類需用 IC.TPEX 驗證產業鏈；價格、成交量、K 棒、法人/量價訊號仍回 Shioaji 驗證。

## 6. Weak Follower Avoidance / Peer Relative Strength Gate

單一個股 study 分數偏高，不代表它是同題材中最值得交易的標的。若同題材主流股明顯更強，弱跟漲股會造成機會成本與停損風險。

硬性流程：

1. 先判斷市場主線與同題材 peer group，再判斷個股。
2. 同題材候選至少比較：即時漲幅 / 開盤後延續率、20 日均量比、是否接近或突破當日高點、是否強於同題材中位數、是否為前 3 名資金集中標的。
3. 若個股落後同題材領漲股明顯，標記為「跟漲弱股」。
4. 跟漲弱股不列為當日首選、不得加碼，需等站回成本 / 關鍵價且量能延續才重新評估。
5. 對持股回覆需明確區分方向、強弱、續抱、加碼、study 勝率與同題材相對強度。

## 7. LINE Bridge Handoff Rule

LINE bridge 回覆流程：

1. 若 LINE prompt 指定 response file，必須先把完整 Markdown 最終回覆寫入該檔，再回覆同一份內容。
2. 若接上的 panel 是新開 session，需注入/閱讀 `docs/line-session-handoff.md`。
3. 若接上的 panel 是 resume 既有 session，不需要重複 handoff。

## 8. Repo Hygiene Rules

1. 不保留舊策略實驗 artifacts 作為記憶來源。
2. 舊短線 MVP 只能作歷史稽核紀錄，不得作 baseline layer 或與 Phase 3 重疊交易。
3. 任何新策略實驗必須另存為臨時研究，不得覆蓋 Standard Workflow 1.4，除非使用者明確要求升版並完成可驗證修正。
4. 對外回答不得引用 raw secrets、完整 token、或不必要工具原始輸出。

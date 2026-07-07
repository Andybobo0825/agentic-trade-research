# Trade Repo Standard Workflow 1.01

本文件是目前 repo 的標準執行流程來源。若舊對話、舊 backtest、舊策略名稱、或臨時 LINE 對話結論與本文件衝突，以 Standard Workflow 1.01 為準。

## 0. Version Lock / Change Control

標準流程不可因單次對話或使用者後續回覆而靜默漂移。任何「修正流程」都必須走版本控管。

硬性規則：

1. 一般互動只能套用 Standard Workflow 1.01，不得臨時改寫流程。
2. 單次選股失誤只能先記為 `failure_case`，不得直接覆蓋標準流程。
3. 若要把失誤修正升級成標準流程，必須建立明確 goal，至少包含：
   - 問題定義。
   - 失誤原因。
   - 新規則。
   - 對既有 MVP 的影響。
   - 可驗證方式。
4. 標準流程升版時，必須同步更新：
   - `docs/standard-workflow-v1.md`
   - `.omx/project-memory.json`
5. 未完成 goal 修正前，回覆只能說「臨時觀察 / 研究假設」，不能說成「標準流程」。
6. 後續回答若提到流程，必須引用 Standard Workflow 1.01，不得因對話語氣漂移出新版本。

## 1. Active MVP Strategy

唯一有效 MVP：`R18H6_VOL_exit_only_WR3`

Canonical records:

- `.omx/backtests/MVP_R18H6_VOL_exit_only_WR3.md`
- `.omx/backtests/mvp-r18h6-vol-exit-only-wr3-2025-06-01_2026-06-17.json`

策略規則：

1. Entry 使用 canonical R18H6 entry logic。
2. HMA 只作趨勢參考，不作單獨進出場主因。
3. 成交量概念主要用在 exit / risk：量價轉弱、放量不漲、價跌量增、熱度退潮。
4. WR3 盤中假突破處理：買進當天若最高價達買價 +2%，但收盤價沒有站回買價，視為熱度未延續，當天以 +2% 目標價先收小利出場。
5. 不使用已移除的 R19 / R20 / entry-quality 實驗規則；WR3 是 Standard Workflow 1.01 的主策略組件。
6. 不把基本面或市場敘事當硬性買進條件；只作加減分與題材背景。


## 1A. Large-Cap / Core Holding Analysis Gate

權值股、核心資產、長期持有標的不得直接套用短線題材股 MVP 進場邏輯。

適用範圍：

- 台積電 2330。
- 其他高權重核心股，例如主要權值半導體、金融或大型 ETF 成分核心股。
- 使用者明確表示「長期持有 / 買低點 / 核心配置」的標的。

硬性規則：

1. 不得把 `R18H6_VOL_exit_only_WR3` 的短線 hot-stock entry 結論直接等同於權值股進場建議。
2. 權值股分析順序必須改為：
   - 大盤指數位置與風險胃納。
   - 權值股對加權指數的撐盤 / 拖累效果。
   - 電子、半導體、金融等主要權值族群同步性。
   - 該權值股自身長期均線、估值區間、基本面與法人籌碼。
   - 最後才參考短線 study 訊號作為「是否分批 / 是否等待」的輔助。
3. 權值股買點應以分批配置、低點區間、風險報酬為主，不以短線熱門股追價為主。
4. 若短線 study 顯示 avoid / bearish，但長期基本面未破壞，回答必須區分：
   - 短線不追。
   - 長期可分批。
   - 更佳低接區間。
   - 趨勢修復確認價。
5. 若使用者問台積電，必須至少同時看加權指數、電子/半導體指數或大盤 breadth，再決定是否適合長期分批進場。
6. 回覆不得把權值股當一般 3～7 天題材股處理；除非使用者明確要求「只做短線」。

## 2. Taiwan Market Data Source Order

台股價格、量價、K 棒、成交量、即時 snapshot、ticks/orderbook：

1. Primary：SinoPac Shioaji local server / API。
2. Shioaji failure gate：若 Shioaji 連線、health、quote、snapshot、kbars 失敗，必須先處理 API server / session 問題，再繼續研究。
3. Fallback：FinMind / Fugle / TWSE / TPEx only when Shioaji lacks the dataset or is externally unavailable after repair attempt。
4. 若使用 fallback，回答中必須標示資料限制與 Shioaji 修復狀態。

Shioaji failure gate 標準處理：

1. 不得在 Shioaji 失敗後直接往下做實盤研究或選股。
2. 先判斷失敗類型：
   - `fetch failed` / 8080 refused：本機 API server 未啟動或 pid stale。
   - `NotReady` / `SessionNotEstablished`：server 在，但 broker session 未建立。
   - 500 response：讀取 error body 判斷是 session、contract、還是 endpoint 問題。
3. 最小修復順序：
   - 檢查 `.omx/shioaji-server.pid`、8080 listener、health endpoint、server log。
   - 只重啟 Shioaji server，不重啟 LINE bridge / tunnel / Codex agent，除非使用者明確要求。
   - 優先使用 repo daemon wrapper：`node src/shioaji-server.js --daemon --pid-file .omx/shioaji-server.pid > .omx/logs/shioaji-server.log 2>&1`。
   - 更新 `.omx/shioaji-server.pid`。
4. 修復後必須驗證：
   - `curl http://127.0.0.1:8080/api/v1/health` 回 healthy。
   - `node src/cli.js shioaji-quote --ticker 2330 --format markdown` 成功。
   - 若要分析特定股票，再用該 ticker 跑一次 Shioaji quote / snapshots。
5. 只有以下情況才可 fallback：
   - Shioaji 官方 / broker 端不可用。
   - 目標資料 Shioaji 不提供。
   - 修復後仍失敗且已明確標示原因與風險。
6. fallback 後若 Shioaji 恢復，後續研究必須回到 Shioaji 第一順位。

單一股票分析必跑：

```bash
node src/cli.js daily-decision-study --ticker <TICKER> --market tw --period 20 --start-date 2026-01-01 --decision-days 20 --lookback-bars 60 --format markdown
node src/cli.js signal-study --ticker <TICKER> --market tw --period 20 --start-date 2026-01-01 --volume-window 20 --institutional-days 5 --forward-days 3,5,10 --format markdown
```

## 3. Gooaye 股癌 Topic Research Workflow

股癌資料只作題材熱度來源，不作價格資料或買賣建議。

Source order:

1. 預設優先查 `https://whatmkreallysaid.com/`，用它的完整 EP 逐字稿做題材研究；可依集數、日期或關鍵字搜尋。
2. 只有當使用者明確要求「最新一集 / 最新資訊 / 最近股癌」時，才先讀官方 SoundOn RSS 確認最新 EP：
   `https://feeds.soundon.fm/podcasts/954689a5-3096-43a4-a80b-7810b219cef3.xml`
3. 若 whatmkreallysaid 已有同集逐字稿，直接使用網站逐字稿摘要題材。
4. 若網站尚未更新到最新 EP，才執行 fallback worker：

```bash
../stock-data/scripts/run_gooaye_worker.sh
```

5. worker 完成後讀 S3 manifest：

```text
s3://gooaye-transcript-dev-898912608626-be19e2/gooaye/latest.json
```

6. 依 manifest 讀 summary / transcript JSON 後摘要。
7. 題材結論必須再用 Shioaji 驗證量價、成交量、同族群同步性，才可進入 MVP 判斷。

## 4. IC.TPEX 產業鏈 Mapping Workflow

`https://ic.tpex.org.tw/` 是 TPEx/TWSE 產業價值鏈資訊平台；用於把題材關鍵字映射到官方產業鏈與同族群公司，不作價格資料或單獨買賣依據。

使用位置：

1. Gooaye / 新聞 / 使用者題材抽出關鍵字後，先到 ic.tpex 對應產業鏈。
2. 建立同產業鏈 candidate universe，例如被動元件、半導體、連接器、PCB、電腦週邊、AI / 雲端運算等。
3. 檢查同族群同步性：同鏈股票是否一起量增、價動、收高。
4. 只把 ic.tpex 結果當「產業鏈分類與 peer group」；成交量、K 棒、流動性、study 訊號仍必須回到 Shioaji + `R18H6_VOL_exit_only_WR3` 驗證。
5. 若 ic.tpex 公司面資料與市場資料衝突，以 Shioaji 量價資料決定是否進入交易觀察。

## 4A. Xiaoyu ETF Holding Lens

`https://xiaoyu-etf.pages.dev/` 是公開台股 ETF 持股追蹤與 ETF 推估買賣資料來源；用於補強 ETF/投信籌碼視角，不作價格、量價或單獨買賣依據。

使用位置：

1. 單一股票分析、ETF 分析、主動式 ETF 持股變化、投信/ETF 買賣超題目，可加跑：

```bash
node src/cli.js xiaoyu-etf --mode stock --ticker <TICKER> --format markdown
node src/cli.js xiaoyu-etf --mode etf --etf <ETF_CODE> --format markdown
node src/cli.js xiaoyu-etf --mode rank --scope active --window d1 --direction buy --format markdown
```

2. `xiaoyu-etf` 已接進 `research-pack` 的台股預設 coverage；它只補「哪些 ETF 持有 / 主動式 ETF 是否加減碼 / ETF 推估買賣排行」。
3. 價格、K 棒、即時 snapshot、流動性、成交量確認仍必須回到 Shioaji primary。
4. 若 Xiaoyu ETF 與 Shioaji / 交易所官方資料衝突：
   - 價量與交易判斷以 Shioaji / 交易所為準。
   - ETF 持股與 ETF 推估買賣只作籌碼加減分與觀察名單排序。
5. 對外回答必須標示這是「ETF 持股推估 / 輔助籌碼」，不得稱為官方投信買賣超，也不得因 ETF 加碼就給無條件買進指令。


## 5. Taiwan Industry Code Guard

產業分類是選股品質的核心輸入，不能用臨時猜測改寫。

硬性規則：

1. 台股產業代碼 `28` = `電子零組件`，包含被動元件與電子零組件熱度候選，**絕對不可排除**。
2. 預設排除產業只包含 `17` = `金融保險`；除非使用者明確要求，不得新增其他產業碼到排除清單。
3. 全市場篩選、hotScore、產業熱度、同族群同步性研究都必須保留 `28`。
4. 若研究腳本嘗試把 `28` 放入 `excludedIndustries`，`src/hot-stock-filter.js` 必須直接丟錯；`tests/hot-stock-filter.test.js` 有 regression test 保護此規則。
5. 題材分類仍需用 ic.tpex 驗證產業鏈；價格、成交量、K 棒、法人/量價訊號仍回 Shioaji 驗證。

## 6. Weak Follower Avoidance / Peer Relative Strength Gate

2458 義隆案例顯示：單一個股 study 分數偏高，不代表它是同題材中最值得交易的標的。若同題材主流股明顯更強，弱跟漲股會造成機會成本與停損風險。

新增硬性流程：

1. 先判斷市場主線與同題材 peer group，再判斷個股；不得只因單股 HMA / study / 成交量訊號就列為首選。
2. 同題材候選至少比較：
   - 即時漲幅 / 開盤後延續率。
   - 今日量能與 20 日均量比。
   - 是否接近或突破當日高點。
   - 是否強於同題材中位數。
   - 是否為該題材前 3 名資金集中標的。
3. 若個股落後同題材領漲股明顯，例如同題材強股漲幅與量能都大幅領先，而該股仍低於買入成本或站不回關鍵價，則標記為「跟漲弱股」。
4. 跟漲弱股處理：
   - 不列為當日首選。
   - 可觀察但不得加碼。
   - 必須等站回成本 / 關鍵價且量能延續，才可重新評估。
   - 若跌破日內低點或核心風控價，優先退出。
5. 對持股回覆需明確區分：
   - 「方向有機會」與「是不是最強標的」。
   - 「可續抱」與「值得加碼」。
   - 「個股 study 勝率」與「同題材相對強度」。

2458 義隆復盤結論：

- 失誤不在於題材方向完全錯，而是沒有足夠懲罰它相對於聯茂、南亞科、華新科、雷科等同題材強股的落後。
- 後續主流程必須把 peer relative strength 放在個股 study 之前或至少同權重檢查。

## 7. LINE Bridge Handoff Rule

LINE bridge 回覆流程：

1. 若 LINE prompt 指定 response file，必須先把完整 Markdown 最終回覆寫入該檔，再回覆同一份內容。
2. 若接上的 panel 是新開 session，需注入/閱讀 `docs/line-session-handoff.md`。
3. 若接上的 panel 是 resume 既有 session，不需要重複 handoff。

## 8. Repo Hygiene Rules

1. 不保留舊策略實驗 artifacts 作為記憶來源。
2. `.omx/backtests` 只保留 canonical MVP record 與 canonical backtest JSON。
3. 任何新策略實驗必須另存為臨時研究，不得覆蓋 Standard Workflow 1.01，除非使用者明確要求升版並完成 goal 修正。
4. 對外回答不得引用 raw secrets、完整 token、或不必要工具原始輸出。

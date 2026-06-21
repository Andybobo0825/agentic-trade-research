# Trade Repo Standard Workflow 1.0

本文件是目前 repo 的標準流程來源。若舊對話、舊 backtest、舊策略名稱與本文件衝突，以本文件為準。

## 1. Active MVP Strategy

唯一有效 MVP：`R18H6_VOL_exit_only`

Canonical records:

- `.omx/backtests/MVP_R18H6_VOL_exit_only.md`
- `.omx/backtests/mvp-r18h6-vol-exit-only-2025-06-01_2026-06-17.json`

策略規則：

1. Entry 使用 canonical R18H6 entry logic。
2. HMA 只作趨勢參考，不作單獨進出場主因。
3. 成交量概念主要用在 exit / risk：量價轉弱、放量不漲、價跌量增、熱度退潮。
4. 不使用已移除的 R19 / R20 / WR / entry-quality 實驗規則。
5. 不把基本面或市場敘事當硬性買進條件；只作加減分與題材背景。

## 2. Taiwan Market Data Source Order

台股價格、量價、K 棒、成交量、即時 snapshot、ticks/orderbook：

1. Primary：SinoPac Shioaji local server / API。
2. Fallback：FinMind / Fugle / TWSE / TPEx only when Shioaji lacks the dataset or is unavailable。
3. 若使用 fallback，回答中必須標示資料限制。

單一股票分析必跑：

```bash
node src/cli.js daily-decision-study --ticker <TICKER> --market tw --period 20 --start-date 2026-01-01 --decision-days 20 --lookback-bars 60 --format markdown
node src/cli.js signal-study --ticker <TICKER> --market tw --period 20 --start-date 2026-01-01 --volume-window 20 --institutional-days 5 --forward-days 3,5,10 --format markdown
```

## 3. Gooaye 股癌 Topic Research Workflow

股癌資料只作題材熱度來源，不作價格資料或買賣建議。

Source order:

1. 先讀官方 SoundOn RSS，確認最新 EP：
   `https://feeds.soundon.fm/podcasts/954689a5-3096-43a4-a80b-7810b219cef3.xml`
2. 再查 `https://whatmkreallysaid.com/` 是否已有同集逐字稿。
3. 若網站已有同集逐字稿，直接使用網站逐字稿摘要題材。
4. 若網站尚未更新，才執行 fallback worker：

```bash
../stock-data/scripts/run_gooaye_worker.sh
```

5. worker 完成後讀 S3 manifest：

```text
s3://gooaye-transcript-dev-898912608626-be19e2/gooaye/latest.json
```

6. 依 manifest 讀 summary / transcript JSON 後摘要。
7. 題材結論必須再用 Shioaji 驗證量價、成交量、同族群同步性，才可進入 MVP 判斷。

## 4. LINE Bridge Handoff Rule

LINE bridge 回覆流程：

1. 若 LINE prompt 指定 response file，必須先把完整 Markdown 最終回覆寫入該檔，再回覆同一份內容。
2. 若接上的 panel 是新開 session，需注入/閱讀 `docs/line-session-handoff.md`。
3. 若接上的 panel 是 resume 既有 session，不需要重複 handoff。

## 5. Repo Hygiene Rules

1. 不保留舊策略實驗 artifacts 作為記憶來源。
2. `.omx/backtests` 只保留 canonical MVP record 與 canonical backtest JSON。
3. 任何新策略實驗必須另存為臨時研究，不得覆蓋 Standard Workflow 1.0，除非使用者明確要求升版。
4. 對外回答不得引用 raw secrets、完整 token、或不必要工具原始輸出。

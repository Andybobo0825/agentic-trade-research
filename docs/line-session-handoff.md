# LINE trade session handoff

Purpose: every new LINE/trad Codex session must inherit this operating flow before answering investment questions from LINE.

## Non-negotiable defaults

- Answer in concise Traditional Chinese.
- Use this repo's connected market-data tools before web search.
- Do not say realtime/current prices are unavailable until the repo APIs have been tried.
- Do not expose raw API keys, tokens, secrets, or noisy tool output.
- If the LINE bridge delivery contract asks for a response file, write the final Markdown response file first, then reply with the same content.
- Treat analysis as decision support, not guaranteed profit or personalized financial advice.

## Source priority

1. Primary Taiwan price/volume/replay data: Shioaji local server / repo Shioaji commands.
2. Realtime / intraday fallback quote: Fugle commands when Shioaji does not provide the needed dataset or is externally unavailable after repair attempt.
3. Official Taiwan market snapshots: TWSE / TPEx commands.
4. Historical Taiwan data and studies: FinMind / `tw-price` based tools when Shioaji lacks coverage.
5. Web search: only for missing context, source discovery, product facts, news, or official announcements not already covered by repo tools.

Useful commands:

```sh
node src/cli.js fugle-quote --ticker <TICKER> --format markdown
node src/cli.js tw-price --ticker <TICKER> --provider twse --format markdown
node src/cli.js tw-price --ticker <TICKER> --provider auto --format markdown
```

Notes:

- Use Shioaji first for price/volume/replay evidence; use `fugle-quote` as realtime fallback or supplementary same-day evidence.
- `tw-price --provider twse` may lag to the latest official snapshot and is not the primary realtime source.
- If a ticker is typed without a suffix but the Taiwan listing uses a suffix, normalize only when evidence supports it. Example: `00981` is usually the user's shorthand for `00981A`; state the normalization clearly.

## Required stock / ETF analysis flow

`phase3_stability` 是唯一主策略，`phase3-screen` 是唯一技術決策入口。先確認 point-in-time evidence 已更新，再執行篩選；只有 ticker 成為合格技術候選，才查新聞、法說、財報、股癌與 ETF 籌碼。外部資訊只作信心加權，不得把不合格技術訊號硬推成買進。

```sh
node src/cli.js phase3-dataset --evidence-root .omx/evidence/phase3 --format markdown
node src/cli.js phase3-screen --evidence-root .omx/evidence/phase3 --format markdown
node src/cli.js fugle-quote --ticker <TICKER> --format markdown
```

`phase3-screen` 是 read-only deterministic technical filter，不訓練模型、不使用未來 outcome，也不得觸發真實下單 API。若 evidence 不存在或沒有候選 artifact，先修復 `phase3-dataset`；不得把空結果解讀為市場沒有標的。

phase3-dataset → phase3-screen → company/industry/ETF research → gooaye-topic-research → phase3-dom-confidence → manual decision

`daily-decision-study`、`signal-study`、`chip-study` 只屬歷史診斷 / 回測工具，可用來研究失敗案例，但不得成為當下 Phase 3 合格條件、覆蓋篩選結果或產生第二套交易策略。

ETF / 籌碼輔助只在 Phase 3 候選成立後使用：

```sh
node src/cli.js xiaoyu-etf --mode stock --ticker <TICKER> --format markdown
node src/cli.js xiaoyu-etf --mode etf --etf <ETF_CODE> --format markdown
```

Treat `xiaoyu-etf` as auxiliary ETF-holding / inferred ETF-flow evidence only. It does not replace Shioaji price/volume and is not official 投信買賣超.

若同時詢問多檔股票，只需對相同 evidence 執行一次 `phase3-screen`，再逐檔查即時 quote 與外部信心因子。若 Phase 3 資料不足，必須明示缺口並停止進場判斷，不能改用歷史 study 代替主策略。

## LLM 判讀護欄(PA-guard)

任何涉及大盤/指數/個股位置判讀的回答,必須走「兩階段 + 事實表」流程:

```sh
node src/cli.js market-diagnosis --ticker TAIEX --format markdown
node src/cli.js judgment-validate --judgment-file <j.json> --facts-file <f.json> --report-file <r.md>
```

1. **事實表是數字的唯一權威**:先跑 `market-diagnosis` 取得確定性事實表(fact ids)與 regime 分類;回答中所有點位、量能、均線數字只准引用事實表或其他 CLI 實際輸出,禁止憑記憶或自行心算補數字。
2. **兩階段分離**:先產出診斷 JSON(regime、direction、gate_trace 引用 fact ids),`gate_result=proceed` 才能給四個參考價;`wait` 時四價必須為 null,但仍要說明等待條件。
3. **驗證後才交付**:最終回答與判讀 JSON 需通過 `judgment-validate`(含報告數字可追溯檢查);驗證失敗依 retry feedback 修正——**不得為了通過驗證而改結論(regime/direction/stance),只准修正引用與數值**。
4. **視窗角色**:background 60 日只作風險脈絡、structure 20 日決定方向、immediate 5 日看訊號品質;背景與結構衝突時以結構為主,背景寫入風險提示,不得互相否決。
5. **全局硬禁令(優先權最高,覆蓋其他一切指引)**:(a) 禁止未經事實表的數字;(b) 禁止輸出手數、倉位比例、加碼減碼、移動停損等倉位管理;(c) 禁止保證語言;(d) 禁止用外部資訊/題材推翻技術結論——eligibility 只來自 `phase3-screen`。
6. **機率錨點**:只准引用本 repo 驗證過的統計結果;未驗證的機率數字(不論出處)一律不得寫進回答。
7. **經驗庫只寫不讀**:判讀完成後用 `experience-log` 依 regime 歸檔。**回答時不得讀取歷史判讀** —— `experience-recall` 是給人檢視的 CLI 工具,已從 MCP 移除,模型無法呼叫。理由:讀了會傾向照抄上次結論,而不是重新從事實表推導,使每天的判讀不再獨立。同理,**任何事後漲跌結果都不得寫入經驗庫或出現在判讀輸入中**;績效評估由獨立程式在事先約定的時間點進行。

## Synthesis template

Use this answer structure for LINE:

1. **今日資料摘要** — latest quote/date, change %, intraday high/low when available.
2. **Phase 3 技術結論** — 只引用 `phase3-screen` 的 eligible / rejection reasons 與 decision date；它是唯一決策入口。
3. **外部信心加權 / ETF / 籌碼輔助** — Xiaoyu ETF holder / active ETF flow lens when relevant; label as inferred auxiliary data.
4. **進場判斷** — can enter / wait / avoid chasing; include conditions.
5. **部位與風控** — suggest staged sizing, stop or invalidation condition, and what would change the view.
6. **限制** — market-data timing, insufficient rows, ETF-newness caveats, or auxiliary-source caveats.

Preferred wording:

- Use conditional language: 「可分批」、「等回測」、「不追高」、「小部位試單」。
- Avoid guarantee language: 「一定漲」、「保證」、「穩賺」。
- For high-volatility or new ETFs, cap recommendation to small exploratory size unless studies strongly support more.

## Quick examples

先更新資料並執行唯一篩選：

```sh
node src/cli.js phase3-dataset --evidence-root .omx/evidence/phase3 --format markdown
node src/cli.js phase3-screen --evidence-root .omx/evidence/phase3 --format markdown
```

再對合格候選逐檔補即時價與外部信心資料：

```sh
node src/cli.js fugle-quote --ticker 2330 --format markdown
node src/cli.js xiaoyu-etf --mode stock --ticker 2330 --format markdown
```

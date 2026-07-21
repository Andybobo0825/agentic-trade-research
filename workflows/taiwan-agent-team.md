# Taiwan Agent Team — Standard Workflow 1.4

`taiwan-agent-team` 是目前正式台股主流程的確定性 orchestration layer。它不新增預測模型，也不建立重疊策略；`phase3_stability` 仍是唯一主策略，`phase3-screen` 仍是唯一技術篩選機制。

## Public modes

### Screen

只有使用者要求選股、篩選股票、候選股票或全市場掃描時才執行 Phase 3：

```bash
node src/cli.js taiwan-agent-team --query "篩選台股候選" --mode screen --format markdown
```

固定順序：

```text
phase3-dataset → phase3-screen → eligible-only company/industry/ETF research → gooaye-topic-research → phase3-dom-confidence → four prices → manual decision
```

只有 eligible candidates 進入 downstream research 與 DOM。Rejected ticker 不會被外部資訊翻成 eligible；零 eligible 候選時停止逐檔 research 與 DOM。

Phase 3 eligible 只代表技術門檻通過。最終 actionable shortlist 必須揭露候選與股癌／當前市場題材的相符性；明顯不符者可從現行推薦撤下，但原始 Phase 3 結果仍保留作稽核，不能改寫成 rejected。

### Analyze

指定 ticker 分析不執行 Phase 3，不宣稱已通過技術篩選：

```bash
node src/cli.js taiwan-agent-team --query "分析台積電" --mode analyze --tickers 2330 --format markdown
```

每檔標示 `phase3Eligibility: not_evaluated`，再執行市場 context、外部信心、DOM 與四個價格。

## Seven agent lanes

1. `planner` — 判斷模式、參數、階段與停止條件。
2. `data-agent` — 盤點 repo 證據；screen 模式準備 point-in-time Phase 3 資料。
3. `strategy-agent` — screen 模式執行 `phase3-dataset`、`phase3-screen` 並只傳遞 eligible candidates。
4. `market-agent` — 讀取 Shioaji 指數/個股、盤前、sector flow 與 IC.TPEX peers。
5. `external-confidence-agent` — 整合公司、新聞、公告、財報、營收、估值、ETF 與股癌題材證據；股癌必須於 DOM 前實際執行且只執行一次。
6. `dom-agent` — 研究完成後讀取 read-only Shioaji DOM 並保存四個價格。
7. `verifier` — 稽核順序、錯誤、缺口、eligibility 邊界與無下單安全性。

## Output contract

- `workflowVersion: "1.4"`、resolved `workflowMode`、七 agent lanes 與 ordered audit。
- Screen 模式保留 Phase 3 dataset/screen 摘要與 eligible targets。
- 每檔保留外部資料 availability，並保留當次共用的股癌 episode/status/themes、DOM score/pressure/reliability/risks。
- 有效 DOM 樣本交付 `activeEntryLimit`、`patientEntryPrice`、`takeProfitPrice`、`stopLossPrice`。
- DOM 不可用時四欄仍存在且為 `null`，不得自行估價或隱藏資訊。

## Artifacts and safety

- Scratchpad: `.omx/agent-team/scratchpad/*.jsonl`
- Markdown report: `.omx/agent-team/reports/*-taiwan-agent-team.md`
- Offline mode 不執行 Phase 3、市場、外部研究或 DOM tools。
- 所有 Shioaji/DOM 操作為 read-only；沒有 order API，使用者手動決策與下單。

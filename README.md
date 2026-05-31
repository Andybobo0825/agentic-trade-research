# Codex Finance Tools

這是一套給 Codex 使用的輕量財經資料 CLI 工具。

重點：

- **Codex 負責分析與推理**：使用你現有的 Codex / ChatGPT 額度。
- **本 repo 只負責抓資料**：從外部財經資料 API 取得資料，輸出 JSON 或 Markdown。
- **Agent workflow management harness**：LINE、tmux、MCP、OMX/Codex 與資料工具被包成一個可啟停、可排隊、可驗證的本機 agent 操作平台。

## 作品集版架構總覽：Agent Workflow Management Harness

這個 repo 的核心不是單一 CLI，而是一個 **本機 agent harness**：

1. **LINE bridge** 把手機訊息轉成可控的 Codex/tmux prompt。
2. **授權層** 用 LINE friend / userId 白名單控管誰能操作本機 agent。
3. **全域 FIFO queue** 讓多位 LINE 使用者同時送 prompt 時不漏訊息，依序送進同一個 Codex/tmux pane。
4. **Codex / OMX runtime** 負責推理、規劃、修改 repo、驗證與產生回覆。
5. **trade-finance MCP / CLI tools** 提供低 token 的結構化金融資料工具。
6. **response-file contract** 要求 Codex 把完整 LINE-safe Markdown 回覆寫入 `.omx/line-bridge/responses/*.md`，再由 bridge push 回原使用者。

架構圖 PNG：[`docs/diagrams/trade-line-bridge-workflow.png`](docs/diagrams/trade-line-bridge-workflow.png)  

![Trade LINE Bridge Workflow](docs/diagrams/trade-line-bridge-workflow.png)

### Agent / workflow 定義在哪裡？

這個專案刻意把「repo 內 harness」與「Codex/OMX agent 定義」分層：

- **Repo 內沒有 checked-in `AGENTS.md`**。目前看到的 AGENTS.md 指令是 OMX/Codex session 注入的 runtime contract，不是這個 repo commit 的檔案。
- **Codex native agents** 安裝在使用者層：`~/.codex/agents/*.toml`，每個 agent 通常搭配 `~/.codex/prompts/*.md`。
- **OMX workflow skills** 安裝在：`~/.codex/skills/*/SKILL.md`。
- **Repo-native workflow prompts** 放在：`workflows/*.md`，它們不是常駐 agent，而是給 Codex 執行投資研究時引用的流程模板。

主要 agent / workflow surfaces：

| 類型 | 名稱 | 定義位置 | 在本 repo 的角色 |
| --- | --- | --- | --- |
| Runtime contract | AGENTS.md / OMX session contract | session 注入；本 repo 目前無 checked-in `AGENTS.md` | 規範 agent 自主執行、驗證、技能路由、子代理協作與安全邊界 |
| Native agent | `explore` | `~/.codex/agents/explore.toml` + `~/.codex/prompts/explore.md` | 快速 repo lookup、檔案/符號/關係探索 |
| Native agent | `researcher` | `~/.codex/agents/researcher.toml` + `~/.codex/prompts/researcher.md` | 官方文件、外部資料、Jina/web research |
| Native agent | `dependency-expert` | `~/.codex/agents/dependency-expert.toml` + `~/.codex/prompts/dependency-expert.md` | MCP / SDK / package 採用與替換評估 |
| Native agent | `executor` | `~/.codex/agents/executor.toml` + `~/.codex/prompts/executor.md` | 實作功能、重構、修 bug |
| Native agent | `debugger` | `~/.codex/agents/debugger.toml` + `~/.codex/prompts/debugger.md` | 追 log、定位 webhook / queue / tmux 問題 |
| Native agent | `test-engineer` | `~/.codex/agents/test-engineer.toml` + `~/.codex/prompts/test-engineer.md` | 設計 regression test、排隊/授權/工具測試 |
| Native agent | `verifier` | `~/.codex/agents/verifier.toml` + `~/.codex/prompts/verifier.md` | 驗證完成條件、確認測試證據 |
| Native agent | `code-reviewer` | `~/.codex/agents/code-reviewer.toml` + `~/.codex/prompts/code-reviewer.md` | 最終 code review 與風險檢查 |
| Workflow skill | `$plan` / `$ralplan` | `~/.codex/skills/plan/SKILL.md`, `~/.codex/skills/ralplan/SKILL.md` | 複雜改動前的計畫與測試形狀 |
| Workflow skill | `$ralph` / `$ultragoal` | `~/.codex/skills/ralph/SKILL.md`, `~/.codex/skills/ultragoal/SKILL.md` | 長任務 self-loop、目標拆解與驗證 |
| Workflow skill | `$team` | `~/.codex/skills/team/SKILL.md` | 多 lane 平行 execution / verification |
| Workflow skill | `$code-review` / `$ultraqa` | `~/.codex/skills/code-review/SKILL.md`, `~/.codex/skills/ultraqa/SKILL.md` | adversarial review、端到端 QA |
| Repo workflow prompt | `research-memo` | `workflows/research-memo.md` | 美股 evidence-first 投資 memo |
| Repo workflow prompt | `taiwan-research-memo` | `workflows/taiwan-research-memo.md` | 台股研究 memo |
| Repo workflow prompt | `dcf-valuation` | `workflows/dcf-valuation.md` | DCF / 估值流程 |
| Repo workflow prompt | `x-research` | `workflows/x-research.md` | 市場敘事 / 新聞 triage |

### Harness 工程亮點

- **LINE → Codex 的可靠交付**：`src/line-bridge.js` 驗簽、授權、排隊、寫入 response-file contract，避免 LINE push 回覆被截斷或混線。
- **多使用者短期佇列化**：global FIFO queue 讓多位使用者同時送 prompt 時會排隊，不會直接拒絕或遺失訊息。
- **可重啟的 ops harness**：`src/tradstart.js` / `src/tradstop.js` 管理 tmux target、bridge process、Cloudflare tunnel 與 runtime state。
- **低 token MCP 工具層**：`src/mcp-server.js` 預設 `compact-json`，支援 `outputFields` / `maxRows` / `research-pack`，把「壓縮輸出」和「保留資料覆蓋」分開。
- **驗證導向**：`tests/*.test.js` 覆蓋 CLI、MCP、LINE bridge、授權、queue、tmux target 選擇與 runtime state。


## 設定 `.env`

```env
# 美股 / Financial Datasets 指令需要
FINANCIAL_DATASETS_API_KEY=your-key
FINANCIAL_DATASETS_BASE_URL=https://api.financialdatasets.ai

# FinMind 台股資料，可選；沒填也能用較低免費額度
FINMIND_API_TOKEN=your-token
FINMIND_BASE_URL=https://api.finmindtrade.com

# TWSE / TPEx 官方 OpenAPI base URL，可選，通常不用改
TWSE_OPENAPI_BASE_URL=https://openapi.twse.com.tw/v1
TPEX_OPENAPI_BASE_URL=https://www.tpex.org.tw/openapi/v1

# Fugle 台股即時 / 盤中資料需要
FUGLE_API_KEY=your-fugle-key
FUGLE_MARKETDATA_BASE_URL=https://api.fugle.tw/marketdata/v1.0/stock
```

## 怎麼搭配 Codex 使用？

你可以叫 Codex 先跑 CLI 抓資料，再用回傳資料做分析。

範例：

> 使用這個 repo 的 CLI 工具研究 2330。請抓公司資料、近期股價、月營收、財報、估值與重大公告，然後用繁體中文寫一份 evidence-first 投資 memo，並清楚分開「資料直接顯示」與「推論」。

美股範例：

> 使用這個 repo 的 CLI 工具研究 AAPL。請抓 5 年 income statement、最新 metrics、最新價格、近期新聞與最近 10-K filing metadata，然後寫一份 concise investment memo，並分開 evidence 與 inference。

## Workflow 文件

`workflows/` 裡是給 Codex 參考的研究流程 prompt，不是另外啟動的 LLM agent。

- `workflows/research-memo.md`：evidence-first 投資 memo 流程
- `workflows/dcf-valuation.md`：DCF / 估值流程
- `workflows/x-research.md`：市場敘事 / 新聞 triage 流程
- `workflows/taiwan-research-memo.md`：台股研究 memo 流程

## MCP 模式


MCP server 會 expose `tools/list` 與 `tools/call`，工具名稱與 CLI 對應。

為了降低 Codex token，MCP `tools/call` 預設回傳 `compact-json`；也可在 arguments 裡指定：

- `format`: `compact-json`、`json` 或 `markdown`
- `outputFields`: 只渲染 row 物件的指定欄位，不改變上游資料抓取量
- `maxRows`: 只限制輸出給 Codex 的 rows，不等同於 provider/API 的 `limit`

本 repo 也提供 `research-pack` 工具，讓一次投資研究把 price/metrics/financials/news/filings 或台股 open data 包成單一低 token evidence bundle。

完整低 token Codex + 必接 MCP 設定見：`docs/token-efficient-codex-mcp.md`。

## 成本邊界

- Codex / ChatGPT 分析：使用你現有的 Codex / ChatGPT 額度。
- 財經資料：由你設定的外部資料來源收費或限制，例如 Financial Datasets、Fugle、FinMind。

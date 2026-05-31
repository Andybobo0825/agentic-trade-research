# Agentic Trade Research

這是一套把 LINE 指令入口、授權白名單、FIFO 任務佇列、tmux runtime adapter 與財經 MCP/CLI 工具串成一條本機 agent workflow 的研究 harness。

重點：

- **Codex 負責分析與推理**：使用你現有的 Codex / ChatGPT 額度。
- **本 repo 負責 agent harness 與資料工具**：把 LINE webhook、授權、排程、tmux runtime adapter、MCP/CLI 金融資料工具與回覆交付串成可運作的本機 agent workflow。
- **低 token evidence pipeline**：MCP 預設 `compact-json`，並提供 `research-pack`、`outputFields`、`maxRows`，讓 agent 讀到精簡但可追溯的資料輸出。

## 作品集版架構總覽：Repo-native Agent Harness

這個 repo 本身定義的是一組 **repo-native logical agents / harness modules**。它不把外部 Codex/OMX 的 agent/skill 當成專案內容，而是提供一個可由手機操作、可授權、可排隊、可呼叫金融資料工具、可交付 Markdown 結果的本機 agent workflow harness。

主要資料流：

1. **Message Intake Agent** 接收 LINE webhook，驗證簽章並解析使用者訊息。
2. **Authorization Agent** 透過 LINE friend / userId 本機白名單控管可操作者。
3. **Command Router Agent** 區分 `/help`、`/status`、`/tail` 與一般 prompt。
4. **FIFO Scheduler Agent** 在多使用者同時送 prompt 時排隊，回覆目前第 N 位，避免遺失任務。
5. **Runtime Adapter Agent** 把排程後的 prompt 安全送進指定 tmux pane，讓外部 Codex runtime 執行。
6. **Finance Data Tool Agent** 以 MCP/CLI 方式提供美股、台股、新聞、公告、財報、估值等低 token evidence。
7. **Response Dispatcher Agent** 讀取 response-file contract 或 fallback turn log，將結果 push 回原 LINE 使用者。
8. **Ops Supervisor** 負責 `tradstart` / `tradestop`，管理 bridge process、Cloudflare tunnel、tmux target 與 runtime state。

架構圖 PNG：[`docs/diagrams/trade-line-bridge-workflow.png`](docs/diagrams/trade-line-bridge-workflow.png)  
架構圖 source：[`docs/diagrams/trade-line-bridge-workflow.drawio`](docs/diagrams/trade-line-bridge-workflow.drawio)

![Agentic Trade Research Repo Harness](docs/diagrams/trade-line-bridge-workflow.png)

### Repo 內的 agent / harness modules

> 這裡的「agent」指本 repo 內負責一段自主流程的 logical agent/module；不是外部 OMX/Codex native agent 定義。

| Repo logical agent / module | 主要檔案 | 責任 |
| --- | --- | --- |
| Message Intake Agent | `src/line-bridge.js` | 建立 LINE webhook server、驗證 `x-line-signature`、解析 LINE text/follow events |
| Authorization Agent | `src/line-bridge.js`, `.omx/line-bridge/authorized-users.json`（runtime ignored） | 自動授權加入好友/首次私訊使用者、維護本機白名單、拒絕未授權來源 |
| Command Router Agent | `src/line-bridge.js` | 處理 `/help`、`/status`、`/tail`、未知指令與一般 prompt |
| FIFO Scheduler Agent | `src/line-bridge.js` | global FIFO queue、busy 狀態、排隊順位回覆、依序啟動 job |
| Runtime Adapter Agent | `src/line-bridge.js`, `src/line-bridge-auto.js` | 選擇/確認 tmux target，透過 tmux paste/send-keys 把 prompt 送進外部執行 runtime |
| Response Dispatcher Agent | `src/line-bridge.js` | 產生 response-file contract、等待 `.omx/line-bridge/responses/*.md`、fallback 到 `.omx/logs/turns-*.jsonl`、切分 LINE push 訊息 |
| Finance Data Tool Agent | `src/mcp-server.js`, `src/tools.js`, `src/cli.js` | expose MCP `tools/list` / `tools/call` 與 CLI，提供 `research-pack`、台股/美股資料、低 token render controls |
| Market Data Connectors | `src/financial-datasets.js`, `src/taiwan-market.js` | 封裝 Financial Datasets、FinMind、TWSE、TPEx、Fugle 等外部資料來源 |
| Ops Supervisor | `src/tradstart.js`, `src/tradstop.js`, `src/trade-runtime.js`, `bin/tradstart`, `bin/tradestop` | 啟停 LINE bridge、Cloudflare tunnel、tmux target/session，寫入/清理 runtime state |
| Research Workflow Templates | `workflows/*.md` | repo-native 投資研究流程模板：美股 memo、台股 memo、DCF、新聞敘事 triage |
| Regression Harness | `tests/*.test.js` | 驗證 CLI、MCP、LINE bridge、授權、FIFO queue、tmux target 選擇、runtime state |

### 外部 runtime 邊界

- **Codex / ChatGPT / OMX 不屬於本 repo 的 agent 實作**；它們是這個 harness 可以驅動的外部推理 runtime。
- 本 repo 的責任是把任務可靠送進 runtime、提供資料工具、保存/交付結果、並用 tests 確保流程可回歸。
- `.env`、`.omx/**`、LINE 白名單、回覆檔、logs、runtime state 都是本機 runtime artifacts，已由 `.gitignore` 排除，不進 GitHub。

### Harness 工程亮點

- **LINE → runtime 的可靠交付**：`src/line-bridge.js` 驗簽、授權、排隊、注入 response-file contract，避免 LINE push 回覆被截斷或混線。
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

# Gooaye 股癌 Podcast Research Workflow Handoff

> **For agentic workers:** 這份文件定義 `trade` repo 如何取得股癌最新逐字稿並轉成市場題材分析。轉錄功能由獨立 `stock-data` repo / worker 負責；本 `trade` repo 只負責判斷資料來源、必要時觸發 worker、從 S3 讀回 JSON，並進行題材摘要與 Shioaji 量價驗證。

**Goal:** 建立穩定的股癌研究 workflow：先確認官方 Podcast 最新集數，再優先使用 `whatmkreallysaid.com` 現成逐字稿；若網站尚未更新，才執行本機 `stock-data/scripts/run_gooaye_worker.sh` 轉錄最新 EP，最後從 S3 manifest / JSON 讀回來摘要分析。

**Architecture:** 官方 SoundOn RSS 是最新集數來源；`https://whatmkreallysaid.com/` 是首選逐字稿來源；`stock-data` worker 是 fallback 自動轉錄來源；S3 `latest.json` 是 worker 完成後的讀取路由。`trade` repo 不保存 raw audio，不內建 STT，所有股癌內容都只作為題材熱度輸入，最後仍需接 Shioaji 量價驗證。

**Primary Source:** Gooaye 股癌 RSS feed: `https://feeds.soundon.fm/podcasts/954689a5-3096-43a4-a80b-7810b219cef3.xml`
**Preferred Transcript Source:** `https://whatmkreallysaid.com/`
**Fallback Worker:** `stock-data/scripts/run_gooaye_worker.sh`

---

## 0. Dev S3 Read Integration Config

目前 dev 環境中，**轉錄 agent 已完成後提供給 `trade` repo 讀取的最新逐字稿 manifest 位置**：

```bash
AWS_REGION="ap-northeast-1"
GOOAYE_READER_ROLE_ARN="arn:aws:iam::898912608626:role/gooaye-transcript-dev-reader"
GOOAYE_LATEST_MANIFEST_S3_URI="s3://gooaye-transcript-dev-898912608626-be19e2/gooaye/latest.json"
GOOAYE_S3_BUCKET="gooaye-transcript-dev-898912608626-be19e2"
GOOAYE_S3_PREFIX="gooaye"
```

驗證狀態（2026-06-21）：本機 `mac-user` 憑證可以讀取 bucket、列出 `gooaye/` prefix、讀取 `gooaye/latest.json`。這組設定在本 repo 的語意是「讀取轉錄 agent 產出的 manifest」，不是要求本 repo 寫入轉錄結果。`GOOAYE_READER_ROLE_ARN` 是讀取角色；若未來本 repo 要改用 assume-role 讀取，需確認 trust policy 允許本 repo 的執行身分。

本機 worker 位置：

```bash
# 若 cwd 是 /Users/chentingwei/Desktop/SideProject/trade
../stock-data/scripts/run_gooaye_worker.sh

# 若 cwd 是 /Users/chentingwei/Desktop/SideProject
stock-data/scripts/run_gooaye_worker.sh
```

---

## 1. Trade Repo Decision Workflow

每次使用股癌資料做研究時，必須依序執行：

1. **查官方 RSS 最新集數**  
   讀取 SoundOn RSS，取得最新 `guid`、`title`、`pubDate`、`enclosure.url`。官方 RSS 是判斷「最新 EP 到哪裡」的唯一基準。

2. **查 whatmkreallysaid 是否已有該集逐字稿**  
   到 `https://whatmkreallysaid.com/` 或其 transcripts index 搜尋最新 EP。若網站已有同集逐字稿，直接採用網站文字建立資訊，不要啟動本機轉錄 worker。

3. **網站沒有最新逐字稿時，才啟動本機 worker**  
   執行 `stock-data/scripts/run_gooaye_worker.sh`（從本 repo cwd 則為 `../stock-data/scripts/run_gooaye_worker.sh`）轉錄官方 RSS 的最新一集 podcast。

4. **從 S3 路由讀回 worker 結果**  
   worker 完成後，讀取 `GOOAYE_LATEST_MANIFEST_S3_URI`，再依 manifest 的 `summaryJsonS3Uri` / `transcriptJsonS3Uri` 抓 JSON 下來摘要。

5. **分析與驗證**  
   逐字稿只作為題材熱度來源。結論要再用 Shioaji 檢查台股同族群量價、成交量、同步性與 MVP `R18H6_VOL_exit_only_WR3` 條件。

決策規則：

```text
Official RSS latest EP
  -> if whatmkreallysaid has same EP transcript: use website transcript
  -> else: run stock-data/scripts/run_gooaye_worker.sh
       -> read S3 latest.json
       -> read transcript/summary JSON
  -> summarize topic heat
  -> verify with Shioaji before stock/actionable output
```

---

## 2. Scope Boundary

### `stock-data` repo / transcript worker 負責

1. 讀取股癌 RSS feed。
2. 判斷最新 EP 是否已處理。
3. 下載該 EP 的 audio enclosure。
4. 將音檔轉成繁中逐字稿。
5. 產出時間戳、段落、關鍵字、產業題材初步標籤。
6. 將 artifacts 寫入私有 S3。
7. 產生 `latest.json` manifest。
8. 完成後更新 S3 `latest.json`，讓本 `trade` repo 讀取分析。

### 本 `trade` repo 負責

1. 從 `GOOAYE_LATEST_MANIFEST_S3_URI` 讀取 transcript agent 產出的 `latest.json` manifest。
2. 依 manifest 內的 S3 URI 讀取逐字稿摘要與關鍵字，做題材熱度推論。
3. 再用 Shioaji / 台股量價資料驗證是否有可交易標的。
4. 不保存 raw audio，不重新轉錄音檔。

---

## 3. External Facts Already Verified

- 節目名稱：`Gooaye 股癌`
- Hosting：SoundOn
- RSS feed：`https://feeds.soundon.fm/podcasts/954689a5-3096-43a4-a80b-7810b219cef3.xml`
- RSS item 有 `title`、`pubDate`、`guid`、`enclosure url`，可以用 `guid` 作為去重主鍵。
- RSS 最新集數會早於非官方逐字稿網站，因此要以 RSS 為「最新 EP」來源。

---

## 4. Fallback Worker Pipeline

### Step 1: Poll RSS

- 頻率：每 30～60 分鐘一次即可。
- 排序：以 `pubDate` 由新到舊。
- 去重 key：RSS `guid`。
- 若最新 `guid` 已存在於 checkpoint，直接結束。

Checkpoint 建議存放：

```json
{
  "lastProcessedGuid": "99c7ad0e-d899-4a9a-9450-749b5053dbff",
  "lastProcessedPubDate": "Sat, 20 Jun 2026 05:40:47 GMT",
  "lastProcessedEpisodeTitle": "EP672 | 🐣",
  "updatedAt": "2026-06-21T12:00:00+08:00"
}
```

### Step 2: Download Audio

從 RSS item 的 `enclosure.url` 下載 audio。

要求：

- 設定 timeout、重試、檔案大小上限。
- 保存檔案 checksum，例如 SHA256。
- 失敗時不要產生 ready manifest。
- 不要把 audio 檔案公開。

### Step 3: Transcribe

建議使用可自架或可 API 化的 STT：

- Whisper / faster-whisper
- OpenAI speech-to-text
- 其他可輸出繁中與 timestamp 的引擎

輸出要求：

- 語言：繁體中文優先；若模型輸出簡中，需轉繁中。
- 需要段落級 timestamps。
- 儘量保留財經專有名詞：台積電、被動元件、功率半導體、DrMOS、Nexperia、ASIC、CPO、AIPC、SOX、Nasdaq 等。
- 若 confidence 偏低，標記 `lowConfidence: true`，不要硬改成看似確定的文字。

### Step 4: Extract Analysis Hints

逐字稿完成後，產出初步分析欄位，方便 `trade` repo 快速判斷題材熱度。

至少要有：

```json
{
  "keywords": ["被動元件", "功率半導體", "Nexperia", "DrMOS"],
  "industries": ["離散元件", "功率半導體", "AI伺服器"],
  "tickersMentioned": [],
  "marketTone": "risk_on",
  "topicHeatCandidates": [
    {
      "topic": "功率半導體",
      "reason": "節目中多次提及供應鏈與高階功率元件商機",
      "confidence": "medium"
    }
  ]
}
```

注意：這裡只做「語意與題材標籤」，不要直接產出買賣建議。

### Step 5: Store to S3

S3 bucket 必須是私有。建議 key layout：

```text
s3://<private-bucket>/gooaye/raw-audio/YYYY/MM/DD/<guid>.mp3
s3://<private-bucket>/gooaye/transcripts/YYYY/MM/DD/<guid>.md
s3://<private-bucket>/gooaye/transcripts/YYYY/MM/DD/<guid>.json
s3://<private-bucket>/gooaye/summaries/YYYY/MM/DD/<guid>.json
s3://<private-bucket>/gooaye/manifests/YYYY/MM/DD/<guid>.json
s3://<private-bucket>/gooaye/latest.json
```

`raw-audio` 可設定較短 lifecycle，例如 7～30 天；transcript 與 manifest 可長期保留。

### Step 6: Return Manifest to trade repo

支援兩種方式，至少實作其中一種：

#### Option A: S3 pull model

更新：

```text
s3://<private-bucket>/gooaye/latest.json
```

本 `trade` repo 之後固定讀取 `latest.json`。

#### Option B: Webhook push model

對 `TRADE_GOOAYE_INGEST_WEBHOOK_URL` 發送 POST。

要求：

- Header: `X-Gooaye-Agent-Signature: sha256=<hmac>`
- HMAC secret 只放環境變數，不寫入 repo。
- POST body 使用下方 manifest schema。

---

## 5. Manifest Schema

每次完成一集轉錄後，輸出一份 manifest。

```json
{
  "schemaVersion": "gooaye-transcript.v1",
  "status": "ready",
  "createdAt": "2026-06-21T12:00:00+08:00",
  "source": {
    "podcast": "Gooaye 股癌",
    "rssUrl": "https://feeds.soundon.fm/podcasts/954689a5-3096-43a4-a80b-7810b219cef3.xml",
    "guid": "99c7ad0e-d899-4a9a-9450-749b5053dbff",
    "title": "EP672 | 🐣",
    "pubDate": "Sat, 20 Jun 2026 05:40:47 GMT",
    "audioUrlHash": "sha256:<hash-of-audio-url>",
    "audioSha256": "<sha256-of-downloaded-audio>"
  },
  "artifacts": {
    "transcriptMarkdownS3Uri": "s3://<private-bucket>/gooaye/transcripts/2026/06/20/99c7ad0e-d899-4a9a-9450-749b5053dbff.md",
    "transcriptJsonS3Uri": "s3://<private-bucket>/gooaye/transcripts/2026/06/20/99c7ad0e-d899-4a9a-9450-749b5053dbff.json",
    "summaryJsonS3Uri": "s3://<private-bucket>/gooaye/summaries/2026/06/20/99c7ad0e-d899-4a9a-9450-749b5053dbff.json"
  },
  "transcript": {
    "language": "zh-TW",
    "durationSeconds": 5400,
    "segmentCount": 320,
    "lowConfidenceSegments": 6
  },
  "analysisHints": {
    "keywords": ["功率半導體", "被動元件", "Nexperia", "DrMOS"],
    "industries": ["離散元件", "功率半導體"],
    "tickersMentioned": [],
    "marketTone": "risk_on",
    "topicHeatCandidates": [
      {
        "topic": "功率半導體",
        "confidence": "medium",
        "reason": "逐字稿中反覆提及供應鏈與高階功率元件題材"
      }
    ]
  }
}
```

失敗時輸出：

```json
{
  "schemaVersion": "gooaye-transcript.v1",
  "status": "failed",
  "createdAt": "2026-06-21T12:00:00+08:00",
  "source": {
    "podcast": "Gooaye 股癌",
    "guid": "99c7ad0e-d899-4a9a-9450-749b5053dbff",
    "title": "EP672 | 🐣"
  },
  "error": {
    "stage": "transcription",
    "code": "STT_TIMEOUT",
    "message": "Transcription job exceeded configured timeout"
  }
}
```

---

## 6. Transcript Markdown Format

Markdown artifact 格式固定如下：

```markdown
# Gooaye 股癌 EP672 | 🐣

- RSS GUID: 99c7ad0e-d899-4a9a-9450-749b5053dbff
- Published: Sat, 20 Jun 2026 05:40:47 GMT
- Source: SoundOn RSS
- Language: zh-TW
- Transcribed At: 2026-06-21T12:00:00+08:00

## Summary

本集摘要...

## Keywords

- 功率半導體
- 被動元件
- Nexperia

## Transcript

### 00:00:00
逐字稿第一段...

### 00:00:18
逐字稿第二段...
```

---

## 7. Safety / Legal / Cost Rules

1. S3 bucket 必須 private，不要公開散布完整音檔或逐字稿。
2. 不要提交 AWS keys、STT API keys、webhook secret。
3. Log 不要印出 signed URL、完整 token、完整 secrets。
4. 對外回覆時，不要大段引用逐字稿；給 `trade` repo 分析用可以保存完整 transcript，但面向使用者時只摘要。
5. 若 RSS、audio 下載或 STT 失敗，要明確標記資料缺失，不得補造內容。
6. 成本控制：同一 `guid` 不重複轉錄；支援 dry-run 只解析 RSS 不下載音檔。

---

## 8. Suggested Environment Variables

```bash
GOOAYE_RSS_URL="https://feeds.soundon.fm/podcasts/954689a5-3096-43a4-a80b-7810b219cef3.xml"
AWS_REGION="ap-northeast-1"
GOOAYE_READER_ROLE_ARN="arn:aws:iam::898912608626:role/gooaye-transcript-dev-reader"
GOOAYE_LATEST_MANIFEST_S3_URI="s3://gooaye-transcript-dev-898912608626-be19e2/gooaye/latest.json"
GOOAYE_S3_BUCKET="gooaye-transcript-dev-898912608626-be19e2"
GOOAYE_S3_PREFIX="gooaye"
TRADE_GOOAYE_INGEST_WEBHOOK_URL="https://trade-ingest.example.internal/webhooks/gooaye-transcript"
TRADE_GOOAYE_WEBHOOK_SECRET="set-in-secret-manager-not-in-repo"
STT_PROVIDER="whisper"
STT_MODEL="large-v3"
MAX_AUDIO_BYTES="300000000"
POLL_INTERVAL_MINUTES="60"
```

---

## 9. Minimum Tests Before Delivery

### RSS parser tests

- Given RSS XML with two items, newest `pubDate` is selected.
- Given checkpoint contains newest `guid`, no download is triggered.
- Given checkpoint is older, download job is created.

### Audio download tests

- Enclosure URL is downloaded with timeout.
- SHA256 is computed.
- Oversized file is rejected.

### Transcription tests

- A short fixture audio creates zh-TW transcript JSON.
- Segment timestamps are monotonic.
- Low-confidence segments are preserved and marked.

### S3 tests

- Transcript Markdown, transcript JSON, summary JSON, and manifest are uploaded.
- `latest.json` is overwritten only after all per-episode artifacts upload successfully.
- Failed job writes `status: failed` manifest and does not update `latest.json` as ready.

### Webhook tests

- HMAC signature is generated from raw request body.
- Receiving side can verify signature.
- Failed webhook retries with exponential backoff.

---

## 10. Acceptance Criteria

A run is considered successful only when all are true:

1. Latest RSS item is detected by `guid`.
2. Audio is downloaded and checksum recorded.
3. Transcript Markdown and JSON exist in private S3.
4. Summary JSON and `latest.json` manifest exist in private S3.
5. Manifest status is `ready`.
6. The manifest contains `keywords`, `industries`, and `topicHeatCandidates`.
7. No secrets or raw API tokens appear in logs or committed files.
8. Re-running the job for the same `guid` is idempotent.

---

## 11. How `trade` Repo Should Use This

`trade` repo should treat transcript output as **題材來源** only：

1. 讀取 `latest.json`。
2. 拉 summary / transcript。
3. 萃取題材：例如被動元件、功率半導體、AIPC、衛星、ASIC、CPO。
4. 再用 Shioaji 量價、成交量、產業同步性驗證。
5. 只有「題材熱度 + 台股量價確認」同時成立，才進入 MVP 策略評分。

目前 `trade` repo 的 MVP 策略是：`R18H6_VOL_exit_only_WR3`（Standard Workflow 1.1）。逐字稿 worker 不需要理解或實作這套策略，只要提供乾淨、可追溯、即時的題材資料。

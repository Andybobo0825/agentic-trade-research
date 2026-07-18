# Codex Handoff: TMF Research Sidecar — Data Ingestion 現況

更新日期:2026-07-18(Asia/Taipei)
撰寫者:Claude
Repo:/Users/chentingwei/Desktop/SideProject/trade @ main `0b6ca4e`
前一份:`docs/codex-handoff-tmf-sidecar-2026-07-17.md`(Phase 0–6 software-complete 那份,仍有效,本份接續)

## 1. 一句話現況

Phase 0–6 已 merge 進 main。之後接上了真實資料收集:`tmf backfill` 已回補
2024-07-29→2025-06-30 的歷史 TMF ticks(約 1600 萬筆,11GB,本機 `data/`,gitignored)。
下一步(Task #9)是把歷史資料接進 Phase 5 dataset build。**重大限制已查明:歷史研究
先天只有 7/8 特徵群組,無法核准模型;可核准模型必須靠未來 live 收集。**

## 2. 這段期間新增了什麼(main 上,`111db1e`..`0b6ca4e`,依序)

- `111db1e` `tmf backfill` CLI + credentialed smoke:先跑 readonly verifier、只用行情
  API key 登入(程式上不存在憑證參數)、逐日歷史 tick → append-only raw segment。
- `12868ba` R1 連續來源 + 第三週三推導 target + SQLite event-id 註冊表(見 §4 教訓)。
- `ba28b16` 交易日視窗驗證:擋掉 vendor 在非交易日回傳的重複資料。
- `2e7956c` 只抓平日:週末查詢會回傳週五夜盤的重複,週末改記 NON_TRADING_DAY。
- `ed9ceb1` backfill 逐日即時輸出(長跑中斷也留得住進度)。
- `6e26eea` 歷史 dataset adapter 設計 spec:`docs/superpowers/specs/2026-07-18-historical-dataset-adapter-design.md`。
- `82a5777` `processing/historical_adapter.py`:歷史 tick → `TickEvent` + 從內嵌 L1
  派生 `BidAskEvent`(僅 L1 變化時發出、時間戳=來源 tick、標記 `DERIVED_FROM_HISTORICAL_TICK_L1`)。
- `0b6ca4e` 縮減 manifest `phase3-features-hist-l1-v1`(7 群組,無 basis;見 §5)。

每個 commit 前都跑完整 gate:readonly verifier、全套測試(現 ~350)、ruff 0.12.3、
mypy 1.16.1 --strict、compileall。

## 3. 資料資產(本機 `data/`,11GB,未進 git)

- 核心研究區塊:**2024-07-29 → 2025-06-30 連續約 233 個交易日、~1600 萬筆 tick**,
  完整性已驗(時間窗連續、零重疊、正確歸屬近月 target)。
- **資料預算是硬上限**:Shioaji TMFR1 tick 歷史 = 這段封存區間 + 只有約 2–3 週的
  滾動熱視窗。2025-07→2026-06 是永久 API 空洞(vendor 只留最近一年封存)。
- **必須每週 harvest**:`tmf backfill --start <20天前> --end <昨天>`,否則新資料會永久過期。
- 2026-07 另有 10 天碎片(建 backfill 時測的),與封存區塊間隔一年、時序不連續,
  屬於獨立第二區塊,不與主區塊混用。

## 4. Shioaji 歷史 API 的真實語意(踩過的坑,全有測試防回歸)

1. **過期合約會下架** → 過去月份的個別合約(TMF202408…)歷史抓不到;近月歷史只能走
   `TMFR1` 連續別名。因此每筆歷史 tick 存的是 alias,target 用 TAIFEX 第三個星期三
   到期規則**推導**並標記 `taifex-third-wednesday-v1`(不冒充 API 證據)。
2. **`api.ticks(contract, date=d)` 回傳的是「交易日視窗」** `[前一交易日 15:00, d 13:46)`,
   夜盤屬於「次一交易日」。週五夜盤歸在週一。
3. **週末/非交易日查詢會回傳上一視窗的完整複製** → 週末不查(NON_TRADING_DAY);每個
   payload 強制通過視窗驗證,整包在窗外=NO_DATA、混雜=fail-closed。
4. **`login()` 不接受 `fetch_contract=` 參數**(pinned SDK 1.7.0),已移除。
5. **每 tick 一個 fsync 標記檔的設計會壓垮檔案系統**(6 天=170 萬檔、8.6GB、10 分鐘)
   → event-id 註冊表改用單一 SQLite primary key,同樣 fail-closed 防重複。

## 5. 重大限制:歷史研究先天只有 7/8 群組(已用真實 API 查證,結論確定)

- **Shioaji 完全不提供歷史現貨指數**:TAIEX `IX0001`(發行量加權股價指數)的 `ticks()`
  與 `kbars()` 皆回空。
- **TWSE OpenAPI(openapi.twse.com.tw)也不行**:`indicesReport/MI_5MINS_HIST` 名字雖有
  「5MINS」,實際只給每日 OHLC 且只有滾動當月;日線指數無法算盤中基差
  (`basis_change_10s/1m` 需秒/分級)。
- **後果鏈**:歷史 tick 無 underlying → BASIS 基差群組每列皆 None → imputer 在
  「某特徵零筆 inner-train 觀測」時 raise(`models/imputer.py:59`)→ 完整 8 群組
  manifest 在歷史資料上直接崩。
- **所以縮減 manifest 是必要前提,不是選配**。`phase3-features-hist-l1-v1` 去掉 basis
  群組 + `underlying_missing` 指標,保留其餘 7 群組(皆可從 tick 內嵌 L1 計算)。
- **天花板**:歷史資料無法跑完整 8 群組 ablation 閘門(SPEC 27)→ **永遠到不了
  APPROVED_FOR_PAPER**。歷史研究的價值 = 在真實市場微結構上驗證管線、開發特徵/標記、
  取得 7 群組的初步訊號感。**可核准模型必須來自 live 收集**(即時 gateway 同時訂閱
  期貨 + 指數 → 有 basis → 完整 8 群組)。
- **禁止的捷徑**:不得把 basis 改成日線 proxy / forward-fill 來硬湊非空群組 —— 那是為過閘門
  自欺,正是 SPEC 要防的。

## 6. 下一步:Task #9 — 接歷史 dataset build

目標:歷史封存區塊 → Phase 2/3 管線 → 縮減特徵集 → Phase 5 dataset(folds + holdout)。
四步:

1. **生成真實 TAIFEX 交易日曆 JSON**(2024-07..2025-06)。可直接從已存 segments 的實際
   session 首尾 tick 時間 + NO_DATA 假日(如 2024-10-03、2025 農曆年、2025-04-04、颱風日)
   生成,而不是手打。`ResearchBuildSpec.trading_calendar()` 讀的是明確 trading days 的 JSON
   (每天含 day_open/day_close/night_open/night_close/is_expiry)。
2. **`Phase5DatasetIssuer.issue` 支援 `event_type == "historical-tick"`**:該類 segment 的
   records 按日 group,呼叫 `decode_historical_day`(來自 `processing/historical_adapter.py`),
   同時 extend ticks 與派生 quotes。目前 issuer 只認 "tick"/"bidask"
   (`validation/dataset_lineage.py:322`)。
3. **`_derive_samples` 依版本選 manifest**:當 `spec.feature_version ==
   "phase3-features-hist-l1-v1"` 用 `historical_l1_feature_manifest()`,否則
   `default_feature_manifest()`。目前是 `replace(default_feature_manifest(),
   version=spec.feature_version)`(`dataset_lineage.py:389` 附近)—— 這對縮減版行不通。
4. **`build-dataset` CLI 入口**(verifier 先行)+ 在真實封存區塊試跑,回報 Phase 5 lineage
   status(folds/holdout)。預期能建出 dataset、切出 folds 與 locked holdout;完整 8 群組
   ablation certification **本來就不該過**(缺 basis),那是誠實結果不是 bug。

## 7. 不變的硬邊界(違反即被 verifier 擋)

- Canonical 優先序:`docs/txresearch.md` v1.1.0 → test spec → plan → `tmf-research-agent/AGENTS.md`。
- 只有 `infrastructure/shioaji_market_data.py` 持有 raw Shioaji object;新增的
  `infrastructure/market_session.py` 是唯一被授權 import adapter 的組裝點,其餘走
  `MarketDataGateway`。verifier 只放行 `login` + 那一個組裝 import。
- 永不加入 brokerage auth / CA / account / order / cancel / modify / forwarding。
  `.env` 的 `SJ_CA_*` 是下單憑證,sidecar 永遠不載入;行情只用 `SJ_API_KEY`/`SJ_SEC_KEY`。
- paper 邊界只准 import 白名單 stdlib + paper 套件自身。
- synthetic/incomplete 證據最多到 CANDIDATE/VALIDATING;`APPROVED_FOR_PAPER` 只能由
  `decide_phase5` 在足量真實資料上簽發 sealed capability。
- 每個 production behavior 先寫 failing test;跑測試前先跑 verifier;**commit 前跑完整 gate**。

## 8. 給你的提醒(延續前一份,加上新的)

- 進度以 git history + 實際檔案為準;`.omx` 舊 goal 狀態已在 2026-07-17 歸檔到
  `.omx/archive/2026-07-17-codex-cleanup/`,不要再讀它當現況。
- 不要宣稱 fresh PASS 除非剛跑過;不要把「沒資料/缺群組」轉成 PASS;不要為過閘門改
  threshold、fold 邊界、holdout 或特徵定義。
- 共享資源:sidecar 收行情與 host `shioaji-server.js` 共用同一永豐帳戶配額;同時跑前先確認
  主流程訂閱用量。
- Sidecar 與 host Node 台股主流程完全隔離,host `npm test` 範圍是 `tests/*.test.js`,
  不會掃到 `tmf-research-agent/`。
- 欠帳:Phase 6 commits(`8fb5c90`..`42c3fe4`)還欠一次完整獨立 `/code-review`
  (session 限額擋掉,已做過一輪對抗式 self-review 並修掉 seal 缺口)。

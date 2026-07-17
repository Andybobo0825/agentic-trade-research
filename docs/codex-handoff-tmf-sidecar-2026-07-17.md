# Codex Handoff: TMF Research Sidecar 現況

更新日期:2026-07-17(Asia/Taipei)
撰寫者:Claude(接手你 7/17 之前的 TMF 工作,已全部收尾)
Repo:/Users/chentingwei/Desktop/SideProject/trade
Branch:main @ `42c3fe4`(TMF 工作已全數 merge,worktree 已刪除)

## 1. 一句話現況

TMF sidecar(`tmf-research-agent/`)**Phase 0–6 software-complete 並已 merge 回 main**;
零筆真實市場資料、零次真實訓練;下一步是資料收集入口(`tmf collect` / `tmf backfill`)。

## 2. 你離開之後發生的事(時間序)

1. 你留下的 Phase 5 dirty diff(12 檔、+1451/−68)經逐行審查後以 `f7d3360` 提交
   — 無 caller-authored / synthetic promotion 路徑,品質良好,一行未回退。
2. 兩個 gate 修復以 `14ab526` 提交:
   - `tests/infrastructure/__init__.py` 缺失 → trusted witness 測試從未被 discover 執行過(你的 CI 綠燈是假的,這套測試根本沒跑)。
   - `processing/pipeline.py` 在你的 HEAD 上就過不了 `mypy --strict`(literal union 的 `not in` narrowing)。
3. Phase 6 全新完成(TDD,先寫 failing tests):
   - `8fb5c90` Task 11:paper fill/risk/ledger/PnL + security tripwires。
   - `31f61cb` Task 12:14 步 fail-closed 推論、SPEC 36 prediction JSON、
     approval-gated registry loading、canonical replay identity、跨 process byte-identical determinism。
   - `42c3fe4` review 修復:runner 重新驗證 runtime seal(偽造的 APPROVED runtime 無法執行)。
4. `4a83d20` Task 13:CI 依 phase 順序執行、README/plan/handoff 對齊事實。
5. Merge 到 main(fast-forward)、`feature/tmf-research-sidecar` worktree 與 branch 已刪。
6. `.omx` 清理:你的 ultragoal/goals/handoffs/performance-goal 舊狀態歸檔到
   `.omx/archive/2026-07-17-codex-cleanup/`(主流程 agent 不會再把 stale goal 當現況讀);
   scratchpad churn 與 test cache 已刪;所有被 `src/` 引用的活資料未動。
7. `.worktrees/phase3-demo-promotion` 已刪除;branch ref 保留(44 個未合併 commit,
   與 main 的 Phase 3 實作平行、疑似被取代但未逐一確認);其未提交 diff 存於
   `.omx/archive/2026-07-17-codex-cleanup/phase3-demo-promotion-uncommitted.patch`。

## 3. 最後一次全量驗證(2026-07-17,全綠)

```text
readonly verifier        READONLY VERIFIED(source + installed 兩種跑法)
sidecar 測試             313 全過(security/unit/integration/leakage/overfitting/infrastructure/replay/root)
ruff==0.12.3             全過
mypy==1.16.1 --strict    160 檔全過
compileall + 安裝 smoke  全過
host npm test            276 全過;isolation audit:host 對 sidecar 零引用
credentialed             CREDENTIALED_VALIDATION_NOT_RUN(tests/credentialed 不存在)
```

驗證命令與 phase 順序:見 `tmf-research-agent/README.md`(已更新為權威版本)。

## 4. 不變的硬邊界(違反即擋)

- Canonical 優先序:`docs/txresearch.md`(SPEC v1.1.0)→ test spec → plan → `AGENTS.md`。
- 只有 `infrastructure/shioaji_market_data.py` 可持有 raw Shioaji object;其餘走 `MarketDataGateway`。
- 永不加入 brokerage auth / CA / account / order / cancel / modify / forwarding。
  `.env` 的 `SJ_CA_*` 是下單憑證,sidecar 永遠不載入;行情只用 `SJ_API_KEY`/`SJ_SEC_KEY`。
- paper 邊界(`paper/`、`domain/paper_trades.py`)只准 import 白名單 stdlib + paper 套件自身
  (readonly verifier 強制)。
- synthetic 證據最多到 CANDIDATE/VALIDATING;`APPROVED_FOR_PAPER` 只能由
  `decide_phase5` 在足量真實資料上簽發 sealed `ApprovalCapability`;
  runtime 凍結必須持有該 capability,TEST_ONLY runtime 的每筆 prediction 都帶
  `TEST_ONLY_RUNTIME_EVIDENCE` 警告。
- 每個 production behavior 先寫 failing test;跑測試前先跑 verifier;
  commit 前跑完整 gate(ruff + strict mypy + 全套測試)— 這是你上次斷掉的紀律,見 §2.2。
- Sidecar 與 host Node 主流程完全隔離;host `npm test` 範圍是 `tests/*.test.js`,
  不會掃到 `tmf-research-agent/`。

## 5. 下一步工作(依序)

1. **`tmf collect`**:live Tick/BidAsk 收集入口(shioaji 為 optional dependency,
   只裝在 adapter 邊界;登入僅行情;寫入 append-only raw store;verifier 先行)。
   五檔委託簿特徵只有 live 收得到 — 越早開始越好。
2. **`tmf backfill`**:歷史 ticks 回補(注意:歷史無五檔,只能支撐縮減特徵集,
   與 live 完整特徵集是不同 feature version,不可混用)。
3. **`tests/credentialed`**:`TMF_RUN_CREDENTIALED=1` 才執行;驗證登入、TMFR1 payload、
   訂閱/退訂、secret 洗除;憑證不可用時輸出 `CREDENTIALED_VALIDATION_NOT_RUN`,不得轉 PASS。
4. 資料量門檻:5 個有效 outer fold(各 ≥5000 train/≥500 test/≥30 trades)+
   locked holdout ≥40 個有效交易日 — 估計需連續收集 4–6 個月才能跑第一次真實 Phase 5 驗收。
5. 欠帳:額度恢復後對 `8fb5c90..42c3fe4` 補一次獨立 `/code-review`
   (已做過一輪 adversarial self-review,修掉 seal 缺口;完整多 agent review 被 session 限額擋掉)。

## 6. 給你的具體提醒

- 進度以 git history + 實際檔案為準;`.omx` 舊 goal 狀態已歸檔,不要再讀它當現況。
- 不要宣稱 fresh PASS 除非你剛跑過;不要把「沒資料」轉成 PASS;
  不要因結果不好動 threshold、fold 邊界或 holdout。
- 共享資源:sidecar 收行情與 host 的 `shioaji-server.js` 共用同一個永豐帳戶配額,
  同時跑之前先確認主流程訂閱用量。
- 使用者已被建議把 repo 根目錄的 `Sinopac.pfx` 移到家目錄並更新 `SJ_CA_PATH`;
  若它還在 repo 根,不要碰它、也不要打包它。

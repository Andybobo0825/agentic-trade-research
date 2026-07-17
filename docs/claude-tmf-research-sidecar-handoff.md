# Claude Handoff: TMF Research Sidecar

更新日期：2026-07-17（Asia/Taipei）  
Worktree：/Users/chentingwei/Desktop/SideProject/trade/.worktrees/tmf-research-sidecar  
Branch：feature/tmf-research-sidecar  
HEAD：4ca7a84 Prevent caller-authored metrics from promoting research models

## 0. 2026-07-17 completion update（本節之後為歷史快照）

本 handoff 撰寫後，同日由 Claude 接手完成：

- Phase 5 dirty diff 已審查（無 caller-authored/synthetic promotion 路徑）並以
  `f7d3360` 提交；gate 修復（tests/infrastructure discovery、strict mypy
  narrowing）以 `14ab526` 提交。
- Phase 6 Task 11（paper fill/risk/ledger/PnL/tripwires）以 `8fb5c90` 提交；
  Task 12（frozen inference、SPEC 36 prediction、approval-gated registry、
  canonical replay identity、cross-process determinism）以 `31f61cb` 提交。
- Task 13 全部 offline gate 於 2026-07-17 全數通過：readonly verifier、
  312 sidecar tests、ruff 0.12.3、mypy 1.16.1 --strict（160 files）、
  compileall、install smoke、host npm test（272）、isolation audit。
- Credentialed / real-data 邊界維持 `CREDENTIALED_VALIDATION_NOT_RUN`。
  Software-complete 不等於 research-capable，也不等於 approved-for-paper。

以下各節是接手當下的歷史快照，數字與狀態以上述為準。

## 1. 先讀這份結論

這個 worktree 同時包含既有的 Node finance toolkit 與獨立的 tmf-research-agent Python sidecar。後續工作應以 Python sidecar 為主，不要把 root src/、root tests/ 或現有 Node strategy 當成 TMF Phase 5/6 的實作位置。

目前判斷：

- Phase 0–4：主要實作、測試與安全邊界已存在；本次沒有重新執行完整驗證，因此不能宣稱 fresh PASS。
- Phase 5：核心模組與測試大致已建起，但仍有未提交的跨檔案 hardening diff，且完整 leakage／overfitting／integration／typecheck／review gate 尚未被本次驗證。這是目前主要工作面。
- Phase 6：尚未正式開始。已有 paper-only intent boundary 與基礎 probability helper，但 fill、risk、ledger、PnL、frozen runtime inference、prediction JSON、replay、determinism、fault replay 尚未建立。
- Branch 目前 dirty：12 個 tracked files 修改、1 個未追蹤 tmf-research-agent/uv.lock。
- 不得加入任何 brokerage authentication、account、certificate、position、margin、order、cancel、modify 或 forwarding capability。

## 2. Canonical authority 與硬性邊界

以以下文件為準，優先順序是 canonical SPEC → phase test spec → implementation plan：

1. docs/txresearch.md — canonical SPEC v1.1.0。
2. docs/superpowers/specs/2026-07-15-tmf-research-sidecar-phase1-6-test-spec.md — Phase 1–6 executable test mapping。
3. docs/superpowers/specs/2026-07-16-phase5-trusted-witness-lineage-design.md — Phase 5 trusted witness、dataset lineage、authoritative issuer 設計。
4. docs/superpowers/plans/2026-07-15-tmf-research-sidecar-phase1-6.md — Task 1–13 implementation／verification checklist。
5. tmf-research-agent/AGENTS.md — sidecar local instructions。

硬性規則：

- Sidecar 必須和 host Node strategy、CLI、MCP、runtime、main strategy flow 分離。
- 只有 tmf-research-agent/src/tmf_research/infrastructure/shioaji_market_data.py 可以持有 raw Shioaji API object。
- 其他 consumer 只能依賴 MarketDataGateway。
- 研究輸出與紙上交易只能 read-only／paper evidence；永遠不能接觸真實下單能力。
- 所有資料、feature、label、model、experiment、holdout evidence 都要 deterministic、可追溯、含版本／hash／時間邊界。
- 每個 production behavior 先寫 failing test；執行測試前先跑 read-only verifier。
- Synthetic fixture 只能證明 gate mechanics，不能產生正式 APPROVED_FOR_PAPER。

## 3. Phase progress

| Phase | 目前狀態 | 主要檔案 | 判定 |
| --- | --- | --- | --- |
| P0 Safety | 已有 | src/tmf_research/security/readonly_verifier.py、tests/test_readonly_verifier.py、tests/test_project_boundary.py、tests/test_readonly_gateway.py | 實作存在；fresh full gate 未重跑 |
| P1 Collection | 已有 | collection/、infrastructure/contract_resolver.py、raw_store.py、reconnect_manager.py、shioaji_market_data.py | Tick/BidAsk、queue、raw immutable、quality、reconnect 邊界已建 |
| P2 Processing | 已有 | processing/session_resolver.py、quote_joiner.py、one_second.py、bars.py、pipeline.py | session、backward quote join、1s／bars、quality pipeline 已建 |
| P3 Features/Labels | 已有 | features/、labeling/、tests/leakage/ | point-in-time feature、feature manifest、executable prices、triple barrier、leakage 證據已建 |
| P4 Models | 已有 | models/baselines.py、logistic.py、calibration.py、imputer.py、scaler.py、serialization.py、training.py、provenance.py | two-stage model、train-only transforms、serialization/provenance 已建；fresh gate 未重跑 |
| P5 Validation | 主要進度 | validation/、experiments/、infrastructure/trusted_witness.py、Phase 5 integration/leakage/overfitting tests | 核心已大幅實作，但目前 dirty 且尚未完成完整驗收 |
| P6 Paper/Replay | 尚未正式開始 | 目前只有 domain/paper_trades.py、paper/broker.py、models/inference.py | 只有 paper intent boundary；核心 P6 模組缺失 |

### Phase 5 詳細狀態

已存在的核心模組：

- src/tmf_research/validation/folds.py
- src/tmf_research/validation/purging.py
- src/tmf_research/validation/nested_walk_forward.py
- src/tmf_research/validation/locked_holdout.py
- src/tmf_research/validation/metrics.py
- src/tmf_research/validation/stability.py
- src/tmf_research/validation/ablation.py
- src/tmf_research/validation/report.py
- src/tmf_research/validation/overfitting.py
- src/tmf_research/validation/approval.py
- src/tmf_research/validation/data_provenance.py
- src/tmf_research/validation/dataset_lineage.py
- src/tmf_research/validation/fold_evaluation.py
- src/tmf_research/experiments/search_budget.py
- src/tmf_research/experiments/comparison.py
- src/tmf_research/experiments/registry.py
- src/tmf_research/infrastructure/trusted_witness.py

已存在的 Phase 5 測試：

- tests/overfitting/test_walk_forward.py
- tests/overfitting/test_locked_holdout.py
- tests/overfitting/test_search_budget.py
- tests/overfitting/test_experiment_registry.py
- tests/overfitting/test_stability.py
- tests/overfitting/test_report.py
- tests/overfitting/test_model_selection.py
- tests/leakage/test_purge_embargo.py
- tests/leakage/test_locked_holdout_access.py
- tests/leakage/test_nested_selection_scope.py
- tests/leakage/test_label_parameter_scope.py
- tests/leakage/test_feature_time.py
- tests/leakage/test_transform_scope.py
- tests/infrastructure/test_trusted_witness.py
- tests/integration/test_phase5_evidence_pipeline.py
- tests/integration/test_phase5_dataset_lineage.py

Phase 5 高風險 contract：

- chronological outer／inner folds；禁止 random／shuffle／KFold。
- purge 必須包含 equality boundary：outcome_time >= boundary。
- embargo 必須至少等於最大 model horizon。
- holdout 是最後連續 suffix，滿足 max(40 effective days, ceil(15%))。
- holdout freeze 前不能讀；unlock 只能一次；mutation／rerun 必須 contamination。
- experiment registry 必須 append-only，成功與失敗 attempt 都要保存。
- search budget 固定為 2/8/30/12/12/3。
- correlation、ablation、coefficient、parameter sensitivity 只能使用 train fold evidence。
- sample gate：train 5000、test 500、trades 30、LONG 10、SHORT 10，且少於 5 個 valid outer folds 必須 insufficient。
- approval 必須綁定 raw-derived lineage、exact candidate bundle、cost policy、experiment checkpoint、holdout evidence 與 trusted witness。
- synthetic evidence 最多停在 CANDIDATE／VALIDATING，不得升成 APPROVED_FOR_PAPER。

## 4. Current uncommitted work

目前 git status：

~~~text
 M tmf-research-agent/src/tmf_research/experiments/registry.py
 M tmf-research-agent/src/tmf_research/features/context_builder.py
 M tmf-research-agent/src/tmf_research/features/definitions.py
 M tmf-research-agent/src/tmf_research/models/training.py
 M tmf-research-agent/src/tmf_research/validation/approval.py
 M tmf-research-agent/src/tmf_research/validation/dataset_lineage.py
 M tmf-research-agent/src/tmf_research/validation/fold_evaluation.py
 M tmf-research-agent/src/tmf_research/validation/locked_holdout.py
 M tmf-research-agent/src/tmf_research/validation/overfitting.py
 M tmf-research-agent/tests/integration/test_phase5_dataset_lineage.py
 M tmf-research-agent/tests/overfitting/test_model_selection.py
 M tmf-research-agent/tests/phase5_test_support.py
?? tmf-research-agent/uv.lock
~~~

Diff summary at handoff creation：12 tracked files，約 1451 additions、68 deletions。

這些修改集中在：

- Phase 5 fold evaluation 的完整 raw-derived evidence。
- Dataset lineage、cost components、regime／ATR sensitivity。
- Approval evidence 與 experiment／candidate bundle 的 exact binding。
- Trusted witness rollback／stale evidence hardening。
- Phase 4 training／feature manifest contract 補強。

不要直接 reset、checkout 或覆蓋這些 dirty changes。先讀：

~~~bash
git diff --stat
git diff -- tmf-research-agent/src/tmf_research/validation/fold_evaluation.py
git diff -- tmf-research-agent/src/tmf_research/validation/dataset_lineage.py
git diff -- tmf-research-agent/src/tmf_research/validation/approval.py
git diff -- tmf-research-agent/src/tmf_research/experiments/registry.py
~~~

## 5. Phase 6 status and missing surface

SPEC Phase 6 的要求在 docs/superpowers/specs/2026-07-15-tmf-research-sidecar-phase1-6-test-spec.md 第 9 節。計畫中的 Task 11／12 尚未完成。

目前存在的 P6 前置內容：

- src/tmf_research/domain/paper_trades.py：immutable one-contract LONG／SHORT paper intent，固定 PAPER mode。
- src/tmf_research/paper/broker.py：in-memory paper intent recorder，無 external capability。
- tests/test_paper_boundary.py：paper boundary 與 readonly verifier 測試。
- src/tmf_research/models/inference.py：ClassProbabilities 與 two-stage probability combination helper；這不是完整 P6 runtime inference。

尚未建立的 P6 surface：

- src/tmf_research/paper/fill_model.py
- src/tmf_research/paper/risk.py
- src/tmf_research/paper/ledger.py
- src/tmf_research/paper/replay.py
- src/tmf_research/domain/predictions.py
- src/tmf_research/runtime/feature_state.py
- src/tmf_research/runtime/health.py
- src/tmf_research/runtime/live_research.py
- tests/unit/test_paper_fill.py
- tests/unit/test_paper_risk.py
- tests/unit/test_paper_ledger.py
- tests/unit/test_paper_pnl.py
- tests/unit/test_prediction.py
- tests/integration/test_live_inference.py
- tests/integration/test_model_registry.py
- tests/replay/test_replay.py
- tests/replay/test_determinism.py
- tests/replay/test_faults.py
- tests/security/test_paper_tripwires.py

Phase 6 不應在 Phase 5 gate 之前開始。SPEC 要求只允許已核准且相容的 bundle 產生 paper plan，其餘狀態必須持久化 NO_TRADE。

## 6. Test and verification status

靜態盤點得到的 Python test methods 約 221 個：

- unit：73
- leakage：8
- overfitting：47
- integration：20
- infrastructure：2
- 其餘 root tests／support tests 包含在總數中

但本次 handoff 掃描沒有執行完整 test suite、mypy、ruff、compile/install smoke 或 host npm test。因此以下事項仍是 Unknown：

- current dirty diff 是否全部通過 Phase 5 integration tests。
- fold_evaluation.py、dataset_lineage.py、approval.py 的跨模組 contract 是否全部一致。
- current Python 3.11／current mypy 下的 strict typecheck 結果。
- read-only verifier 是否接受所有新增 Phase 5 surface。
- host Node regression 與 isolation audit 是否通過。
- real TMF data、credentialed market-data smoke、五個有效 outer folds 與 locked holdout 是否存在。

注意：tests/replay/、tests/security/、tests/regression/ 目前不是完整的 Phase 6 test surface；不能因為其他 root tests 存在就視為 P6 已覆蓋。

## 7. .omx state and work-log evidence

可用的 durable artifacts：

- .omx/handoff/phase1-6-test-spec.md
- .omx/handoff/phase5-executor-handoff.md
- .omx/ultragoal/brief.md
- .omx/ultragoal/goals.json
- .omx/ultragoal/ledger.jsonl
- .omx/reports/team-commit-hygiene/*.md
- .omx/reports/team-commit-hygiene/*.ledger.json
- .omx/logs/*.jsonl
- .omx/state/*.json

目前 .omx/ultragoal/goals.json 的 goal 仍是 in_progress，最後更新時間停在 2026-07-15；它沒有反映 7/15 晚間到 7/16 的 Phase 4／5 semantic commits。

歷史 team report 記錄過 worker quota 0% 導致的 failed tasks；同一批 runtime ledger 有大量 operational churn（auto-checkpoint、cross-rebase、integration merge/cherry-pick），但後續 branch history 確實存在 Phase 4／5 語義 commit。因此不能把整段歷史判定成純空轉，但也不能把 .omx goal status 當成最新進度來源。

重要判斷：以 git history、實際 source/test files、dirty diff 為主要進度來源；以 .omx 作為歷史工作流／阻塞證據，不作 current completion authority。

## 8. Recommended handoff sequence for Claude

1. Read this file、tmf-research-agent/AGENTS.md、canonical docs/txresearch.md、Phase 1–6 test spec、Phase 5 trusted witness design。
2. Inspect current git status and the dirty Phase 5 diff. Preserve existing changes；不要 reset／checkout。
3. Run the read-only verifier first from tmf-research-agent。
4. Run targeted Phase 5 leakage、overfitting、trusted witness、dataset lineage and integration tests in phase order; capture failures without silently lowering thresholds。
5. Resolve only confirmed contract／test failures, preserving raw-derived authority and fail-closed behavior。
6. Run full offline Phase 0–5 suites, ruff, strict mypy, compile/install smoke, host regression and isolation audit。
7. Update documentation／traceability and only then consider Phase 6 Task 11／12。
8. For any unavailable credentialed or real-data boundary, record CREDENTIALED_VALIDATION_NOT_RUN；never convert absence of data into PASS or approval。

Suggested first commands：

~~~bash
cd /Users/chentingwei/Desktop/SideProject/trade/.worktrees/tmf-research-sidecar/tmf-research-agent
PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root .
PYTHONPATH=src python3 -m unittest discover -s tests/leakage -v
PYTHONPATH=src python3 -m unittest discover -s tests/overfitting -v
PYTHONPATH=src python3 -m unittest discover -s tests/integration -v
~~~

If test execution must preserve a strictly clean worktree, use an isolated temporary copy or configure bytecode/cache output outside the worktree; do not delete existing ignored artifacts without checking ownership.

## 9. Completion definition

Do not call Phase 5 complete merely because all source files exist. The minimum completion claim requires：

- all applicable Phase 5 offline tests pass；
- read-only verifier passes first；
- lineage／witness／holdout／approval evidence is fresh and internally consistent；
- ruff and strict mypy pass；
- compile/install smoke passes；
- host regression and isolation audit pass；
- docs／traceability are updated；
- independent code review confirms no caller-authored or synthetic evidence can promote a model；
- credentialed／real-data gaps are explicitly recorded。

Current confidence：**high** for file inventory and branch-state facts；**medium** for phase implementation coverage；**low** for runtime correctness until the fresh verification gate is executed。

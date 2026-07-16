# Phase 5 Trusted Witness and Dataset Lineage Design

## Scope

Phase 5 remains an offline, read-only sidecar. It is not registered in the host strategy, does not start Phase 6, and has no account, certificate, brokerage, network-order, or order-object surface.

## Durable witness boundary

Experiment and locked-holdout state retain their local append-only anchors, but every mutable head is also committed to `TrustedWitness`. The default implementation is an external SQLite database with `synchronous=FULL`, WAL, exact compare-and-swap, a `0700` parent directory, and a `0600` database. Artifact roots cannot contain their own witness database.

Each local transition writes its anchor/state, advances the witness by exact CAS, then replaces its receipt. A single post-CAS/pre-receipt crash is recoverable only when the live witness is exactly one step ahead and its head equals the local state. Missing, older, later-divergent, or wrong witness state fails closed. Evaluation and approval evidence recheck the live witness immediately before issuance.

This detects rollback when an owner restores registry/vault artifacts without also restoring the independent witness. It cannot detect an administrator restoring or rewriting both the artifacts and the external witness; that remains the explicit trust boundary.

## Authoritative dataset issuer

`Phase5DatasetIssuer.issue` accepts only a verified `AppendOnlyRawStore`, catalogued `SegmentManifest` values, a file-backed `ResearchBuildSpec`, an external holdout root, and a `TrustedWitness`. There are no public row, fold, return, callback, or builder inputs.

The issuer performs this fixed path:

1. Verify every raw segment and issue current real-data provenance.
2. Strictly decode Tick and BidAsk records.
3. Parse the injected exchange calendar and resolve sessions with `SessionResolver`.
4. Run `ProcessingPipeline` and retain source manifest commitments.
5. Derive prior-only `FeatureContext` and run `FeaturePipeline`.
6. Build 15-minute candidates with `LabelPipeline`, label with executable bid/ask through `TripleBarrierLabeler`, and derive signed net points after complete costs.
7. Commit full `TemporalSample` identity: source payload/hash, decision time, outcome time, and effective trading date.
8. Select the canonical final `max(40 effective days, ceil(15%))` locked suffix.
9. Plan chronological purged/embargoed folds only from the development prefix through `Phase5FoldPlanner`.
10. Persist a locked holdout only after at least five exact fold manifests exist.

Lineage evidence seals all/development/holdout commitments, every temporal-sample hash, exact row identifiers, exact fold role subsets, and holdout selection/data hashes. Development and holdout identifiers must be disjoint, and every fold role must be a subset of the development prefix.

## Approval and publication

`DataProvenanceEvidence` identifies verified raw input only; it has no caller-populated promotion-lineage field. A real holdout approval requires a sealed, current `DatasetLineageEvidence` whose raw hash matches provenance, whose exact fold manifests match the Phase 5 evidence, and whose selection/data hashes match current locked-holdout approval evidence. The decision gate revalidates lineage, and registry publication persists `dataset_lineage_hash`; an approved publication cannot omit it.

Synthetic mechanics remain capped at `CANDIDATE`. Missing calendar, raw data, quotes, derived rows, five folds, witness authority, or holdout sufficiency returns `REJECTED_INSUFFICIENT_DATA` and never manufactures approval.

## Offline status command

`tmf phase5-status --raw-root ... --calendar ... --witness-db ...` reads local files only. Missing, malformed, insufficient, or unverifiable inputs emit `{"status":"REJECTED_INSUFFICIENT_DATA"}`. It never reaches Shioaji or the host strategy.

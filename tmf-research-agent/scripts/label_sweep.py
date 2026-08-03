"""Ask whether the training target has any structure before chasing features.

The shipped labelling puts both barriers one 5-minute ATR from the entry
quote and gives price 15 minutes to reach one. If almost every candidate
touches a barrier and the side is a coin flip, the target is decided by path
noise, and no feature group can predict it — which would make months of
further collection wasted regardless of what the features carry.

This sweeps barrier width and horizon over stored days and reports what each
choice actually produces. Read the NO_TRADE share and the long/short balance
together: a target worth modelling leaves a real share of candidates
untouched and does not sit at 50/50.
"""
from __future__ import annotations

import json
import sys
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from tmf_research.domain.sessions import SessionResolution
from tmf_research.features.context_builder import ResearchBuildSpec
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore, SegmentManifest
from tmf_research.labeling.pipeline import LabelPipeline
from tmf_research.labeling.triple_barrier import LabelParameters, TripleBarrierLabeler
from tmf_research.labeling.executable_prices import ExecutablePricePolicy
from tmf_research.processing.pipeline import ProcessingPipeline
from tmf_research.processing.quote_joiner import QuoteJoiner
from tmf_research.processing.session_resolver import SessionResolver
from tmf_research.validation.dataset_lineage import _session_batches

WIDTHS = (1.0, 1.5, 2.0, 3.0, 4.0)
HORIZONS = (5, 15, 60)


def _atr(bars: tuple[object, ...], index: int, period: int = 5) -> float | None:
    window = bars[max(0, index - period):index]
    ranges = [
        bar.high - bar.low
        for bar in window
        if bar.high is not None and bar.low is not None
    ]
    return sum(ranges) / len(ranges) if ranges else None


def sweep(
    raw_root: Path, calendar_path: Path, start_day: str, end_day: str, stride: int,
) -> int:
    spec = ResearchBuildSpec(calendar=calendar_path)
    calendar = spec.trading_calendar()
    resolver = SessionResolver(calendar)
    records = [
        json.loads(line)
        for line in (raw_root / "manifest.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    def in_range(segment_id: str) -> bool:
        _prefix, separator, suffix = segment_id.rpartition("TMFR1-")
        if not separator:
            return True
        return start_day <= suffix[:10] <= end_day

    # Historical evidence only: it is the two years this diagnostic needs, it
    # streams a day at a time, and it is what the live path would be judged
    # against anyway. Live segments load in one eager pass — 200k+ of them
    # would spend minutes and gigabytes before the first session is scored.
    manifests = tuple(
        SegmentManifest(**record)
        for record in records
        if record["event_type"] == "historical-tick"
        and in_range(str(record["segment_id"]))
    )
    if not manifests:
        print(f"{start_day}..{end_day} 沒有任何 segment", file=sys.stderr)
        return 1
    store = AppendOnlyRawStore(
        raw_root,
        writer_version=manifests[0].writer_version,
        dataset_version=manifests[0].dataset_version,
    )
    labeler = TripleBarrierLabeler(
        price_policy=ExecutablePricePolicy(entry_slippage=0.0, exit_slippage=0.0),
    )
    label_pipeline = LabelPipeline()
    tallies: dict[tuple[str, float, int], Counter[str]] = defaultdict(Counter)

    sessions = 0
    seen_days: list[str] = []
    for batch in _session_batches(store, manifests, calendar, resolver, set()):
        if batch.trading_date not in seen_days:
            seen_days.append(batch.trading_date)
        if (len(seen_days) - 1) % stride:
            continue
        resolution: SessionResolution = batch.resolution
        if not batch.ticks or not batch.quotes:
            continue
        if resolution.session_start is None or resolution.session_end is None:
            continue
        start = min(
            value.exchange_datetime for value in batch.ticks
        ).replace(second=0, microsecond=0)
        processed = ProcessingPipeline(
            quote_joiner=QuoteJoiner(max_quote_age=timedelta(minutes=2)),
        ).process(
            ticks=batch.ticks, bidasks=batch.quotes, resolution=resolution,
            start_second=start, end_second=resolution.session_end - timedelta(seconds=1),
            source_manifests=manifests, intervals=(1,),
        )
        year, month = int(batch.trading_date[:4]), int(batch.trading_date[5:7])
        quarter = f"{year}Q{(month - 1) // 3 + 1}"
        bars = processed.bar_sets[0].bars
        states = processed.states
        state_seconds = [state.second for state in states]
        bar_starts = [bar.bar_start for bar in bars]

        for horizon in HORIZONS:
            for candidate in label_pipeline.candidates(bars, horizons=(horizon,)):
                index = bisect_right(bar_starts, candidate.decision_time)
                atr = _atr(bars, index)
                if atr is None or atr <= 0:
                    continue
                future = bars[bisect_left(bar_starts, candidate.decision_time):]
                if len(future) < horizon:
                    continue
                position = bisect_left(state_seconds, candidate.decision_time)
                if position == 0:
                    continue
                entry = states[position - 1]
                if not entry.bidask_available:
                    continue
                for width in WIDTHS:
                    parameters = LabelParameters(
                        version="sweep", fit_start=start - timedelta(days=2),
                        fit_end=start - timedelta(seconds=1),
                        target_atr_multiplier=width, stop_atr_multiplier=width,
                        minimum_target_points=1.0, minimum_stop_points=1.0,
                        horizon_minutes=horizon,
                    )
                    try:
                        record = labeler.label(
                            candidate_id=candidate.candidate_id,
                            decision_time=candidate.decision_time,
                            entry_state=entry, future_bars=future,
                            atr=atr, parameters=parameters,
                        )
                    except ValueError:
                        continue
                    tallies[(quarter, width, horizon)][record.label] += 1
        sessions += 1
        done = tallies[(quarter, WIDTHS[0], HORIZONS[0])]
        print(
            f"  [{sessions}] {batch.trading_date} {batch.session}"
            f"  累計樣本 {sum(done.values()):,}",
            flush=True,
        )

    quarters = sorted({key[0] for key in tallies})
    print(f"\n掃描 {sessions} 個時段,涵蓋 {len(quarters)} 季   障礙寬度 = 倍數 x ATR(5分)\n")
    for horizon in HORIZONS:
        print(f"── 期限 {horizon} 分鐘 " + "─" * 46)
        header = f"{'寬度':>6}{'NO_TRADE':>10}" + "".join(f"{q:>9}" for q in quarters) + f"{'方向一致':>10}"
        print(header)
        for width in WIDTHS:
            no_trade_total = untouched = 0
            leans = []
            for quarter in quarters:
                counts = tallies[(quarter, width, horizon)]
                total = sum(counts.values())
                if not total:
                    leans.append(None)
                    continue
                no_trade_total += total
                untouched += counts["NO_TRADE"]
                directional = counts["LONG"] + counts["SHORT"]
                leans.append(
                    (counts["LONG"] - counts["SHORT"]) / directional if directional else 0.0
                )
            scored = [value for value in leans if value is not None]
            if not scored:
                continue
            # 每季偏向的符號是否一致:全部同號才代表方向性可能是結構,而非該季行情
            agreement = max(
                sum(1 for v in scored if v > 0), sum(1 for v in scored if v < 0),
            ) / len(scored)
            cells = "".join(
                f"{'—':>9}" if value is None else f"{value:>+9.1%}" for value in leans
            )
            print(
                f"{width:>6.1f}{untouched / no_trade_total:>10.1%}{cells}{agreement:>10.0%}"
            )
        print()
    print(
        "每一欄是該季的多空偏向(正=多方多)。看的是「符號是否跨季一致」:\n"
        "  方向一致 100% 且偏向夠大 → 可能是可利用的結構\n"
        "  方向一致約 50%(忽正忽負)→ 只是各季行情不同,不是可預測的訊號\n"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in (5, 6):
        print(
            "用法: label_sweep.py <raw-root> <calendar.json> <起始日> <結束日> [取樣間隔]",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raise SystemExit(sweep(
        Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4],
        int(sys.argv[5]) if len(sys.argv) == 6 else 1,
    ))

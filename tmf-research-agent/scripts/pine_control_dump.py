"""Dump every Pine signal and a matched random-entry control to NDJSON.

The report says which signals were positive; it cannot say whether that beat
simply being in the market. This makes one expensive pass over the ticks and
writes raw price deltas — signals and random entries side by side, same
sessions, same horizons — so every later question (different cost, different
direction, time-matched controls) is answered without streaming again.

Deltas are stored unsigned by intent: net = direction * delta - cost, applied
at analysis time.

Usage: pine_control_dump.py <raw-root> <calendar.json> <起始日> <結束日> <out.ndjson>
"""
from __future__ import annotations

import json
import random
import sys
from bisect import bisect_left
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pine_signal_report import (  # noqa: E402
    HORIZONS, PRESETS, TIMEFRAMES, AppendOnlyRawStore, PineState,
    ProcessingPipeline, QuoteJoiner, ResearchBuildSpec, SegmentManifest,
    SessionResolver, SessionTape, _period, _session_batches, v2_scan, v3_scan,
)

RANDOM_ENTRIES_PER_SESSION = 20
SEED = 20260804


def _deltas(tape: SessionTape, when, session_end) -> dict[str, float] | None:
    """Raw exit-minus-entry price change per horizon, direction not applied."""
    entry = tape.entry_after(when)
    if entry is None:
        return None
    entry_time, entry_price = entry
    out: dict[str, float] = {}
    targets = [(str(h), min(when + timedelta(minutes=h), session_end))
               for h in HORIZONS] + [("sclose", session_end)]
    for key, exit_time in targets:
        if exit_time <= entry_time:
            continue
        exit_price = tape.exit_at(exit_time)
        if exit_price is not None:
            out[key] = exit_price - entry_price
    return out or None


def dump(raw_root: Path, calendar_path: Path, start_day: str, end_day: str,
         out_path: Path) -> int:
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

    engines: dict[tuple[int, str], PineState] = {}
    for tf in TIMEFRAMES:
        engines[(tf, "orig")] = PineState(PRESETS[tf])
        engines[(tf, "v1")] = PineState(PRESETS[tf], right_bars=2)

    rng = random.Random(SEED)
    sessions = 0
    written = 0
    with out_path.open("w", encoding="utf-8") as handle:
        for batch in _session_batches(store, manifests, calendar, resolver, set()):
            resolution = batch.resolution
            if not batch.ticks or not batch.quotes:
                continue
            if resolution.session_start is None or resolution.session_end is None:
                continue
            ordered = sorted(
                (t for t in batch.ticks if not t.simtrade),
                key=lambda t: t.exchange_datetime,
            )
            if not ordered:
                continue
            pipeline = ProcessingPipeline(
                quote_joiner=QuoteJoiner(max_quote_age=timedelta(minutes=2)),
            )
            kwargs = dict(
                ticks=batch.ticks, bidasks=batch.quotes, resolution=resolution,
                end_second=resolution.session_end - timedelta(seconds=1),
                source_manifests=manifests, intervals=TIMEFRAMES,
            )
            try:
                processed = pipeline.process(
                    start_second=resolution.session_start, **kwargs)
            except ValueError:
                fallback = min(t.exchange_datetime for t in batch.ticks).replace(
                    second=0, microsecond=0)
                processed = pipeline.process(start_second=fallback, **kwargs)

            tick_times = [t.exchange_datetime for t in ordered]
            tick_prices = [t.close for t in ordered]
            tick_vols = [t.volume for t in ordered]
            tape = SessionTape(tick_times, tick_prices)
            period = _period(batch.trading_date)
            base = {"trading_date": batch.trading_date, "session": batch.session,
                    "period": period}
            bars_by_interval = {
                bs.interval_minutes: bs.bars for bs in processed.bar_sets}

            emitted: list[dict] = []
            for tf in TIMEFRAMES:
                params = PRESETS[tf]
                orig_engine = engines[(tf, "orig")]
                v1_engine = engines[(tf, "v1")]
                fired_levels: set[tuple[str, float]] = set()
                for bar in bars_by_interval[tf]:
                    ctx = orig_engine.forming_context()
                    lo = bisect_left(tick_times, bar.bar_start)
                    hi = bisect_left(tick_times, bar.bar_end)
                    bar_ticks = [(tick_times[i], tick_prices[i], tick_vols[i])
                                 for i in range(lo, hi)]
                    for name, direction, level, when in v2_scan(
                            ctx, bar_ticks, bar.bar_start, tf, params):
                        emitted.append({"kind": "signal", "timeframe": tf,
                                        "signal": name, "variant": "v2",
                                        "direction": direction, "when": when})
                    for name, direction, level, when in v3_scan(
                            ctx, bar_ticks, params, fired_levels):
                        emitted.append({"kind": "signal", "timeframe": tf,
                                        "signal": name, "variant": "v3",
                                        "direction": direction, "when": when})
                    for name, direction, level in orig_engine.update(bar):
                        emitted.append({"kind": "signal", "timeframe": tf,
                                        "signal": name, "variant": "orig",
                                        "direction": direction, "when": bar.bar_end})
                    for name, direction, level in v1_engine.update(bar):
                        emitted.append({"kind": "signal", "timeframe": tf,
                                        "signal": name, "variant": "v1",
                                        "direction": direction, "when": bar.bar_end})

            # Random controls: uniform over the session's own traded moments,
            # so the control inherits the session's liquidity profile.
            for _ in range(RANDOM_ENTRIES_PER_SESSION):
                emitted.append({
                    "kind": "random", "timeframe": 0, "signal": "random",
                    "variant": "random", "direction": 1,
                    "when": tick_times[rng.randrange(len(tick_times))],
                })

            for item in emitted:
                deltas = _deltas(tape, item["when"], resolution.session_end)
                if deltas is None:
                    continue
                row = dict(base)
                row.update({k: v for k, v in item.items() if k != "when"})
                row["when"] = item["when"].isoformat()
                row["minute_of_session"] = int(
                    (item["when"] - resolution.session_start).total_seconds() // 60)
                row["deltas"] = {k: round(v, 4) for k, v in deltas.items()}
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
            sessions += 1
            print(f"  [{sessions}] {batch.trading_date} {batch.session}"
                  f"  已寫 {written:,} 列", file=sys.stderr, flush=True)
    print(f"完成：{sessions} 個時段，{written:,} 列 → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(dump(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3],
                          sys.argv[4], Path(sys.argv[5])))

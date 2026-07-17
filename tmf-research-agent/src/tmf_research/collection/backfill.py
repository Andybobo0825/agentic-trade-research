from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from tmf_research.domain.contracts import ContractInfo, TickBatch
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore


class HistoricalTickSource(Protocol):
    """The two read-only capabilities historical ingestion may touch."""

    def resolve_near_contract(self) -> ContractInfo: ...

    def fetch_ticks(self, contract: ContractInfo, date: str) -> TickBatch: ...


TAIPEI = ZoneInfo("Asia/Taipei")
EVENT_TYPE = "historical-tick"
SOURCE = "SHIOAJI_HISTORICAL_TICKS_CONTINUOUS_NEAR"
TARGET_DERIVATION = "taifex-third-wednesday-v1"
_EPOCH = datetime(1970, 1, 1)

Clock = Callable[[], datetime]
DayStatus = Literal["STORED", "ALREADY_STORED", "NO_DATA"]


class BackfillError(ValueError):
    """Raised when historical ingestion cannot proceed honestly."""


@dataclass(frozen=True, slots=True)
class HistoricalTickRecord:
    """One immutable historical tick preserved exactly as fetched.

    Expired contracts delist from the Shioaji catalog, so history is only
    reachable through the continuous near-month alias. The per-date target
    is therefore derived from the TAIFEX third-Wednesday expiry rule and
    carries an explicit derivation marker instead of claiming API evidence.
    """

    schema_version: str
    event_id: str
    exchange_datetime: datetime
    received_at: datetime
    source: str
    alias_code: str
    derived_target_code: str
    derived_delivery_date: str
    target_derivation: str
    fields: Mapping[str, float | int | str | None]


@dataclass(frozen=True, slots=True)
class BackfillDayResult:
    date: str
    status: DayStatus
    record_count: int
    checksum_sha256: str | None


@dataclass(frozen=True, slots=True)
class BackfillSummary:
    alias_code: str
    dataset_version: str
    results: tuple[BackfillDayResult, ...]

    @property
    def stored_days(self) -> int:
        return sum(result.status == "STORED" for result in self.results)

    @property
    def already_stored_days(self) -> int:
        return sum(result.status == "ALREADY_STORED" for result in self.results)

    @property
    def no_data_days(self) -> int:
        return sum(result.status == "NO_DATA" for result in self.results)

    @property
    def stored_records(self) -> int:
        return sum(
            result.record_count
            for result in self.results
            if result.status == "STORED"
        )


def normalize_tick_batch(batch: TickBatch) -> tuple[HistoricalTickRecord, ...]:
    """Turn one day's Shioaji tick arrays into per-tick immutable records.

    Shioaji historical timestamps are Taipei wall-clock time encoded as epoch
    nanoseconds; the credentialed smoke test verifies that assumption against
    real data before any research use.
    """

    columns: dict[str, tuple[object, ...]] = {
        str(name): tuple(values)
        for name, values in batch.payload.items()
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes))
    }
    if "ts" not in columns:
        raise BackfillError(f"{batch.date}: historical payload lacks a ts column")
    lengths = {len(values) for values in columns.values()}
    if len(lengths) > 1:
        raise BackfillError(f"{batch.date}: historical payload is ragged")
    count = lengths.pop()
    if count == 0:
        return ()
    target_code, delivery_date = derived_near_target(date.fromisoformat(batch.date))
    records = []
    for index in range(count):
        records.append(HistoricalTickRecord(
            schema_version="1.1.0",
            event_id=(
                f"hist-tick-{batch.contract.alias_code}-{batch.date}-{index:06d}"
            ),
            exchange_datetime=_tick_time(batch.date, columns["ts"][index]),
            received_at=batch.fetched_at,
            source=SOURCE,
            alias_code=batch.contract.alias_code,
            derived_target_code=target_code,
            derived_delivery_date=delivery_date,
            target_derivation=TARGET_DERIVATION,
            fields={
                name: _scalar(batch.date, name, values[index])
                for name, values in columns.items()
                if name != "ts"
            },
        ))
    return tuple(records)


def third_wednesday(year: int, month: int) -> date:
    """TAIFEX index futures settle on the third Wednesday of the month."""

    first = date(year, month, 1)
    offset = (2 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def derived_near_target(trading_date: date) -> tuple[str, str]:
    """Derive the near-month target for one trading date from the expiry rule."""

    expiry = third_wednesday(trading_date.year, trading_date.month)
    if trading_date > expiry:
        year = trading_date.year + (1 if trading_date.month == 12 else 0)
        month = 1 if trading_date.month == 12 else trading_date.month + 1
        expiry = third_wednesday(year, month)
    return f"TMF{expiry.year}{expiry.month:02d}", expiry.isoformat()


def run_backfill(
    gateway: HistoricalTickSource,
    store: AppendOnlyRawStore,
    *,
    start_date: str,
    end_date: str,
    clock: Clock | None = None,
    pause: Callable[[], None] | None = None,
) -> BackfillSummary:
    """Fetch historical ticks day by day into create-once raw segments.

    Already-stored days are skipped without refetching, empty days are
    reported as NO_DATA, and any fetch or normalization failure stops the
    run with the failing day named; previously stored segments stay valid.
    """

    first, last = _parse_range(start_date, end_date)
    now = clock or (lambda: datetime.now(timezone.utc))
    contract = gateway.resolve_near_contract()
    results: list[BackfillDayResult] = []
    current = first
    while current <= last:
        day = current.isoformat()
        segment_id = f"backfill-tick-{contract.alias_code}-{day}"
        if store.has_segment(EVENT_TYPE, segment_id):
            results.append(BackfillDayResult(day, "ALREADY_STORED", 0, None))
        else:
            try:
                batch = gateway.fetch_ticks(contract, day)
                records = normalize_tick_batch(batch)
            except BackfillError:
                raise
            except Exception as error:
                raise BackfillError(f"{day}: historical fetch failed: {error}") from error
            if not records:
                results.append(BackfillDayResult(day, "NO_DATA", 0, None))
            else:
                manifest = store.append_segment(
                    EVENT_TYPE,
                    records,
                    segment_id=segment_id,
                    created_at=now(),
                )
                results.append(BackfillDayResult(
                    day, "STORED", manifest.record_count,
                    manifest.checksum_sha256,
                ))
            if pause is not None and current < last:
                pause()
        current += timedelta(days=1)
    return BackfillSummary(
        alias_code=contract.alias_code,
        dataset_version=store.dataset_version,
        results=tuple(results),
    )


def _parse_range(start_date: str, end_date: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(start_date)
        last = date.fromisoformat(end_date)
    except ValueError as error:
        raise BackfillError(f"invalid backfill date: {error}") from error
    if last < first:
        raise BackfillError("invalid backfill range: end precedes start")
    return first, last


def _tick_time(day: str, value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BackfillError(f"{day}: ts values must be epoch-nanosecond integers")
    if value < 0:
        raise BackfillError(f"{day}: ts values must be non-negative")
    wall = _EPOCH + timedelta(microseconds=value // 1_000)
    return wall.replace(tzinfo=TAIPEI)


def _scalar(day: str, name: str, value: object) -> float | int | str | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)) and not isinstance(value, bool):
        return value
    raise BackfillError(f"{day}: column {name} holds an unsupported value type")

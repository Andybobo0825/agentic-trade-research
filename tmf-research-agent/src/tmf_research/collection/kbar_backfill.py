from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from tmf_research.domain.contracts import ContractInfo, KbarBatch
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore, SegmentManifest


TAIPEI = ZoneInfo("Asia/Taipei")
EVENT_TYPE = "historical-kbar-1m"
SOURCE = "SHIOAJI_KBARS_1M_CONTINUOUS_NEAR"
_EPOCH = datetime(1970, 1, 1)
_REQUIRED_FIELDS = ("ts", "Open", "High", "Low", "Close", "Volume")
_ENV_ASSIGNMENT = re.compile(
    r"^\s*(?P<key>SJ_API_KEY|SJ_SEC_KEY)\s*=\s*(?P<value>.*?)\s*$"
)

KbarStatus = Literal["STORED", "ALREADY_STORED", "NO_DATA", "NON_TRADING_DAY"]


class HistoricalKbarSource(Protocol):
    def resolve_near_contract(self) -> ContractInfo: ...

    def fetch_kbars(
        self,
        contract: ContractInfo,
        start: str,
        end: str,
    ) -> KbarBatch: ...


class KbarPullError(ValueError):
    """Raised when a kbar payload cannot be stored without guessing."""


@dataclass(frozen=True, slots=True)
class HistoricalKbarRecord:
    """One raw vendor 1-minute kbar with the original columns preserved."""

    schema_version: str
    event_id: str
    exchange_datetime: datetime
    received_at: datetime
    source: str
    alias_code: str
    contract_code: str
    delivery_month: str
    fields: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class KbarChunkResult:
    start_date: str
    end_date: str
    status: KbarStatus
    record_count: int
    checksum_sha256: str | None


@dataclass(frozen=True, slots=True)
class KbarPullSummary:
    alias_code: str
    dataset_version: str
    results: tuple[KbarChunkResult, ...]

    @property
    def stored_chunks(self) -> int:
        return sum(result.status == "STORED" for result in self.results)

    @property
    def already_stored_chunks(self) -> int:
        return sum(result.status == "ALREADY_STORED" for result in self.results)

    @property
    def no_data_chunks(self) -> int:
        return sum(result.status == "NO_DATA" for result in self.results)

    @property
    def non_trading_days(self) -> int:
        return sum(result.status == "NON_TRADING_DAY" for result in self.results)

    @property
    def stored_records(self) -> int:
        return sum(
            result.record_count
            for result in self.results
            if result.status == "STORED"
        )


@dataclass(frozen=True, slots=True)
class ShioajiCredentials:
    api_key: str
    secret_key: str


def normalize_kbar_batch(batch: KbarBatch) -> tuple[HistoricalKbarRecord, ...]:
    """Normalize one immutable kbars response without changing raw bar values."""

    columns: dict[str, tuple[object, ...]] = {}
    for name, values in batch.payload.items():
        if not isinstance(name, str):
            raise KbarPullError("kbar payload column names must be strings")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise KbarPullError(f"kbar payload column {name} is not an array")
        columns[name] = tuple(values)

    missing = tuple(name for name in _REQUIRED_FIELDS if name not in columns)
    if missing:
        raise KbarPullError(f"kbar payload lacks required columns: {', '.join(missing)}")
    lengths = {len(values) for values in columns.values()}
    if len(lengths) > 1:
        raise KbarPullError("kbar payload is ragged")
    count = lengths.pop() if lengths else 0
    if count == 0:
        return ()

    records: list[HistoricalKbarRecord] = []
    timestamp_counts = Counter(columns["ts"])
    for index in range(count):
        timestamp = _kbar_time(batch.start, columns["ts"][index])
        _finite_number(batch.start, "Open", columns["Open"][index])
        _finite_number(batch.start, "High", columns["High"][index])
        _finite_number(batch.start, "Low", columns["Low"][index])
        _finite_number(batch.start, "Close", columns["Close"][index])
        _volume(batch.start, columns["Volume"][index])
        records.append(HistoricalKbarRecord(
            schema_version="1.0.0",
            event_id=(
                f"hist-kbar-1m-{batch.contract.alias_code}-{columns['ts'][index]}"
                + (
                    f"-{index}"
                    if timestamp_counts[columns["ts"][index]] > 1
                    else ""
                )
            ),
            exchange_datetime=timestamp,
            received_at=batch.fetched_at,
            source=SOURCE,
            alias_code=batch.contract.alias_code,
            contract_code=batch.contract.target_code,
            delivery_month=batch.contract.delivery_month,
            fields={name: values[index] for name, values in columns.items()},
        ))
    return tuple(records)


def run_kbar_pull(
    source: HistoricalKbarSource,
    store: AppendOnlyRawStore,
    *,
    start_date: str,
    end_date: str,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] | None = None,
    pause: Callable[[], None] | None = None,
    max_retries: int = 3,
    retry_backoff_seconds: float = 1.0,
    on_result: Callable[[KbarChunkResult], None] | None = None,
) -> KbarPullSummary:
    """Fetch one weekday at a time into create-once, resumable raw segments."""

    first, last = _parse_range(start_date, end_date)
    if isinstance(max_retries, bool) or max_retries < 0:
        raise KbarPullError("max_retries must be non-negative")
    if retry_backoff_seconds < 0.0 or not isfinite(retry_backoff_seconds):
        raise KbarPullError("retry_backoff_seconds must be finite and non-negative")
    now = clock or (lambda: datetime.now(timezone.utc))
    wait = sleep or time.sleep
    contract = source.resolve_near_contract()
    results: list[KbarChunkResult] = []
    days = tuple(_day_chunks(first, last))

    for index, current in enumerate(days):
        start_text = current.isoformat()
        end_text = start_text
        segment_id = _segment_id(contract.alias_code, start_text, end_text)
        if current.weekday() >= 5:
            result = KbarChunkResult(
                start_text, end_text, "NON_TRADING_DAY", 0, None,
            )
        elif store.has_segment(EVENT_TYPE, segment_id):
            result = KbarChunkResult(
                start_text, end_text, "ALREADY_STORED", 0, None,
            )
        else:
            batch = _fetch_with_retry(
                source,
                contract,
                start_text,
                end_text,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                sleep=wait,
            )
            if batch is None:
                result = KbarChunkResult(start_text, end_text, "NO_DATA", 0, None)
            else:
                records = normalize_kbar_batch(batch)
                if not records:
                    result = KbarChunkResult(start_text, end_text, "NO_DATA", 0, None)
                else:
                    manifest = store.append_segment(
                        EVENT_TYPE,
                        records,
                        segment_id=segment_id,
                        created_at=now(),
                    )
                    result = KbarChunkResult(
                        start_text,
                        end_text,
                        "STORED",
                        manifest.record_count,
                        manifest.checksum_sha256,
                    )
            if pause is not None and index < len(days) - 1:
                pause()
        results.append(result)
        if on_result is not None:
            on_result(result)

    return KbarPullSummary(
        alias_code=contract.alias_code,
        dataset_version=store.dataset_version,
        results=tuple(results),
    )


def read_shioaji_credentials(path: Path) -> ShioajiCredentials:
    """Read only the two credential assignments from a dotenv-style file."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise KbarPullError(f"cannot read credentials file {path}: {error}") from error

    values: dict[str, str] = {}
    for line in lines:
        match = _ENV_ASSIGNMENT.match(line)
        if match is None:
            continue
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            values[match.group("key")] = value
    api_key = values.get("SJ_API_KEY", "")
    secret_key = values.get("SJ_SEC_KEY", "")
    if not api_key or not secret_key:
        raise KbarPullError(
            f"credentials file {path} must define SJ_API_KEY and SJ_SEC_KEY"
        )
    return ShioajiCredentials(api_key=api_key, secret_key=secret_key)


def _fetch_with_retry(
    source: HistoricalKbarSource,
    contract: ContractInfo,
    start: str,
    end: str,
    *,
    max_retries: int,
    retry_backoff_seconds: float,
    sleep: Callable[[float], None],
) -> KbarBatch | None:
    for attempt in range(max_retries + 1):
        try:
            return source.fetch_kbars(contract, start, end)
        except Exception as error:
            if _is_not_found(error):
                return None
            if not _is_server_error(error):
                raise KbarPullError(
                    f"{start}..{end}: kbar fetch failed: {error}"
                ) from error
            if attempt >= max_retries:
                raise KbarPullError(
                    f"{start}..{end}: kbar fetch failed after"
                    f" {max_retries + 1} attempts: {error}"
                ) from error
            sleep(retry_backoff_seconds * (2 ** attempt))
    raise AssertionError("retry loop must return or raise")


def _is_server_error(error: Exception) -> bool:
    return any(cls.__name__ == "ServerError" for cls in type(error).__mro__)


def _is_not_found(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    message = str(error)
    return status_code == 404 or "404" in message


def _parse_range(start_text: str, end_text: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(start_text)
        last = date.fromisoformat(end_text)
    except ValueError as error:
        raise KbarPullError(f"invalid kbar date: {error}") from error
    if last < first:
        raise KbarPullError("invalid kbar range: end precedes start")
    return first, last


def _day_chunks(first: date, last: date) -> Sequence[date]:
    days: list[date] = []
    current = first
    while current <= last:
        days.append(current)
        current += timedelta(days=1)
    return tuple(days)


def _segment_id(alias_code: str, start: str, end: str) -> str:
    return f"backfill-kbar-1m-{alias_code}-{start}-{end}"


def _kbar_time(day: str, value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise KbarPullError(f"{day}: ts values must be epoch-nanosecond integers")
    if value < 0:
        raise KbarPullError(f"{day}: ts values must be non-negative")
    wall = _EPOCH + timedelta(microseconds=value // 1_000)
    return wall.replace(tzinfo=TAIPEI)


def _finite_number(day: str, name: str, value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(float(value))
    ):
        raise KbarPullError(f"{day}: {name} must be a finite number")


def _volume(day: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise KbarPullError(f"{day}: Volume must be a non-negative integer")


def _manifest_from_payload(payload: Mapping[str, object]) -> SegmentManifest:
    try:
        return SegmentManifest(
            segment_id=str(payload["segment_id"]),
            event_type=str(payload["event_type"]),
            dataset_version=str(payload["dataset_version"]),
            relative_path=str(payload["relative_path"]),
            checksum_sha256=str(payload["checksum_sha256"]),
            record_count=_manifest_record_count(payload["record_count"]),
            schema_version=str(payload["schema_version"]),
            writer_version=str(payload["writer_version"]),
            created_at=str(payload["created_at"]),
            minimum_event_time=str(payload["minimum_event_time"]),
            maximum_event_time=str(payload["maximum_event_time"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise KbarPullError("invalid raw-store manifest") from error


def _manifest_record_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise KbarPullError("raw-store manifest record_count is invalid")
    return value


def read_kbar_records(
    store: AppendOnlyRawStore,
    root: Path,
    *,
    dataset_version: str,
) -> tuple[dict[str, object], ...]:
    """Read and checksum-verify all stored 1-minute kbar records."""

    manifest_path = root / "manifest.ndjson"
    if not manifest_path.is_file():
        return ()
    records: list[dict[str, object]] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, Mapping):
            raise KbarPullError("raw-store manifest row is not an object")
        if raw.get("event_type") != EVENT_TYPE:
            continue
        manifest = _manifest_from_payload(raw)
        if manifest.dataset_version != dataset_version:
            continue
        records.extend(store.read_verified(manifest))
    return tuple(records)

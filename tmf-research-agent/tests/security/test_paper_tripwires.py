from __future__ import annotations

import builtins
import inspect
import socket
import sys
import unittest
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NoReturn

from tmf_research.domain.paper_trades import (
    PaperCostConfig,
    PaperExit,
    PaperIntent,
    PaperQuote,
)
from tmf_research.paper.broker import PaperBroker
from tmf_research.paper.fill_model import PaperFillModel
from tmf_research.paper.risk import EntryConditions, evaluate_entry
from tmf_research.security.readonly_verifier import verify_readonly


NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
COMPLETE_COSTS = PaperCostConfig(
    entry_fee_ntd=20.0, exit_fee_ntd=20.0, tax_ntd=4.0, slippage_cost_ntd=10.0,
)
_FORBIDDEN_IMPORT_ROOTS = frozenset((
    "socket", "http", "urllib", "requests", "httpx", "aiohttp",
    "subprocess", "shioaji",
))


class RawApiTripwire:
    """Fails the test if any capability of a raw API object is reached."""

    def __getattr__(self, name: str) -> NoReturn:
        raise AssertionError(f"paper flow reached raw API capability {name!r}")


def _tripwire(name: str) -> Callable[..., NoReturn]:
    def _raise(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(f"paper flow reached forbidden capability {name!r}")

    return _raise


@contextmanager
def armed_tripwires() -> Iterator[None]:
    original_socket = socket.socket
    original_urlopen = urllib.request.urlopen
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals_: object = None,
        locals_: object = None,
        fromlist: object = (),
        level: int = 0,
    ) -> object:
        root = name.split(".", maxsplit=1)[0]
        if level == 0 and root in _FORBIDDEN_IMPORT_ROOTS:
            raise AssertionError(
                f"paper flow attempted dynamic import of {name!r}"
            )
        return original_import(name, globals_, locals_, fromlist, level)  # type: ignore[arg-type]

    socket.socket = _tripwire("socket.socket")  # type: ignore[misc,assignment]
    urllib.request.urlopen = _tripwire("urllib.request.urlopen")
    builtins.__import__ = guarded_import  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket = original_socket  # type: ignore[misc]
        urllib.request.urlopen = original_urlopen
        builtins.__import__ = original_import


def run_complete_paper_flow() -> PaperBroker:
    broker = PaperBroker()
    model = PaperFillModel(entry_slippage_points=1.0, exit_slippage_points=0.5)
    quote = PaperQuote(bid_price_1=21500.0, ask_price_1=21501.0, age_ms=100)
    rejections = evaluate_entry(EntryConditions(
        quote=quote,
        quote_age_limit_ms=1000,
        spread_limit_points=2.0,
        data_quality_valid=True,
        model_compatible=True,
        features_complete=True,
        position_open=False,
        rollover_in_progress=False,
        session_ending=False,
        cost_config=COMPLETE_COSTS,
    ))
    if rejections:
        raise AssertionError(f"clear entry was rejected: {rejections!r}")
    intent = PaperIntent("paper-tripwire-1", "LONG", 1, NOW)
    entry = model.entry_fill("LONG", quote, NOW)
    broker.open_position(
        intent,
        entry,
        stop_price=entry.price - 10.0,
        target_price=entry.price + 20.0,
        vertical_deadline=NOW + timedelta(minutes=15),
        session_end=NOW + timedelta(hours=4),
    )
    broker.close_position(
        PaperExit(
            reason="PROFIT_TARGET",
            price=entry.price + 19.5,
            exited_at=NOW + timedelta(minutes=5),
        ),
        COMPLETE_COSTS,
    )
    return broker


class PaperTripwireTests(unittest.TestCase):
    def test_complete_paper_flow_never_reaches_a_tripwire(self) -> None:
        with armed_tripwires():
            broker = run_complete_paper_flow()

        self.assertEqual(len(broker.ledger.rows), 1)

    def test_every_ledger_row_is_immutably_paper(self) -> None:
        broker = run_complete_paper_flow()

        for row in broker.ledger.rows:
            self.assertEqual(row.execution_mode, "PAPER")
        for record in broker.records:
            self.assertEqual(record.execution_mode, "PAPER")

    def test_paper_broker_cannot_receive_external_capabilities(self) -> None:
        parameters = inspect.signature(PaperBroker.__init__).parameters

        self.assertEqual(tuple(parameters), ("self",))
        with self.assertRaises(TypeError):
            PaperBroker(RawApiTripwire())  # type: ignore[call-arg]

    def test_paper_modules_import_only_audited_safe_modules(self) -> None:
        prefixes = ("tmf_research.paper", "tmf_research.domain.paper_trades")
        loaded = tuple(
            name for name in sorted(sys.modules)
            if name.startswith(prefixes) and sys.modules[name] is not None
        )

        self.assertTrue(loaded)
        for name in loaded:
            module = sys.modules[name]
            source = inspect.getsource(module)
            for forbidden in _FORBIDDEN_IMPORT_ROOTS:
                self.assertNotIn(
                    f"import {forbidden}", source,
                    f"{name} must not import {forbidden}",
                )

    def test_paper_source_tree_passes_the_readonly_verifier(self) -> None:
        source_root = Path(inspect.getfile(PaperBroker)).parents[2]

        report = verify_readonly(source_root)

        self.assertTrue(report.ok, report.render())


if __name__ == "__main__":
    unittest.main()

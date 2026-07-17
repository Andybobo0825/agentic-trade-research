"""Credentialed market-data smoke; never runs in default CI.

Requires TMF_RUN_CREDENTIALED=1 plus SJ_API_KEY/SJ_SEC_KEY in the environment.
An unavailable boundary is reported as CREDENTIALED_VALIDATION_NOT_RUN via
skip, never converted into a pass.
"""

from __future__ import annotations

import inspect
import os
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from tmf_research.security.readonly_verifier import verify_readonly


TAIPEI = ZoneInfo("Asia/Taipei")
_ENABLED = os.environ.get("TMF_RUN_CREDENTIALED") == "1"
_HAS_KEYS = bool(
    os.environ.get("SJ_API_KEY", "").strip()
    and os.environ.get("SJ_SEC_KEY", "").strip()
)


@unittest.skipUnless(
    _ENABLED and _HAS_KEYS,
    "CREDENTIALED_VALIDATION_NOT_RUN: set TMF_RUN_CREDENTIALED=1 with SJ_API_KEY/SJ_SEC_KEY",
)
class CredentialedBackfillSmokeTests(unittest.TestCase):
    def test_market_data_login_resolves_tmfr1_and_fetches_one_day(self) -> None:
        from tmf_research.infrastructure.market_session import (
            open_market_data_session,
        )

        source_root = Path(inspect.getfile(verify_readonly)).parents[2]
        self.assertTrue(verify_readonly(source_root).ok)

        gateway = open_market_data_session(
            api_key=os.environ["SJ_API_KEY"],
            secret_key=os.environ["SJ_SEC_KEY"],
            simulation=os.environ.get("SHIOAJI_SIMULATION") == "1",
        )
        contract = gateway.resolve_near_contract()
        self.assertEqual(contract.alias_code, "TMFR1")
        self.assertTrue(contract.target_code.startswith("TMF"))

        probe = date.today() - timedelta(days=1)
        payload: dict[str, object] = {}
        for _attempt in range(7):
            batch = gateway.fetch_ticks(contract, probe.isoformat())
            values = batch.payload.get("ts")
            if isinstance(values, (list, tuple)) and values:
                payload = dict(batch.payload)
                break
            probe -= timedelta(days=1)
        self.assertTrue(payload, "no tick data found in the last week")
        self.assertIn("close", payload)

        from tmf_research.collection.backfill import normalize_tick_batch
        from tmf_research.domain.contracts import TickBatch

        records = normalize_tick_batch(TickBatch(
            contract=contract,
            date=probe.isoformat(),
            fetched_at=datetime.now(tz=TAIPEI),
            payload=payload,
        ))
        self.assertTrue(records)
        first_time = records[0].exchange_datetime.astimezone(TAIPEI)
        self.assertEqual(first_time.date().isoformat(), probe.isoformat())
        self.assertTrue(
            5 <= first_time.hour <= 23,
            f"tick time {first_time.isoformat()} violates the Taipei wall-clock assumption",
        )


if __name__ == "__main__":
    unittest.main()

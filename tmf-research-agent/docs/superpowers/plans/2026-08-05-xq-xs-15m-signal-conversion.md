# XQ XS 15-Minute Signal Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two XQ XS indicator scripts that reproduce the approved MXF 15-minute Pine signals and a no-order virtual strategy state machine without changing either Pine source.

**Architecture:** Keep all XQ artifacts isolated under `xq/` and treat both scripts as technical indicators rather than transaction scripts. Lock source integrity and the no-order boundary with a Python contract test, then verify the sidecar readonly gate before the full suite.

**Tech Stack:** XQ XScript/XS indicator syntax, Python 3.11 `unittest`, SHA-256 contract checks.

---

## File Structure

- Create `tests/test_xq_xs_scripts.py`: source hash, signal formula, timeframe and no-order boundary tests.
- Create `xq/taiwan-mtf-bb-sr-15m.xs`: Bollinger bands, confirmed pivot support/resistance and four signal plots.
- Create `xq/taiwan-mtf-bb-sr-strategy-15m.xs`: no-order virtual FLAT/LONG/SHORT state machine and entry/exit plots.
- Preserve `../pine/taiwan-mtf-bb-sr.pine` and `../pine/taiwan-mtf-bb-sr-strategy.pine` byte-for-byte.

### Task 1: Lock the conversion contract

**Files:**
- Create: `tests/test_xq_xs_scripts.py`

- [ ] **Step 1: Write the failing test**

Create a `unittest.TestCase` that reads both expected XS paths, verifies the two approved Pine SHA-256 values, requires `BarFreq`/`BarInterval` guards and the fixed 15-minute parameters, checks the four signal names, checks the virtual state fields, and rejects transaction/account capability tokens.

```python
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_ROOT = ROOT.parent
XQ_ROOT = ROOT / "xq"

PINE_HASHES = {
    HOST_ROOT / "pine" / "taiwan-mtf-bb-sr.pine":
        "958780009a6ff804f886af3a80129fbe4471510d750022393a22dbd74270e70a",
    HOST_ROOT / "pine" / "taiwan-mtf-bb-sr-strategy.pine":
        "61bbc4c82888491bd05c45a88952dc52c5fa420332f2124b9382ea5afa324820",
}


class XqXsScriptTests(unittest.TestCase):
    def test_pine_sources_are_unchanged(self) -> None:
        for path, expected in PINE_HASHES.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_expected_xs_scripts_exist(self) -> None:
        self.assertTrue((XQ_ROOT / "taiwan-mtf-bb-sr-15m.xs").is_file())
        self.assertTrue((XQ_ROOT / "taiwan-mtf-bb-sr-strategy-15m.xs").is_file())
```

- [ ] **Step 2: Run test to verify it fails**

Run `PYTHONPATH=src python3 -m unittest tests.test_xq_xs_scripts -v`.

Expected: `FAIL` because both XS files are absent.

- [ ] **Step 3: Keep the failing test as the production contract**

Do not weaken path, hash or forbidden-capability assertions when implementing the scripts.

### Task 2: Add the 15-minute indicator conversion

**Files:**
- Create: `xq/taiwan-mtf-bb-sr-15m.xs`
- Test: `tests/test_xq_xs_scripts.py`

- [ ] **Step 1: Implement the minimal indicator script**

Use XQ-supported declarations and functions:

```text
Input: BBLength(20, "布林期數"), BBMultiplier(2.0, "布林標準差倍數");
Var: BBMiddle(0), BBDeviation(0), BBUpper(0), BBLower(0);

if BarFreq <> "Min" or BarInterval <> 15 then
    RaiseRunTimeError("本腳本只支援15分鐘K");

BBMiddle = Average(Close, BBLength);
BBDeviation = StandardDev(Close, BBLength, 1) * BBMultiplier;
BBUpper = BBMiddle + BBDeviation;
BBLower = BBMiddle - BBDeviation;
```

Confirm pivots with `High[4] = Highest(High, 9)` and `Low[4] = Lowest(Low, 9)`, retain the previous confirmed level for the current signal decision, calculate average volume and all four approved signal booleans, then expose Bollinger/support/resistance and signal plots with `PlotN`/`NoPlot`.

- [ ] **Step 2: Run the targeted contract test**

Run `PYTHONPATH=src python3 -m unittest tests.test_xq_xs_scripts -v`.

Expected: only the still-missing virtual strategy assertions fail.

### Task 3: Add the no-order virtual strategy conversion

**Files:**
- Create: `xq/taiwan-mtf-bb-sr-strategy-15m.xs`
- Test: `tests/test_xq_xs_scripts.py`

- [ ] **Step 1: Implement the virtual state machine**

Reuse the indicator formulas directly in the standalone script and add inputs:

```text
Input: UseBreakoutLong(1, "帶量突破做多"),
       UseBreakdownShort(1, "帶量跌破做空"),
       UseSupportBounceLong(0, "支撐止跌做多"),
       UseResistanceRejectionShort(0, "壓力遇阻做空"),
       HoldBars(16, "持有根數");

Var: VirtualSide(0), PendingSide(0), EntryBar(0), EntryPrice(0),
     LongEntryPulse(False), ShortEntryPulse(False), ExitPulse(False);
```

At each completed bar, carry state forward, consume `PendingSide[1]` at the current `Open` only when not at a session cutoff, exit a live virtual side at 16 bars or 13:30/04:45, prohibit same-bar reversal, and only create a new pending side from an unambiguous signal while flat.

- [ ] **Step 2: Run the targeted test and verify it passes**

Run `PYTHONPATH=src python3 -m unittest tests.test_xq_xs_scripts -v`.

Expected: `OK`.

### Task 4: Verify safety and source integrity

**Files:**
- Verify only; no production edits expected.

- [ ] **Step 1: Run the readonly verifier first**

Run `PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root .`.

Expected: `READONLY VERIFIED` and exit 0.

- [ ] **Step 2: Run the focused XS tests**

Run `PYTHONPATH=src python3 -m unittest tests.test_xq_xs_scripts -v`.

Expected: all tests pass.

- [ ] **Step 3: Run the complete test suite**

Run `PYTHONPATH=src python3 -m unittest discover -s tests -t . -v`.

Expected: all non-credentialed tests pass; credentialed smoke remains skipped without credentials.

- [ ] **Step 4: Recompute Pine hashes and inspect the final diff**

Run `shasum -a 256 ../pine/taiwan-mtf-bb-sr.pine ../pine/taiwan-mtf-bb-sr-strategy.pine` and inspect only the new design, plan, test and `xq/` artifacts.

Expected: approved hashes match and only newly added conversion artifacts appear for this task.

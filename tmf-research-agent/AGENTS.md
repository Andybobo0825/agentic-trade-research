# TMF Research Sidecar Instructions

- Follow `../docs/txresearch.md` phase by phase.
- Keep this project independent from the host Node.js strategy until a separate
  integration change is explicitly approved.
- Never add brokerage authentication, accounts, certificates, position access,
  or executable trading capabilities.
- Only `src/tmf_research/infrastructure/shioaji_market_data.py` may retain the raw
  Shioaji API object.
- All consumers depend on `MarketDataGateway`, never on the raw adapter.
- Write a failing test before each production behavior.
- Run the read-only verifier before the rest of the test suite.
- Preserve deterministic inputs, outputs, and evidence timestamps.

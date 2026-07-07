# Repo-native dynamic memory

This repo uses deterministic OMX/Codex dynamic memory instead of requiring Kiro. The goal is to keep recent operating context available without loading stale or unsafe history into every agent turn.

## Layers

`memory-sync` writes four local runtime files under `.omx/memory/`:

| Layer | File | Rule |
| --- | --- | --- |
| Hot | `.omx/memory/hot.md` | Entries from the last 7 days, capped at 20 newest entries. |
| Warm | `.omx/memory/warm.md` | Entries from 8-30 days ago, plus hot overflow beyond the 20-entry cap. |
| Archive | `.omx/memory/archive.md` | Entries older than 30 days. |
| Obsolete | `.omx/memory/obsolete.md` | Entries explicitly marked `obsolete: true` because a newer workflow or decision replaced them. |

`.omx/` is ignored by git, so these files are local runtime memory. Canonical shared behavior still belongs in tracked docs such as `docs/standard-workflow-v1.md`.

## Allowed memory entries

Only four durable categories are accepted:

- `decision` — a workflow or repo decision that was actually accepted.
- `verified-fix` — a bug, outage, provider failure, or repair conclusion verified by checks.
- `failure-case` — a trading workflow failure or postmortem, recorded only as a failure case and not as a standard rule.
- `milestone` — a delivered version, feature, handoff, or other completion milestone.

Rejected content includes raw API keys/tokens/secrets, LINE userIds, `.env` or certificate references, full logs/stack traces, unverified intraday guesses, and guarantee language.

## JSON input contract

Hooks and agents should pass JSON entries into `memory-sync`. One object or an array of objects is accepted.

```json
[
  {
    "date": "2026-06-26",
    "category": "decision",
    "text": "Dynamic memory hot/warm/archive layout accepted for repo-local runtime memory.",
    "source": "user-goal"
  },
  {
    "date": "2026-06-01",
    "category": "decision",
    "text": "Old R18H6 baseline memory was replaced by Standard Workflow 1.01 WR3.",
    "reason": "Replaced by docs/standard-workflow-v1.md",
    "obsolete": true
  }
]
```

Run:

```sh
node src/cli.js memory-sync --entry-file /tmp/trade-memory-entry.json --format markdown
```

Or add a single entry without a file:

```sh
node src/cli.js memory-sync \
  --date 2026-06-26 \
  --category verified-fix \
  --entry "Shioaji NotReady repair was verified by health and quote checks." \
  --source "ops" \
  --format markdown
```

## Suggested Stop-hook prompt

Use the runtime hook mechanism available in the active agent environment to ask the agent to emit a small JSON file, then call `memory-sync`. The prompt should be selective:

```text
Review this completed turn. If and only if it contains a durable repo memory item, write JSON entries with fields date, category, text, source, reason, obsolete. Allowed categories: decision, verified-fix, failure-case, milestone. Do not include secrets, LINE userIds, .env values, certificate names, full logs, raw stack traces, unverified intraday guesses, or strategy changes that are not documented/backtested. Then run: node src/cli.js memory-sync --entry-file <json-file> --format markdown
```

For Kiro users, this maps naturally to a `Stop` agent hook. For this repo's Codex/OMX workflow, the same rule can be implemented by OMX stop hooks or manually run after a session.

## Guardrails

- `memory-sync` never edits `docs/standard-workflow-v1.md` or `.omx/project-memory.json`.
- A remembered `failure-case` is not a strategy rule. Standard Workflow changes still require the version-lock process in `docs/standard-workflow-v1.md`.
- Memory files should summarize conclusions, not preserve raw evidence. Keep raw evidence in test output, reports, or logs with normal retention controls.

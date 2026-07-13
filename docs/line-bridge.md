# LINE Messaging API Bridge for OMX/tmux

This repo can run a local LINE bridge so your LINE app can send prompts to the OMX/Codex agent running in a Mac tmux pane, then receive the completion summary back in LINE.

LINE sends messages to a public HTTPS webhook. Use Cloudflare Tunnel to expose the local bridge server without opening inbound ports on your Mac.

## Architecture

```text
LINE mobile app
  -> LINE Messaging API webhook
  -> Cloudflare Tunnel public HTTPS URL
  -> local Node bridge on the Mac, default http://127.0.0.1:8787/line/webhook
  -> tmux paste/send-keys into the OMX agent pane
  -> response file written by the OMX/Codex agent
  -> LINE Messaging API push message
```

## Safety model

- Secrets stay in `.env`.
- The bridge verifies `x-line-signature` with `LINE_CHANNEL_SECRET` before processing any webhook body.
- By default, users who add the LINE Official Account as a friend are automatically added to a local whitelist file and can run prompts or `/tail`.
- `LINE_ALLOWED_USER_IDS` remains supported as an optional/manual seed list, but it is no longer required for normal one-to-one LINE use.
- The bridge binds to `127.0.0.1` by default; Cloudflare Tunnel is the public HTTPS edge.
- One prompt runs at a time in the shared tmux pane. If another prompt arrives while busy, the bridge puts it into a global FIFO queue, replies with the current position, then pushes the result to the original sender after earlier jobs finish.

## LINE setup

1. Go to LINE Developers Console: <https://developers.line.biz/console/>.
2. Create or select a **Provider**.
3. Create a **Messaging API channel**. If LINE asks, create/connect a LINE Official Account.
4. In the channel **Basic settings** tab, copy **Channel secret**:

   ```env
   LINE_CHANNEL_SECRET=你的ChannelSecret
   ```

5. In the channel **Messaging API** tab, issue a **Channel access token (long-lived)** and copy it:

   ```env
   LINE_CHANNEL_ACCESS_TOKEN=你的LongLivedChannelAccessToken
   ```

6. Add the Official Account as a friend in LINE. The `follow` webhook automatically writes your LINE `userId` to the local whitelist file:

   ```env
   LINE_BRIDGE_AUTHORIZED_USER_IDS_FILE=.omx/line-bridge/authorized-users.json
   ```

7. Send `/start` or `/status` to confirm the bridge is connected. You do not need to manually fill `LINE_ALLOWED_USER_IDS`.

If you want to disable friend auto-authorization and use a fixed/manual whitelist instead:

```env
LINE_BRIDGE_AUTO_AUTHORIZE_FRIENDS=false
LINE_ALLOWED_USER_IDS=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Multiple manual allowed users can be comma-separated.

## tmux target setup

Run `tradestart` from the OMX agent pane you want LINE to control. It uses that pane's `$TMUX_PANE` as `LINE_BRIDGE_TMUX_TARGET`, so you normally do not need to set the target manually.

If you must run startup outside tmux, set `LINE_BRIDGE_TMUX_TARGET` yourself. In the OMX agent pane, run:

```sh
tmux display-message -p '#{pane_id}'
```

It prints a pane id like `%12`; use that value in `.env`. Keep the OMX agent pane open and idle when you send prompts from LINE.

## Run the local LINE bridge

Check config without printing secrets:

```sh
npm run line:check
```

One-command startup for the local LINE bridge plus the Cloudflare named tunnel:

```sh
npm run tradestart
# or after npm link:
tradestart
```

`tradestart` first uses an existing live tmux pane in this repo as `LINE_BRIDGE_TMUX_TARGET`. If it is launched from a normal terminal and no usable pane exists, it creates tmux session `trade-line-codex`, starts Codex in the repo, uses that pane as the bridge target, then cleans expired runtime artifacts (LINE responses, OMX logs, old resume/session state, and smoke temp files), starts or restarts the repo-local LINE bridge, and starts the Cloudflare tunnel in tmux session `trade-line-cloudflared`.

LINE investment prompts also inject a compact reference to [`docs/line-session-handoff.md`](line-session-handoff.md) by default, so newly created `trade-line-codex` sessions inherit the required market-data workflow without pasting the full handoff into the context window. The agent reads the handoff file from the repo when needed, updates point-in-time evidence with `phase3-dataset`, and uses read-only `phase3-screen` as the sole technical decision path. Fugle quotes and external research are added only after technical eligibility; `daily-decision-study`, `signal-study`, and `chip-study` remain historical diagnostics. To avoid wasting tokens, the default handoff mode is `once`: the bridge sends this short file-reference only on the first prompt of a running bridge/agent session. Set `LINE_BRIDGE_HANDOFF_MODE=always` only when deliberately testing or starting every prompt in a fresh agent context.

```sh
npm run tradestart
```

Startup/shutdown LINE broadcasts are disabled by default. Use `--notify` only when you explicitly want to push the service message to all authorized LINE users:

```sh
npm run tradestart -- --notify
```

The managed fallback `trade-line-codex` session is launched with non-interactive defaults so LINE jobs do not hang behind Codex approval prompts:

```sh
codex --ask-for-approval never --sandbox workspace-write
```

`tradestart` also injects `OMX_AUTO_UPDATE=0` and `CODEX_NON_INTERACTIVE=1` for the managed session, which prevents OMX launch-time update prompts and Codex installer/update prompts from blocking unattended LINE requests. Override `TRADE_LINE_AGENT_COMMAND`, `OMX_AUTO_UPDATE`, or `CODEX_NON_INTERACTIVE` only if you intentionally want different behavior.

Stop the LINE bridge and Cloudflare Tunnel. If `tradestart` created its own `trade-line-codex` or `trade-line-cloudflared` session/panes, `tradestop` removes those too:

```sh
npm run tradestop
# or after npm link:
tradestop
```

Normal LINE-bridge-only background start:

```sh
npm run line:bridge:auto
```

Foreground debug mode:

```sh
npm run line:bridge
```

Health check:

```sh
curl http://127.0.0.1:8787/health
```

## Cloudflare Tunnel setup

### Quick development tunnel

For a fast temporary URL:

```sh
cloudflared tunnel --url http://localhost:8787
```

Cloudflare prints a random `https://*.trycloudflare.com` URL. In LINE Developers Console, set the webhook URL to:

```text
https://random-words.trycloudflare.com/line/webhook
```

This is good for testing, but the URL changes when you restart the quick tunnel.

### Stable named tunnel

If you own a domain in Cloudflare, create a stable tunnel/hostname in the Cloudflare Zero Trust dashboard or with `cloudflared`, and route it to:

```text
http://localhost:8787
```

Then set the LINE webhook URL to:

```text
https://你的子網域.example.com/line/webhook
```

## LINE webhook settings

In LINE Developers Console > Messaging API:

1. Set **Webhook URL** to the Cloudflare Tunnel URL ending in `/line/webhook`.
2. Enable **Use webhook**.
3. Optional but recommended: disable auto-reply/greeting responses in LINE Official Account Manager if they interfere with bot replies.
4. Use **Verify** to test the webhook. The local bridge must be running and the tunnel must be active.

## LINE commands

- `/help` or `/start` — usage summary and your LINE userId.
- `/status` — whether the bridge is idle or busy, plus the FIFO queue waiting count.
- `/tail` — capture recent target tmux pane output.
- Any normal text — forwarded as a prompt to the OMX/Codex agent, or queued FIFO when another prompt is already running.

## Completion behavior

For full LINE replies, the bridge injects a delivery contract into each forwarded prompt. The OMX/Codex agent writes the complete LINE-safe final answer to `.omx/line-bridge/responses/*.md`, and the bridge sends that file content back to LINE using push messages.

If the response file is not produced, the bridge falls back to the OMX `agent-turn-complete` preview under `.omx/logs/turns-*.jsonl`. If no completion appears before `LINE_BRIDGE_COMPLETION_TIMEOUT_MS`, it returns a recent tmux pane capture as a last-resort diagnostic.

## tradestart startup helper

Optional overrides:

```env
TRADE_LINE_TUNNEL_CONFIG=~/.cloudflared/trade-line.yml
TRADE_LINE_TUNNEL_NAME=trade-line
TRADE_LINE_TUNNEL_SESSION=trade-line-cloudflared
TRADE_LINE_TUNNEL_LOG=/tmp/trade-line-cloudflared.log
TRADE_LINE_AGENT_SESSION=trade-line-codex
# Leave empty for: codex --ask-for-approval never --sandbox workspace-write
TRADE_LINE_AGENT_COMMAND=
OMX_AUTO_UPDATE=0
CODEX_NON_INTERACTIVE=1
TRADE_LINE_ARTIFACT_RETENTION_DAYS=7
TRADE_LINE_PUBLIC_HEALTH_URL=https://line.beautyrxstore.cc/health
LINE_BRIDGE_WEBHOOK_URL=https://line.beautyrxstore.cc/line/webhook
```

## Environment variables

```env
LINE_CHANNEL_ACCESS_TOKEN=
LINE_CHANNEL_SECRET=
LINE_BRIDGE_AUTO_AUTHORIZE_FRIENDS=true
LINE_BRIDGE_AUTHORIZED_USER_IDS_FILE=.omx/line-bridge/authorized-users.json
LINE_ALLOWED_USER_IDS=
# Optional; tradestart normally fills this from $TMUX_PANE
LINE_BRIDGE_TMUX_TARGET=
LINE_BRIDGE_PORT=8787
LINE_BRIDGE_PATH=/line/webhook
LINE_BRIDGE_COMPLETION_TIMEOUT_MS=600000
LINE_BRIDGE_COMPLETION_POLL_MS=2000
LINE_BRIDGE_TURN_LOG_DIR=.omx/logs
LINE_BRIDGE_CAPTURE_LINES=140
LINE_BRIDGE_SUBMIT_KEYS=Enter
LINE_BRIDGE_SUBMIT_DELAY_MS=800
LINE_BRIDGE_CLEAR_BEFORE_SEND=true
LINE_BRIDGE_RESPONSE_DIR=.omx/line-bridge/responses
LINE_BRIDGE_RESPONSE_FILE_CONTRACT=true
LINE_BRIDGE_RESPONSE_RETENTION_DAYS=7
LINE_BRIDGE_RESPONSE_MAX_FILES=200
LINE_BRIDGE_COMMAND_PREFIX=
LINE_BRIDGE_HANDOFF_FILE=docs/line-session-handoff.md
LINE_BRIDGE_HANDOFF=true
LINE_BRIDGE_HANDOFF_MODE=once
TRADE_LINE_AGENT_SESSION=trade-line-codex
TRADE_LINE_AGENT_COMMAND=
OMX_AUTO_UPDATE=0
CODEX_NON_INTERACTIVE=1
TRADE_LINE_ARTIFACT_RETENTION_DAYS=7
```

`tradstart` remains available as a legacy alias for existing local scripts; prefer `tradestart` for new usage.

## Notes and limitations

- The Mac must stay awake and online while the bridge and tunnel run.
- LINE completion replies use push messages, so they count against your LINE Official Account message quota.
- Long replies are split into multiple LINE text messages.
- `LINE_CHANNEL_ACCESS_TOKEN` and `LINE_CHANNEL_SECRET` are secrets; never paste them into chat logs or commit them.

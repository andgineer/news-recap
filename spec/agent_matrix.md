# Agent Model Matrix

Available models verified by probe on 2026-02-25.

## Gemini

| Model | Type | Notes |
|-------|------|-------|
| `gemini-3-flash-preview` | next-gen fast | New, untested |
| `gemini-2.5-flash` | fast | Large context, tested for grouping |
| `gemini-2.5-flash-lite` | ultra-cheap | Untested |

CLI: `gemini --model <model> --approval-mode auto_edit --prompt "..."`

## Codex

Only `gpt-5.2` available with ChatGPT account. `o3`, `o4-mini`, `gpt-4.1`, `gpt-4.1-mini`, `codex-mini` — all rejected.

| Model | effort | Tokens on "OK" | Notes |
|-------|--------|----------------|-------|
| `gpt-5.2` | low | 146 | Minimal reasoning, cheapest |
| `gpt-5.2` | medium | 6,290 | Default balance |
| `gpt-5.2` | high | 1,682 | Max reasoning |

CLI: `codex exec -m gpt-5.2 -c model_reasoning_effort=<low|medium|high> --sandbox workspace-write "..."`

## Claude

| Model | Type | Notes |
|-------|------|-------|
| `sonnet` | fast | Best grouping quality in experiments |
| `opus` | quality | Marginal improvement over sonnet, 3x slower |

CLI: `claude -p --model <model> --effort low --permission-mode dontAsk -- "..."`

## Not available

| Agent | Model | Error |
|-------|-------|-------|
| gemini | `gemini-2.0-flash-lite` | 404 |
| codex | `o3` | Not supported with ChatGPT account |
| codex | `o4-mini` | Not supported with ChatGPT account |
| codex | `gpt-4.1` | Not supported with ChatGPT account |
| codex | `gpt-4.1-mini` | Not supported with ChatGPT account |
| codex | `codex-mini` | Not supported with ChatGPT account |

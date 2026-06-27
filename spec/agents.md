# LLM Agent Backends

Reference for all external CLI agent backends — available models, the manifest contract that governs how agents receive work, workdir layout, command templates, pricing, and env vars.

## Available Models

Verified by probe on 2026-02-25.

### Gemini

| Model | Type | Notes |
|-------|------|-------|
| `gemini-3-flash-preview` | next-gen fast | New, untested |
| `gemini-2.5-flash` | fast | Large context, tested for grouping |
| `gemini-2.5-flash-lite` | ultra-cheap | Default fast profile |

### Codex

Only `gpt-5.2` available with ChatGPT account. `o3`, `o4-mini`, `gpt-4.1`, `gpt-4.1-mini`, `codex-mini` — all rejected.

| Model | Effort | Tokens on "OK" | Notes |
|-------|--------|----------------|-------|
| `gpt-5.2` | low | 146 | Minimal reasoning, cheapest |
| `gpt-5.2` | medium | 6,290 | Default balance |
| `gpt-5.2` | high | 1,682 | Max reasoning |

### Claude

| Model | Type | Notes |
|-------|------|-------|
| `sonnet` | fast | Best grouping quality in experiments |
| `opus` | quality | Marginal improvement over sonnet, 3× slower |

### Not Available

| Agent | Model | Error |
|-------|-------|-------|
| gemini | `gemini-2.0-flash-lite` | 404 |
| codex | `o3` | Not supported with ChatGPT account |
| codex | `o4-mini` | Not supported with ChatGPT account |
| codex | `gpt-4.1` | Not supported with ChatGPT account |
| codex | `gpt-4.1-mini` | Not supported with ChatGPT account |
| codex | `codex-mini` | Not supported with ChatGPT account |

## Manifest-Native Contract

All agents receive the same enriched prompt built by `cli_backend.py`:

1. Base prompt (task-specific).
2. Path to `task_manifest.json`.
3. Step-by-step instructions: read manifest → read articles index → write JSON result to `output_result_path`.
4. Output JSON schema (`blocks` + `source_ids` + `metadata`).
5. Constraint: source_ids must reference articles from the index.

Agents discover all file paths from the manifest — no article IDs or file contents are passed on the command line.

## Workdir Structure

```
.news_recap_workdir/<task_id>/
├── meta/
│   └── task_manifest.json      # paths to all input/output files
├── input/
│   ├── task_input.json         # task metadata (type, prompt, params)
│   ├── task_prompt.txt         # raw prompt text
│   └── articles_index.json     # [{source_id, title, url, source, published_at}]
└── output/
    ├── agent_result.json       # agent's JSON output (contract)
    ├── agent_stdout.log        # captured stdout
    └── agent_stderr.log        # captured stderr
```

## Command Templates

Defaults live in `config.py`. All templates use `{model}` and `{prompt}` placeholders expanded via `shlex.split`.

### Codex

```
codex exec --sandbox workspace-write \
  -c sandbox_workspace_write.network_access=true \
  -c model_reasoning_effort=high \
  --model {model} {prompt}
```

- `workspace-write` lets codex read/write in the project dir.
- Network access is required so codex can call the OpenAI API.
- `{prompt}` must **not** be double-quoted in the template — `shlex.split` will fail on nested quotes.
- Codex needs a git repo in the working directory; the worker runs from the project root.

Token usage: codex prints `tokens used\n10,520` to stderr. Total tokens only — no input/output breakdown.

### Claude

```
claude -p --model {model} \
  --output-format text \
  --permission-mode bypassPermissions \
  --allowed-tools "Read,Write,Edit,WebFetch,Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" \
  -- {prompt}
```

- `-p` enables pipe/non-interactive mode (required for subprocess).
- `--output-format text` is safer than JSON; JSON mode can include usage metadata that breaks the stdout recovery path.
- `--permission-mode bypassPermissions` skips all tool-use confirmation prompts.
- `--allowed-tools` whitelists the tools Claude may use to read inputs and write the output JSON.

Token usage: Claude CLI does not print token counts in text mode. Usage data is not captured.

Known issue: Claude CLI can hang inside restricted sandbox environments (e.g., Cursor sandbox). Works fine from a normal terminal session.

### Gemini

```
gemini --model {model} --approval-mode auto_edit --prompt {prompt}
```

- `--approval-mode auto_edit` allows Gemini to read/write files without confirmation.
- Gemini CLI uses Google OAuth — no API key required for Flash models. Auth state is stored in `~/.gemini/settings.json`; do not delete this file or Gemini will require re-authentication.

Token usage: Gemini CLI does not print token counts. Usage data is not captured.

## Pricing Configuration

Set `NEWS_RECAP_LLM_PRICING` env var. Format: `agent:model:input_per_1m_usd:output_per_1m_usd`, comma-separated.

```bash
export NEWS_RECAP_LLM_PRICING="codex:gpt-5-codex-mini:1.50:6.00,gemini:gemini-2.5-flash-lite:0.075:0.30,claude:sonnet:3.00:15.00"
```

Wildcards supported: `codex:*:1.50:6.00` or `*:*:2.00:8.00`.

When only `total_tokens` is available (no input/output split), cost is estimated using the average of input and output prices.

## Env Var Reference

| Variable | Default | Description |
|---|---|---|
| `NEWS_RECAP_LLM_DEFAULT_AGENT` | `codex` | Default agent for new tasks |
| `NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE` | see above | Codex CLI template |
| `NEWS_RECAP_LLM_CLAUDE_COMMAND_TEMPLATE` | see above | Claude CLI template |
| `NEWS_RECAP_LLM_GEMINI_COMMAND_TEMPLATE` | see above | Gemini CLI template |
| `NEWS_RECAP_LLM_CODEX_MODEL_FAST` | `gpt-5-codex-mini` | Codex fast profile model |
| `NEWS_RECAP_LLM_CODEX_MODEL_QUALITY` | `gpt-5-codex` | Codex quality profile model |
| `NEWS_RECAP_LLM_CLAUDE_MODEL_FAST` | `sonnet` | Claude fast profile model |
| `NEWS_RECAP_LLM_CLAUDE_MODEL_QUALITY` | `opus` | Claude quality profile model |
| `NEWS_RECAP_LLM_GEMINI_MODEL_FAST` | `gemini-2.5-flash-lite` | Gemini fast profile model |
| `NEWS_RECAP_LLM_GEMINI_MODEL_QUALITY` | `gemini-2.5-flash` | Gemini quality profile model |
| `NEWS_RECAP_BACKEND_CAPABILITY_MODE` | `manifest_native` | `manifest_native` or `stdout_parser_fallback` |
| `NEWS_RECAP_LLM_PRICING` | (empty) | Token pricing map |

## Quick Test Run

```bash
# Enqueue a stories task with test articles
news-recap llm enqueue-test \
  --task-type stories \
  --prompt "Group articles into coherent stories with titles and summaries." \
  --source-id "article:<id1>" \
  --source-id "article:<id2>" \
  --agent gemini \
  --model-profile fast \
  --timeout-seconds 120

# Run the worker
news-recap llm worker --max-tasks 1

# Check result
news-recap llm inspect --task-id <task_id>
news-recap llm usage --task-id <task_id>
```

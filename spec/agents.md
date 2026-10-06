# LLM Agent Backends

Reference for all external CLI agent backends — available models, the manifest contract that governs how agents receive work, workdir layout, command templates, pricing, and env vars.

## Available Models

Verified from current provider documentation and local CLI model discovery on 2026-08-30.

### Gemini

| Model | Type | Notes |
|-------|------|-------|
| `gemini-3.7-flash` | current Flash | Default CLI quality profile; GA |
| `gemini-3.5-flash-lite` | current Flash-Lite | Cheapest current API/Gemini CLI profile |
| `gemini-3.1-pro-preview` | current Pro | Experimental quality comparison only |

Antigravity CLI exposes Gemini 3.7 Flash but not Flash-Lite. Production pipeline routing uses
Gemini 3.7 Flash with low effort for every task to preserve the constrained free-tier quota.
Higher effort levels belong in explicit experiments, not in the default pipeline.

### Codex

| Model | Role | API input/output per MTok | Notes |
|-------|------|---------------------------|-------|
| `gpt-5.6-luna` | high-volume | $0.20 / $1.20 | Classification and constrained layout cleanup |
| `gpt-5.6-terra` | balanced | $2.00 / $12.00 | Enrichment, deduplication, and digest generation |
| `gpt-5.6-sol` | flagship | $4.00 / $20.00 | Global section merge and watchdog quality profile |

All pipeline defaults preserve `model_reasoning_effort=low`; model tier, rather than uniformly
higher reasoning effort, supplies the required quality difference between stages.

### Claude

| Model | Type | API input/output per MTok | Notes |
|-------|------|---------------------------|-------|
| `claude-haiku-4-5-20251001` / `haiku` | fast | $1.00 / $5.00 | Default for cost-sensitive pipeline stages |
| `claude-sonnet-5` | balanced | $2.00 / $10.00 | Global section merge |
| `claude-opus-5` | quality | $5.00 / $25.00 | Watchdog and explicit quality experiments only |

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

### Antigravity

```
agy {model} --dangerously-skip-permissions --output-format json -p "Read your task from {prompt_file} and execute it."
```

- `-p` must come last: agy takes the token right after `-p` as the prompt.
- agy's internal log is redirected to the task's stderr log, so quota and auth errors land where error detection looks.
- `--output-format json` wraps the answer in an envelope with `response`, `error` and `usage`. The pipeline unwraps it: `response` becomes the captured stdout the parsers read, and `error` is appended to the stderr log.

Token usage: the envelope's input, output, thinking, cache-read and total tokens are saved per task. Measured 2026-10-05 with `gemini-3.7-flash --effort low`: a "Reply OK" launch used 12,921 input tokens, which is the per-launch agent overhead, and a 20-headline classify launch used 25,117 input and 2,245 output tokens.

## Configuration

The agent, the per-task model flags and the API-mode settings are user settings in
`<data_dir>/config.toml` (the `agent` key and the `[llm]` and `[api]` sections), with the
release defaults written there commented out. Agent API keys are secrets: they come only from
the environment and are stripped from agent subprocesses unless API mode needs them.

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

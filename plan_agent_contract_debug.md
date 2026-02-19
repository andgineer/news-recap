# Agent Contract Debug Plan

## Root Cause (Already Identified)

Default command templates for all real agents use only `{prompt}`:

```
codex exec ... --model {model} {prompt}
claude -p --model {model} ... -- {prompt}
gemini --model {model} ... --prompt {prompt}
```

The agent receives only the prompt **text** — it has no idea:
1. Where to write `agent_result.json` (the output path)
2. What JSON schema is required (`AgentOutputContract`)
3. Where to find `articles_index.json`

The benchmark agent works because it uses `{task_manifest}` and reads the manifest
to discover all paths. Real agents get none of that context.

The fix direction: inject contract context into the prompt (path + schema) **or**
switch real agents to manifest-native mode via `{task_manifest}` + file read.

---

## Pre-Flight: Read a Real Failed Workdir

Before any isolated runs, find a real failed task workdir (not benchmark) and inspect:

```bash
# Find the most recent real failed task workdir
news-recap llm stats
# or query directly:
sqlite3 .news_recap.db \
  "SELECT task_id, task_type, failure_class, error_summary
   FROM llm_tasks
   WHERE failure_class IS NOT NULL
     AND task_id NOT IN (SELECT task_id FROM llm_tasks WHERE task_type LIKE '%benchmark%')
   ORDER BY created_at DESC LIMIT 5;"

# Then inspect:
cat .news_recap_workdir/<task_id>/input/task_prompt.txt
cat .news_recap_workdir/<task_id>/output/agent_stdout.log
cat .news_recap_workdir/<task_id>/output/agent_stderr.log
# Check if agent_result.json was written:
ls .news_recap_workdir/<task_id>/output/
```

**Expected finding:** prompt contains no mention of output file path or JSON schema;
stdout contains plain-text prose.

---

## Isolated Debug Scaffold

Each isolated run uses a minimal workdir created by hand — no DB, no worker, no queue.
This lets us iterate on prompt/command without the full stack.

### Scaffold setup (run once)

```bash
mkdir -p /tmp/agent-debug/input /tmp/agent-debug/output /tmp/agent-debug/meta

# Minimal articles index (2 articles)
cat > /tmp/agent-debug/input/articles_index.json << 'EOF'
{
  "articles": [
    {
      "source_id": "article:test-001",
      "title": "OpenAI releases new model",
      "url": "https://example.com/openai-new-model",
      "source": "TechCrunch",
      "published_at": "2026-02-19T10:00:00+00:00"
    },
    {
      "source_id": "article:test-002",
      "title": "Google updates search algorithm",
      "url": "https://example.com/google-search-update",
      "source": "The Verge",
      "published_at": "2026-02-19T09:00:00+00:00"
    }
  ]
}
EOF

# Task manifest
cat > /tmp/agent-debug/meta/task_manifest.json << 'EOF'
{
  "contract_version": 2,
  "task_id": "debug-test-001",
  "task_type": "highlights",
  "workdir": "/tmp/agent-debug",
  "task_input_path": "/tmp/agent-debug/input/task_input.json",
  "articles_index_path": "/tmp/agent-debug/input/articles_index.json",
  "output_result_path": "/tmp/agent-debug/output/agent_result.json",
  "output_stdout_path": "/tmp/agent-debug/output/agent_stdout.log",
  "output_stderr_path": "/tmp/agent-debug/output/agent_stderr.log"
}
EOF
```

### Output validation helper

```bash
# After each agent run, validate the result:
python3 - << 'EOF'
import json, sys
path = "/tmp/agent-debug/output/agent_result.json"
try:
    data = json.loads(open(path).read())
    blocks = data.get("blocks", [])
    print(f"OK: {len(blocks)} block(s)")
    for i, b in enumerate(blocks):
        print(f"  block[{i}]: {len(b.get('text',''))} chars, source_ids={b.get('source_ids')}")
except FileNotFoundError:
    print("FAIL: agent_result.json not written")
except json.JSONDecodeError as e:
    print(f"FAIL: invalid JSON: {e}")
    print(open(path).read()[:500])
EOF
```

---

## Phase 1: Codex

### 1-A. Baseline — current command template, no contract context

Goal: confirm the bug is reproduced in isolation.

```bash
rm -f /tmp/agent-debug/output/agent_result.json

PROMPT="Write highlights for today's tech news."

codex exec \
  --sandbox workspace-write \
  -c sandbox_workspace_write.network_access=true \
  -c model_reasoning_effort=high \
  --model gpt-5-codex-mini \
  "$PROMPT"
```

Expected: plain text to stdout, no `agent_result.json`. Confirms root cause.

### 1-B. Prompt with embedded schema + explicit output path

Goal: test if codex follows instructions when the schema and file path are in the prompt.

```bash
rm -f /tmp/agent-debug/output/agent_result.json

PROMPT='You are a news highlights agent.

Articles available (source_ids for citations):
- article:test-001 — "OpenAI releases new model" (TechCrunch)
- article:test-002 — "Google updates search algorithm" (The Verge)

Task: Write 2 highlight bullets for today'"'"'s tech news.

Output MUST be written as JSON to this exact file path:
  /tmp/agent-debug/output/agent_result.json

Required JSON schema:
{
  "blocks": [
    {
      "text": "<highlight text>",
      "source_ids": ["article:test-001"]
    }
  ],
  "metadata": {}
}

Rules:
- Each block.source_ids must only contain IDs from the articles list above.
- Do not write anything to stdout. Write ONLY the JSON file.
- The file must be valid JSON when complete.'

codex exec \
  --sandbox workspace-write \
  -c sandbox_workspace_write.network_access=true \
  -c model_reasoning_effort=high \
  --model gpt-5-codex-mini \
  "$PROMPT"
```

Then validate. Record: did agent write the file? Is schema correct? Are source_ids valid?

### 1-C. Manifest-native: pass `{task_manifest}` path, agent reads context itself

Goal: test if codex can read the manifest and discover paths autonomously.

```bash
rm -f /tmp/agent-debug/output/agent_result.json

MANIFEST=/tmp/agent-debug/meta/task_manifest.json

PROMPT="You are a news highlights agent. Your task manifest is at: $MANIFEST

Steps:
1. Read the manifest JSON at that path.
2. Read articles_index_path from the manifest — this lists available articles with their source_ids.
3. Write highlight bullets (one block per highlight) to output_result_path from the manifest.
4. The output file must follow this JSON schema exactly:
   {\"blocks\": [{\"text\": \"<text>\", \"source_ids\": [\"<id>\"]}], \"metadata\": {}}
5. source_ids in each block must only contain IDs from articles_index.

Do not print anything. Write only the output file."

codex exec \
  --sandbox workspace-write \
  -c sandbox_workspace_write.network_access=true \
  -c model_reasoning_effort=high \
  --model gpt-5-codex-mini \
  "$PROMPT"
```

Validate. This is the preferred approach — it mirrors how the benchmark agent works.

### 1-D. Codex integration test (full stack)

Once one of 1-B or 1-C produces a valid `agent_result.json` in isolation, update
the command template in env and run through the real worker:

```bash
# If 1-C wins (manifest-native):
export NEWS_RECAP_LLM_CODEX_COMMAND_TEMPLATE=\
"codex exec --sandbox workspace-write \
  -c sandbox_workspace_write.network_access=true \
  -c model_reasoning_effort=high \
  --model {model} {prompt}"
# Note: prompt here would need to include manifest path — see implementation note below.

news-recap llm enqueue --task-type highlights
news-recap llm worker --max-tasks 1
news-recap llm stats
```

Check: `failure_class` is null, `agent_result.json` exists with valid blocks.

---

## Phase 2: Claude

Repeat after Codex is confirmed working.

### 2-A. Baseline

```bash
rm -f /tmp/agent-debug/output/agent_result.json

PROMPT="Write highlights for today's tech news."

claude -p \
  --model sonnet \
  --permission-mode dontAsk \
  --allowed-tools "Read,Write,Edit,WebFetch,Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" \
  -- "$PROMPT"
```

### 2-B. Prompt with embedded schema + explicit output path

Same prompt structure as 1-B but sent to `claude`. Note: claude has `Read` and `Write`
tools available in the default template — it should be capable of file I/O.

```bash
rm -f /tmp/agent-debug/output/agent_result.json

PROMPT='... (same as 1-B prompt above) ...'

claude -p \
  --model sonnet \
  --permission-mode dontAsk \
  --allowed-tools "Read,Write,Edit,WebFetch,Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" \
  -- "$PROMPT"
```

### 2-C. Manifest-native

Same as 1-C but sent to `claude`. Claude's `Read` tool makes this a natural fit:
it can `Read` the manifest and articles index, then `Write` the output file.

```bash
rm -f /tmp/agent-debug/output/agent_result.json

MANIFEST=/tmp/agent-debug/meta/task_manifest.json
PROMPT="... (same as 1-C prompt above) ..."

claude -p \
  --model sonnet \
  --permission-mode dontAsk \
  --allowed-tools "Read,Write,Edit,WebFetch,Bash(curl:*),Bash(cat:*),Bash(shasum:*),Bash(pwd:*),Bash(ls:*)" \
  -- "$PROMPT"
```

### 2-D. Claude integration test

```bash
export NEWS_RECAP_LLM_DEFAULT_AGENT=claude
news-recap llm enqueue --task-type highlights
news-recap llm worker --max-tasks 1
news-recap llm stats
```

---

## Phase 3: Gemini

Repeat after Claude is confirmed working.

### 3-A. Baseline

```bash
rm -f /tmp/agent-debug/output/agent_result.json

gemini --model gemini-2.5-flash \
  --approval-mode auto_edit \
  --prompt "Write highlights for today's tech news."
```

Note: gemini's `--approval-mode auto_edit` — clarify whether it supports file writes
or only stdout. This is a key unknown: gemini CLI may require a different tool-access
flag equivalent to claude's `--allowed-tools`.

### 3-B. Prompt with schema + path

```bash
rm -f /tmp/agent-debug/output/agent_result.json

PROMPT='... (same as 1-B prompt) ...'

gemini --model gemini-2.5-flash --approval-mode auto_edit --prompt "$PROMPT"
```

### 3-C. Manifest-native (if gemini supports file I/O)

```bash
rm -f /tmp/agent-debug/output/agent_result.json

MANIFEST=/tmp/agent-debug/meta/task_manifest.json
PROMPT="... (same as 1-C prompt) ..."

gemini --model gemini-2.5-flash --approval-mode auto_edit --prompt "$PROMPT"
```

If gemini cannot write files, fallback approach: stdout-parser mode must be
marked explicit in the command template config (not a hidden fallback).

### 3-D. Gemini integration test

```bash
export NEWS_RECAP_LLM_DEFAULT_AGENT=gemini
news-recap llm enqueue --task-type highlights
news-recap llm worker --max-tasks 1
news-recap llm stats
```

---

## Decision Matrix

After isolated runs, fill this in:

| Agent  | Can write file? | Responds to schema in prompt? | Reads manifest? | Recommended mode     |
|--------|----------------|-------------------------------|-----------------|----------------------|
| Codex  | ?              | ?                             | ?               | manifest-native / embedded-schema |
| Claude | likely yes     | ?                             | likely yes      | manifest-native      |
| Gemini | ?              | ?                             | ?               | stdout-parser / manifest-native |

---

## Implementation Note: Command Template Refactor

Once the winning approach per agent is confirmed, the command template changes will be:

**Option A — embedded schema in prompt** (prompt is self-contained):
- Command template stays as `... {prompt}`
- The `intelligence.py` / `OrchestratorService` builds a prompt that embeds
  the output path, schema, and articles inline.
- Pro: no manifest reading by agent. Con: large prompt, articles repeated.

**Option B — manifest-native** (preferred):
- Command template includes `{task_manifest}`: `... {prompt_file}`
  where `prompt_file` contains only the instruction to read the manifest.
- Or: a tiny wrapper script reads the manifest and builds the final prompt.
- Pro: clean separation, articles_index read by agent at runtime. Con: requires
  agent to be capable of reading files.

The benchmark_agent is already Option B. The goal is to make real agents match it.

---

## Success Criteria

Each phase is complete when:

1. **Isolated**: `agent_result.json` written with valid schema, `blocks` non-empty,
   all `source_ids` in the allowed set.
2. **Integration**: worker reports `succeeded`, `failure_class` is null, DB has
   `user_output` record with content.
3. **Semantic check**: output is meaningful (highlights/stories/qa), not "I don't
   know what to do" or similar refusal text.

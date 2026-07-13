# Plan: Secure CLI Agent Execution

Status: proposed. Companion plan: `plan-token-optimization.md` (Phase 1 there removes
most of the attack surface for the `claude` agent and should land first).

## Threat model

The recap pipeline embeds **untrusted text** into agent prompts:

- RSS headlines (classify, dedup, oneshot_digest) — controlled by any feed publisher.
- Full extracted page text, up to 5 000 chars per article (enrich) — controlled by any
  website an article links to.

A malicious article can carry instructions for the LLM ("ignore the task, run X").
Prompt-level defenses ("Do NOT make network requests" in `prompts.py`) are requests,
not controls. What matters is what the agent process is *able* to do when hijacked.

Current default command templates (`config.py`):

| Agent | Template risk |
|---|---|
| `antigravity` | `--dangerously-skip-permissions` — arbitrary command execution |
| `claude` | `--permission-mode dontAsk` + unrestricted `Read` + `Bash(curl:*)` + `WebFetch` — read any host file (`~/.ssh`, `~/.aws`, `.env`) and exfiltrate it |
| `codex` | `--sandbox workspace-write` with `sandbox_workspace_write.network_access=true` — network egress from inside the sandbox |

Additional exposure independent of templates:

- `ai_agent.py:_run_agent_cli` passes `env = os.environ.copy()` to the subprocess —
  every secret in the operator's shell is visible to the agent.
- `spec/agents.md` documents an even wider template (`bypassPermissions`, `Write,Edit`)
  than the code ships — the spec must be brought in line as part of this plan.

Assets to protect, in priority order:

1. Host filesystem secrets (`~/.ssh`, `~/.aws`, browser profiles, other projects).
2. Host environment variables.
3. The agents' own subscription auth tokens (`~/.claude`, `~/.codex`, `~/.gemini`).
4. Integrity of pipeline output (digest text) — lowest priority; a poisoned digest is
   visible and recoverable, a stolen SSH key is not.

Constraint: the CLI backend is the primary execution path (subscription billing), so
agents must keep (a) access to their auth state and (b) network access to their own
API endpoint. Full network cut-off is not possible; the design goal is to shrink the
blast radius of a hijacked agent to "the task's own files + the agent's own token".

## Verified facts (research done 2026-07-13)

- `claude` CLI supports `--tools ""` (disables ALL built-in tools — no tool schemas
  in context) and accepts the prompt on **stdin** in `-p` mode. Verified live: a
  classify-style task ran correctly with `--tools ""` and stdin delivery. With no
  tools, a hijacked claude agent cannot touch the filesystem or network at all —
  the model can only emit text.
- `claude --bare` is **not** usable for subscription users: bare mode reads auth
  strictly from `ANTHROPIC_API_KEY` (OAuth/keychain never read). Use
  `--tools "" --system-prompt … --setting-sources ""` instead.
- Docker 29.x semantics assumed below; foreground `docker run` proxies SIGTERM to
  the container (default `--sig-proxy`), `--init` makes PID 1 handle it.
- The pipeline's own code already isolates well at the launch site:
  `_run_agent_cli` copies the prompt into a fresh `TemporaryDirectory` and runs the
  agent with `cwd=tmp` (`ai_agent.py:340-349`) — a single, clean mount point for a
  container.

## Phase 0 — Template and environment hardening (no Docker, ~1 day)

Cheap, immediate, and independent of containerization. Do these regardless.

1. **claude: drop all tools.** The pipeline tasks are text→text; resource fetching is
   done by the pipeline (`ResourceLoader`), not the agent. Change the default
   template to stdin delivery with `--tools ""` (see token plan Phase 1 for the
   exact template — the same change serves both goals). If file-based delivery must
   be kept for some reason, the minimum is: remove `Bash(curl:*)`, `Bash(cat:*)`,
   `WebFetch` from `--allowed-tools`, keeping only `Read`.
2. **codex: close sandbox network.** Remove
   `-c sandbox_workspace_write.network_access=true`. The codex CLI talks to the
   OpenAI API from outside its workspace sandbox; in-sandbox network is only needed
   if the *task* fetches URLs — ours don't. Verify with one probe run; if codex
   cannot reach its API without the flag, keep the flag and rely on Phase 1/2.
3. **antigravity: remove `--dangerously-skip-permissions`.** Probe which permission
   flags `agy` needs for non-interactive text-only output (`--help` audit +. one
   probe run). If it cannot run non-interactively without the flag, mark antigravity
   as **container-only** (refuse to launch it outside Docker once Phase 1 lands, with
   a clear error).
4. **Environment allowlist.** In `_run_agent_cli`, replace `os.environ.copy()` with
   an explicit allowlist builder:
   - always: `PATH`, `HOME`, `LANG`, `LC_ALL`, `TERM`, `TMPDIR`
   - per agent: its auth/config vars (`agent_api_key_vars` when `use_api_key=True`)
   - pipeline vars already set explicitly (`NEWS_RECAP_*`, `MAX_THINKING_TOKENS`, …)
   - plus `routing.extra_env`
   Add a `NEWS_RECAP_AGENT_ENV_PASSTHROUGH` env var (CSV) as an escape hatch for
   users whose CLIs need extra vars (proxies etc.).
5. **Update `spec/agents.md`** to match the shipped templates (it currently documents
   `bypassPermissions` and `Write,Edit`, which the code no longer uses).
6. **Tests:**
   - unit: env builder never passes a var not on the allowlist
     (seed `os.environ["FAKE_SECRET"]`, assert absent).
   - unit: rendered default templates contain no `curl`, `WebFetch`,
     `dangerously-skip-permissions`.

Residual risk after Phase 0: codex/antigravity still run as host processes with the
whole home directory readable. Phase 1 addresses that.

## Phase 1 — Docker sandbox (~2–3 days)

Run each agent invocation in a hardened, throwaway container. This is the primary
mitigation for agents that need tools/filesystem (codex, antigravity) and defense in
depth for claude.

### 1.1 Image

One image, all CLIs (they are all node-based), non-root user:

```dockerfile
FROM node:22-slim
RUN npm install -g @anthropic-ai/claude-code @openai/codex <agy-package> \
    && useradd -m -u 1000 agent
USER agent
WORKDIR /work
```

Build via `scripts/agent-sandbox-build.sh`; tag `news-recap-agent:latest`.
(If the agy package is not on npm, install per vendor instructions; keep one image —
per-agent images add maintenance without security benefit.)

### 1.2 Auth state in named volumes — never bind-mount host dotfiles

```bash
docker volume create news-recap-claude-auth   # -> /home/agent/.claude
docker volume create news-recap-codex-auth    # -> /home/agent/.codex
docker volume create news-recap-agy-auth      # -> /home/agent/.gemini (verify path)
```

One-time interactive login per agent:

```bash
docker run -it --rm -v news-recap-claude-auth:/home/agent/.claude \
  news-recap-agent claude login
```

Rationale: CLIs *write* to their config dirs (token refresh, locks), so read-only
bind mounts of host `~/.claude` break; read-write bind mounts expose host creds and
let a hijacked agent tamper with host CLI config. Named volumes keep subscription
auth working, persistent, and completely separate from the host account state.

### 1.3 Launcher script `scripts/agent-sandbox.sh`

Interface kept template-compatible so `build_run_args`, timeouts, and stdout capture
in `ai_agent.py` need **no changes**:

```
agent-sandbox.sh <agent> <prompt_file_host_path> <agent-args...>
```

The script:

1. Maps `dirname(prompt_file)`'s parent (the per-run temp dir) to `/work` read-write.
2. Picks the auth volume for `<agent>`.
3. Rewrites the prompt-file path to `/work/input/task_prompt.txt`.
4. Executes:

```bash
exec docker run --rm --init \
  --name "news-recap-agent-$$-$RANDOM" \
  --read-only --tmpfs /tmp:size=64m \
  --cap-drop=ALL --security-opt no-new-privileges \
  --pids-limit 256 --memory 2g --cpus 2 \
  --user 1000:1000 \
  -v "$auth_volume:/home/agent/$auth_dir" \
  -v "$workdir:/work" \
  -e HOME=/home/agent -e NEWS_RECAP_REPAIR_MODE=0 \
  $EXTRA_ENV_FLAGS \
  news-recap-agent "$agent" "${agent_args[@]}"
```

Notes:

- `docker run -e` flags implement the env allowlist for free — the container sees
  only what the script passes (Phase 0 item 4 still applies to non-container runs).
- Foreground run + `--init` + default sig-proxy means the existing
  `run_subprocess._terminate_process` (SIGTERM → wait → SIGKILL) works unchanged for
  the happy path. Because SIGKILL on the docker *client* orphans the container, the
  script also installs a `trap` that `docker rm -f`s by `--name`, and the pipeline's
  timeout path (SIGTERM first) is the normal case.
- stdin passthrough: `docker run -i` when the claude stdin-delivery template is used.

### 1.4 Template integration

Default templates become (opt-in via `NEWS_RECAP_AGENT_SANDBOX=1`, then flipped to
default once burned in):

```
agent-sandbox.sh codex {prompt_file} exec --sandbox workspace-write {model} "Read your task from /work/input/task_prompt.txt and execute it."
agent-sandbox.sh agy   {prompt_file} {model} -p "Read your task from /work/input/task_prompt.txt and execute it."
```

(claude uses the stdin thin-client template from the token plan; wrapping it in the
sandbox as well is optional hardening since it has no tools.)

Implementation detail: `build_run_args` validates placeholders — `agent-sandbox.sh`
consumes `{prompt_file}` as `$2`, so existing validation (`prompt_file` required)
still holds. Inside the container the agent-visible path is fixed (`/work/...`), so
the awkward host-path quoting issues disappear.

### 1.5 What Docker does and does not give

Closed: host filesystem, host env, host processes, resource exhaustion (memory/pids
caps). Still open: **network egress** (agent must reach its API — an injected prompt
can still POST data to an attacker host) and the agent's own auth token (inside the
container by necessity). Phase 2 closes the first; the second is irreducible — a
hijacked agent can always burn/leak its own subscription token, which is revocable
and low-value compared to host secrets.

### 1.6 Tests / acceptance

- Canary test (integration, requires docker): place `~/canary.txt` on the host,
  feed a task whose "article text" instructs the agent to read and print it; assert
  the file content never appears in stdout/stderr and the task otherwise completes
  or fails cleanly.
- Env test: export `FAKE_SECRET=x` in the parent; assert a task instructed to
  `echo $FAKE_SECRET` cannot produce `x`.
- Lifecycle test: task with 5 s timeout and a stalling agent → container is gone
  (`docker ps` empty) after the pipeline returns.
- These run behind `NEWS_RECAP_RUN_SANDBOX_TESTS=1` (same pattern as stress tests).

## Phase 2 — Egress allowlist (optional, ~1 day)

Closes arbitrary exfiltration for the tool-using agents:

1. `docker network create --internal news-recap-agents` for agent containers.
2. A proxy sidecar (tinyproxy or squid) attached to both the internal network and
   the default bridge, with a domain allowlist: `api.anthropic.com`,
   `chatgpt.com`/`api.openai.com`, antigravity endpoints (probe exact hosts with
   `agy` + proxy logs before finalizing).
3. `HTTP(S)_PROXY` env in the agent container; all three CLIs honor proxy vars.
4. Compose file `scripts/agent-sandbox-compose.yml` to manage proxy lifecycle;
   `agent-sandbox.sh` gains `--network news-recap-agents` + proxy env when the
   compose stack is up.

After Phase 2 the only remaining exfiltration channel is *through the LLM API
itself* (the model echoing data into a response the attacker can't read, or the
provider account) — accepted as irreducible.

## Rollout order

1. Phase 0 (immediately; also unblocks token plan Phase 1).
2. Phase 1 behind `NEWS_RECAP_AGENT_SANDBOX=1`; run daily pipeline both ways for a
   few days; compare failure rates.
3. Flip sandbox to default; antigravity becomes container-only.
4. Phase 2 when convenient.

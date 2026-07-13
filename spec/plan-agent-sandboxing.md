# Plan: Secure CLI Agent Execution

Status: proposed. Companion plan: `plan-token-optimization.md` (its Phase 1 turns the
`claude` agent into a tool-less thin client — the same `--tools ""` change serves both
plans and should land first).

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
| `antigravity` | `--dangerously-skip-permissions` — arbitrary command execution, no isolation |
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

Constraint: the CLI backend is the primary execution path (subscription billing; the
API backend is experiment-only), so agents must keep (a) access to their auth state and
(b) network access to their own API endpoint. Full network cut-off is not possible; the
design goal is to shrink the blast radius of a hijacked agent to "the task's own files +
the agent's own token".

## Design decision: no Docker, per-agent isolation instead

The CLI backend is mandatory, and a container and a lighter sandbox run the *same* CLI
on the *same* subscription — so containerization has to earn its weight on security
alone. Per agent it does not:

- **claude** — with `--tools ""` (Phase 0) it has no tools at all; it can only emit text
  on stdout. There is nothing to isolate. A container adds nothing.
- **codex** — ships its own OS-level sandbox (`--sandbox workspace-write`: Apple Seatbelt
  on macOS, Landlock + seccomp on Linux) that already confines *writes* to the workspace.
  Phase 0 closes its in-sandbox network. A container would duplicate protection codex
  already enforces itself.
- **antigravity** — the only agent with no built-in isolation
  (`--dangerously-skip-permissions`). This is the one that needs a real sandbox, and
  `bubblewrap` gives the same kernel primitive (mount / PID namespaces) as a container
  without the Docker tax.

Concurrency makes the choice sharper. Pipeline phases run sequentially and each phase
uses one agent, so the peak number of concurrent sandboxes equals that agent's
`agent_max_parallel` (`codex: 3, claude: 2, antigravity: 1`). Since only antigravity is
sandboxed, **at most one sandbox ever runs at a time** — the "many parallel containers"
cost vanishes by construction.

What Docker would have cost here, and what this avoids:

- A **reaper** for orphaned containers — unavoidable with Docker because
  `_terminate_process` (`subprocess.py:309`) sends SIGTERM, waits **2 s**, then SIGKILL;
  a mid-inference CLI rarely exits in 2 s, so the docker client is usually SIGKILLed and
  the container is orphaned on nearly every timeout. `bubblewrap --die-with-parent`
  removes this entirely.
- Named auth **volumes** + a one-time interactive login *inside a container* per agent,
  UID/chown matching, tmpfs sizing, and a compose stack for the egress proxy.
- A hard dependency on a running **Docker daemon** on every host — this is a local CLI
  tool that also runs on dev laptops and CI.

## Verified facts (research done 2026-07-13)

- **Output is always stdout, never an agent-written file.** Every parser reads
  `output/agent_stdout.log` through `read_agent_stdout` (`tasks/base.py:50`,
  used by classify/enrich/dedup/oneshot/merge/refine); the parent captures the child's
  stdout pipe in `run_subprocess`. No task reads an agent-written `agent_result.json`
  (the "write JSON to `output_result_path`" contract in `spec/agents.md` is stale). So
  removing an agent's write ability (claude `--tools ""`, or a read-only sandbox) cannot
  break output delivery — the agent never needed to write the result.
- `claude` CLI supports `--tools ""` (disables ALL built-in tools — no tool schemas in
  context) and accepts the prompt on **stdin** in `-p` mode. Verified live: a
  classify-style task ran correctly with `--tools ""` and stdin delivery. With no tools a
  hijacked claude agent cannot touch the filesystem or network at all — the model can
  only emit text.
- `claude --bare` is **not** usable for subscription users: bare mode reads auth strictly
  from `ANTHROPIC_API_KEY` (OAuth/keychain never read). Use
  `--tools "" --system-prompt … --setting-sources ""` instead — this keeps subscription
  auth.
- `codex --sandbox workspace-write` confines **writes** to the workspace + temp via the
  OS sandbox, but does **not** block reads outside the workspace by default, so a hijacked
  codex can still *read* host files. With in-sandbox network closed (Phase 0 item 2) there
  is no channel to exfiltrate what it reads except echoing into the digest (asset 4), so
  the residual is low-value. Verify codex still reaches its API with `network_access`
  removed (it talks to the API from outside the sandbox — expected to work).
- The prompt path substituted into templates is `{prompt_file}` =
  `manifest.workdir/input/task_prompt.txt` (`ai_agent.py:309`). For the antigravity
  wrapper the sandbox ro-binds that `input/` dir; results come back over stdout, not the
  filesystem.

## Phase 0 — Template and environment hardening (~1 day)

Cheap, immediate, and the foundation for everything below. Do these regardless.

1. **claude: drop all tools.** The pipeline tasks are text→text; resource fetching is
   done by the pipeline (`ResourceLoader`), not the agent. Change the default template to
   stdin delivery with `--tools ""` (see token plan Phase 1 for the exact template — the
   same change serves both goals). If file-based delivery must be kept for some reason,
   the minimum is: remove `Bash(curl:*)`, `Bash(cat:*)`, `WebFetch` from
   `--allowed-tools`, keeping only `Read`.
2. **codex: close sandbox network.** Remove
   `-c sandbox_workspace_write.network_access=true`. The codex CLI talks to the OpenAI API
   from outside its workspace sandbox; in-sandbox network is only needed if the *task*
   fetches URLs — ours don't. Verify with one probe run; if codex cannot reach its API
   without the flag, keep the flag and revisit egress in Phase 2.
3. **antigravity: remove `--dangerously-skip-permissions`.** Probe which permission flags
   `agy` needs for non-interactive text-only output (`--help` audit + one probe run). If
   it cannot run non-interactively without the flag, mark antigravity as **sandbox-only**
   (refuse to launch it outside the bubblewrap wrapper once Phase 1 lands, with a clear
   error).
4. **Environment allowlist.** In `_run_agent_cli`, replace `os.environ.copy()` with an
   explicit allowlist builder:
   - always: `PATH`, `HOME`, `LANG`, `LC_ALL`, `TERM`, `TMPDIR`
   - per agent: its auth/config vars (`agent_api_key_vars` when `use_api_key=True`)
   - pipeline vars already set explicitly (`NEWS_RECAP_*`, `MAX_THINKING_TOKENS`, …)
   - plus `routing.extra_env`
   Add a `NEWS_RECAP_AGENT_ENV_PASSTHROUGH` env var (CSV) as an escape hatch for users
   whose CLIs need extra vars (proxies etc.).
5. **Update `spec/agents.md`** to match the shipped templates (it currently documents
   `bypassPermissions` and `Write,Edit`, which the code no longer uses).
6. **Tests:**
   - unit: env builder never passes a var not on the allowlist (seed
     `os.environ["FAKE_SECRET"]`, assert absent).
   - unit: rendered default templates contain no `curl`, `WebFetch`,
     `dangerously-skip-permissions`.

Residual risk after Phase 0:

- **claude** — closed. No tools, no filesystem, no network.
- **codex** — writes confined by its own sandbox, in-sandbox network closed, host env
  stripped. Host-file *reads* remain possible but have no exfil channel (low-value,
  asset 4 only).
- **antigravity** — still a bare host process with the whole home directory readable and
  writable. Phase 1 addresses that.

## Phase 1 — Sandbox antigravity with bubblewrap (~1 day)

claude and codex need nothing here (see *Design decision*). Only antigravity is wrapped.

### 1.1 Wrapper `scripts/agy-sandbox.sh`

Interface kept template-compatible so `build_run_args`, timeouts, and stdout capture in
`ai_agent.py` need **no changes**: the wrapper takes the same args the template renders
and execs `agy` inside `bwrap`.

```bash
#!/usr/bin/env bash
set -euo pipefail
input_dir="$(dirname "$2")"          # {prompt_file} = <workdir>/input/task_prompt.txt
scratch="$(mktemp -d)"; trap 'rm -rf "$scratch"' EXIT

exec bwrap \
  --ro-bind /usr /usr --ro-bind /bin /bin --ro-bind /lib /lib --ro-bind /lib64 /lib64 \
  --ro-bind /etc/ssl /etc/ssl --ro-bind /etc/resolv.conf /etc/resolv.conf \
  --proc /proc --dev /dev --tmpfs /tmp \
  --ro-bind "$input_dir" /work/input \
  --bind "$HOME/.gemini" "$HOME/.gemini" \     # agy token refresh — writable, ONLY this
  --tmpfs "$HOME/.cache" \
  --bind "$scratch" /work/scratch \
  --unshare-all --share-net \                  # new pid/ipc/uts/mount ns; keep net for the API
  --die-with-parent --chdir /work \
  agy "${@:3}"
```

- `--die-with-parent` → the sandbox dies with the pipeline process. No orphans, no reaper,
  no lifecycle machinery — the whole ugliest part of the Docker approach is gone.
- Writable set is exactly: `~/.gemini` (token refresh), `~/.cache` (tmpfs), `/work/scratch`
  (tmpfs). Everything else is ro-bind or absent → a hijacked agy cannot touch `~/.ssh`,
  `~/.aws`, other projects, or the pipeline's `meta/`/`output/`.
- `--share-net` keeps network (agy must reach its own API). Egress is Phase 2.
- Runs as the same host user (no UID/chown dance, no named volumes, no separate login):
  agy already uses the operator's own `~/.gemini`; we simply expose *only* that path.

### 1.2 Sandbox-only enforcement

Once Phase 1 lands, refuse to launch `agy` outside the wrapper (clear error), mirroring
the "sandbox-only" intent from Phase 0 item 3. `bwrap` must be installed; a missing
binary is a hard failure, not a silent fallback to a bare `agy`.

### 1.3 Writable paths (burn-in)

Task output is stdout (captured by the parent), so the sandbox needs no writable workdir
for results. The agy CLI itself writes only its auth dir and a cache dir (granted above).
Confirm during burn-in that agy needs no other writable path; add a `--tmpfs`/`--bind` if
it does.

### 1.4 Tests / acceptance (behind `NEWS_RECAP_RUN_SANDBOX_TESTS=1`)

- **Canary**: place `~/canary.txt` on the host; feed an agy task whose "article text"
  instructs it to read and print the file; assert the content never appears in
  stdout/stderr.
- **Env**: export `FAKE_SECRET=x`; assert an agy task told to `echo $FAKE_SECRET` cannot
  produce `x` (covers Phase 0 allowlist + sandbox).
- **Write confinement**: agy task told to write `~/.ssh/probe` fails; the file never
  appears on the host.
- **Lifecycle**: agy task with a 5 s timeout and a stalling agent → after the pipeline
  returns, no `bwrap`/`agy` process is left (verifies `--die-with-parent`; no reaper
  needed).

## Phase 2 — Optional egress allowlist for antigravity (low priority)

antigravity must reach its own API, so its sandbox keeps network (`--share-net`); a
hijacked agy could still POST to an attacker host. Priority is **low**: Phase 0 stripped
host env vars and Phase 1 removed host filesystem access, so a hijacked agy has little
worth exfiltrating beyond its own low-value token.

Close it only if a concrete need appears: run the agy sandbox in its own network
namespace (`--unshare-net` + a slirp/proxy) behind a domain-allowlisted forward proxy
(tinyproxy/squid), and set `HTTP(S)_PROXY` in the sandbox env. Probe agy's real host set
first (API + auth-refresh + telemetry) or disable telemetry via env so the allowlist can
stay narrow — a too-tight allowlist fails the CLI, not just the exfil.

After Phase 2 the only remaining exfiltration channel is *through the LLM API itself* (the
model echoing data into a response the attacker can't read) — accepted as irreducible.

## Rollout order

1. Phase 0 immediately (also unblocks token plan Phase 1).
2. Phase 1 behind `NEWS_RECAP_AGENT_SANDBOX=1`; run antigravity both ways for a few days;
   compare failure rates. Then flip to default; agy becomes sandbox-only.
3. Phase 2 only if a concrete egress concern appears.

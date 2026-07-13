# Plan: Secure CLI Agent Execution

Status: proposed. **Target platform: macOS** — the pipeline runs on the operator's MacBook,
so the sandbox mechanism is Apple's native `sandbox-exec`/Seatbelt, **not** Linux
`bubblewrap` or Docker (see *Design decision*). Companion plan:
`plan-token-optimization.md` (its Phase 1 turns the `claude` agent into a tool-less thin
client). The `--tools ""` + stdin change serves both plans; to keep this plan
self-contained, Phase 0 here pulls in the small `run_subprocess` stdin plumbing itself
(Phase 0 item 1a) and coordinates with the token plan so the edit is not duplicated.

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

1. Host filesystem secrets (`~/.ssh`, `~/.aws`, browser profiles, other projects,
   macOS Keychain, `~/Library/Application Support`).
2. Host environment variables.
3. The agents' own subscription auth tokens (`~/.claude`, `~/.codex`, `~/.gemini`).
4. Integrity of pipeline output (digest text) — lowest priority; a poisoned digest is
   visible and recoverable, a stolen SSH key is not.

Constraint: the CLI backend is the primary execution path (subscription billing; the
API backend is experiment-only), so agents must keep (a) access to their auth state and
(b) network access to their own API endpoint. Full network cut-off is not possible; the
design goal is to shrink the blast radius of a hijacked agent to "the task's own files +
the agent's own token".

## Design decision: native macOS sandbox (`sandbox-exec`), no Docker, no bubblewrap

The CLI backend is mandatory, and a container and a lighter sandbox run the *same* CLI
on the *same* subscription — so isolation has to earn its weight on security alone. On
**macOS** the natural, zero-dependency primitive is Apple **Seatbelt** via
`sandbox-exec`, which is exactly the mechanism `codex` already uses for its own
`--sandbox workspace-write`. Per agent:

- **claude** — with `--tools ""` (Phase 0) it has no tools at all; it can only emit text
  on stdout. There is nothing to isolate. A sandbox adds nothing.
- **codex** — ships its own OS-level sandbox (`--sandbox workspace-write` → Apple Seatbelt
  on macOS) that already confines *writes* to the workspace. Phase 0 closes its in-sandbox
  network. Wrapping it again would duplicate protection codex already enforces itself.
- **antigravity** — the only agent with no built-in isolation
  (`--dangerously-skip-permissions`). This is the one that needs a real sandbox, and on
  macOS `sandbox-exec` with a Seatbelt profile gives kernel-enforced file/network
  confinement with no daemon and no VM.

Why `sandbox-exec` rather than `bubblewrap` or Docker on macOS:

- **`bubblewrap` does not exist on macOS.** It relies on Linux mount/PID namespaces;
  there is no port. It is off the table for this deployment.
- **Docker on macOS is a full Linux VM** (Docker Desktop / Colima). It is heavier than a
  daemon-on-Linux would be, *and* it changes the execution environment: agy would run
  under Linux with different auth paths, so the operator's real `~/.gemini` subscription
  state no longer applies. `sandbox-exec` keeps agy native, using the operator's own
  auth, and adds no daemon.
- **No path remapping.** Seatbelt does not build a new mount view; the filesystem is the
  host's, and the profile only *allows/denies* by path. This removes an entire class of
  wrapper bugs (a mount-remapped prompt path that no longer resolves) and makes
  file-based prompt delivery correct by construction.
- **No orphan/reaper problem.** `sandbox-exec` applies the profile and `exec`-replaces
  itself with `agy`, so the PID the pipeline spawns *is* the sandboxed agy. The existing
  `_terminate_process` (`subprocess.py:309`: SIGTERM → wait 2 s → SIGKILL) reaps it
  directly. With Docker, `_terminate_process` would SIGKILL the docker client and orphan
  the container on nearly every timeout; there is no such wrapper process here, so no
  reaper, no named auth volumes, no compose stack, no UID/chown dance.

Concurrency makes the choice sharper. Pipeline phases run sequentially and each phase
uses one agent, so the peak number of concurrent sandboxes equals that agent's
`agent_max_parallel`. Only antigravity is sandboxed and its default is
`agent_max_parallel["antigravity"] == 1` (`config.py:78`), so **at most one sandbox runs
at a time by default**. This is a property of the current config, not a structural
guarantee: raising that value would spawn N concurrent sandboxes. The Python-side wrapper
allocates a fresh per-invocation scratch/profile temp dir, so it stays correct either way.

Note: `sandbox-exec` is marked deprecated in its man page but remains the de-facto
CLI-level sandbox on macOS (Chromium, codex, and many tools rely on it) with no supported
public replacement. The Seatbelt allow-set needs burn-in on the real Mac (see Phase 1).

## Verified facts (research done 2026-07-13; sandbox-exec profile not yet burned in on Mac)

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
- `codex --sandbox workspace-write` confines **writes** to the workspace + temp via Apple
  Seatbelt, but does **not** block reads outside the workspace by default, so a hijacked
  codex can still *read* host files. With in-sandbox network closed (Phase 0 item 2) there
  is no channel to exfiltrate what it reads except echoing into the digest (asset 4), so
  the residual is low-value. Verify codex still reaches its API with `network_access`
  removed (it talks to the API from outside the sandbox — expected to work).
- The prompt path substituted into templates is `{prompt_file}` =
  `manifest.workdir/input/task_prompt.txt` (`ai_agent.py:309`). Under Seatbelt there is no
  mount view, so agy (if it reads the file) reads it at that same real path — the profile
  simply grants `file-read*` on `input/`. Results come back over stdout, not the
  filesystem.
- **Not yet verified (blocking probes — Phase 0/Phase 1):** (a) whether `agy` accepts the
  prompt on stdin; (b) whether `agy` can still read the prompt file non-interactively once
  `--dangerously-skip-permissions` is removed; (c) the exact Seatbelt allow-set agy needs
  on macOS (dyld shared cache, mach services, Keychain access for auth, cache-dir
  location). These decide prompt delivery and the profile — see the probe gate in
  Phase 1.

## Phase 0 — Template and environment hardening (~1–1.5 days)

Cheap, immediate, and the foundation for everything below. Do these regardless.

1. **claude: drop all tools, deliver prompt on stdin.** The pipeline tasks are
   text→text; resource fetching is done by the pipeline (`ResourceLoader`), not the
   agent. Change the default template to `--tools ""` with stdin delivery (see token plan
   Phase 1 for the exact flag set — same change, coordinate the edit).
   - **1a. `run_subprocess` stdin plumbing (pulled into this plan).** `run_subprocess`
     currently hardcodes `stdin=subprocess.DEVNULL` (`subprocess.py:200`); stdin delivery
     is impossible without changing it. Add an optional `stdin_path: Path | None`;
     `_run_agent_cli` passes the prompt file when the template is stdin-mode (a per-agent
     `prompt_delivery: "stdin" | "file"` flag, or the token plan's `{prompt_stdin}`
     pseudo-placeholder — pick one and share it with the token plan). This is the same
     edit token-plan Phase 1 item 2 needs; land it once.
   - If file-based delivery must be kept for claude for some reason, the minimum is:
     remove `Bash(curl:*)`, `Bash(cat:*)`, `WebFetch` from `--allowed-tools`, keeping only
     `Read`.
2. **codex: close sandbox network.** Remove
   `-c sandbox_workspace_write.network_access=true`. The codex CLI talks to the OpenAI API
   from outside its workspace sandbox; in-sandbox network is only needed if the *task*
   fetches URLs — ours don't. Verify with one probe run; if codex cannot reach its API
   without the flag, keep the flag and revisit egress in Phase 2.
3. **antigravity: remove `--dangerously-skip-permissions`.** Probe which permission flags
   `agy` needs for non-interactive text-only output (`--help` audit + one probe run), and
   in the same probe record **whether agy can still read the prompt file** without the
   flag (feeds the Phase 1 prompt-delivery gate). If it cannot run non-interactively
   without the flag, mark antigravity as **sandbox-only** (refuse to launch it outside the
   `sandbox-exec` wrapper once Phase 1 lands, with a clear error).
4. **Environment allowlist.** In `_run_agent_cli`, replace `os.environ.copy()` with an
   explicit allowlist builder:
   - always: `PATH`, `HOME`, `LANG`, `LC_ALL`, `TERM`, `TMPDIR`
   - per agent: its auth/config vars (`agent_api_key_vars` when `use_api_key=True`)
   - pipeline vars already set explicitly (`NEWS_RECAP_*`, `MAX_THINKING_TOKENS`, …)
   - plus `routing.extra_env`
   Add a `NEWS_RECAP_AGENT_ENV_PASSTHROUGH` env var (CSV) as an escape hatch for users
   whose CLIs need extra vars (proxies etc.).
5. **Update `spec/agents.md`** to match the shipped templates (it currently documents
   `bypassPermissions`, `Write,Edit`, and the stale `output_result_path` contract, which
   the code no longer uses). Coordinate with the token plan, which also edits `agents.md`.
6. **Tests:**
   - unit: env builder never passes a var not on the allowlist (seed
     `os.environ["FAKE_SECRET"]`, assert absent).
   - unit: rendered default templates contain no `curl`, `WebFetch`,
     `dangerously-skip-permissions`.
   - unit: `run_subprocess` feeds `stdin_path` to the child (echo mock agent round-trips
     the prompt from stdin).

Residual risk after Phase 0:

- **claude** — closed. No tools, no filesystem, no network.
- **codex** — writes confined by its own Seatbelt sandbox, in-sandbox network closed, host
  env stripped. Host-file *reads* remain possible but have no exfil channel (low-value,
  asset 4 only).
- **antigravity** — still a bare host process with the whole home directory readable and
  writable. Phase 1 addresses that.

## Phase 1 — Sandbox antigravity with `sandbox-exec` (Seatbelt) (~1.5–2 days)

claude and codex need nothing here (see *Design decision*). Only antigravity is wrapped.

### 1.1 Python-side wrapping in `_run_agent_cli` (no shell script)

The wrapping is done **in Python**, not in a `scripts/*.sh` wrapper, because the shell
approach breaks on the real template: `{model}` renders to a multi-token string
(`--model gemini-3.5-flash`) inserted raw, and `{prompt_file}` is embedded *inside* the
quoted `-p` argument — so positional shell parsing (`$2` = prompt file) does not match the
rendered args, and swapping the executable would change `command_head` away from `agy`,
silently disabling the `--log-file` injection and stderr handling that key off
`command_head == "agy"` (`ai_agent.py:319-322,354`). Doing it in Python avoids all of
that:

- `build_run_args` returns `(run_args, command_head)` with `command_head == "agy"`
  (`ai_agent.py:313`). Keep the existing `elif command_head == "agy":
  _inject_agy_log_file(...)` (line 321-322) untouched.
- **After** that injection and just before `run_subprocess`, when the agent is antigravity
  and the sandbox is enabled, render a Seatbelt profile to a file in the existing
  `tempfile.TemporaryDirectory` (auto-cleaned — no leaked scratch dir) and **prepend**
  `["sandbox-exec", "-f", <profile>, "-D", ...] ` to `run_args`.
- Because `command_head` was computed before the prepend, it stays `agy`: `--log-file`
  injection and `monitor_stderr == (command_head != "agy")` (line 354) keep their current
  behavior. `run_subprocess` itself needs **no** change.
- Exact paths are known in Python (`manifest.workdir`, `stderr_path`, `$HOME`), so the
  profile's allow-set is built from real values, not parsed out of a command string.

This is a deliberate, small change to `ai_agent.py` — the earlier "no changes to
ai_agent.py" assumption does not hold and is dropped.

### 1.2 Seatbelt profile (SBPL)

Rendered per task with `-D` parameters. Target shape (allow-set finalized in burn-in,
§1.4):

```scheme
(version 1)
(deny default)
(allow process-fork)
(allow process-exec* (literal (param "AGY_BIN")))

;; read-only system + the task's prompt input (real host path — no remap)
(allow file-read*
  (subpath "/usr") (subpath "/bin") (subpath "/System") (subpath "/Library")
  (subpath (param "INPUT_DIR")))

;; the only writable host paths
(allow file-read* file-write* (subpath (param "GEMINI_DIR")))   ; agy auth/token refresh
(allow file-read* file-write* (subpath (param "SCRATCH")))      ; cache / scratch (temp)
(allow file-write* (literal (param "LOG_FILE")))                ; agy --log-file target

;; agy must reach its own API; domain-level egress control is Phase 2
(allow network*)
```

- Everything not explicitly allowed — `~/.ssh`, `~/.aws`, browser profiles, Keychain
  items, `~/.claude`, `~/.codex`, other projects, and the pipeline's own `meta/`/`output/`
  — is denied by `(deny default)`, protecting assets 1-3.
- **`LOG_FILE` is included in the writable set** (this is the workdir `stderr_path` agy
  opens via `--log-file`; it is the pipeline's own file, not a secret). This resolves the
  otherwise-fatal conflict between the `--log-file` injection and a read-only workdir.
- `GEMINI_DIR` / `SCRATCH` / cache: on macOS agy's auth and cache locations must be probed
  (`~/.gemini` vs Keychain vs `~/Library/Application Support`; cache under
  `~/Library/Caches` not `~/.cache`). Whatever agy actually needs writable goes here and
  nowhere else.
- **Prompt delivery is decided by the Phase 0/§1.4 probe gate**, not assumed:
  - if agy accepts the prompt on **stdin** (preferred — narrower: agy needs no file-read
    of the prompt at all), drop the `INPUT_DIR` read grant and deliver via the Phase 0
    stdin plumbing;
  - else use **file delivery** with `(allow file-read* (subpath (param "INPUT_DIR")))`,
    which is correct under Seatbelt because there is no path remap.
  The probe is a **blocking gate**: the final wrapper design is not frozen until it runs
  on the Mac.

### 1.3 Sandbox-only enforcement

Once Phase 1 lands, refuse to launch `agy` outside the wrapper (clear error), mirroring
the "sandbox-only" intent from Phase 0 item 3. `sandbox-exec` must be present and the
platform must be macOS; a missing binary or non-Darwin host is a hard failure with a
clear message, not a silent fallback to a bare `agy`.

### 1.4 Burn-in (behind `NEWS_RECAP_RUN_SANDBOX_TESTS=1`, macOS only)

Seatbelt with `(deny default)` commonly needs extra grants to boot a real macOS binary
(dyld shared cache, `mach-lookup` for services agy uses, `com.apple.securityd`/Keychain
if auth lives there, DNS mach services for network). Burn-in fills the allow-set:

- Confirm agy starts, authenticates, reaches its API, and produces stdout under the
  profile. Add the minimal grants it demands (record each in `spec/agents.md`).
- Confirm the prompt-delivery choice (stdin vs file) end-to-end.
- Confirm agy needs no writable path beyond `GEMINI_DIR`/`SCRATCH`/`LOG_FILE`.
- **Fallback if `(deny default)` proves too fragile:** invert to `(allow default)` +
  `(deny file-write* (subpath "/"))` re-allowing the writable set + explicit
  `(deny file-read* file-write* …)` for the sensitive asset paths (`~/.ssh`, `~/.aws`,
  `~/.claude`, `~/.codex`, `~/Library/...`, other project dirs). Weaker (unlisted paths
  stay readable) but low-breakage; note the trade-off if taken.

### 1.5 Tests / acceptance (behind `NEWS_RECAP_RUN_SANDBOX_TESTS=1`, macOS only)

- **Canary**: place `~/canary.txt` on the host; feed an agy task whose "article text"
  instructs it to read and print the file; assert the content never appears in
  stdout/stderr.
- **Env**: export `FAKE_SECRET=x`; assert an agy task told to `echo $FAKE_SECRET` cannot
  produce `x` (covers Phase 0 allowlist + sandbox).
- **Write confinement**: agy task told to write `~/.ssh/probe` fails; the file never
  appears on the host.
- **Lifecycle**: agy task with a 5 s timeout and a stalling agent → after the pipeline
  returns, no `sandbox-exec`/`agy` process is left (verifies the exec-replace + existing
  `_terminate_process` reaping; no reaper needed).

## Phase 2 — Optional egress allowlist for antigravity (low priority)

antigravity must reach its own API, so its profile keeps `(allow network*)`; a hijacked
agy could still POST to an attacker host. Priority is **low**: Phase 0 stripped host env
vars and Phase 1 removed host filesystem access, so a hijacked agy has little worth
exfiltrating beyond its own low-value token.

Seatbelt cannot filter outbound network by **hostname** (only by socket/port/ip, and
remote-host filtering is limited), so a domain allowlist is enforced the same way it would
be under any sandbox: route agy through a local domain-allowlisting forward proxy
(tinyproxy/squid) by setting `HTTP(S)_PROXY` in the sandbox env, and tighten the profile
to `(deny network*)` + `(allow network-outbound (remote unix-socket …))` / the proxy's
local port only. Probe agy's real host set first (API + auth-refresh + telemetry) or
disable telemetry via env so the allowlist can stay narrow — a too-tight allowlist fails
the CLI, not just the exfil.

After Phase 2 the only remaining exfiltration channel is *through the LLM API itself* (the
model echoing data into a response the attacker can't read) — accepted as irreducible.

## Rollout order

1. Phase 0 immediately (also unblocks token plan Phase 1; shares the stdin plumbing).
2. Phase 1 behind `NEWS_RECAP_AGENT_SANDBOX=1`; run antigravity both ways on the Mac for a
   few days; compare failure rates and settle the Seatbelt allow-set. Then flip to
   default; agy becomes sandbox-only (macOS + `sandbox-exec` required).
3. Phase 2 only if a concrete egress concern appears.

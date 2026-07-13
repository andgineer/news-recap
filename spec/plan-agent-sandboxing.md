# Plan: Secure CLI Agent Execution

Status: proposed. **Target platform: macOS** — the pipeline runs on the operator's MacBook,
so the sandbox mechanism is Apple's native `sandbox-exec`/Seatbelt, **not** Linux
`bubblewrap` or Docker (see *Design decision*). Companion plan:
`plan-token-optimization.md` (its Phase 1 slims down the `claude` launch). Both plans
**retain the current file-based prompt delivery** (`{prompt_file}`) and stdout result
capture — see *Prompt delivery: file-based, not stdin* below.

## Prompt delivery: file-based, not stdin (experiment finding)

Experiments and upstream reports show the CLI agents do **not** handle stdin prompt
delivery reliably at the sizes this pipeline produces, so **file-based delivery is
retained for all agents** — the agent reads the prompt from `{prompt_file}` and the
result is captured from stdout, exactly as today. This plan does **not** switch any
agent to stdin, and `run_subprocess` keeps `stdin=subprocess.DEVNULL`.

- **claude** — `claude -p` in headless mode returns **empty output** once piped stdin
  exceeds a few kilobytes (anthropics/claude-code#7263: works at ~2.5 KB, empty at
  ~7 KB), while our enrich prompts reach `_MAX_BATCH_CHARS = 60_000`. Empty stdout is
  exactly the failure `run_ai_agent` raises on (`ai_agent.py:129-141`), so this would
  fail whole phases. Upstream guidance for large inputs is explicitly "write to a file
  and reference the path, don't pipe."
- **antigravity (`agy`)** — early `agy -p` versions **silently drop stdout** when run
  under a pipe / subprocess / redirect, which is exactly how the pipeline runs it.
- **codex** — `codex exec -` reads stdin, but `codex exec "<prompt>"` **hangs on EOF**
  when stdin is a non-TTY pipe with no writer (openai/codex#20919); file delivery avoids
  the whole class.

Consequence for this plan: keep `{prompt_file}`; do **not** add stdin plumbing to
`run_subprocess`; and since claude must keep a file-read tool to read the prompt, its
Phase 0 hardening is "restrict `--allowed-tools` to `Read`" rather than "no tools at
all". Under the operating threat model (no network exfiltration, no host writes; local
reads are not a prioritized asset) a read-only claude with no network/write tools still
satisfies the goals.

## Defense options without stdin (menu)

Dropping stdin removes exactly one lever: we can no longer starve claude of *all* tools
(it must keep `Read` to open `{prompt_file}`). Everything else is still on the table, and
none of it depends on how the prompt is delivered. The controls below are organized by the
three assets the operator cares about — **secrets**, **network egress**, and **host
writes** — and each is scored on *portability* (the pipeline also ships a
`scripts/linux_run.sh`, so macOS-only controls can't be the whole story), *cost*, and
*residual risk*. Phases 0–2 below already pick some of these; two levers (**minimal
`$HOME`** and a **uniform egress proxy**) are new and are folded into the phases in the
"Chosen stack" note at the end.

The root cause almost everything traces back to is one line:
`_run_agent_cli` does `env = os.environ.copy()` and passes the operator's **real
`$HOME`** (`ai_agent.py:329`). Two of the strongest, most portable controls come from
attacking that line directly, without any OS sandbox.

### A. Secrets (env vars + on-disk secrets: `~/.ssh`, `~/.aws`, Keychain, browser profiles)

| Option | Mechanism | Portable? | Cost | Residual |
|---|---|---|---|---|
| **A1. Env allowlist (default-deny)** | Replace `os.environ.copy()` with an explicit allowlist builder (`PATH`, `HOME`, `LANG`, `LC_ALL`, `TERM`, `TMPDIR`, the agent's own auth vars, `NEWS_RECAP_*`, `routing.extra_env`); CSV escape hatch `NEWS_RECAP_AGENT_ENV_PASSTHROUGH`. | ✅ any OS | ~2 h | Nothing in the shell env leaks; on-disk secrets untouched (see A2). |
| **A2. Minimal throwaway `$HOME`** ⟵ *new* | Point `HOME` at a fresh per-run temp dir and link **only** the agent's own auth dir into it (`~/.claude` / `~/.codex` / `~/.gemini`). The Node/Rust CLIs resolve `~` via `$HOME` (`os.homedir()` / `dirs::home_dir()`), so `~/.ssh`, `~/.aws`, other projects, and stray dotfiles simply **do not resolve** — no path rules, no Seatbelt. | ✅ any OS | ~0.5 day | (a) macOS **Keychain** is not under `$HOME`, so auth stored there is still reachable — needs A3/write-confinement to gate `com.apple.securityd`. (b) A tool that calls `getpwuid()` instead of reading `$HOME` sees the real home — Seatbelt (A3) closes that, `$HOME` alone doesn't. |
| **A3. Seatbelt read-deny of secret paths** | Even for claude/codex (which the plan leaves un-sandboxed), a tiny `sandbox-exec` profile that `(deny file-read* (subpath "~/.ssh") …)` for the known-sensitive set. Defense-in-depth for the "`Read` tool gets hijacked" case. | ❌ macOS only | ~0.5 day | Only denies the enumerated paths; unknown secret locations stay readable. Weaker than A2's "nothing but auth exists" model. |
| **A4. Separate low-priv macOS user** | Run agents as a dedicated unix account with no read access to the operator's home. | ❌ macOS/Unix | high (launchd/sudo, auth re-setup) | Strongest, but re-provisions all three agents' subscription auth under the new user — high friction. Overkill given A1+A2. |

### B. Network egress (exfiltration to attacker hosts)

Hard constraint: **every** CLI agent must reach *its own* API endpoint (subscription
billing), so a blanket `(deny network*)` is impossible. The goal is a *domain allowlist*,
and Seatbelt can only filter by socket/port/IP — not hostname — so the real control is a
proxy, not the sandbox.

| Option | Mechanism | Portable? | Cost | Residual |
|---|---|---|---|---|
| **B1. Strip the network *tools*** | claude → `--allowed-tools "Read"` (drop `WebFetch`, `Bash(curl:*)`); codex → remove `sandbox_workspace_write.network_access=true`. Removes the agent's *first-class* way to fetch a URL. | ✅ any OS | ~1 h | The agent's model can still emit an HTTP call if it has *any* shell/network primitive; codex/agy retain runtime network for their API. Tool-stripping is necessary but not sufficient. |
| **B2. Uniform allowlisting forward proxy** ⟵ *new / elevated* | Run one local `tinyproxy`/`squid` that only permits `api.anthropic.com`, `api.openai.com`, `*.googleapis.com` + the three auth-refresh hosts; inject `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY` into the agent env (all three CLIs honor them). Confines egress for **every** agent regardless of OS or sandbox. | ✅ any OS | ~1 day (proxy + host allowlist burn-in) | Exfil only possible *through the allowed APIs themselves* (model echoing data into a response the attacker can't read) — irreducible. A too-tight list breaks the CLI, so probe each agent's real host set first. |
| **B3. Seatbelt egress lockdown** | `(deny network*)` + allow only the proxy's local port (`(allow network-outbound (remote ip "localhost:8080"))`). Forces even a hijacked agy through B2's proxy. | ❌ macOS only | ~0.5 day | Belt-and-suspenders on top of B2; without B2 it can only pin to IPs (rotate constantly). |

The current plan scopes the proxy (B2/B3) to **antigravity only, Phase 2, low priority**.
Recommendation below is to *elevate B2 to all three agents* because it is the single
portable control that actually enforces the domain allowlist the prompt-level "do not make
network requests" text only *requests*.

### C. Host writes ("changes on the laptop")

| Option | Mechanism | Portable? | Cost | Residual |
|---|---|---|---|---|
| **C1. Strip the write *tools*** | claude → `Read` only (no `Write`/`Edit`/`Bash`); codex → keep its own `--sandbox workspace-write`, which already confines writes to the workspace + temp. | ✅ any OS | ~1 h | claude can't write at all; codex writes confined by its own Seatbelt. antigravity (`--dangerously-skip-permissions`) is unconfined → C2/C3. |
| **C2. Writes land in throwaway `$HOME` (A2 reuse)** ⟵ *new* | With `HOME` = per-run temp dir, an agent that "writes to `~/.config/...`" writes into the disposable dir that is deleted after the run — the real home is never touched. Free once A2 exists. | ✅ any OS | shares A2 | Absolute-path writes (`/etc`, other project dirs) still land on the host — needs C3. |
| **C3. Seatbelt write-confinement** | `(deny default)` + `(allow file-write* (subpath WORKDIR) (subpath SCRATCH) (subpath AUTH_DIR) (literal LOG_FILE))`. The plan applies this to **antigravity only**; the *option* is to apply the same profile to **all three** for uniform, mechanism-enforced write confinement. | ❌ macOS only | ~1.5–2 days (allow-set burn-in) | Mandatory for antigravity (no built-in isolation). For claude/codex it's redundant with C1/codex-sandbox — the "uniform vs targeted" trade-off is the real decision (see below). |

### Cross-cutting decision: targeted vs uniform sandbox

The plan deliberately sandboxes **only antigravity** (claude is read-only, codex
self-sandboxes). The alternative is one **uniform `sandbox-exec` profile wrapping all
three**: identical read/write/network rules for every agent, so posture doesn't depend on
each CLI's own honesty. Trade-off: uniform = more burn-in (three allow-sets instead of
one) and a hard macOS dependency for the whole pipeline; targeted = less work but relies on
claude's tool-restriction and codex's own sandbox holding. Given A2 (minimal `$HOME`) and
B2 (uniform proxy) already give portable, agent-independent coverage of secrets + egress +
home-writes, the **targeted** sandbox stays the right call — Seatbelt is then only the
macOS-native belt-and-suspenders for antigravity's absolute-path writes.

### Chosen stack (folds the two new levers into the phases below)

Layered so each control is independent and the weakest single failure still leaves two
others standing — none of it uses stdin:

1. **A1 env allowlist** — Phase 0 item 4 (already planned). Portable.
2. **A2 minimal `$HOME`** — *add to Phase 0.* Portable, ~0.5 day, and the single highest-leverage
   change: it neutralizes the secrets-read *and* home-write classes for **all three** agents
   at once, before any OS sandbox. This is the biggest thing the current plan is missing.
3. **B1/C1 tool + sandbox-flag stripping** — Phase 0 items 1–3 (already planned). Portable.
4. **B2 uniform egress proxy** — *promote from Phase 2 antigravity-only to a Phase 0/1 control
   for all three agents.* Portable; the only real enforcement of the domain allowlist.
5. **C3 Seatbelt write-confinement for antigravity** — Phase 1 (already planned). macOS-only
   belt-and-suspenders for the one agent with no built-in isolation.

Portable core (A1+A2+B1/C1+B2) protects the Linux launcher too; Seatbelt (A3/B3/C3) is the
macOS-only hardening on top. Residual after the stack is the irreducible one the plan
already names: data echoed *through the model's own allowed API response*.

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

- **claude** — Phase 0 restricts `--allowed-tools` to `Read` (needed to read the prompt
  file) and strips every network/write tool (`WebFetch`, `Bash(curl:*)`, …). It can read
  files and emit text, but has no way to reach the network or modify the host, so a
  hijacked claude can neither exfiltrate nor write. The only residual is host-file
  *reads* with no exfil channel — the same low-value residual as codex (asset 4), which
  does not justify a second sandbox under this threat model.
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
  restricting claude to `Read` (or a read-only sandbox for agy) cannot break output
  delivery — the agent never needed to write the result.
- `claude` CLI reads the prompt file via its `Read` tool (current template) and returns
  the result on stdout. Restricting `--allowed-tools` to `Read` removes every
  network/write tool, so a hijacked claude cannot reach the network or modify the host —
  it can only read files and emit text. (stdin delivery is **not** used: `claude -p`
  returns empty output on large piped stdin — see the *Prompt delivery* finding.)
- `claude --bare` is **not** usable for subscription users: bare mode reads auth strictly
  from `ANTHROPIC_API_KEY` (OAuth/keychain never read). Use
  `--allowed-tools "Read" --system-prompt … --setting-sources ""` instead — this keeps
  subscription auth and the file-based prompt read.
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
- **Not yet verified (blocking probes — Phase 0/Phase 1):** (a) whether `agy` can still
  read the prompt file non-interactively once `--dangerously-skip-permissions` is removed;
  (b) the exact Seatbelt allow-set agy needs on macOS (dyld shared cache, mach services,
  Keychain access for auth, cache-dir location). These decide the profile — see the probe
  gate in Phase 1.

## Phase 0 — Template and environment hardening (~1–1.5 days)

Cheap, immediate, and the foundation for everything below. Do these regardless.

1. **claude: restrict tools to `Read`, keep file delivery.** The pipeline tasks are
   text→text; resource fetching is done by the pipeline (`ResourceLoader`), not the
   agent, so the only tool claude needs is `Read` to read `{prompt_file}`. Change the
   default `--allowed-tools` from the current list to just `"Read"` — drop `WebFetch`,
   `Bash(curl:*)`, `Bash(cat:*)`, `Bash(shasum:*)`, `Bash(pwd:*)`, `Bash(ls:*)`. Keep
   `--permission-mode dontAsk` so `Read` runs non-interactively, and keep the existing
   `-- "Read your task from {prompt_file} and execute it."` positional (file delivery,
   unchanged). This removes every network/write capability while preserving the working
   file-based flow; `run_subprocess` stays as-is (`stdin=subprocess.DEVNULL`), no stdin
   plumbing is added. (The token plan additionally strips the default system prompt and
   settings for token savings — coordinate that flag set; neither plan uses stdin.)
2. **codex: close sandbox network.** Remove
   `-c sandbox_workspace_write.network_access=true`. The codex CLI talks to the OpenAI API
   from outside its workspace sandbox; in-sandbox network is only needed if the *task*
   fetches URLs — ours don't. Verify with one probe run; if codex cannot reach its API
   without the flag, keep the flag and revisit egress in Phase 2.
3. **antigravity: remove `--dangerously-skip-permissions`.** Probe which permission flags
   `agy` needs for non-interactive text-only output (`--help` audit + one probe run), and
   in the same probe record **whether agy can still read the prompt file** without the
   flag (file delivery requires it — confirmed again in §1.4 burn-in). If it cannot run
   non-interactively
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
     `dangerously-skip-permissions`; the claude template's `--allowed-tools` is exactly
     `Read`.
   - unit: every rendered template still carries `{prompt_file}` (file delivery
     preserved; no stdin).

Residual risk after Phase 0:

- **claude** — no network egress and no write capability (only `Read` remains). A
  hijacked claude can read host files but has no channel to exfiltrate or modify them
  (residual: reads only, asset 4).
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
- **Prompt delivery is file-based** (stdin is not used — see the *Prompt delivery*
  finding): the profile grants `(allow file-read* (subpath (param "INPUT_DIR")))` so agy
  reads `{prompt_file}` at its real host path, which is correct under Seatbelt because
  there is no path remap. §1.4 burn-in still confirms agy reads the file
  non-interactively once `--dangerously-skip-permissions` is removed.

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
- Confirm file-based prompt delivery works end-to-end under the profile.
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

1. Phase 0 immediately (also unblocks token plan Phase 1; both keep file delivery, share
   the one claude template edit).
2. Phase 1 behind `NEWS_RECAP_AGENT_SANDBOX=1`; run antigravity both ways on the Mac for a
   few days; compare failure rates and settle the Seatbelt allow-set. Then flip to
   default; agy becomes sandbox-only (macOS + `sandbox-exec` required).
3. Phase 2 only if a concrete egress concern appears.

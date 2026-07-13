# Plan: Secure CLI Agent Execution

Status: proposed. **Target platform: macOS** — the pipeline runs on the operator's MacBook
via cron (`scripts/macos_run.sh`); a `scripts/linux_run.sh` launcher also exists, so
controls that work on both are preferred where cheap. Companion plan:
`plan-token-optimization.md` (its Phase 1 slims down the `claude` launch). Both plans
**retain the current file-based prompt delivery** (`{prompt_file}`) and stdout result
capture — see *Prompt delivery* below.

## Backend priority (drives every decision here)

- **antigravity (`agy`) is the default and must stay the default.** It is the only backend
  that runs **fully free, no subscription** — that is why it is the primary path. claude
  and codex are **optional quality upgrades** the operator may switch to per phase; they
  are not the baseline. Consequence: hardening cannot make agy unusable or force a paid
  backend. If a control breaks agy headless, the control is wrong, not agy.
- **gemini CLI is gone.** Google sunset Gemini CLI on **2026-06-18** (free/Pro/Ultra users
  get HTTP 410; only enterprise *Gemini Code Assist Standard/Enterprise* licenses retain
  access). The `migrate from gemini to agy` commit (2026-06-26) was a direct reaction to
  that sunset. "Go back to gemini" is therefore **not an option** for this deployment
  unless the operator holds an enterprise Code Assist license (assumed not). Antigravity
  CLI is Google's official successor.
- claude and codex remain available and are the quality-tier fallbacks.

## Prompt delivery: file-based, not stdin (settled)

CLI agents do **not** handle stdin prompt delivery reliably at the sizes this pipeline
produces (claude `-p` returns empty output past a few KB — anthropics/claude-code#7263;
`agy -p` can drop stdout under a pipe; `codex exec "<prompt>"` hangs on EOF with a non-TTY
stdin — openai/codex#20919). So **file-based delivery is retained for all agents**: the
agent reads `{prompt_file}`, the result is captured from stdout, `run_subprocess` keeps
`stdin=subprocess.DEVNULL`. This is a fixed premise, not revisited here. Its one security
consequence: every agent needs a **read tool** to open the prompt file, so "strip all
tools" is not achievable — the minimum is "read-only".

## Threat model (calibrated)

The pipeline embeds **untrusted text** into agent prompts — RSS headlines (classify,
dedup, oneshot_digest) and up to 5 000 chars of extracted page text per article (enrich).
A malicious article can carry LLM instructions ("ignore the task, run X"). This is textbook
**indirect prompt injection** (OWASP LLM01). Prompt-level defenses in `prompts.py` are
requests, not controls; what matters is what the process *can do* when hijacked.

**Realistic probability is low, blast radius is high.** A news feed is a broadcast medium:
an attacker planting text in an article does not know the operator runs an agent, does not
know the host/paths, and cannot see the agent's output (blind exfil). It is opportunistic
spray, not a targeted hit; as of 2026 no headline incident has landed (Willison's "lethal
trifecta"). But *if* it lands under the current flags, the damage is catastrophic and
irreversible (a stolen SSH key does not come back). Low probability × irreversible loss
justifies **cheap, proportionate** controls — not a hand-built kernel sandbox. The design
target is to break one leg of the lethal trifecta (private data / untrusted content /
exfiltration) using each vendor's **own** protections, preferring the exfiltration leg.

Current default command templates (`config.py:58-72`) deliberately disable those built-in
protections for headless convenience:

| Agent | Current flag | What it disables |
|---|---|---|
| `antigravity` | `--dangerously-skip-permissions` | agy's **own** Terminal Sandbox + all approvals (see finding below) |
| `claude` | `--permission-mode dontAsk` + `WebFetch` + `Bash(curl:*)` + broad `Read` | permission prompts + gives network/exfil tools |
| `codex` | `--sandbox workspace-write -c ...network_access=true` | in-sandbox network egress |

Plus, independent of templates: `_run_agent_cli` passes `env = os.environ.copy()`
(`ai_agent.py:329`) — every secret in the operator's shell is handed to the agent.

Assets to protect, priority order: (1) host FS secrets (`~/.ssh`, `~/.aws`, browser
profiles, Keychain, `~/Library/...`); (2) host env vars; (3) agents' own auth tokens
(`~/.gemini/antigravity-cli/`, `~/.claude`, `~/.codex`); (4) output integrity (lowest — a
poisoned digest is visible and recoverable).

## What we already verified (2026-07-13)

- **claude — dangerous flags are overreach; proven removable.** Live experiment (claude
  CLI v2.1.207, faithful conditions: cwd = a separate workspace, prompt file at an absolute
  path *outside* cwd): `claude -p --allowed-tools "Read"` with **no** `--permission-mode`
  and **no** network tools read the prompt file and emitted correct stdout, exit 0. With
  Read **not** allowlisted it could not read (asked for permission, no TTY → gave up). So
  `--allowed-tools "Read"` is **necessary and sufficient**; `dontAsk`/`bypassPermissions`
  are not needed for the file-read flow, and `WebFetch`/`Bash(curl:*)` are pure exfil
  surface. Bonus observed: claude's own model-level injection defense refused a payload-
  shaped prompt — real but probabilistic, not relied on as a control.
- **codex — network flag is overreach for our tasks (verify with one probe).** codex's
  sandbox "applies to spawned commands"; codex's own model API call is made by the
  un-sandboxed orchestrator, so removing `network_access=true` should **not** block codex
  from reaching its API — it only stops *shell commands the agent runs* from using the
  network, which our text→text tasks never need. Not runnable here (codex not installed);
  confirm with a single probe run on the Mac (macOS Seatbelt has known network edge cases —
  codex#10390, #9298).
- **antigravity — key correction: `agy` HAS its own sandbox, and the current flag turns it
  off.** agy ships a native **Terminal Sandbox** (OS-level: `sandbox-exec` on macOS,
  `nsjail` on Linux, AppContainer on Windows) plus a permission layer, configured in
  `~/.gemini/antigravity-cli/settings.json`:
  - `enableTerminalSandbox` (bool, default **false**) — confines command execution.
  - `toolPermission` (`always-proceed` | `request-review` | `strict` | `proceed-in-sandbox`,
    default `request-review`) — approval policy.
  - `permissions.allow` / `permissions.deny` — command/path allow/deny lists
    (e.g. `deny: ["command(curl)","command(wget)","command(rm -rf)"]`).

  Critically, `--dangerously-skip-permissions` auto-approves **not only** normal prompts
  **but also the "bypass the sandbox" prompt** (antigravity-cli#36) — i.e. the current
  default specifically defeats agy's own protection. Open limitation: agy has **no
  read-only / plan mode for non-interactive `-p` runs** (antigravity-cli#45, unresolved),
  and reports differ on whether bare `-p` auto-approves `write_file` or hangs waiting for a
  prompt. This is the crux the Phase 1 experiments resolve.

**Design principle:** use each vendor's built-in protection; do **not** build a custom
sandbox unless the built-in demonstrably fails. The old plan's hand-written Seatbelt (SBPL)
profile is demoted to a last resort (Phase 3), because agy's own Terminal Sandbox is the
same mechanism (`sandbox-exec`) exposed as a supported switch.

## Phase 0 — Flag & environment hardening (cheap, do regardless) (~1 day)

Foundation for everything; none of it depends on stdin.

1. **claude → `--allowed-tools "Read"`.** Drop `--permission-mode dontAsk`, `WebFetch`,
   `Bash(curl:*)`, `Bash(cat:*)`, `Bash(shasum:*)`, `Bash(pwd:*)`, `Bash(ls:*)`. Keep the
   `-- "Read your task from {prompt_file} …"` positional (file delivery). **Proven** above.
2. **codex → drop `-c sandbox_workspace_write.network_access=true`;** keep
   `--sandbox workspace-write` (its write confinement is good). Gate on the one probe run
   above; if codex cannot reach its API without it, restore the flag and note it.
3. **antigravity → drop `--dangerously-skip-permissions`.** This flag is the thing that
   disables agy's own sandbox, so removing it is the prerequisite for Phase 1. Its
   replacement (headless approval policy + sandbox settings) is decided by the Phase 1
   experiments — do not ship agy with the flag removed until Phase 1 picks the working
   settings, or headless runs may hang. Until then, agy stays on the flag behind a clear
   "insecure default, see Phase 1" note.
4. **Environment allowlist.** Replace `os.environ.copy()` (`ai_agent.py:329`) with an
   explicit default-deny builder: always `PATH`, `HOME`, `LANG`, `LC_ALL`, `TERM`,
   `TMPDIR`; per-agent auth vars (`agent_api_key_vars` when `use_api_key`); pipeline vars
   already set explicitly (`NEWS_RECAP_*`, `MAX_THINKING_TOKENS`, …); plus
   `routing.extra_env`. Add `NEWS_RECAP_AGENT_ENV_PASSTHROUGH` (CSV) as an escape hatch.
   Portable, benefits all agents and the Linux launcher.
5. **Update `spec/agents.md`** to the shipped templates (it still documents
   `bypassPermissions`, `Write,Edit`, and a stale `output_result_path` contract).
6. **Tests:** env builder never leaks a non-allowlisted var (seed `FAKE_SECRET`, assert
   absent); rendered claude template's `--allowed-tools` is exactly `Read` and contains no
   `curl`/`WebFetch`; codex template has no `network_access`; agy template carries no
   `--dangerously-skip-permissions` once Phase 1 lands; every template still has
   `{prompt_file}`.

## Phase 1 — Make agy safe via its OWN sandbox (the target outcome) (~2–3 days, macOS)

This is the center of the plan: agy is the default, so its safety is the whole point, and
the best outcome is that agy's built-in Terminal Sandbox + permission settings are enough —
no Docker, no custom profile. All experiments run on the Mac behind
`NEWS_RECAP_RUN_SANDBOX_TESTS=1` (agy is not installable in CI/this env). Record every
result in `spec/agents.md`.

### 1.0 Open question to resolve first: how the pipeline enforces the settings

agy reads `~/.gemini/antigravity-cli/settings.json` — a **global** file the operator also
uses interactively. The pipeline must apply the safe settings **without clobbering** it.
Probe, in order of preference: (a) a per-run config path / env override (e.g. a
config-dir or `--settings`-style flag — audit `agy --help`); (b) pointing agy at a
pipeline-owned config dir via env; (c) as a last resort, merge-in the required keys on
startup and restore on exit. Pick the least invasive that works headless.

### 1.1 Experiments (each = one small agy `-p` run; assert on stdout/stderr/exit + host FS)

- **E1 — baseline behavior without the flag.** Run a normal recap task with
  `--dangerously-skip-permissions` **removed** and default settings. Classify the result:
  *works* / *hangs waiting for approval* / *auto-approves everything*. Sets the starting
  point.
- **E2 — turn the sandbox on.** `settings.json`: `enableTerminalSandbox: true`. Test
  `toolPermission` at `proceed-in-sandbox` **and** `strict`. For each: does a real task
  still complete headless **without hanging** and produce parity output? (Expect
  `strict` may hang for lack of a TTY; `proceed-in-sandbox` is the likely headless-safe
  value.)
- **E3 — containment canaries** (the acceptance bar), under the E2 settings that ran:
  - **read**: `~/canary.txt` on host; task's "article text" tells agy to read and print it
    → assert the content never appears in stdout/stderr.
  - **write**: task told to write `~/.ssh/probe` → assert the file is never created.
  - **network/exfil**: task told to `curl`/POST a canary to a remote host → assert no
    egress (and that `permissions.deny: [command(curl),command(wget)]` blocks the tool).
  - **env**: `FAKE_SECRET=x` in the (allowlisted) env test → assert a task told to
    `echo $FAKE_SECRET` cannot emit `x` (covers Phase 0 allowlist + sandbox together).
- **E4 — quality/parity.** Run a full real recap under the chosen safe settings; confirm
  digest output matches the pre-hardening baseline (no regression from losing tools).
- **E5 — lifecycle.** A stalling agy task with a short timeout → after the pipeline
  returns, no `agy` (or sandbox helper) process is left (existing `_terminate_process`,
  `subprocess.py:309`, reaps it).

### 1.2 Decision forks (chosen by E2/E3 results)

- **HAPPY — E2 runs headless without hanging AND E3 blocks read/write/network/env.**
  agy's built-in sandbox is the solution. Ship those `settings.json` values as the managed
  default (via the 1.0 mechanism), keep `--dangerously-skip-permissions` **removed**
  permanently, and **stop here** — no Docker, no custom Seatbelt profile. This is the
  intended end state and keeps agy free, native, and default.
- **PARTIAL — commands are confined but the `write_file` *tool* still writes, or `strict`
  hangs while `proceed-in-sandbox` leaks writes.** Tighten within agy first: prefer
  `proceed-in-sandbox`, add `permissions.deny` for write/network tools, and check whether
  agy can disable the `write_file` tool for the run (audit `agy --help` / plugin/tool
  config). Re-run E3. If writes become blockable → treat as HAPPY. If host writes remain
  reachable from untrusted prompts → Phase 2.
- **FAIL — agy cannot run headless under any setting that also contains it (e.g. every
  non-hanging config auto-approves writes, matching antigravity-cli#45).** Escalate to
  Phase 2 (Docker). Do **not** fall back to `--dangerously-skip-permissions` on the host.

## Phase 2 — Docker isolation for agy (fallback, only if Phase 1 = FAIL/leaky) (~2–3 days)

The community already solved headless-agy-on-untrusted-input with disposable containers;
reuse rather than reinvent. Reference: `shelajev/agy-sbx-kit` (and `Shiritai/sanity-gravity`).
The kit demonstrates the three things a from-scratch wrapper gets wrong:

- **Egress allowlist** baked in — only `antigravity.google`, the auto-updater host, Google
  OAuth (`accounts.google.com`, `oauth2.googleapis.com`, `www.googleapis.com`) and the API
  hosts (`cloudaicompanion.googleapis.com`, `cloudcode-pa.googleapis.com`,
  `generativelanguage.googleapis.com`). This is the domain allowlist Seatbelt cannot express.
- **Headless OAuth** — sets `SSH_CONNECTION` so agy uses copy/paste auth; token persists at
  `~/.gemini/antigravity-cli/antigravity-oauth-token` in a persistent home volume, so the
  free subscription still works inside the container.
- **stdin closure** for `-p` (`agy … < /dev/null`).

Integration costs to weigh here (not before): macOS Docker is a Linux VM (Docker
Desktop/Colima) — startup weight and the auth-path change the old plan flagged; and the
`_terminate_process` reaper must target the container, not a docker-client wrapper, to avoid
orphaned containers on timeout. Concurrency is bounded — `agent_max_parallel["antigravity"]
== 1` (`config.py:78`) — so at most one container at a time by default.

## Phase 3 — Last resort (only if Phase 1 and Phase 2 both fail)

- **Custom Seatbelt (SBPL) profile via `sandbox-exec`**, wrapping agy in Python inside
  `_run_agent_cli` (deny-default; allow read of system + `input/`, write only to
  workdir/scratch/auth-refresh/`--log-file`, `allow network*` with domain control deferred
  to a local proxy). This was the previous plan's centerpiece; it is now a fallback because
  it duplicates agy's own Terminal Sandbox and needs its own burn-in for dyld cache, mach
  services, and Keychain. Full SBPL sketch and burn-in notes are preserved in git history
  (pre-2026-07-13 revision of this file).
- **Or demote agy to opt-in** and default to hardened codex/claude — explicitly rejected by
  the operator (agy must stay the free default), so this is documented only as the
  break-glass option if agy proves unsecurable headless.

## Cross-cutting: network egress allowlist (low priority)

Any agent must reach its own API, so a blanket network cut is impossible and Seatbelt can't
filter by hostname — a domain allowlist needs a proxy. If E3's network test shows a residual
egress channel and the threat is judged to warrant it, route agents through a local
allowlisting forward proxy (`tinyproxy`/`squid`) via `HTTPS_PROXY`/`NO_PROXY` in the
(allowlisted) env; the Phase 2 kit already does this in-container. Given the low, blind-exfil
probability this stays optional. The irreducible residual after any of this is data echoed
*through the model's own allowed API response* — accepted.

## Rollout order

1. **Phase 0** immediately (portable, benefits the Linux launcher too; shares the one
   claude template edit with the token plan). Ships behind no flag — it only removes
   overreach and is proven for claude.
2. **Phase 1** behind `NEWS_RECAP_AGENT_SANDBOX=1` on the Mac: run E1–E5, settle the
   `settings.json` values, take the fork. On HAPPY, flip agy to the sandboxed settings as
   the default and drop `--dangerously-skip-permissions` for good.
3. **Phase 2** only on a Phase 1 FAIL/leaky result; **Phase 3** only if Phase 2 also fails.

## Open decisions

- Confirm the operator has **no** enterprise Gemini Code Assist license (if they do, gemini
  with `--approval-mode plan` — a real headless read-only mode agy lacks — reopens as an
  option).
- Phase 1.0: which settings-injection mechanism is least invasive to the operator's global
  `~/.gemini/antigravity-cli/settings.json`.

# Prefect Migration Plan (Code Simplification First)

## Goal

Simplify the application by fully migrating recap pipeline execution to Prefect.
Tooling lock-in is acceptable.

## Non-Goals

- Do not migrate legacy orchestration history.
- Do not port old `llm_tasks`, `recap_pipeline_runs`, or in-flight tasks.
- Do not introduce an abstraction layer on top of Prefect.

## Runtime Modes

- If `NEWS_RECAP_PREFECT_MODE` is not set, use `ephemeral`.
- `NEWS_RECAP_PREFECT_MODE=ephemeral`: always run in local ephemeral mode.
- `NEWS_RECAP_PREFECT_MODE=server`: require external Prefect server via `PREFECT_API_URL`; fail fast if unavailable.
- `NEWS_RECAP_PREFECT_MODE=auto`: probe server quickly (300-500ms), then fall back to `ephemeral` if unavailable.
- Do not auto-start a Prefect server from `main`.

## Target Architecture (After Cutover)

- `recap run` starts a single Prefect flow: `recap_flow`.
- Each pipeline step is a Prefect task:
  - `recap_classify`
  - `resource_load`
  - `recap_enrich`
  - `recap_group`
  - `resource_load_full`
  - `recap_enrich_full`
  - `recap_synthesize`
  - `recap_compose`
- Agent calls (`codex`, `claude`, `gemini`) run directly inside tasks via `subprocess`.
- Prefect owns retry, timeout, state transitions, and observability (instead of custom worker loops).

## Implementation Plan

1. **Create Prefect pipeline module**
   - Add `src/news_recap/recap/prefect_flow.py`.
   - Implement `@flow recap_flow(...)` and `@task` wrappers for all runner steps.
   - Reuse subprocess helpers from `src/news_recap/orchestrator/backend/cli_backend.py`:
     - `_build_run_args`
     - `_run_subprocess_with_shutdown`
   - Preserve existing business logic; do not rewrite algorithms.

2. **Add minimal runtime wiring (inline-first)**
   - Implement mode selection locally in `main.py`/`config.py`.
   - If logic grows (>20-30 lines, repeated usage), extract to `src/news_recap/recap/prefect_runtime.py`:
     - `resolve_mode_from_env()`
     - `check_server_available()`
     - `configure_prefect_mode()`
   - Keep this as runtime wiring only (no adapter layer).

3. **Switch CLI to Prefect entrypoint**
   - Switch `recap run` to `recap_flow` in the chain `src/news_recap/main.py` -> `src/news_recap/recap/controllers.py`.
   - Print the selected runtime mode at run start (`ephemeral`, `server`, or `auto-resolved`).
   - Keep the current UX (no new heavy CLI options).
   - Decide low-level CLI handling:
     - `recap task list/kill`: remove or keep as thin wrappers.
     - `llm worker/tasks/cancel/retry`: remove as legacy surface or keep as thin wrappers without queue/worker loop behavior.

4. **Parallelize classify batches in Prefect**
   - Use `.submit()` for batched classify with explicit concurrency limits.
   - Configure batch-level retry and checkpoint behavior via Prefect task states.

5. **Cut over with clean DB reset**
   - Recreate local SQLite (`.news_recap.db`).
   - Do not migrate legacy orchestration history.

6. **Remove legacy orchestration code after parity**
   - Remove legacy orchestration code only after parity is confirmed on real runs.
   - Execute removal as a separate atomic stage.

7. **Update test suite for the new execution model**
   - Update or remove tests tied to legacy worker/task-queue lifecycle.
   - Add Prefect-focused scenarios: `ephemeral`, `server` fail-fast, `auto` fallback, batched classify retry.

8. **Final validation**
   - Complete the full validation checklist.
   - Run `uv run pytest --cov=src tests/` and `invoke pre`.

## Code to Remove (After Parity Is Confirmed)

- `src/news_recap/orchestrator/worker.py` (claim/loop/heartbeat/retry orchestration)
- Queue/task-lifecycle parts of `src/news_recap/orchestrator/backend/cli_backend.py`  
  (while reusing `_build_run_args` and `_run_subprocess_with_shutdown` inside Prefect tasks)
- Task-queue lifecycle parts of `src/news_recap/orchestrator/repository.py`
- Legacy orchestration paths in `src/news_recap/recap/runner.py`:
  - `_start_worker`
  - `_stop_worker`
  - `_worker_loop`
  - `_run_llm_step`
  - `_poll_until_done`
  - enqueue/poll orchestration paths

## CLI Scope Simplification

- Keep high-level user commands: `recap run`, `recap status`.
- For `recap task list/kill`: remove or keep as thin wrappers over Prefect run operations.
- For `llm worker`, `llm tasks`, `llm cancel`, `llm retry`: remove as legacy worker surface or keep as compatibility-only thin wrappers.

## Validation Checklist

- Run `recap run` in `ephemeral` mode with no external server.
- Run `recap run` in `server` mode and verify fail-fast when `PREFECT_API_URL` is unavailable.
- Run `recap run` in `auto` mode and verify fallback to `ephemeral` when server is unavailable.
- Validate retry/resume behavior for failures in the middle of batched classify.
- Run end-to-end on a fresh DB and measure latency/cost.
- Remove legacy orchestration code with no user-facing CLI regression.
- Confirm tests are updated: legacy worker tests removed/rewritten, Prefect-focused scenarios added.

## Implementation TODO Checklist (File-by-File)

1. **Flow scaffold**
   - [ ] Create `src/news_recap/recap/prefect_flow.py`.
   - [ ] Add `@flow recap_flow(...)`.
   - [ ] Add `@task` wrappers for:
     - `recap_classify`
     - `resource_load`
     - `recap_enrich`
     - `recap_group`
     - `resource_load_full`
     - `recap_enrich_full`
     - `recap_synthesize`
     - `recap_compose`
   - [ ] Reuse `_build_run_args` and `_run_subprocess_with_shutdown` from `src/news_recap/orchestrator/backend/cli_backend.py`.
   - [ ] Verify parity for timeout, graceful shutdown, and stdout/stderr capture behavior.

2. **Runtime mode wiring (inline-first)**
   - [ ] Add mode resolve/configure logic in existing `main.py`/`config.py`.
   - [ ] Implement `ephemeral`, `server` (fail-fast), and `auto` (probe + fallback) behavior.
   - [ ] Extract to `src/news_recap/recap/prefect_runtime.py` only if logic grows.

3. **CLI wiring**
   - [ ] Switch `recap run` to `recap_flow` in `src/news_recap/main.py` and `src/news_recap/recap/controllers.py`.
   - [ ] Print selected runtime mode at run start.
   - [ ] Confirm `recap run` and `recap status` UX compatibility.
   - [ ] Decide fate of `recap task list/kill`: remove or thin-wrapper.
   - [ ] Decide fate of `llm worker/tasks/cancel/retry`: remove or thin-wrapper.

4. **Parallel classify**
   - [ ] Move batched classify execution to Prefect `.submit()` with concurrency limits.
   - [ ] Configure batch-level retry/checkpoint behavior via Prefect task states.
   - [ ] Document expected behavior for partial batch failures.

5. **Cutover + DB reset**
   - [ ] Recreate local `.news_recap.db`.
   - [ ] Skip migration of legacy orchestration history.
   - [ ] Run smoke/E2E after reset.

6. **Legacy code removal (post-parity)**
   - [ ] Remove legacy orchestration code listed in **Code to Remove**.
   - [ ] In `runner.py`, remove `_start_worker`, `_stop_worker`, `_worker_loop`, `_run_llm_step`, `_poll_until_done`, and enqueue/poll paths.

7. **Tests update**
   - [ ] Update/remove legacy worker/backend tests (`test_orchestrator_worker.py`, worker-related parts of `test_llm_cli.py`, `test_worker_recap_bypass.py`).
   - [ ] Update `tests/test_cli_backend.py` for subprocess-helper reuse.
   - [ ] Recheck/update `tests/test_orchestrator_repository.py`, `tests/test_story_flows_cli.py`, and `tests/test_orchestrator_routing.py` if needed.
   - [ ] Add tests for `ephemeral`, `server` fail-fast, and `auto` fallback.
   - [ ] Add retry/resume test for batched classify.
   - [ ] Update CLI integration tests for the new execution model.

8. **Final validation**
   - [ ] Complete the full validation checklist.
   - [ ] Run `uv run pytest --cov=src tests/`.
   - [ ] Run `invoke pre`.

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
- Pipeline visibility (status, task list, cancellation) delegated entirely to Prefect UI.

## Current Status

Steps 1-3 are **complete**. The recap pipeline runs through Prefect in ephemeral mode.
CLI status/task commands have been removed — observability is delegated to Prefect UI.

### What Has Been Done

| File | Change |
|------|--------|
| `pyproject.toml` | Added `prefect>=3.0.0` dependency |
| `src/news_recap/config.py` | Added `PrefectMode` enum, `resolve_prefect_mode()`, `configure_prefect_runtime()`, `_probe_prefect_server()` |
| `src/news_recap/recap/prefect_flow.py` | **New.** `@flow recap_flow`, `@task run_agent_step`, `@task load_resources_step`, `_FlowContext` dataclass, 3 phase helpers |
| `src/news_recap/recap/controllers.py` | Switched `run_pipeline` to call `recap_flow`. Removed `pipeline_status`, `list_tasks`, `kill_tasks`, `_PipelineTracker`, and all legacy DB query helpers |
| `src/news_recap/recap/runner.py` | Renamed 10 private helpers to public (e.g. `_to_article_index` → `to_article_index`) for reuse by `prefect_flow.py` |
| `src/news_recap/main.py` | Removed `recap status`, `recap task list`, `recap task kill` CLI commands and their imports |
| `tests/test_recap_runner.py` | Updated imports and call sites for renamed public helpers |

### What Remains

- Step 4: Parallel classify batches (`.submit()`)
- Step 5: Cutover with clean DB reset
- Step 6: Remove legacy orchestration code (runner class, worker, queue lifecycle)
- Step 7: Update test suite
- Step 8: Final validation

## Implementation Plan

1. **Create Prefect pipeline module** — DONE
   - Added `src/news_recap/recap/prefect_flow.py`.
   - Implemented `@flow recap_flow(...)` and `@task` wrappers for all pipeline steps.
   - Reuses `CliAgentBackend` for subprocess execution (no task-queue, no polling).
   - Business-logic helpers reused from `runner.py` (made public).
   - Refactored into `_FlowContext` dataclass + 3 phase helpers to comply with complexity limits.

2. **Add minimal runtime wiring (inline-first)** — DONE
   - Mode selection lives in `config.py` (stayed under 30 lines, no separate module needed).
   - `ephemeral`, `server` (fail-fast), and `auto` (probe + fallback) all implemented.
   - Health probe uses `httpx` with 500ms timeout; appends `/health` to `PREFECT_API_URL`.

3. **Switch CLI to Prefect entrypoint** — DONE
   - `recap run` calls `recap_flow` via `controllers.py`.
   - Selected runtime mode printed at run start.
   - **Decision: removed** `recap status`, `recap task list`, `recap task kill` — visibility delegated to Prefect UI.
   - `llm worker/tasks/cancel/retry` commands: pending decision (step 6).

4. **Parallelize classify batches in Prefect**
   - Use `.submit()` for batched classify with explicit concurrency limits.
   - Configure batch-level retry and checkpoint behavior via Prefect task states.
   - Deferred until E2E validation of the basic sequential flow.

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
  - `RecapPipelineRunner` class (including `_start_worker`, `_stop_worker`, `_worker_loop`,
    `_run_llm_step`, `_poll_until_done`, `_persist_*`, `_check_no_active_run`)
- `llm worker`, `llm tasks`, `llm cancel`, `llm retry` CLI commands (pending decision)
- `recap_pipeline_runs` / `recap_pipeline_tasks` DB tables and migration (no longer populated or queried)

## CLI Scope Simplification

- **Keep:** `recap run`.
- **Removed:** `recap status`, `recap task list`, `recap task kill` — visibility via Prefect UI.
- **Pending decision:** `llm worker`, `llm tasks`, `llm cancel`, `llm retry` — remove as legacy surface or keep as compatibility-only thin wrappers.

## Validation Checklist

- [ ] Run `recap run` in `ephemeral` mode with no external server.
- [ ] Run `recap run` in `server` mode and verify fail-fast when `PREFECT_API_URL` is unavailable.
- [ ] Run `recap run` in `auto` mode and verify fallback to `ephemeral` when server is unavailable.
- [ ] Validate retry/resume behavior for failures in the middle of batched classify.
- [ ] Run end-to-end on a fresh DB and measure latency/cost.
- [ ] Remove legacy orchestration code with no user-facing CLI regression.
- [ ] Confirm tests are updated: legacy worker tests removed/rewritten, Prefect-focused scenarios added.

## Implementation TODO Checklist (File-by-File)

1. **Flow scaffold** — DONE
   - [x] Create `src/news_recap/recap/prefect_flow.py`.
   - [x] Add `@flow recap_flow(...)`.
   - [x] Add `@task run_agent_step` (LLM subprocess steps) and `@task load_resources_step` (resource loading).
   - [x] Reuse `CliAgentBackend` for subprocess execution.
   - [x] Verify parity for timeout, graceful shutdown, and stdout/stderr capture behavior.

2. **Runtime mode wiring (inline-first)** — DONE
   - [x] Add mode resolve/configure logic in `config.py`.
   - [x] Implement `ephemeral`, `server` (fail-fast), and `auto` (probe + fallback) behavior.
   - [x] Health probe via `httpx`; appends `/health` to `PREFECT_API_URL`.

3. **CLI wiring** — DONE
   - [x] Switch `recap run` to `recap_flow` in `main.py` and `controllers.py`.
   - [x] Print selected runtime mode at run start.
   - [x] Remove `recap status`, `recap task list/kill` (visibility via Prefect UI).
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
   - [ ] Remove `RecapPipelineRunner` class from `runner.py`.
   - [ ] Remove legacy orchestration code listed in **Code to Remove**.
   - [ ] Remove `recap_pipeline_runs`/`recap_pipeline_tasks` tables + migration.

7. **Tests update**
   - [x] Update `tests/test_recap_runner.py` for renamed public helpers.
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

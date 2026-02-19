"""Task orchestrator for file-based CLI LLM execution.

Why not Celery / Dramatiq / Arq?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The core problem this package solves is not task queuing — it is the
integration boundary between the queue and external CLI agents (codex,
claude, gemini) that communicate via on-disk file contracts (JSON manifests,
workdirs, agent_result.json).  Key responsibilities that no generic queue
covers:

- Per-task workdir materialisation with typed JSON input/output contracts.
- Output-contract validation, structured repair passes, and citation
  snapshot extraction — all tightly coupled to agent output format.
- Agent-specific failure classification from exit codes and stderr
  (billing, auth, model-not-found, transient) driving a domain retry
  policy.
- Per-attempt cost/usage parsing from heterogeneous agent telemetry.

A generic broker (Redis, RabbitMQ) would add an operational dependency
for what is a single-machine, SQLite-only, CLI-first tool — while still
requiring all of the above as custom task logic inside the Celery worker.
The simple claim → execute → validate → commit loop with SQLite-backed
queue (~300 LoC in worker.py) is the right trade-off for this scope.
"""

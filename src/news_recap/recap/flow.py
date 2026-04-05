"""Top-level function for the recap pipeline.

Orchestrates classify -> load_resources -> enrich -> deduplicate ->
oneshot_digest -> refine_layout.

Each step lives in its own module and subclasses ``TaskLauncher``
which handles checkpoint skip/save and early stopping.
"""

from __future__ import annotations

import contextlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from news_recap.recap.agents.ai_agent import read_agent_usage
from news_recap.recap.models import Digest, DigestArticle, to_article_index
from news_recap.recap.pipeline_setup import _DIGEST_FILENAME, register_digest
from news_recap.recap.storage.pipeline_io import read_pipeline_input
from news_recap.recap.storage.workdir import TaskWorkdirManager
from news_recap.recap.tasks.base import (
    FlowContext,
    RecapPipelineError,
    StopPipelineError,
)
from news_recap.recap.tasks.classify import Classify
from news_recap.recap.tasks.deduplicate import Deduplicate
from news_recap.recap.tasks.enrich import Enrich
from news_recap.recap.tasks.load_resources import LoadResources
from news_recap.recap.tasks.oneshot_digest import OneshotDigest
from news_recap.recap.tasks.refine_layout import RefineLayout
from news_recap.storage.io import load_msgspec

logger = logging.getLogger(__name__)
_USAGE_FILENAME = "meta/usage.json"


def _log_pipeline_token_summary(logger: Any, pdir: Path) -> None:
    """Scan all task workdirs for usage.json and log per-phase and total tokens."""
    phase_tokens: dict[str, int] = {}
    for usage_path in sorted(pdir.glob(f"*/{_USAGE_FILENAME}")):
        task_dir = usage_path.parent.parent
        _, tokens = read_agent_usage(task_dir)
        if not tokens:
            continue
        phase = task_dir.name.rsplit("-", 1)[0]
        phase_tokens[phase] = phase_tokens.get(phase, 0) + tokens

    if not phase_tokens:
        return

    total = sum(phase_tokens.values())
    parts = [f"{phase}={tokens:,}" for phase, tokens in phase_tokens.items()]
    logger.info(
        "[bold cyan]── tokens ──[/bold cyan] %s | total=%s",
        ", ".join(parts),
        f"{total:,}",
    )


def _latest_published_at(articles: list[DigestArticle]) -> str | None:
    """Return the latest ``published_at`` ISO timestamp, or ``None``."""
    timestamps: list[datetime] = []
    for a in articles:
        with contextlib.suppress(ValueError, TypeError):
            timestamps.append(datetime.fromisoformat(a.published_at))
    return max(timestamps).isoformat() if timestamps else None


def _load_checkpoint(pdir: Path) -> Digest | None:
    path = pdir / _DIGEST_FILENAME
    if path.exists():
        return load_msgspec(path, Digest)
    return None


def recap_flow(  # noqa: PLR0915
    pipeline_dir: str,
    run_date: str,
    stop_after: str | None = None,
) -> None:
    """Run the daily recap pipeline.

    *stop_after* halts the pipeline after the named task completes
    (e.g. ``"classify"``).  ``None`` runs all tasks.
    """
    pdir = Path(pipeline_dir)
    inp = read_pipeline_input(pipeline_dir)
    workdir_mgr = TaskWorkdirManager(pdir)

    effective_stop = stop_after or os.getenv("NEWS_RECAP_STOP_AFTER") or None

    existing = _load_checkpoint(pdir)
    if existing:
        digest = existing
        digest.status = "running"
        logger.info(
            "Resuming from checkpoint: %d completed task(s)",
            len(digest.completed_phases),
        )
    else:
        digest = Digest(
            digest_id=str(uuid4()),
            run_date=run_date,
            status="running",
            pipeline_dir=str(pdir),
            articles=list(inp.articles),
            coverage_start=inp.coverage_start,
            coverage_end=_latest_published_at(inp.articles),
        )

    article_entries = to_article_index(inp.articles)
    logger.info(
        "[bold]Pipeline starting:[/bold] %d articles, date=%s",
        len(inp.articles),
        run_date,
    )

    transport = None
    cc = None
    if inp.routing_defaults.execution_backend == "api":
        from news_recap.recap.agents.concurrency import ConcurrencyController
        from news_recap.recap.agents.transport_anthropic import DirectAnthropicTransport

        rd = inp.routing_defaults
        transport = DirectAnthropicTransport()
        cc = ConcurrencyController(
            initial_cap=rd.api_max_parallel,
            recovery_successes=rd.api_concurrency_recovery_successes,
            downshift_pause=rd.api_downshift_pause_seconds,
            max_backoff=rd.api_retry_max_backoff_seconds,
            jitter=rd.api_retry_jitter_seconds,
        )
        logger.info(
            "API backend: model_map=%s parallel=%d",
            rd.api_model_map,
            rd.api_max_parallel,
        )

    ctx = FlowContext(
        pdir=pdir,
        workdir_mgr=workdir_mgr,
        inp=inp,
        article_map={e.source_id: e for e in article_entries},
        digest=digest,
        stop_after=effective_stop,
        transport=transport,
        cc=cc,
    )
    ctx.save_checkpoint()

    try:
        Classify.run(ctx)
        LoadResources.run(ctx)
        Enrich.run(ctx)
        Deduplicate.run(ctx)
        OneshotDigest.run(ctx)
        RefineLayout.run(ctx)

        digest.status = "completed"
        ctx.save_checkpoint()
        register_digest(pdir.parent, pdir, digest)
        logger.info("[bold green]Pipeline completed[/bold green]")

    except StopPipelineError:
        digest.status = "completed"
        ctx.save_checkpoint()
        register_digest(pdir.parent, pdir, digest)
        logger.info(
            "[bold green]Pipeline stopped[/bold green] (stop_after=%s)",
            effective_stop,
        )

    except RecapPipelineError as exc:
        digest.status = "failed"
        ctx.save_checkpoint()
        logger.error("[bold red]Pipeline failed:[/bold red] %s", exc)

    except KeyboardInterrupt:
        digest.status = "failed"
        ctx.save_checkpoint()
        logger.warning("Pipeline interrupted (Ctrl+C)")
        os._exit(130)  # force-exit: avoids blocking on in-flight HTTP thread joins

    except Exception:  # noqa: BLE001
        digest.status = "failed"
        ctx.save_checkpoint()
        logger.exception("Pipeline unexpected error")

    _log_pipeline_token_summary(logger, pdir)

"""Prefect @flow for the recap pipeline.

Orchestrates classify -> enrich -> group -> enrich_full -> synthesize -> compose.
Each step lives in its own ``task_*.py`` module and subclasses ``TaskLauncher``
which handles checkpoint skip/save and early stopping.

``from __future__ import annotations`` is intentionally NOT used —
Prefect inspects parameter annotations at runtime for the Inputs tab.
"""

import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from prefect import flow
from prefect.logging import get_run_logger

from news_recap.recap.models import Digest
from news_recap.recap.runner import (
    PipelineRunResult,
    PipelineStepResult,
    RecapPipelineError,
    to_article_index,
)
from news_recap.recap.storage.pipeline_io import read_pipeline_input
from news_recap.recap.storage.workdir import TaskWorkdirManager
from news_recap.recap.tasks.base import FlowContext, StopPipelineError
from news_recap.recap.tasks.classify import Classify
from news_recap.recap.tasks.compose import Compose
from news_recap.recap.tasks.enrich import Enrich, EnrichFull
from news_recap.recap.tasks.group import Group
from news_recap.recap.tasks.synthesize import Synthesize
from news_recap.storage.io import load_msgspec

_DIGEST_FILENAME = "digest.json"


def _load_checkpoint(pdir: Path) -> Digest | None:
    path = pdir / _DIGEST_FILENAME
    if path.exists():
        return load_msgspec(path, Digest)
    return None


def _flow_run_name(
    business_date: str = "",  # noqa: ARG001
    **_kwargs: Any,
) -> str:
    now = datetime.now(tz=UTC).strftime("%H:%M:%S")
    return f"recap {business_date} {now}"


@flow(name="recap_pipeline", flow_run_name=_flow_run_name)
def recap_flow(
    pipeline_dir: str,
    business_date: str,
    stop_after: str | None = None,
) -> PipelineRunResult:
    """Top-level Prefect flow for the daily recap pipeline.

    *stop_after* halts the pipeline after the named task completes
    (e.g. ``"classify"``).  ``None`` runs all tasks.
    """
    pf_logger = get_run_logger()
    pdir = Path(pipeline_dir)
    inp = read_pipeline_input(pipeline_dir)
    workdir_mgr = TaskWorkdirManager(pdir)

    effective_stop = stop_after or os.getenv("NEWS_RECAP_STOP_AFTER") or None

    existing = _load_checkpoint(pdir)
    if existing and existing.status != "failed":
        digest = existing
        pf_logger.info(
            "Resuming from checkpoint: %d completed task(s)",
            len(digest.completed_phases),
        )
    else:
        digest = Digest(
            digest_id=str(uuid4()),
            business_date=business_date,
            status="running",
            pipeline_dir=str(pdir),
            articles=list(inp.articles),
        )

    article_entries = to_article_index(inp.articles)
    bd = date.fromisoformat(business_date)
    result = PipelineRunResult(pipeline_id=digest.digest_id, business_date=bd)
    pf_logger.info("Pipeline starting: %d articles, date=%s", len(inp.articles), business_date)

    ctx = FlowContext(
        pdir=pdir,
        workdir_mgr=workdir_mgr,
        inp=inp,
        article_map={e.source_id: e for e in article_entries},
        result=result,
        digest=digest,
        stop_after=effective_stop,
    )
    ctx.save_checkpoint()

    try:
        Classify.run(ctx)
        Enrich.run(ctx)
        Group.run(ctx)
        EnrichFull.run(ctx)
        Synthesize.run(ctx)
        Compose.run(ctx)

        digest.status = "completed"
        ctx.save_checkpoint()
        result.status = "completed"
        pf_logger.info("Pipeline completed")

    except StopPipelineError:
        digest.status = "completed"
        ctx.save_checkpoint()
        result.status = "completed"
        pf_logger.info("Pipeline stopped early (stop_after=%s)", effective_stop)

    except RecapPipelineError as exc:
        result.steps.append(PipelineStepResult(exc.step, None, "failed", error=str(exc)))
        digest.status = "failed"
        ctx.save_checkpoint()
        result.status = "failed"
        result.error = str(exc)
        pf_logger.error("Pipeline failed: %s", exc)

    except Exception as exc:  # noqa: BLE001
        digest.status = "failed"
        ctx.save_checkpoint()
        result.status = "failed"
        result.error = f"Unexpected error: {exc}"
        pf_logger.exception("Pipeline unexpected error")

    return result

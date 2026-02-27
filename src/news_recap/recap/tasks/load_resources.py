"""Task launcher: load full-text resources for articles needing enrichment.

Runs between classify and enrich.  Downloads article text via
``load_resource_texts`` (which caches results in ``ResourceCache``),
marks successfully loaded articles in the digest, and resets the verdict
of articles whose resources could not be loaded.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from prefect.logging import get_run_logger

from news_recap.recap.storage.pipeline_io import load_resource_texts, resource_cache_dir
from news_recap.recap.tasks.base import (
    RecapPipelineError,
    TaskLauncher,
)

if TYPE_CHECKING:
    from news_recap.recap.flow import FlowContext
    from news_recap.recap.models import DigestArticle

logger = logging.getLogger(__name__)

_MAX_FAILURE_RATE = 0.3


def _reset_ineligible_verdicts(
    remaining_ids: list[str],
    ctx: FlowContext,
    by_id: dict[str, DigestArticle],
) -> list:
    """Reset verdicts for articles without article_map entry or URL.

    Returns the list of eligible ``ArticleIndexEntry`` objects.
    """
    entries = [ctx.article_map[sid] for sid in remaining_ids if sid in ctx.article_map]

    for sid in remaining_ids:
        if sid not in ctx.article_map and sid in by_id:
            by_id[sid].verdict = "ok"
    for e in entries:
        if not e.url and e.source_id in by_id:
            by_id[e.source_id].verdict = "ok"

    return [e for e in entries if e.url]


class LoadResources(TaskLauncher):
    """Load full-text resources for articles flagged vague/follow by classify."""

    name = "load_resources"

    def restore_state(self) -> None:
        """Reconstruct ``enrich_ids`` from digest — only loaded articles."""
        ctx = self.ctx
        ctx.state["enrich_ids"] = [
            a.article_id
            for a in ctx.digest.articles
            if a.verdict in ("vague", "follow") and a.resource_loaded
        ]

    def execute(self) -> None:
        ctx = self.ctx
        pf_logger = get_run_logger()
        enrich_ids: list[str] = ctx.state.get("enrich_ids", [])

        if not enrich_ids:
            pf_logger.info("[load_resources] No articles need resources")
            return

        already_loaded = {a.article_id for a in ctx.digest.articles if a.resource_loaded}
        remaining_ids = [sid for sid in enrich_ids if sid not in already_loaded]

        if already_loaded:
            pf_logger.info(
                "[load_resources] %d already loaded, %d remaining",
                len(already_loaded),
                len(remaining_ids),
            )

        if not remaining_ids:
            ctx.state["enrich_ids"] = [sid for sid in enrich_ids if sid in already_loaded]
            return

        by_id = {a.article_id: a for a in ctx.digest.articles}
        eligible = _reset_ineligible_verdicts(remaining_ids, ctx, by_id)

        if not eligible:
            pf_logger.info("[load_resources] No articles with URLs to load")
            ctx.state["enrich_ids"] = [sid for sid in enrich_ids if sid in already_loaded]
            return

        loaded = load_resource_texts(
            eligible,
            cache_dir=resource_cache_dir(ctx.inp.data_dir, ctx.inp.business_date),
            min_resource_chars=ctx.inp.min_resource_chars,
        )

        loaded_ids = set(loaded)
        failed_ids = {e.source_id for e in eligible} - loaded_ids
        failure_rate = len(failed_ids) / len(eligible)

        pf_logger.info(
            "[load_resources] %d/%d loaded, %d failed (%.0f%%)",
            len(loaded_ids),
            len(eligible),
            len(failed_ids),
            failure_rate * 100,
        )

        for sid in loaded_ids:
            if sid in by_id:
                by_id[sid].resource_loaded = True
        for sid in failed_ids:
            if sid in by_id:
                by_id[sid].verdict = "ok"

        if failure_rate > _MAX_FAILURE_RATE:
            raise RecapPipelineError(
                "load_resources",
                f"Too many resource loading failures: {len(failed_ids)}/{len(eligible)}"
                f" ({failure_rate:.0%} > {_MAX_FAILURE_RATE:.0%})",
            )

        enrich_set = set(enrich_ids)
        ctx.state["enrich_ids"] = [
            sid for sid in enrich_ids if sid in (already_loaded | loaded_ids) & enrich_set
        ]

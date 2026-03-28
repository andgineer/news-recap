"""Shared helpers for setting up a recap pipeline directory.

Used by both ``launcher.py`` (``run`` command) and ``export_prompt.py`` (``prompt`` command).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import msgspec

from news_recap.config import Settings
from news_recap.recap.agents.routing import RoutingDefaults
from news_recap.recap.models import Digest, DigestArticle, UserPreferences
from news_recap.recap.storage.pipeline_io import _DEFAULT_MIN_RESOURCE_CHARS
from news_recap.storage.io import load_msgspec

logger = logging.getLogger(__name__)

_DIGEST_FILENAME = "digest.json"


def _build_routing_defaults(settings: Settings) -> RoutingDefaults:
    """Build RoutingDefaults from Settings for the recap pipeline."""
    return RoutingDefaults(
        default_agent=settings.orchestrator.default_agent,
        task_model_map=settings.orchestrator.task_model_map,
        command_templates={
            "claude": settings.orchestrator.claude_command_template,
            "codex": settings.orchestrator.codex_command_template,
            "gemini": settings.orchestrator.gemini_command_template,
        },
        task_type_timeout_map=settings.orchestrator.task_type_timeout_map,
        agent_max_parallel=settings.orchestrator.agent_max_parallel,
        agent_launch_delay=settings.orchestrator.agent_launch_delay,
        execution_backend=settings.orchestrator.execution_backend,
        api_model_map=settings.orchestrator.api_model_map,
        api_max_parallel=settings.orchestrator.api_max_parallel,
        api_concurrency_recovery_successes=settings.orchestrator.api_concurrency_recovery_successes,
        api_downshift_pause_seconds=settings.orchestrator.api_downshift_pause_seconds,
        api_retry_max_backoff_seconds=settings.orchestrator.api_retry_max_backoff_seconds,
        api_retry_jitter_seconds=settings.orchestrator.api_retry_jitter_seconds,
        agent_api_key_vars=dict(settings.orchestrator.agent_api_key_vars),
    )


def _find_resumable_pipeline(
    workdir_root: Path,
    business_date: date,
    article_limit: int | None,
) -> Path | None:
    """Find the latest incomplete pipeline dir for *business_date*.

    Returns ``None`` when no resumable candidate exists or the candidate
    was created with a different article limit (comparing actual article
    count to the requested limit).
    """
    if not workdir_root.is_dir():
        return None

    prefix = f"pipeline-{business_date}-"
    candidates: list[Path] = sorted(
        (p for p in workdir_root.iterdir() if p.is_dir() and p.name.startswith(prefix)),
        key=lambda p: p.name,
        reverse=True,
    )

    for pdir in candidates:
        digest_path = pdir / _DIGEST_FILENAME
        if not digest_path.exists():
            continue
        try:
            digest = load_msgspec(digest_path, Digest)
        except Exception:  # noqa: BLE001
            logger.debug("Cannot read digest in %s, skipping", pdir.name)
            continue

        if article_limit and len(digest.articles) != article_limit:
            logger.info(
                "Skipping %s: article count mismatch (%d vs requested %d)",
                pdir.name,
                len(digest.articles),
                article_limit,
            )
            continue

        return pdir

    return None


def _write_pipeline_input(  # noqa: PLR0913
    pipeline_dir: Path,
    *,
    business_date: date,
    articles: list[DigestArticle],
    preferences: UserPreferences,
    routing_defaults: RoutingDefaults,
    agent_override: str | None,
    data_dir: str,
    min_resource_chars: int = _DEFAULT_MIN_RESOURCE_CHARS,
    dedup_threshold: float = 0.90,
    dedup_model_name: str = "intfloat/multilingual-e5-small",
    use_api_key: bool = False,
) -> None:
    """Serialize all pipeline inputs to ``pipeline_input.json`` in *pipeline_dir*."""
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "business_date": business_date.isoformat(),
        "articles": [msgspec.structs.asdict(a) for a in articles],
        "preferences": msgspec.structs.asdict(preferences),
        "routing_defaults": msgspec.structs.asdict(routing_defaults),
        "agent_override": agent_override,
        "data_dir": data_dir,
        "min_resource_chars": min_resource_chars,
        "dedup_threshold": dedup_threshold,
        "dedup_model_name": dedup_model_name,
        "use_api_key": use_api_key,
    }
    (pipeline_dir / "pipeline_input.json").write_text(
        json.dumps(payload, ensure_ascii=False, default=str),
        "utf-8",
    )

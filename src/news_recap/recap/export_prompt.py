"""``prompt`` command — export a ready-to-paste LLM prompt from recent articles.

With ``--ai`` (default) the full classify → dedup pipeline runs first, matching the ``recap``
command scope.  With ``--no-ai`` no LLM calls are made and raw ingested articles are used directly.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime

import click

from news_recap.config import Settings
from news_recap.ingestion.repository import IngestionStore
from news_recap.recap.article_ordering import (  # noqa: F401 — re-exported
    build_article_lines,
    reorder_articles,
)
from news_recap.recap.dedup.embedder import SentenceTransformerEmbedder
from news_recap.recap.flow import recap_flow
from news_recap.recap.launcher import (
    _base_selection_params,
    _find_matching_resumable,
    _patch_pipeline_input,
    _validate_date_filters,
)
from news_recap.recap.models import Digest, DigestArticle, UserPreferences, language_display_name
from news_recap.recap.pipeline_setup import (
    _build_routing_defaults,
    _effective_to,
    _filter_articles_before,
    _find_digest_pipeline_dir,
    _resolve_article_window,
    _write_pipeline_input,
    create_digest_entry,
    ensure_digest_entry,
    since_display_date,
)
from news_recap.storage.io import load_msgspec
from news_recap.user_config import UserConfigManager

_DEFAULT_GROUP_THRESHOLD = 0.65

_CLIPBOARD_CMDS = [
    ["pbcopy"],  # macOS
    ["xclip", "-selection", "clipboard"],  # Linux (xclip)
    ["xsel", "--clipboard", "--input"],  # Linux (xsel)
    ["clip"],  # Windows
]

_TASK_TEMPLATE = """\
=== TASK ===
You are a news editor. The articles below are pre-sorted by topic similarity.
Produce a digest in {language}: group related articles into sections with a bold heading
and a 2-4 sentence summary. List source URLs at the end of each section.
Do not invent information beyond what the titles tell you."""


def _render_prompt(
    ordered: list[DigestArticle],
    since_date: date | datetime,
    language: str,
) -> str:
    article_lines = build_article_lines(ordered, include_url=True)
    header = f"=== {len(ordered)} ARTICLES (since {since_display_date(since_date)}) ==="
    note = "Note: articles are pre-sorted by topic similarity."
    task = _TASK_TEMPLATE.format(language=language_display_name(language))
    return f"{task}\n\n{header}\n{note}\n\n{article_lines}"


def _copy_to_clipboard(text: str) -> bool:
    """Try to copy *text* to clipboard. Returns True on success."""
    text_bytes = text.encode("utf-8")
    for cmd in _CLIPBOARD_CMDS:
        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                input=text_bytes,
                capture_output=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
    return False


@dataclass(slots=True)
class PromptCommand:
    """CLI parameters for the ``prompt`` command."""

    group_threshold: float = _DEFAULT_GROUP_THRESHOLD
    language: str | None = None
    out: str = "clipboard"
    ai: bool = True
    fresh: bool = False
    agent: str | None = None
    max_days: int | None = None
    all_articles: bool = False
    from_digest: int | None = None
    date_from: date | datetime | None = None
    date_to: date | datetime | None = None


def _selection_params_for_prompt(command: PromptCommand) -> dict[str, object]:
    """Selection params for ``prompt`` (no command-specific extras)."""
    return _base_selection_params(
        from_digest=command.from_digest,
        max_days=command.max_days,
        all_articles=command.all_articles,
        date_from=command.date_from,
        date_to=command.date_to,
    )


def _run_ai_pipeline(  # noqa: PLR0913
    command: PromptCommand,
    settings: Settings,
    store: IngestionStore,
    cap_days: int,
    since_date: datetime | date,
    preferences: UserPreferences,
) -> list[DigestArticle]:
    """Run classify → load_resources → enrich → deduplicate, return post-dedup articles."""
    routing_defaults = _build_routing_defaults(settings)
    run_date = datetime.now(tz=UTC).date()
    workdir_root = settings.orchestrator.workdir_root.resolve()

    sel_params = _selection_params_for_prompt(command)
    pdir = None if command.fresh else _find_matching_resumable(workdir_root, cap_days, sel_params)
    if pdir is not None:
        digest = load_msgspec(pdir / "digest.json", Digest)
        ensure_digest_entry(workdir_root, pdir, digest)
        if command.agent:
            _patch_pipeline_input(pdir, agent_override=command.agent.strip().lower())
    else:
        articles = store.list_retrieval_articles(
            lookback_days=cap_days,
            limit=2000,
            since=since_date,
        )

        upper = _effective_to(command.date_from, command.date_to)
        coverage_end: str | None = None
        if upper is not None:
            articles = _filter_articles_before(articles, upper)
            if type(upper) is datetime:
                coverage_end = upper.isoformat()

        if not articles:
            return []

        ts = datetime.now(tz=UTC).strftime("%H%M%S")
        pdir = (workdir_root / f"pipeline-{run_date}-{ts}").resolve()
        _write_pipeline_input(
            pdir,
            run_date=run_date,
            articles=articles,
            preferences=preferences,
            routing_defaults=routing_defaults,
            agent_override=command.agent,
            data_dir=str(settings.data_dir),
            coverage_end=coverage_end,
            min_resource_chars=settings.ingestion.min_resource_chars,
            dedup_threshold=settings.dedup.threshold,
            dedup_model_name=settings.dedup.model_name,
            selection_params=sel_params,
        )
        create_digest_entry(
            workdir_root,
            pdir.name,
            run_date.isoformat(),
            len(articles),
        )

    recap_flow(
        pipeline_dir=str(pdir),
        run_date=run_date.isoformat(),
        stop_after="deduplicate",
    )

    digest = load_msgspec(pdir / "digest.json", Digest)
    return digest.articles


PromptLine = tuple[str, str]
"""(severity, message) pair emitted during prompt export.

Severity vocabulary: ``"ok"`` | ``"info"`` | ``"warn"`` | ``"log"`` | ``"text"``.
``"text"`` is for the raw prompt body (no styling applied).
"""


class PromptCliController:
    """Load articles, reorder by similarity, render and output the prompt."""

    def prompt(self, command: PromptCommand) -> Iterator[PromptLine]:  # noqa: C901
        _validate_date_filters(
            command.date_from,
            command.date_to,
            command.from_digest,
            command.max_days,
            command.all_articles,
        )

        settings = Settings.from_env()
        cfg_mgr = UserConfigManager(settings.data_dir)
        preferences = cfg_mgr.build_preferences(language_override=command.language)

        if command.from_digest is not None:
            kept_articles, since_date = self._load_digest_articles(
                settings,
                command.from_digest,
            )
            yield (
                "info",
                f"Loaded {len(kept_articles)} articles from digest #{command.from_digest}",
            )
        else:
            store = IngestionStore(
                settings.data_dir,
                gc_retention_days=settings.ingestion.gc_retention_days,
            )
            store.init_schema()

            cap_days, since_date = _resolve_article_window(
                command.date_from,
                settings,
                command.all_articles,
                command.max_days,
            )

            if command.ai:
                kept_articles = _run_ai_pipeline(
                    command,
                    settings,
                    store,
                    cap_days,
                    since_date,
                    preferences,
                )
            else:
                kept_articles = store.list_retrieval_articles(
                    lookback_days=cap_days,
                    limit=2000,
                    since=since_date,
                )
                upper = _effective_to(command.date_from, command.date_to)
                if upper is not None:
                    kept_articles = _filter_articles_before(kept_articles, upper)

        if not kept_articles:
            yield ("warn", "No articles found.")
            return

        yield ("log", "Loading embedding model (first run may download ~100 MB)…")
        embedder = SentenceTransformerEmbedder(model_name=settings.dedup.model_name)
        ordered = reorder_articles(kept_articles, embedder, command.group_threshold)

        prompt = _render_prompt(ordered, since_date, preferences.language)

        if command.out == "console":
            yield ("text", prompt)
        elif _copy_to_clipboard(prompt):
            yield ("ok", f"Prompt ({len(ordered)} articles) copied to clipboard.")
        else:
            yield ("warn", "No clipboard command available. Printing to console instead.")
            yield ("text", prompt)

    @staticmethod
    def _load_digest_articles(
        settings: Settings,
        digest_id: int,
    ) -> tuple[list[DigestArticle], date]:
        workdir_root = settings.orchestrator.workdir_root.resolve()
        pdir = _find_digest_pipeline_dir(workdir_root, digest_id)
        if pdir is None:
            raise click.ClickException(
                f"Digest #{digest_id} not found. Use `news-recap list` to see available digests.",
            )
        digest = load_msgspec(pdir / "digest.json", Digest)
        return digest.articles, date.fromisoformat(digest.run_date)

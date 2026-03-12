"""`recap prompt` — export a ready-to-paste LLM prompt from recent articles.

With ``--ai`` (default) the full classify → dedup pipeline runs first, matching ``recap run``
scope.  With ``--no-ai`` no LLM calls are made and raw ingested articles are used directly.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from news_recap.config import Settings
from news_recap.ingestion.repository import IngestionStore
from news_recap.recap.dedup.cluster import group_similar
from news_recap.recap.dedup.embedder import (
    Embedder,
    SentenceTransformerEmbedder,
    Vector,
    cosine_similarity,
)
from news_recap.recap.flow import recap_flow
from news_recap.recap.models import Digest, DigestArticle, UserPreferences, language_display_name
from news_recap.recap.pipeline_setup import (
    _build_routing_defaults,
    _find_resumable_pipeline,
    _write_pipeline_input,
)
from news_recap.storage.io import load_msgspec

_DEFAULT_GROUP_THRESHOLD = 0.65
_DEFAULT_LANGUAGE = "ru"

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


def _order_cluster(ids: list[str], embeddings: dict[str, Vector]) -> list[str]:
    """Order a cluster using greedy nearest-neighbour from the most central article."""
    remaining = list(ids)
    if len(remaining) == 1:
        return remaining

    start = max(
        remaining,
        key=lambda i: sum(
            cosine_similarity(embeddings[i], embeddings[j]) for j in remaining if j != i
        ),
    )
    ordered = [start]
    remaining.remove(start)
    while remaining:
        last = ordered[-1]
        nxt = max(remaining, key=lambda i: cosine_similarity(embeddings[last], embeddings[i]))
        ordered.append(nxt)
        remaining.remove(nxt)
    return ordered


def reorder_articles(
    articles: list[DigestArticle],
    embedder: Embedder,
    threshold: float,
) -> list[DigestArticle]:
    """Cluster by similarity and apply greedy nearest-neighbour ordering.

    Returns the full article list reordered so similar articles are adjacent.
    """
    if not articles:
        return []

    titles = [a.title for a in articles]
    vectors = embedder.embed(titles)
    ids: list[str] = []
    embeddings: dict[str, Vector] = {}
    articles_by_id: dict[str, DigestArticle] = {}
    for a, v in zip(articles, vectors, strict=True):
        ids.append(a.article_id)
        embeddings[a.article_id] = v
        articles_by_id[a.article_id] = a

    clusters = group_similar(ids, embeddings, threshold, max_group_size=len(articles))

    ordered_clusters = []
    clustered_ids: set[str] = set()
    for cluster in clusters:
        ordered_cluster = _order_cluster(cluster, embeddings)
        ordered_clusters.append(ordered_cluster)
        clustered_ids.update(ordered_cluster)

    singletons = [a for a in articles if a.article_id not in clustered_ids]

    ordered = [articles_by_id[aid] for cluster in ordered_clusters for aid in cluster]
    ordered += singletons
    return ordered


def build_article_lines(ordered: list[DigestArticle]) -> str:
    """Return numbered article lines for use in an LLM prompt.

    Format per line: "1. Title (source.com) — https://url"

    No headers, no task section — plain numbered list only.
    Used by recap prompt (which adds its own wrapper) and by single_pass
    (which embeds the lines in a different prompt template).
    """
    return "\n".join(
        f"{i}. {article.title} ({article.source}) \u2014 {article.url}"
        for i, article in enumerate(ordered, start=1)
    )


def _render_prompt(
    ordered: list[DigestArticle],
    lookback_days: int,
    language: str,
) -> str:
    article_lines = build_article_lines(ordered)
    header = f"=== {len(ordered)} ARTICLES (last {lookback_days} day(s)) ==="
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
    """CLI parameters for recap prompt."""

    data_dir: Path | None = None
    group_threshold: float = _DEFAULT_GROUP_THRESHOLD
    language: str = _DEFAULT_LANGUAGE
    out: str = "clipboard"
    ai: bool = True
    fresh: bool = False


def _run_ai_pipeline(
    command: PromptCommand,
    settings: Settings,
    store: IngestionStore,
) -> list[DigestArticle]:
    """Run classify → load_resources → enrich → deduplicate, return post-dedup articles."""
    routing_defaults = _build_routing_defaults(settings)
    business_date = datetime.now(tz=UTC).date()
    workdir_root = settings.orchestrator.workdir_root.resolve()

    pdir = None if command.fresh else _find_resumable_pipeline(workdir_root, business_date, article_limit=None)
    if pdir is None:
        articles = store.list_retrieval_articles(
            lookback_days=settings.ingestion.digest_lookback_days,
            limit=2000,
        )
        ts = datetime.now(tz=UTC).strftime("%H%M%S")
        pdir = (workdir_root / f"pipeline-{business_date}-{ts}").resolve()
        _write_pipeline_input(
            pdir,
            business_date=business_date,
            articles=articles,
            preferences=UserPreferences(),
            routing_defaults=routing_defaults,
            agent_override=None,
            data_dir=str(settings.data_dir),
            min_resource_chars=settings.ingestion.min_resource_chars,
            dedup_threshold=settings.dedup.threshold,
            dedup_model_name=settings.dedup.model_name,
        )

    recap_flow(
        pipeline_dir=str(pdir),
        business_date=business_date.isoformat(),
        stop_after="deduplicate",
    )

    digest = load_msgspec(pdir / "digest.json", Digest)
    return digest.articles


class PromptCliController:
    """Load articles, reorder by similarity, render and output the prompt."""

    def prompt(self, command: PromptCommand) -> Iterator[str]:
        settings = Settings.from_env(data_dir=command.data_dir)
        store = IngestionStore(
            settings.data_dir,
            gc_retention_days=settings.ingestion.gc_retention_days,
        )
        store.init_schema()

        if command.ai:
            kept_articles = _run_ai_pipeline(command, settings, store)
        else:
            kept_articles = store.list_retrieval_articles(
                lookback_days=settings.ingestion.digest_lookback_days,
                limit=2000,
            )

        if not kept_articles:
            yield "No articles found."
            return

        yield "Loading embedding model (first run may download ~100 MB)…"
        embedder = SentenceTransformerEmbedder(model_name=settings.dedup.model_name)
        ordered = reorder_articles(kept_articles, embedder, command.group_threshold)

        prompt = _render_prompt(ordered, settings.ingestion.digest_lookback_days, command.language)

        if command.out == "console":
            yield prompt
        elif _copy_to_clipboard(prompt):
            yield f"Prompt ({len(ordered)} articles) copied to clipboard."
        else:
            yield "Warning: no clipboard command available. Printing to console instead."
            yield prompt

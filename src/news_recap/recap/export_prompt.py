"""Export a ready-to-paste LLM prompt from recent articles (no LLM calls)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
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
from news_recap.recap.models import DigestArticle

_DEFAULT_LOOKBACK_DAYS = 1
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
You are a news editor. The articles above are pre-sorted by topic similarity.
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
    Used by export-prompt (which adds its own wrapper) and by single_pass
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
    task = _TASK_TEMPLATE.format(language=language)
    return f"{header}\n{note}\n\n{article_lines}\n\n{task}"


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
class ExportPromptCommand:
    """CLI parameters for export-prompt."""

    data_dir: Path | None = None
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS
    group_threshold: float = _DEFAULT_GROUP_THRESHOLD
    language: str = _DEFAULT_LANGUAGE
    out: str = "clipboard"


class ExportPromptCliController:
    """Load articles, reorder by similarity, render and output the prompt."""

    def export_prompt(self, command: ExportPromptCommand) -> Iterator[str]:
        settings = Settings.from_env(data_dir=command.data_dir)
        store = IngestionStore(
            settings.data_dir,
            gc_retention_days=settings.ingestion.gc_retention_days,
        )
        store.init_schema()

        articles = store.list_retrieval_articles(lookback_days=command.lookback_days)
        if not articles:
            yield f"No articles found for the last {command.lookback_days} day(s)."
            return

        yield f"Found {len(articles)} articles."
        yield "Loading embedding model (first run may download ~100 MB)…"

        embedder = SentenceTransformerEmbedder(model_name=settings.dedup.model_name)
        ordered = reorder_articles(articles, embedder, command.group_threshold)

        prompt = _render_prompt(ordered, command.lookback_days, command.language)

        if command.out == "console":
            yield prompt
        elif _copy_to_clipboard(prompt):
            yield f"Prompt ({len(ordered)} articles) copied to clipboard."
        else:
            yield "Warning: no clipboard command available. Printing to console instead."
            yield prompt

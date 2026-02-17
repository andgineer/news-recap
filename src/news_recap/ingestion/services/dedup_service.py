"""Semantic deduplication stage service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from news_recap.config import DedupSettings
from news_recap.ingestion.dedup.cluster import cluster_candidates, count_duplicates
from news_recap.ingestion.dedup.embedder import build_embedder
from news_recap.ingestion.models import DedupCandidate, IngestionRunCounters
from news_recap.ingestion.repository import SQLiteRepository

EMBEDDING_TEXT_VERSION = "title-clean-v1"


class DedupStageService:
    """Runs dedup stage and persists clustering artifacts."""

    def __init__(
        self,
        *,
        repository: SQLiteRepository,
        dedup_settings: DedupSettings,
    ) -> None:
        self.repository = repository
        self.dedup_settings = dedup_settings

    def run(self, *, run_id: str, counters: IngestionRunCounters) -> None:
        _touch_run_heartbeat(self.repository, run_id)
        since = datetime.now(tz=UTC) - timedelta(days=self.dedup_settings.lookback_days)
        candidates = self.repository.list_candidates_for_dedup(since=since)
        storage_model_name = _embedding_storage_model_name(self.dedup_settings.model_name)

        if not candidates:
            self.repository.save_dedup_clusters(
                run_id=run_id,
                model_name=storage_model_name,
                threshold=self.dedup_settings.threshold,
                clusters=[],
            )
            return

        article_ids = [candidate.article_id for candidate in candidates]
        embeddings = self.repository.get_embeddings(
            article_ids=article_ids,
            model_name=storage_model_name,
        )

        missing_candidates = [
            candidate for candidate in candidates if candidate.article_id not in embeddings
        ]
        if missing_candidates:
            embedder = build_embedder(
                self.dedup_settings.model_name,
                allow_fallback=self.dedup_settings.allow_model_fallback,
            )
            vectors = embedder.embed(
                [_build_embedding_text(candidate) for candidate in missing_candidates],
            )
            _touch_run_heartbeat(self.repository, run_id)
            generated = {
                candidate.article_id: vector
                for candidate, vector in zip(missing_candidates, vectors, strict=True)
            }
            self.repository.upsert_embeddings(
                model_name=storage_model_name,
                vectors=generated,
                ttl_days=self.dedup_settings.embedding_ttl_days,
            )
            embeddings.update(generated)

        clusters = cluster_candidates(
            candidates=candidates,
            embeddings=embeddings,
            threshold=self.dedup_settings.threshold,
        )

        self.repository.save_dedup_clusters(
            run_id=run_id,
            model_name=storage_model_name,
            threshold=self.dedup_settings.threshold,
            clusters=clusters,
        )
        _touch_run_heartbeat(self.repository, run_id)
        counters.dedup_clusters_count = len(clusters)
        counters.dedup_duplicates_count = count_duplicates(clusters)


def _build_embedding_text(candidate: DedupCandidate) -> str:
    title = candidate.title.strip()
    clean_text = candidate.clean_text.strip()

    if title and clean_text:
        return f"{title}. {clean_text}"
    if title:
        return title
    if clean_text:
        return clean_text
    return f"[article:{candidate.article_id}]"


def _embedding_storage_model_name(model_name: str) -> str:
    return f"{model_name}@{EMBEDDING_TEXT_VERSION}"


def _touch_run_heartbeat(repository: SQLiteRepository, run_id: str) -> None:
    touch = getattr(repository, "touch_run", None)
    if callable(touch):
        touch(run_id)

from __future__ import annotations

from datetime import UTC, datetime

import allure

from news_recap.config import DedupSettings
from news_recap.ingestion.models import DedupCandidate, IngestionRunCounters
from news_recap.ingestion.services.dedup_service import DedupStageService

pytestmark = [
    allure.epic("Dedup Quality"),
    allure.feature("Embeddings & Thresholding"),
]


class FakeRepository:
    def __init__(self, candidates: list[DedupCandidate]) -> None:
        self._candidates = candidates
        self.last_get_model_name: str | None = None
        self.last_upsert_model_name: str | None = None
        self.last_save_model_name: str | None = None
        self.saved_clusters_count = 0

    def list_candidates_for_dedup(self, since: datetime) -> list[DedupCandidate]:  # noqa: ARG002
        return self._candidates

    def get_embeddings(self, article_ids: list[str], model_name: str) -> dict[str, list[float]]:
        self.last_get_model_name = model_name
        return {}

    def upsert_embeddings(
        self,
        *,
        model_name: str,
        vectors: dict[str, list[float]],
        ttl_days: int,  # noqa: ARG002
    ) -> None:
        self.last_upsert_model_name = model_name
        assert vectors

    def save_dedup_clusters(
        self,
        *,
        run_id: str,  # noqa: ARG002
        model_name: str,
        threshold: float,  # noqa: ARG002
        clusters: list[object],
    ) -> None:
        self.last_save_model_name = model_name
        self.saved_clusters_count = len(clusters)


def _candidate(*, article_id: str, title: str, clean_text: str) -> DedupCandidate:
    return DedupCandidate(
        article_id=article_id,
        title=title,
        url=f"https://example.com/{article_id}",
        source_domain="example.com",
        published_at=datetime(2026, 2, 17, tzinfo=UTC),
        clean_text=clean_text,
        clean_text_chars=len(clean_text),
    )


def test_dedup_uses_title_plus_clean_text_for_embedding_input(monkeypatch) -> None:
    repo = FakeRepository(
        [
            _candidate(article_id="a1", title="Title One", clean_text="Body one"),
            _candidate(article_id="a2", title="Title Two", clean_text=""),
        ],
    )
    captured_texts: list[str] = []

    class CapturingEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            captured_texts.extend(texts)
            return [[1.0, 0.0], [0.0, 1.0]]

    monkeypatch.setattr(
        "news_recap.ingestion.services.dedup_service.build_embedder",
        lambda model_name, allow_fallback: CapturingEmbedder(),  # noqa: ARG005
    )

    service = DedupStageService(
        repository=repo, dedup_settings=DedupSettings(model_name="hashing-test", threshold=0.95)
    )
    counters = IngestionRunCounters()
    service.run(run_id="run-1", counters=counters)

    assert captured_texts == ["Title One. Body one", "Title Two"]
    assert repo.last_get_model_name == "hashing-test@title-clean-v1"
    assert repo.last_upsert_model_name == "hashing-test@title-clean-v1"
    assert repo.last_save_model_name == "hashing-test@title-clean-v1"


def test_dedup_does_not_merge_when_clean_text_empty_but_titles_different(monkeypatch) -> None:
    repo = FakeRepository(
        [
            _candidate(article_id="a1", title="Earthquake in Japan", clean_text=""),
            _candidate(article_id="a2", title="Bitcoin ETF gains in US", clean_text=""),
        ],
    )

    class MappingEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            vectors: list[list[float]] = []
            for text in texts:
                if text == "Earthquake in Japan":
                    vectors.append([1.0, 0.0])
                elif text == "Bitcoin ETF gains in US":
                    vectors.append([0.0, 1.0])
                else:
                    vectors.append([1.0, 1.0])
            return vectors

    monkeypatch.setattr(
        "news_recap.ingestion.services.dedup_service.build_embedder",
        lambda model_name, allow_fallback: MappingEmbedder(),  # noqa: ARG005
    )

    service = DedupStageService(
        repository=repo, dedup_settings=DedupSettings(model_name="hashing-test", threshold=0.95)
    )
    counters = IngestionRunCounters()
    service.run(run_id="run-1", counters=counters)

    assert counters.dedup_clusters_count == 2
    assert counters.dedup_duplicates_count == 0


def test_dedup_still_merges_same_fact_with_title_and_text(monkeypatch) -> None:
    repo = FakeRepository(
        [
            _candidate(
                article_id="a1",
                title="Storm Nils hits France",
                clean_text="Flood alerts issued.",
            ),
            _candidate(
                article_id="a2",
                title="Storm Nils hits France",
                clean_text="Severe flood alerts issued.",
            ),
        ],
    )

    class MappingEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            vectors: list[list[float]] = []
            for text in texts:
                if text == "Storm Nils hits France. Flood alerts issued.":
                    vectors.append([1.0, 0.0])
                elif text == "Storm Nils hits France. Severe flood alerts issued.":
                    vectors.append([0.99, 0.01])
                else:
                    vectors.append([0.0, 1.0])
            return vectors

    monkeypatch.setattr(
        "news_recap.ingestion.services.dedup_service.build_embedder",
        lambda model_name, allow_fallback: MappingEmbedder(),  # noqa: ARG005
    )

    service = DedupStageService(
        repository=repo, dedup_settings=DedupSettings(model_name="hashing-test", threshold=0.95)
    )
    counters = IngestionRunCounters()
    service.run(run_id="run-1", counters=counters)

    assert counters.dedup_clusters_count == 1
    assert counters.dedup_duplicates_count == 1

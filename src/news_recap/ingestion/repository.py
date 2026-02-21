"""SQLModel-backed storage facade for ingestion pipeline."""

from __future__ import annotations

import json
import logging
import struct
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, delete, select

from news_recap.brain.models import (
    DailyStorySnapshotView,
    DailyStorySnapshotWrite,
    MonitorQuestionView,
    MonitorQuestionWrite,
    OutputFeedbackWrite,
    ReadStateEventWrite,
    SourceCorpusEntry,
    StoryAssignmentView,
    StoryAssignmentWrite,
    StoryDefinitionView,
    StoryDefinitionWrite,
    UserOutputBlockWrite,
    UserOutputUpsert,
    UserOutputView,
)
from news_recap.ingestion.models import (
    ClusterListResult,
    ClusterMemberPreview,
    ClusterPreview,
    DedupCandidate,
    GapStatus,
    GapWrite,
    GlobalGcResult,
    IngestionGap,
    IngestionRunCounters,
    IngestionRunView,
    IngestionWindowStats,
    NormalizedArticle,
    RetentionPruneResult,
    RunStatus,
    UpsertAction,
    UpsertResult,
)
from news_recap.ingestion.models import (
    DedupCluster as DomainDedupCluster,
)
from news_recap.ingestion.storage.alembic_runner import upgrade_head
from news_recap.ingestion.storage.common import (
    build_sqlite_engine,
    connect_sqlite_with_policy,
    utc_now,
)
from news_recap.ingestion.storage.sqlmodel_models import (
    DEFAULT_USER_ID,
    AppUser,
    Article,
    ArticleDedup,
    ArticleEmbedding,
    ArticleExternalId,
    ArticleRaw,
    ArticleResource,
    DailyStorySnapshot,
    DedupCluster,
    IngestionRun,
    MonitorQuestion,
    OutputFeedback,
    ReadStateEvent,
    RssFeedState,
    RssProcessingSnapshot,
    StoryAssignment,
    UserArticle,
    UserOutput,
    UserOutputBlock,
    UserStoryDefinition,
)
from news_recap.ingestion.storage.sqlmodel_models import (
    IngestionGap as IngestionGapRow,
)

logger = logging.getLogger(__name__)
DEFAULT_ACTIVE_RUN_STALE_AFTER = timedelta(minutes=30)


class SQLiteRepository:
    """Facade that persists ingestion entities using SQLModel and Alembic."""

    def __init__(
        self,
        db_path: Path,
        *,
        user_id: str = DEFAULT_USER_ID,
        user_name: str = "Default User",
        sqlite_busy_timeout_ms: int = 5_000,
    ) -> None:
        self.db_path = db_path
        self.user_id = user_id
        self.user_name = user_name
        self.sqlite_busy_timeout_ms = sqlite_busy_timeout_ms

        # Intentional trade-off: this repository owns its own SQLAlchemy engine
        # even when other repositories point to the same SQLite file.
        # We standardize behavior through a shared SQLite policy
        # (WAL + busy_timeout + foreign_keys) instead of cross-repository
        # engine DI. This keeps repository lifecycle independent and is
        # adequate for the current single-machine runtime.
        self.engine = build_sqlite_engine(
            db_path=db_path,
            busy_timeout_ms=sqlite_busy_timeout_ms,
        )

        # Keep low-level connection for tests and ad-hoc debugging queries.
        self._connection = connect_sqlite_with_policy(
            db_path=db_path,
            busy_timeout_ms=sqlite_busy_timeout_ms,
        )

    def close(self) -> None:
        self._connection.close()
        self.engine.dispose()

    def init_schema(self) -> None:
        upgrade_head(self.db_path)
        self._ensure_actor_context()

    def start_run(
        self,
        source: str,
        *,
        stale_after: timedelta = DEFAULT_ACTIVE_RUN_STALE_AFTER,
    ) -> str:
        if stale_after.total_seconds() <= 0:
            raise ValueError("stale_after must be > 0")

        while True:
            run_id = str(uuid4())
            with Session(self.engine) as session:
                now = utc_now()
                session.add(
                    IngestionRun(
                        run_id=run_id,
                        user_id=self.user_id,
                        source=source,
                        status=RunStatus.RUNNING.value,
                        started_at=now,
                        heartbeat_at=now,
                    ),
                )
                try:
                    session.commit()
                    return run_id
                except IntegrityError as error:
                    session.rollback()
                    active_run = session.exec(
                        select(IngestionRun).where(
                            IngestionRun.user_id == self.user_id,
                            IngestionRun.source == source,
                            IngestionRun.status == RunStatus.RUNNING.value,
                        ),
                    ).one_or_none()
                    if active_run is None:
                        raise

                    if self._is_run_stale(active_run=active_run, stale_after=stale_after):
                        stale_heartbeat_at = active_run.heartbeat_at or active_run.started_at
                        reclaimed_at = utc_now()
                        active_run.status = RunStatus.FAILED.value
                        active_run.finished_at = reclaimed_at
                        active_run.heartbeat_at = reclaimed_at
                        active_run.error_summary = (
                            "Auto-recovered stale running run after crash/interruption."
                        )
                        session.add(active_run)
                        session.commit()

                        logger.warning(
                            "Recovered stale running ingestion run and starting a new one "
                            "(source=%s stale_run_id=%s stale_heartbeat_at=%s).",
                            source,
                            active_run.run_id,
                            _to_utc_aware_datetime(stale_heartbeat_at).isoformat(),
                        )
                        continue

                    heartbeat_at = active_run.heartbeat_at or active_run.started_at
                    raise RuntimeError(
                        "Another ingestion run is already active for this source "
                        f"(source={source}, run_id={active_run.run_id}, "
                        f"heartbeat_at={_to_utc_aware_datetime(heartbeat_at).isoformat()}).",
                    ) from error

    def touch_run(self, run_id: str) -> None:
        with Session(self.engine) as session:
            run = session.exec(
                select(IngestionRun).where(
                    IngestionRun.run_id == run_id,
                    IngestionRun.user_id == self.user_id,
                    IngestionRun.status == RunStatus.RUNNING.value,
                ),
            ).one_or_none()
            if run is None:
                return
            run.heartbeat_at = utc_now()
            session.add(run)
            session.commit()

    def _is_run_stale(self, *, active_run: IngestionRun, stale_after: timedelta) -> bool:
        heartbeat_at = active_run.heartbeat_at or active_run.started_at
        heartbeat_utc = _to_utc_aware_datetime(heartbeat_at)
        return (datetime.now(tz=UTC) - heartbeat_utc) > stale_after

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        counters: IngestionRunCounters,
        error_summary: str | None = None,
    ) -> None:
        with Session(self.engine) as session:
            run = session.exec(
                select(IngestionRun).where(
                    IngestionRun.run_id == run_id,
                    IngestionRun.user_id == self.user_id,
                ),
            ).one_or_none()
            if run is None:
                raise RuntimeError(f"Run not found: {run_id}")

            run.status = status.value
            now = utc_now()
            run.finished_at = now
            run.heartbeat_at = now
            run.ingested_count = counters.ingested_count
            run.updated_count = counters.updated_count
            run.skipped_count = counters.skipped_count
            run.dedup_clusters_count = counters.dedup_clusters_count
            run.dedup_duplicates_count = counters.dedup_duplicates_count
            run.gaps_opened_count = counters.gaps_opened_count
            run.error_summary = error_summary
            session.add(run)
            session.commit()

    def summarize_runs(
        self,
        *,
        since: datetime,
        until: datetime,
        source: str | None = None,
    ) -> IngestionWindowStats:
        with Session(self.engine) as session:
            statement = select(IngestionRun).where(
                IngestionRun.user_id == self.user_id,
                IngestionRun.started_at >= _to_db_datetime(since),
                IngestionRun.started_at < _to_db_datetime(until),
            )
            if source is not None:
                statement = statement.where(IngestionRun.source == source)

            rows = session.exec(statement).all()

        summary = IngestionWindowStats()
        for row in rows:
            summary.runs_count += 1
            summary.ingested_count += row.ingested_count
            summary.updated_count += row.updated_count
            summary.skipped_count += row.skipped_count
            summary.dedup_clusters_count += row.dedup_clusters_count
            summary.dedup_duplicates_count += row.dedup_duplicates_count
            summary.gaps_opened_count += row.gaps_opened_count

            if row.status == RunStatus.SUCCEEDED.value:
                summary.succeeded_runs_count += 1
            elif row.status == RunStatus.PARTIAL.value:
                summary.partial_runs_count += 1
            elif row.status == RunStatus.FAILED.value:
                summary.failed_runs_count += 1
            else:
                summary.other_runs_count += 1

        return summary

    def list_recent_runs(
        self,
        *,
        limit: int = 5,
        source: str | None = None,
    ) -> list[IngestionRunView]:
        with Session(self.engine) as session:
            statement = (
                select(IngestionRun)
                .where(IngestionRun.user_id == self.user_id)
                .order_by(col(IngestionRun.started_at).desc(), col(IngestionRun.run_id).desc())
                .limit(max(1, limit))
            )
            if source is not None:
                statement = statement.where(IngestionRun.source == source)

            rows = session.exec(statement).all()

        return [
            IngestionRunView(
                run_id=row.run_id,
                source=row.source,
                status=row.status,
                started_at=_to_utc_aware_datetime(row.started_at),
                finished_at=(
                    _to_utc_aware_datetime(row.finished_at) if row.finished_at is not None else None
                ),
                ingested_count=row.ingested_count,
                updated_count=row.updated_count,
                skipped_count=row.skipped_count,
                dedup_clusters_count=row.dedup_clusters_count,
                dedup_duplicates_count=row.dedup_duplicates_count,
                gaps_opened_count=row.gaps_opened_count,
            )
            for row in rows
        ]

    def get_latest_run_id(
        self,
        *,
        source: str | None = None,
        since: datetime | None = None,
    ) -> str | None:
        with Session(self.engine) as session:
            statement = select(IngestionRun.run_id).where(IngestionRun.user_id == self.user_id)
            if source is not None:
                statement = statement.where(IngestionRun.source == source)
            if since is not None:
                statement = statement.where(IngestionRun.started_at >= _to_db_datetime(since))
            statement = statement.order_by(
                col(IngestionRun.started_at).desc(),
                col(IngestionRun.run_id).desc(),
            ).limit(1)
            return session.exec(statement).one_or_none()

    def list_clusters_for_run(
        self,
        *,
        run_id: str,
        min_size: int = 1,
        limit: int = 20,
        members_per_cluster: int = 5,
    ) -> ClusterListResult:
        min_size = max(1, min_size)
        limit = max(0, limit)
        members_per_cluster = max(1, members_per_cluster)

        with Session(self.engine) as session:
            cluster_rows = session.exec(
                select(DedupCluster)
                .where(
                    DedupCluster.user_id == self.user_id,
                    DedupCluster.run_id == run_id,
                )
                .order_by(col(DedupCluster.cluster_id)),
            ).all()

            dedup_rows = session.exec(
                select(ArticleDedup).where(
                    ArticleDedup.user_id == self.user_id,
                    ArticleDedup.run_id == run_id,
                ),
            ).all()

            article_ids = {row.article_id for row in dedup_rows}
            article_ids.update(cluster.representative_article_id for cluster in cluster_rows)
            articles_by_id: dict[str, Article] = {}
            if article_ids:
                article_rows = session.exec(
                    select(Article).where(
                        col(Article.article_id).in_(list(article_ids)),
                    ),
                ).all()
                articles_by_id = {row.article_id: row for row in article_rows}

        members_by_cluster: dict[str, list[ArticleDedup]] = defaultdict(list)
        for member in dedup_rows:
            members_by_cluster[member.cluster_id].append(member)

        previews: list[ClusterPreview] = []
        total_articles = 0
        for cluster in cluster_rows:
            members = members_by_cluster.get(cluster.cluster_id, [])
            size = len(members)
            if size < min_size:
                continue

            total_articles += size
            representative = articles_by_id.get(cluster.representative_article_id)
            representative_title = (
                representative.title
                if representative is not None
                else f"[missing] {cluster.representative_article_id}"
            )
            representative_url = representative.url if representative is not None else ""

            sorted_members = sorted(
                members,
                key=lambda row: (not row.is_representative, -row.similarity_to_rep, row.article_id),
            )
            member_previews: list[ClusterMemberPreview] = []
            for member in sorted_members[:members_per_cluster]:
                article = articles_by_id.get(member.article_id)
                member_title = (
                    article.title if article is not None else f"[missing] {member.article_id}"
                )
                member_url = article.url if article is not None else ""
                member_source_domain = article.source_domain if article is not None else "unknown"
                member_previews.append(
                    ClusterMemberPreview(
                        article_id=member.article_id,
                        title=member_title,
                        url=member_url,
                        source_domain=member_source_domain,
                        similarity_to_representative=member.similarity_to_rep,
                        is_representative=member.is_representative,
                    ),
                )

            previews.append(
                ClusterPreview(
                    cluster_id=cluster.cluster_id,
                    run_id=run_id,
                    size=size,
                    representative_article_id=cluster.representative_article_id,
                    representative_title=representative_title,
                    representative_url=representative_url,
                    members=member_previews,
                ),
            )

        visible_clusters = previews[:limit] if limit > 0 else []
        return ClusterListResult(
            run_id=run_id,
            total_clusters=len(previews),
            total_articles=total_articles,
            clusters=visible_clusters,
        )

    def upsert_raw_article(
        self,
        source_name: str,
        external_id: str,
        raw_payload: dict[str, object],
        *,
        article_id: str | None = None,
    ) -> None:
        with Session(self.engine) as session:
            resolved_article_id = article_id
            if resolved_article_id is None:
                alias = session.exec(
                    select(ArticleExternalId).where(
                        ArticleExternalId.source_name == source_name,
                        ArticleExternalId.external_id == external_id,
                    ),
                ).one_or_none()
                if alias is None:
                    return
                resolved_article_id = alias.article_id

            existing = session.exec(
                select(ArticleRaw).where(
                    ArticleRaw.source_name == source_name,
                    ArticleRaw.external_id == external_id,
                ),
            ).one_or_none()
            if existing is None:
                session.add(
                    ArticleRaw(
                        article_id=resolved_article_id,
                        source_name=source_name,
                        external_id=external_id,
                        raw_json=json.dumps(raw_payload, ensure_ascii=False, sort_keys=True),
                        first_seen_at=utc_now(),
                    ),
                )
                session.commit()
                return

            if existing.article_id != resolved_article_id:
                existing.article_id = resolved_article_id
                session.add(existing)
                session.commit()

    def prune_articles(
        self,
        *,
        cutoff: datetime,
        dry_run: bool = False,
    ) -> RetentionPruneResult:
        cutoff_db = _to_db_datetime(cutoff)
        with Session(self.engine) as session:
            candidate_article_ids = session.exec(
                select(UserArticle.article_id).where(
                    UserArticle.user_id == self.user_id,
                    UserArticle.discovered_at < cutoff_db,
                ),
            ).all()
            articles_deleted = len(candidate_article_ids)
            raw_payloads_deleted = 0
            private_resources_deleted = int(
                session.exec(
                    select(func.count())
                    .select_from(ArticleResource)
                    .where(
                        col(ArticleResource.user_id) == self.user_id,
                        col(ArticleResource.updated_at) < cutoff_db,
                    ),
                ).one(),
            )

            if not dry_run:
                if candidate_article_ids:
                    session.exec(
                        delete(UserArticle).where(
                            col(UserArticle.user_id) == self.user_id,
                            col(UserArticle.article_id).in_(candidate_article_ids),
                        ),
                    )
                if private_resources_deleted > 0:
                    session.exec(
                        delete(ArticleResource).where(
                            col(ArticleResource.user_id) == self.user_id,
                            col(ArticleResource.updated_at) < cutoff_db,
                        ),
                    )
                session.commit()

            return RetentionPruneResult(
                cutoff=_to_utc_aware_datetime(cutoff_db),
                dry_run=dry_run,
                articles_deleted=articles_deleted,
                raw_payloads_deleted=raw_payloads_deleted,
                private_resources_deleted=private_resources_deleted,
            )

    def upsert_article(self, article: NormalizedArticle, run_id: str) -> UpsertResult:
        with Session(self.engine) as session:
            existing = self._find_existing_article(session, article)
            inserted_article = False
            if existing is None:
                inserted = self._try_insert_article(session=session, article=article, run_id=run_id)
                if inserted is not None:
                    inserted_article = True
                    existing = session.get(Article, inserted.article_id)
                    if existing is None:
                        raise RuntimeError("Inserted article row not found")
                else:
                    existing = self._find_existing_article(session, article)
                    if existing is None:
                        raise RuntimeError("Failed to resolve article after insertion conflict")

            self._ensure_external_alias(
                session=session,
                source_name=article.source_name,
                external_id=article.external_id,
                article_id=existing.article_id,
            )

            target_fallback_key = _target_fallback_key(
                article,
                existing_fallback_key=existing.fallback_key,
            )
            row_changed = _row_changed(existing, article, target_fallback_key)

            if row_changed:
                existing.url = article.url
                existing.url_canonical = article.url_canonical
                existing.url_hash = article.url_hash
                existing.title = article.title
                existing.source_domain = article.source_domain
                existing.published_at = _to_db_datetime(article.published_at)
                existing.language_detected = article.language_detected
                existing.content_raw = article.content_raw
                existing.summary_raw = article.summary_raw
                existing.is_full_content = article.is_full_content
                existing.clean_text = article.clean_text
                existing.clean_text_chars = article.clean_text_chars
                existing.is_truncated = article.is_truncated
                existing.fallback_key = target_fallback_key
                existing.last_processed_run_id = run_id
                if _is_generated_external_id(
                    existing.external_id,
                ) and not _is_generated_external_id(
                    article.external_id,
                ):
                    existing.external_id = article.external_id

            user_link_inserted = self._ensure_user_article_link(
                session=session,
                article_id=existing.article_id,
            )
            session.add(existing)
            session.commit()

            if user_link_inserted:
                return UpsertResult(article_id=existing.article_id, action=UpsertAction.INSERTED)
            if inserted_article or row_changed:
                return UpsertResult(article_id=existing.article_id, action=UpsertAction.UPDATED)
            return UpsertResult(article_id=existing.article_id, action=UpsertAction.SKIPPED)

    def create_gap(self, *, run_id: str, source: str, gap: GapWrite) -> int:
        with Session(self.engine) as session:
            row = IngestionGapRow(
                user_id=self.user_id,
                run_id=run_id,
                source=source,
                from_cursor_or_time=gap.from_cursor_or_time,
                to_cursor_or_time=gap.to_cursor_or_time,
                error_code=gap.error_code,
                retry_after=gap.retry_after,
                status=GapStatus.OPEN.value,
                created_at=utc_now(),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            if row.gap_id is None:
                raise RuntimeError("Failed to persist ingestion gap")
            return int(row.gap_id)

    def list_open_gaps(self, source: str, limit: int) -> list[IngestionGap]:
        with Session(self.engine) as session:
            rows = session.exec(
                select(IngestionGapRow)
                .where(
                    IngestionGapRow.user_id == self.user_id,
                    IngestionGapRow.source == source,
                    IngestionGapRow.status == GapStatus.OPEN.value,
                )
                .order_by(col(IngestionGapRow.gap_id))
                .limit(limit),
            ).all()

            return [
                IngestionGap(
                    gap_id=int(row.gap_id) if row.gap_id is not None else -1,
                    source=row.source,
                    from_cursor_or_time=row.from_cursor_or_time,
                    to_cursor_or_time=row.to_cursor_or_time,
                    error_code=row.error_code,
                    retry_after=row.retry_after,
                    status=GapStatus(row.status),
                )
                for row in rows
            ]

    def resolve_gap(self, gap_id: int) -> None:
        with Session(self.engine) as session:
            row = session.exec(
                select(IngestionGapRow).where(
                    IngestionGapRow.gap_id == gap_id,
                    IngestionGapRow.user_id == self.user_id,
                ),
            ).one_or_none()
            if row is None:
                return
            row.status = GapStatus.RESOLVED.value
            row.resolved_at = utc_now()
            session.add(row)
            session.commit()

    def get_feed_http_cache(
        self,
        *,
        source_name: str,
        feed_url: str,
    ) -> tuple[str | None, str | None]:
        with Session(self.engine) as session:
            row = session.exec(
                select(RssFeedState).where(
                    RssFeedState.user_id == self.user_id,
                    RssFeedState.source_name == source_name,
                    RssFeedState.feed_url == feed_url,
                ),
            ).one_or_none()
            if row is None:
                return None, None
            return row.etag, row.last_modified

    def upsert_feed_http_cache(
        self,
        *,
        source_name: str,
        feed_url: str,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        with Session(self.engine) as session:
            row = session.exec(
                select(RssFeedState).where(
                    RssFeedState.user_id == self.user_id,
                    RssFeedState.source_name == source_name,
                    RssFeedState.feed_url == feed_url,
                ),
            ).one_or_none()
            if row is None:
                row = RssFeedState(
                    user_id=self.user_id,
                    source_name=source_name,
                    feed_url=feed_url,
                    etag=etag,
                    last_modified=last_modified,
                    updated_at=utc_now(),
                )
            else:
                row.etag = etag
                row.last_modified = last_modified
                row.updated_at = utc_now()
            session.add(row)
            session.commit()

    def get_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
    ) -> tuple[str, str | None, datetime] | None:
        with Session(self.engine) as session:
            row = session.exec(
                select(RssProcessingSnapshot).where(
                    RssProcessingSnapshot.user_id == self.user_id,
                    RssProcessingSnapshot.source_name == source_name,
                    RssProcessingSnapshot.feed_set_hash == feed_set_hash,
                ),
            ).one_or_none()
            if row is None:
                return None
            return (
                row.snapshot_json,
                row.next_cursor,
                _to_utc_aware_datetime(row.updated_at),
            )

    def upsert_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
        snapshot_json: str,
        next_cursor: str | None,
    ) -> None:
        now = utc_now()
        with Session(self.engine) as session:
            row = session.exec(
                select(RssProcessingSnapshot).where(
                    RssProcessingSnapshot.user_id == self.user_id,
                    RssProcessingSnapshot.source_name == source_name,
                    RssProcessingSnapshot.feed_set_hash == feed_set_hash,
                ),
            ).one_or_none()
            if row is None:
                row = RssProcessingSnapshot(
                    user_id=self.user_id,
                    source_name=source_name,
                    feed_set_hash=feed_set_hash,
                    snapshot_json=snapshot_json,
                    next_cursor=next_cursor,
                    created_at=now,
                    updated_at=now,
                )
            else:
                row.snapshot_json = snapshot_json
                row.next_cursor = next_cursor
                row.updated_at = now
            session.add(row)
            session.commit()

    def update_rss_processing_snapshot_cursor(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
        next_cursor: str | None,
    ) -> bool:
        with Session(self.engine) as session:
            row = session.exec(
                select(RssProcessingSnapshot).where(
                    RssProcessingSnapshot.user_id == self.user_id,
                    RssProcessingSnapshot.source_name == source_name,
                    RssProcessingSnapshot.feed_set_hash == feed_set_hash,
                ),
            ).one_or_none()
            if row is None:
                logger.warning(
                    "RSS snapshot cursor update skipped because snapshot row is missing "
                    "(source=%s, feed_set_hash=%s).",
                    source_name,
                    feed_set_hash,
                )
                return False
            row.next_cursor = next_cursor
            row.updated_at = utc_now()
            session.add(row)
            session.commit()
            return True

    def delete_rss_processing_snapshot(
        self,
        *,
        source_name: str,
        feed_set_hash: str,
    ) -> None:
        with Session(self.engine) as session:
            row = session.exec(
                select(RssProcessingSnapshot).where(
                    RssProcessingSnapshot.user_id == self.user_id,
                    RssProcessingSnapshot.source_name == source_name,
                    RssProcessingSnapshot.feed_set_hash == feed_set_hash,
                ),
            ).one_or_none()
            if row is None:
                return
            session.delete(row)
            session.commit()

    def list_candidates_for_dedup(self, since: datetime) -> list[DedupCandidate]:
        with Session(self.engine) as session:
            rows = session.exec(
                select(Article)
                .join(UserArticle, col(UserArticle.article_id) == col(Article.article_id))
                .where(
                    UserArticle.user_id == self.user_id,
                    Article.published_at >= _to_db_datetime(since),
                )
                .order_by(col(Article.published_at).desc()),
            ).all()

            return [
                DedupCandidate(
                    article_id=row.article_id,
                    title=row.title,
                    url=row.url,
                    source_domain=row.source_domain,
                    published_at=_to_utc_aware_datetime(row.published_at),
                    clean_text=row.clean_text,
                    clean_text_chars=row.clean_text_chars,
                )
                for row in rows
            ]

    def get_embeddings(self, article_ids: list[str], model_name: str) -> dict[str, list[float]]:
        if not article_ids:
            return {}

        now = utc_now()
        with Session(self.engine) as session:
            rows = session.exec(
                select(ArticleEmbedding).where(
                    ArticleEmbedding.model_name == model_name,
                    col(ArticleEmbedding.article_id).in_(article_ids),
                    or_(
                        col(ArticleEmbedding.expires_at).is_(None),
                        col(ArticleEmbedding.expires_at) > now,
                    ),
                ),
            ).all()

            return {
                row.article_id: _unpack_vector(row.embedding_blob, row.embedding_dim)
                for row in rows
            }

    def upsert_embeddings(
        self,
        *,
        model_name: str,
        vectors: dict[str, list[float]],
        ttl_days: int,
    ) -> None:
        if not vectors:
            return

        created_at = utc_now()
        expires_at = created_at + timedelta(days=ttl_days)

        with Session(self.engine) as session:
            for article_id, vector in vectors.items():
                row = session.exec(
                    select(ArticleEmbedding).where(
                        ArticleEmbedding.article_id == article_id,
                        ArticleEmbedding.model_name == model_name,
                    ),
                ).one_or_none()
                if row is None:
                    row = ArticleEmbedding(
                        article_id=article_id,
                        model_name=model_name,
                        embedding_dim=len(vector),
                        embedding_blob=_pack_vector(vector),
                        created_at=created_at,
                        expires_at=expires_at,
                    )
                else:
                    row.embedding_dim = len(vector)
                    row.embedding_blob = _pack_vector(vector)
                    row.created_at = created_at
                    row.expires_at = expires_at

                session.add(row)
            session.commit()

    def get_article_resource_for_user(self, *, url_hash: str) -> ArticleResource | None:
        now = utc_now()
        has_content = and_(
            col(ArticleResource.content_text).is_not(None),
            func.length(func.trim(col(ArticleResource.content_text))) > 0,
        )
        with Session(self.engine) as session:
            return session.exec(
                select(ArticleResource)
                .where(
                    ArticleResource.url_hash == url_hash,
                    or_(
                        col(ArticleResource.user_id) == self.user_id,
                        col(ArticleResource.user_id).is_(None),
                    ),
                    or_(
                        col(ArticleResource.expires_at).is_(None),
                        col(ArticleResource.expires_at) > now,
                    ),
                )
                .order_by(
                    case(
                        (has_content, 0),
                        else_=1,
                    ),
                    case(
                        (col(ArticleResource.user_id) == self.user_id, 0),
                        else_=1,
                    ),
                    col(ArticleResource.updated_at).desc(),
                )
                .limit(1),
            ).one_or_none()

    def upsert_public_article_resource(  # noqa: PLR0913
        self,
        *,
        url_hash: str,
        url_canonical: str,
        fetch_status: str,
        http_status: int | None = None,
        content_text: str | None = None,
        error_code: str | None = None,
        fetched_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        with Session(self.engine) as session:
            row = session.exec(
                select(ArticleResource).where(
                    col(ArticleResource.user_id).is_(None),
                    ArticleResource.url_hash == url_hash,
                ),
            ).one_or_none()
            if row is None:
                row = ArticleResource(
                    user_id=None,
                    url_hash=url_hash,
                    url_canonical=url_canonical,
                    fetch_status=fetch_status,
                    http_status=http_status,
                    content_text=content_text,
                    error_code=error_code,
                    fetched_at=fetched_at,
                    updated_at=utc_now(),
                    expires_at=expires_at,
                )
            else:
                row.url_canonical = url_canonical
                row.fetch_status = fetch_status
                row.http_status = http_status
                row.content_text = content_text
                row.error_code = error_code
                row.fetched_at = fetched_at
                row.updated_at = utc_now()
                row.expires_at = expires_at
            session.add(row)
            session.commit()

    def upsert_user_article_resource(  # noqa: PLR0913
        self,
        *,
        url_hash: str,
        url_canonical: str,
        fetch_status: str,
        http_status: int | None = None,
        content_text: str | None = None,
        error_code: str | None = None,
        fetched_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        with Session(self.engine) as session:
            row = session.exec(
                select(ArticleResource).where(
                    col(ArticleResource.user_id) == self.user_id,
                    ArticleResource.url_hash == url_hash,
                ),
            ).one_or_none()
            if row is None:
                row = ArticleResource(
                    user_id=self.user_id,
                    url_hash=url_hash,
                    url_canonical=url_canonical,
                    fetch_status=fetch_status,
                    http_status=http_status,
                    content_text=content_text,
                    error_code=error_code,
                    fetched_at=fetched_at,
                    updated_at=utc_now(),
                    expires_at=expires_at,
                )
            else:
                row.url_canonical = url_canonical
                row.fetch_status = fetch_status
                row.http_status = http_status
                row.content_text = content_text
                row.error_code = error_code
                row.fetched_at = fetched_at
                row.updated_at = utc_now()
                row.expires_at = expires_at
            session.add(row)
            session.commit()

    def prune_user_private_resources(
        self,
        *,
        cutoff: datetime,
        dry_run: bool = False,
    ) -> int:
        cutoff_db = _to_db_datetime(cutoff)
        with Session(self.engine) as session:
            to_delete = int(
                session.exec(
                    select(func.count())
                    .select_from(ArticleResource)
                    .where(
                        col(ArticleResource.user_id) == self.user_id,
                        col(ArticleResource.updated_at) < cutoff_db,
                    ),
                ).one(),
            )
            if not dry_run and to_delete > 0:
                session.exec(
                    delete(ArticleResource).where(
                        col(ArticleResource.user_id) == self.user_id,
                        col(ArticleResource.updated_at) < cutoff_db,
                    ),
                )
                session.commit()
            return to_delete

    def gc_unreferenced_articles(self, *, dry_run: bool = False) -> GlobalGcResult:
        now = utc_now()
        with Session(self.engine) as session:
            orphan_article_ids = session.exec(
                select(Article.article_id).where(
                    ~select(1).where(UserArticle.article_id == Article.article_id).exists(),
                ),
            ).all()
            articles_deleted = len(orphan_article_ids)
            raw_deleted = (
                int(
                    session.exec(
                        select(func.count())
                        .select_from(ArticleRaw)
                        .where(col(ArticleRaw.article_id).in_(orphan_article_ids)),
                    ).one(),
                )
                if orphan_article_ids
                else 0
            )
            public_gc_condition = and_(
                col(ArticleResource.user_id).is_(None),
                or_(
                    and_(
                        col(ArticleResource.expires_at).is_not(None),
                        col(ArticleResource.expires_at) <= now,
                    ),
                    ~select(1)
                    .select_from(Article)
                    .join(
                        UserArticle,
                        col(UserArticle.article_id) == col(Article.article_id),
                    )
                    .where(col(Article.url_hash) == col(ArticleResource.url_hash))
                    .exists(),
                ),
            )
            public_resources_deleted = int(
                session.exec(
                    select(func.count()).select_from(ArticleResource).where(public_gc_condition),
                ).one(),
            )
            if not dry_run:
                if orphan_article_ids:
                    session.exec(
                        delete(Article).where(col(Article.article_id).in_(orphan_article_ids)),
                    )
                if public_resources_deleted > 0:
                    session.exec(
                        delete(ArticleResource).where(public_gc_condition),
                    )
                if orphan_article_ids or public_resources_deleted > 0:
                    session.commit()
            return GlobalGcResult(
                dry_run=dry_run,
                articles_deleted=articles_deleted,
                raw_payloads_deleted=raw_deleted,
                public_resources_deleted=public_resources_deleted,
            )

    def save_dedup_clusters(
        self,
        *,
        run_id: str,
        model_name: str,
        threshold: float,
        clusters: list[DomainDedupCluster],
    ) -> None:
        created_at = utc_now()

        with Session(self.engine) as session:
            session.exec(
                delete(ArticleDedup).where(
                    col(ArticleDedup.user_id) == self.user_id,
                    col(ArticleDedup.run_id) == run_id,
                ),
            )
            session.exec(
                delete(DedupCluster).where(
                    col(DedupCluster.user_id) == self.user_id,
                    col(DedupCluster.run_id) == run_id,
                ),
            )

            for cluster in clusters:
                session.add(
                    DedupCluster(
                        user_id=self.user_id,
                        run_id=run_id,
                        cluster_id=cluster.cluster_id,
                        representative_article_id=cluster.representative_article_id,
                        alt_sources_json=json.dumps(cluster.alt_sources, ensure_ascii=False),
                        model_name=model_name,
                        threshold=threshold,
                        created_at=created_at,
                    ),
                )
            session.flush()

            for cluster in clusters:
                for member in cluster.members:
                    session.add(
                        ArticleDedup(
                            user_id=self.user_id,
                            run_id=run_id,
                            article_id=member.article_id,
                            cluster_id=cluster.cluster_id,
                            is_representative=member.is_representative,
                            similarity_to_rep=member.similarity_to_representative,
                        ),
                    )
            session.commit()

    # ---------------------------------------------------------------------------
    # Intelligence domain: stories, monitors, outputs, feedback, retrieval
    # ---------------------------------------------------------------------------

    def list_user_retrieval_articles(
        self,
        *,
        limit: int = 20,
        since: datetime | None = None,
        until: datetime | None = None,
        source_ids: tuple[str, ...] | None = None,
    ) -> list[SourceCorpusEntry]:
        """Resolve user-scoped retrieval corpus entries from ``user_articles``."""

        with Session(self.engine) as session:
            if source_ids is None:
                statement = (
                    select(Article, UserArticle)
                    .join(
                        UserArticle,
                        col(UserArticle.article_id) == col(Article.article_id),
                    )
                    .where(UserArticle.user_id == self.user_id)
                )
                if since is not None:
                    statement = statement.where(
                        UserArticle.discovered_at >= _to_db_datetime(since),
                    )
                if until is not None:
                    statement = statement.where(
                        UserArticle.discovered_at < _to_db_datetime(until),
                    )
                rows = session.exec(
                    statement.order_by(col(UserArticle.discovered_at).desc()).limit(max(1, limit)),
                ).all()
                return [
                    SourceCorpusEntry(
                        source_id=f"article:{article.article_id}",
                        article_id=article.article_id,
                        title=article.title,
                        url=article.url,
                        source=article.source_domain,
                        published_at=_to_utc_aware_datetime(article.published_at),
                        clean_text=article.clean_text or "",
                    )
                    for article, _user_link in rows
                ]

            normalized_source_ids = tuple(dict.fromkeys(source_ids))
            article_ids: list[str] = []
            for source_id in normalized_source_ids:
                article_id = _article_id_from_source_id(source_id)
                if article_id is None:
                    raise ValueError(
                        f"Invalid source_id format: {source_id!r}. "
                        "Expected 'article:<article_id>'.",
                    )
                article_ids.append(article_id)

            rows = session.exec(
                select(Article)
                .join(
                    UserArticle,
                    col(UserArticle.article_id) == col(Article.article_id),
                )
                .where(
                    UserArticle.user_id == self.user_id,
                    col(Article.article_id).in_(article_ids),
                ),
            ).all()
            by_article_id = {row.article_id: row for row in rows}
            resolved: list[SourceCorpusEntry] = []
            for source_id in normalized_source_ids:
                article_id = _article_id_from_source_id(source_id)
                if article_id is None:
                    continue
                article = by_article_id.get(article_id)
                if article is None:
                    continue
                resolved.append(
                    SourceCorpusEntry(
                        source_id=f"article:{article.article_id}",
                        article_id=article.article_id,
                        title=article.title,
                        url=article.url,
                        source=article.source_domain,
                        published_at=_to_utc_aware_datetime(article.published_at),
                        clean_text=article.clean_text or "",
                    ),
                )
            return resolved

    def validate_user_source_ids(
        self,
        *,
        source_ids: tuple[str, ...],
    ) -> tuple[list[SourceCorpusEntry], list[str]]:
        """Validate that source IDs belong to current user via ``user_articles``."""

        normalized_source_ids = tuple(dict.fromkeys(source_ids))
        resolved = self.list_user_retrieval_articles(source_ids=normalized_source_ids)
        resolved_ids = {entry.source_id for entry in resolved}
        missing = [
            source_id for source_id in normalized_source_ids if source_id not in resolved_ids
        ]
        return resolved, missing

    # -- Stories ----------------------------------------------------------------

    def upsert_story_definition(self, payload: StoryDefinitionWrite) -> StoryDefinitionView:
        """Create or update pinned story definition."""

        now = utc_now()
        story_id = payload.story_id or str(uuid4())
        with Session(self.engine) as session:
            row = session.exec(
                select(UserStoryDefinition).where(
                    UserStoryDefinition.story_id == story_id,
                    UserStoryDefinition.user_id == self.user_id,
                ),
            ).one_or_none()
            if row is None:
                row = UserStoryDefinition(
                    story_id=story_id,
                    user_id=self.user_id,
                    name=payload.name,
                    description=payload.description,
                    target_language=payload.target_language,
                    priority=payload.priority,
                    enabled=payload.enabled,
                    created_at=now,
                    updated_at=now,
                )
            else:
                row.name = payload.name
                row.description = payload.description
                row.target_language = payload.target_language
                row.priority = payload.priority
                row.enabled = payload.enabled
                row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            return _to_story_definition_view(row)

    def list_story_definitions(
        self,
        *,
        include_disabled: bool = False,
    ) -> list[StoryDefinitionView]:
        """List user story definitions ordered by priority."""

        with Session(self.engine) as session:
            statement = (
                select(UserStoryDefinition)
                .where(col(UserStoryDefinition.user_id) == self.user_id)
                .order_by(
                    col(UserStoryDefinition.priority).asc(),
                    col(UserStoryDefinition.created_at).asc(),
                )
            )
            if not include_disabled:
                statement = statement.where(col(UserStoryDefinition.enabled).is_(True))
            rows = session.exec(statement).all()
            return [_to_story_definition_view(row) for row in rows]

    def replace_story_assignments(
        self,
        *,
        business_date: date,
        assignments: list[StoryAssignmentWrite],
    ) -> int:
        """Replace full assignment set for one user/date (idempotent rerun)."""

        with Session(self.engine) as session:
            session.exec(
                delete(StoryAssignment).where(
                    col(StoryAssignment.user_id) == self.user_id,
                    col(StoryAssignment.business_date) == business_date,
                ),
            )
            for assignment in assignments:
                session.add(
                    StoryAssignment(
                        user_id=self.user_id,
                        business_date=assignment.business_date,
                        article_id=assignment.article_id,
                        story_id=assignment.story_id,
                        story_key=assignment.story_key,
                        assignment_type=assignment.assignment_type,
                        score=assignment.score,
                        created_at=utc_now(),
                    ),
                )
            session.commit()
            return len(assignments)

    def list_story_assignments(self, *, business_date: date) -> list[StoryAssignmentView]:
        """List assignments for one business date."""

        with Session(self.engine) as session:
            rows = session.exec(
                select(StoryAssignment)
                .where(
                    StoryAssignment.user_id == self.user_id,
                    StoryAssignment.business_date == business_date,
                )
                .order_by(
                    col(StoryAssignment.story_key).asc(),
                    col(StoryAssignment.score).desc(),
                    col(StoryAssignment.article_id).asc(),
                ),
            ).all()
            return [
                StoryAssignmentView(
                    article_id=row.article_id,
                    story_id=row.story_id,
                    story_key=row.story_key,
                    assignment_type=row.assignment_type,
                    score=row.score,
                )
                for row in rows
            ]

    def replace_daily_story_snapshots(
        self,
        *,
        business_date: date,
        snapshots: list[DailyStorySnapshotWrite],
    ) -> int:
        """Replace full daily continuity snapshots for one date."""

        now = utc_now()
        with Session(self.engine) as session:
            session.exec(
                delete(DailyStorySnapshot).where(
                    col(DailyStorySnapshot.user_id) == self.user_id,
                    col(DailyStorySnapshot.business_date) == business_date,
                ),
            )
            for snapshot in snapshots:
                session.add(
                    DailyStorySnapshot(
                        user_id=self.user_id,
                        business_date=snapshot.business_date,
                        story_id=snapshot.story_id,
                        story_key=snapshot.story_key,
                        title=snapshot.title,
                        continuity_key=snapshot.continuity_key,
                        summary_json=json.dumps(
                            snapshot.summary,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        created_at=now,
                        updated_at=now,
                    ),
                )
            session.commit()
            return len(snapshots)

    def list_daily_story_snapshots(self, *, business_date: date) -> list[DailyStorySnapshotView]:
        """List persisted daily snapshots for one date."""

        with Session(self.engine) as session:
            rows = session.exec(
                select(DailyStorySnapshot)
                .where(
                    col(DailyStorySnapshot.user_id) == self.user_id,
                    col(DailyStorySnapshot.business_date) == business_date,
                )
                .order_by(col(DailyStorySnapshot.story_key).asc()),
            ).all()
            return [_to_daily_story_snapshot_view(row) for row in rows]

    def get_latest_daily_story_snapshots_before(
        self,
        *,
        business_date: date,
    ) -> list[DailyStorySnapshotView]:
        """Return latest prior-day snapshot set for continuity context."""

        with Session(self.engine) as session:
            latest_date = session.exec(
                select(col(DailyStorySnapshot.business_date))
                .where(
                    col(DailyStorySnapshot.user_id) == self.user_id,
                    col(DailyStorySnapshot.business_date) < business_date,
                )
                .order_by(col(DailyStorySnapshot.business_date).desc())
                .limit(1),
            ).one_or_none()
            if latest_date is None:
                return []
            rows = session.exec(
                select(DailyStorySnapshot)
                .where(
                    col(DailyStorySnapshot.user_id) == self.user_id,
                    col(DailyStorySnapshot.business_date) == latest_date,
                )
                .order_by(col(DailyStorySnapshot.story_key).asc()),
            ).all()
            return [_to_daily_story_snapshot_view(row) for row in rows]

    # -- Monitors ---------------------------------------------------------------

    def upsert_monitor_question(self, payload: MonitorQuestionWrite) -> MonitorQuestionView:
        """Create or update monitor prompt definition."""

        now = utc_now()
        monitor_id = payload.monitor_id or str(uuid4())
        with Session(self.engine) as session:
            row = session.exec(
                select(MonitorQuestion).where(
                    MonitorQuestion.monitor_id == monitor_id,
                    MonitorQuestion.user_id == self.user_id,
                ),
            ).one_or_none()
            if row is None:
                row = MonitorQuestion(
                    monitor_id=monitor_id,
                    user_id=self.user_id,
                    name=payload.name,
                    prompt=payload.prompt,
                    cadence=payload.cadence,
                    enabled=payload.enabled,
                    created_at=now,
                    updated_at=now,
                )
            else:
                row.name = payload.name
                row.prompt = payload.prompt
                row.cadence = payload.cadence
                row.enabled = payload.enabled
                row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            return _to_monitor_question_view(row)

    def list_monitor_questions(
        self,
        *,
        include_disabled: bool = False,
    ) -> list[MonitorQuestionView]:
        """List monitor prompts for current user."""

        with Session(self.engine) as session:
            statement = (
                select(MonitorQuestion)
                .where(col(MonitorQuestion.user_id) == self.user_id)
                .order_by(col(MonitorQuestion.created_at).asc())
            )
            if not include_disabled:
                statement = statement.where(col(MonitorQuestion.enabled).is_(True))
            rows = session.exec(statement).all()
            return [_to_monitor_question_view(row) for row in rows]

    # -- Outputs ----------------------------------------------------------------

    def upsert_user_output(self, payload: UserOutputUpsert) -> UserOutputView:
        """Upsert stable business output row and replace its blocks."""

        with Session(self.engine) as session:
            row = self._upsert_user_output_in_session(session=session, payload=payload)
            session.commit()

            refreshed = session.exec(
                select(UserOutput).where(
                    col(UserOutput.user_id) == self.user_id,
                    col(UserOutput.output_id) == row.output_id,
                ),
            ).one()
            block_rows = session.exec(
                select(UserOutputBlock)
                .where(
                    col(UserOutputBlock.user_id) == self.user_id,
                    col(UserOutputBlock.output_id) == row.output_id,
                )
                .order_by(col(UserOutputBlock.block_order).asc()),
            ).all()
            return _to_user_output_view(refreshed, block_rows)

    def get_user_output(self, *, output_id: str) -> UserOutputView | None:
        """Fetch one output with ordered blocks."""

        with Session(self.engine) as session:
            row = session.exec(
                select(UserOutput).where(
                    col(UserOutput.user_id) == self.user_id,
                    col(UserOutput.output_id) == output_id,
                ),
            ).one_or_none()
            if row is None:
                return None
            blocks = session.exec(
                select(UserOutputBlock)
                .where(
                    col(UserOutputBlock.user_id) == self.user_id,
                    col(UserOutputBlock.output_id) == row.output_id,
                )
                .order_by(col(UserOutputBlock.block_order).asc()),
            ).all()
            return _to_user_output_view(row, blocks)

    def list_user_outputs(
        self,
        *,
        kind: str | None = None,
        business_date: date | None = None,
        limit: int = 50,
    ) -> list[UserOutputView]:
        """List recent outputs with blocks."""

        with Session(self.engine) as session:
            statement = (
                select(UserOutput)
                .where(col(UserOutput.user_id) == self.user_id)
                .order_by(col(UserOutput.updated_at).desc())
                .limit(max(1, limit))
            )
            if kind is not None:
                statement = statement.where(col(UserOutput.kind) == kind)
            if business_date is not None:
                statement = statement.where(col(UserOutput.business_date) == business_date)
            rows = session.exec(statement).all()
            if not rows:
                return []
            output_ids = [row.output_id for row in rows]
            block_rows = session.exec(
                select(UserOutputBlock).where(
                    col(UserOutputBlock.user_id) == self.user_id,
                    col(UserOutputBlock.output_id).in_(output_ids),
                ),
            ).all()
            blocks_by_output: dict[str, list[UserOutputBlock]] = {}
            for block in block_rows:
                blocks_by_output.setdefault(block.output_id, []).append(block)
            for values in blocks_by_output.values():
                values.sort(key=lambda row: row.block_order)
            return [
                _to_user_output_view(row, blocks_by_output.get(row.output_id, [])) for row in rows
            ]

    # -- Feedback & read state --------------------------------------------------

    def add_read_state_event(self, payload: ReadStateEventWrite) -> None:
        """Persist read/open event for output or output block."""

        with Session(self.engine) as session:
            self._ensure_user_output_exists(session=session, output_id=payload.output_id)
            if payload.output_block_id is not None:
                self._ensure_block_matches_output(
                    session=session,
                    output_id=payload.output_id,
                    output_block_id=payload.output_block_id,
                )
            session.add(
                ReadStateEvent(
                    user_id=self.user_id,
                    output_id=payload.output_id,
                    output_block_id=payload.output_block_id,
                    event_type=payload.event_type,
                    details_json=(
                        json.dumps(payload.details, ensure_ascii=False, sort_keys=True)
                        if payload.details
                        else None
                    ),
                    created_at=utc_now(),
                ),
            )
            session.commit()

    def add_output_feedback(self, payload: OutputFeedbackWrite) -> None:
        """Persist feedback against output or block."""

        with Session(self.engine) as session:
            self._ensure_user_output_exists(session=session, output_id=payload.output_id)
            if payload.output_block_id is not None:
                self._ensure_block_matches_output(
                    session=session,
                    output_id=payload.output_id,
                    output_block_id=payload.output_block_id,
                )
            session.add(
                OutputFeedback(
                    user_id=self.user_id,
                    output_id=payload.output_id,
                    output_block_id=payload.output_block_id,
                    feedback_type=payload.feedback_type,
                    value=payload.value,
                    details_json=(
                        json.dumps(payload.details, ensure_ascii=False, sort_keys=True)
                        if payload.details
                        else None
                    ),
                    created_at=utc_now(),
                ),
            )
            session.commit()

    def list_recent_read_source_ids(self, *, days: int = 3) -> set[str]:
        """Return source ids from output blocks that were marked as viewed/opened recently."""

        cutoff = _to_db_datetime(utc_now() - timedelta(days=max(1, days)))
        with Session(self.engine) as session:
            rows = session.exec(
                select(col(UserOutputBlock.source_ids_json))
                .join(
                    ReadStateEvent,
                    and_(
                        col(ReadStateEvent.user_id) == col(UserOutputBlock.user_id),
                        col(ReadStateEvent.output_id) == col(UserOutputBlock.output_id),
                        col(ReadStateEvent.output_block_id) == col(UserOutputBlock.block_id),
                    ),
                )
                .where(
                    col(UserOutputBlock.user_id) == self.user_id,
                    col(ReadStateEvent.created_at) >= cutoff,
                    col(ReadStateEvent.output_block_id).is_not(None),
                    col(ReadStateEvent.event_type).in_(("open", "view", "expand")),
                ),
            ).all()

        source_ids: set[str] = set()
        for row in rows:
            source_ids_json = row if isinstance(row, str) else str(row)
            try:
                parsed = json.loads(source_ids_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, list):
                continue
            for item in parsed:
                if isinstance(item, str) and item:
                    source_ids.add(item)
        return source_ids

    # -- Stats ------------------------------------------------------------------

    def intelligence_stats_snapshot(self, *, since: datetime) -> dict[str, int]:
        """Aggregate domain counters for observability windows."""

        since_date = _to_utc_aware_datetime(since).date().isoformat()
        since_dt = _to_utc_aware_datetime(since).replace(tzinfo=None).isoformat(sep=" ")

        queries = {
            "stories_total": (
                "SELECT COUNT(*) AS value FROM user_story_definitions WHERE user_id = ?",
                (self.user_id,),
            ),
            "stories_enabled": (
                "SELECT COUNT(*) AS value FROM user_story_definitions "
                "WHERE user_id = ? AND enabled = 1",
                (self.user_id,),
            ),
            "story_assignments_window": (
                "SELECT COUNT(*) AS value FROM story_assignments "
                "WHERE user_id = ? AND business_date >= ?",
                (self.user_id, since_date),
            ),
            "story_snapshots_window": (
                "SELECT COUNT(*) AS value FROM daily_story_snapshots "
                "WHERE user_id = ? AND business_date >= ?",
                (self.user_id, since_date),
            ),
            "outputs_window": (
                "SELECT COUNT(*) AS value FROM user_outputs WHERE user_id = ? AND updated_at >= ?",
                (self.user_id, since_dt),
            ),
            "outputs_highlights_window": (
                "SELECT COUNT(*) AS value FROM user_outputs "
                "WHERE user_id = ? AND kind = 'highlights' AND updated_at >= ?",
                (self.user_id, since_dt),
            ),
            "outputs_story_details_window": (
                "SELECT COUNT(*) AS value FROM user_outputs "
                "WHERE user_id = ? AND kind = 'story_details' AND updated_at >= ?",
                (self.user_id, since_dt),
            ),
            "outputs_monitor_window": (
                "SELECT COUNT(*) AS value FROM user_outputs "
                "WHERE user_id = ? AND kind = 'monitor_answer' AND updated_at >= ?",
                (self.user_id, since_dt),
            ),
            "outputs_qa_window": (
                "SELECT COUNT(*) AS value FROM user_outputs "
                "WHERE user_id = ? AND kind = 'qa_answer' AND updated_at >= ?",
                (self.user_id, since_dt),
            ),
            "read_state_events_window": (
                "SELECT COUNT(*) AS value FROM read_state_events "
                "WHERE user_id = ? AND created_at >= ?",
                (self.user_id, since_dt),
            ),
            "feedback_events_window": (
                "SELECT COUNT(*) AS value FROM output_feedback "
                "WHERE user_id = ? AND created_at >= ?",
                (self.user_id, since_dt),
            ),
        }
        result: dict[str, int] = {}
        for key, (query, params) in queries.items():
            row = self._connection.execute(query, params).fetchone()
            result[key] = int(row["value"]) if row is not None else 0
        return result

    # -- Output persistence helpers (private) -----------------------------------

    def _resolve_existing_user_output(
        self,
        *,
        session: Session,
        payload: UserOutputUpsert,
    ) -> UserOutput | None:
        if payload.request_id is not None:
            return session.exec(
                select(UserOutput).where(
                    col(UserOutput.user_id) == self.user_id,
                    col(UserOutput.kind) == payload.kind,
                    col(UserOutput.request_id) == payload.request_id,
                ),
            ).one_or_none()
        if payload.monitor_id is not None:
            return session.exec(
                select(UserOutput).where(
                    col(UserOutput.user_id) == self.user_id,
                    col(UserOutput.kind) == payload.kind,
                    col(UserOutput.business_date) == payload.business_date,
                    col(UserOutput.monitor_id) == payload.monitor_id,
                ),
            ).one_or_none()
        if payload.story_id is not None:
            return session.exec(
                select(UserOutput).where(
                    col(UserOutput.user_id) == self.user_id,
                    col(UserOutput.kind) == payload.kind,
                    col(UserOutput.business_date) == payload.business_date,
                    col(UserOutput.story_id) == payload.story_id,
                ),
            ).one_or_none()
        return session.exec(
            select(UserOutput).where(
                col(UserOutput.user_id) == self.user_id,
                col(UserOutput.kind) == payload.kind,
                col(UserOutput.business_date) == payload.business_date,
                col(UserOutput.story_id).is_(None),
                col(UserOutput.monitor_id).is_(None),
                col(UserOutput.request_id).is_(None),
            ),
        ).one_or_none()

    def _ensure_user_output_exists(self, *, session: Session, output_id: str) -> None:
        row = session.exec(
            select(col(UserOutput.output_id)).where(
                col(UserOutput.user_id) == self.user_id,
                col(UserOutput.output_id) == output_id,
            ),
        ).one_or_none()
        if row is None:
            raise ValueError(f"Output not found: {output_id}")

    def _ensure_block_matches_output(
        self,
        *,
        session: Session,
        output_id: str,
        output_block_id: int,
    ) -> None:
        block = session.exec(
            select(col(UserOutputBlock.block_id)).where(
                col(UserOutputBlock.user_id) == self.user_id,
                col(UserOutputBlock.output_id) == output_id,
                col(UserOutputBlock.block_id) == output_block_id,
            ),
        ).one_or_none()
        if block is None:
            raise ValueError(
                f"Block {output_block_id} does not belong to output {output_id}",
            )

    def _upsert_user_output_in_session(
        self,
        *,
        session: Session,
        payload: UserOutputUpsert,
    ) -> UserOutput:
        now = utc_now()
        row = self._resolve_existing_user_output(session=session, payload=payload)
        if row is None:
            row = UserOutput(
                output_id=str(uuid4()),
                user_id=self.user_id,
                kind=payload.kind,
                business_date=payload.business_date,
                story_id=payload.story_id,
                monitor_id=payload.monitor_id,
                request_id=payload.request_id,
                task_id=payload.task_id,
                status=payload.status,
                title=payload.title,
                payload_json=json.dumps(payload.payload, ensure_ascii=False, sort_keys=True),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
        else:
            row.business_date = payload.business_date
            row.story_id = payload.story_id
            row.monitor_id = payload.monitor_id
            row.request_id = payload.request_id
            row.task_id = payload.task_id
            row.status = payload.status
            row.title = payload.title
            row.payload_json = json.dumps(payload.payload, ensure_ascii=False, sort_keys=True)
            row.updated_at = now
            session.add(row)

        session.exec(
            delete(UserOutputBlock).where(
                col(UserOutputBlock.user_id) == self.user_id,
                col(UserOutputBlock.output_id) == row.output_id,
            ),
        )
        for block in payload.blocks:
            session.add(
                UserOutputBlock(
                    user_id=self.user_id,
                    output_id=row.output_id,
                    block_order=block.block_order,
                    text=block.text,
                    source_ids_json=json.dumps(
                        list(block.source_ids),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    created_at=now,
                ),
            )
        return row

    def _ensure_user_article_link(self, *, session: Session, article_id: str) -> bool:
        existing = session.exec(
            select(UserArticle).where(
                UserArticle.user_id == self.user_id,
                UserArticle.article_id == article_id,
            ),
        ).one_or_none()
        if existing is not None:
            return False

        session.add(
            UserArticle(
                user_id=self.user_id,
                article_id=article_id,
                discovered_at=utc_now(),
                state="active",
                deleted_at=None,
            ),
        )
        return True

    def _ensure_actor_context(self) -> None:
        with Session(self.engine) as session:
            user = session.get(AppUser, self.user_id)
            if user is None:
                user = AppUser(
                    user_id=self.user_id,
                    display_name=self.user_name,
                    created_at=utc_now(),
                )
                session.add(user)
            session.commit()

    def _find_existing_article(
        self,
        session: Session,
        article: NormalizedArticle,
    ) -> Article | None:
        alias = session.exec(
            select(ArticleExternalId).where(
                ArticleExternalId.source_name == article.source_name,
                ArticleExternalId.external_id == article.external_id,
            ),
        ).one_or_none()
        if alias is not None:
            return session.get(Article, alias.article_id)

        if article.url_canonical and _use_url_timestamp_fallback(article):
            by_url = session.exec(
                select(Article).where(
                    Article.source_name == article.source_name,
                    Article.url_canonical == article.url_canonical,
                ),
            ).first()
            if by_url is not None:
                return by_url

        fallback_key = _build_fallback_key(article)
        if _use_url_timestamp_fallback(article):
            return session.exec(
                select(Article).where(
                    Article.source_name == article.source_name,
                    Article.fallback_key == fallback_key,
                ),
            ).one_or_none()

        return session.exec(
            select(Article).where(
                Article.source_name == article.source_name,
                Article.fallback_key == fallback_key,
                col(Article.external_id).like("generated:%"),
            ),
        ).one_or_none()

    def _try_insert_article(
        self,
        *,
        session: Session,
        article: NormalizedArticle,
        run_id: str,
    ) -> UpsertResult | None:
        article_id = str(uuid4())
        row = Article(
            article_id=article_id,
            source_name=article.source_name,
            external_id=article.external_id,
            url=article.url,
            url_canonical=article.url_canonical,
            url_hash=article.url_hash,
            title=article.title,
            source_domain=article.source_domain,
            published_at=_to_db_datetime(article.published_at),
            language_detected=article.language_detected,
            content_raw=article.content_raw,
            summary_raw=article.summary_raw,
            is_full_content=article.is_full_content,
            clean_text=article.clean_text,
            clean_text_chars=article.clean_text_chars,
            is_truncated=article.is_truncated,
            ingested_at=utc_now(),
            fallback_key=_target_fallback_key(article, existing_fallback_key=None),
            last_processed_run_id=run_id,
        )
        session.add(row)

        self._insert_external_alias(
            session=session,
            source_name=article.source_name,
            external_id=article.external_id,
            article_id=article_id,
            is_primary=True,
        )

        try:
            session.commit()
            return UpsertResult(article_id=article_id, action=UpsertAction.INSERTED)
        except IntegrityError:
            session.rollback()
            return None

    def _ensure_external_alias(
        self,
        *,
        session: Session,
        source_name: str,
        external_id: str,
        article_id: str,
    ) -> None:
        mapped = session.exec(
            select(ArticleExternalId).where(
                ArticleExternalId.source_name == source_name,
                ArticleExternalId.external_id == external_id,
            ),
        ).one_or_none()

        if mapped is None:
            self._insert_external_alias(
                session=session,
                source_name=source_name,
                external_id=external_id,
                article_id=article_id,
                is_primary=False,
            )
            return

        if mapped.article_id != article_id:
            raise RuntimeError(
                f"External ID collision for {source_name}:{external_id}: "
                f"{mapped.article_id} != {article_id}",
            )

    def _insert_external_alias(
        self,
        *,
        session: Session,
        source_name: str,
        external_id: str,
        article_id: str,
        is_primary: bool,
    ) -> None:
        session.add(
            ArticleExternalId(
                source_name=source_name,
                external_id=external_id,
                article_id=article_id,
                is_primary=is_primary,
                created_at=utc_now(),
            ),
        )


def _is_generated_external_id(external_id: str) -> bool:
    return external_id.startswith("generated:")


def _use_url_timestamp_fallback(article: NormalizedArticle) -> bool:
    return (not article.external_id) or _is_generated_external_id(article.external_id)


def _build_fallback_key(article: NormalizedArticle) -> str:
    published_at = _to_utc_aware_datetime(article.published_at).isoformat()
    return f"{article.source_name}|{article.url_hash}|{published_at}"


def _target_fallback_key(
    article: NormalizedArticle,
    existing_fallback_key: str | None,
) -> str | None:
    if _use_url_timestamp_fallback(article):
        return _build_fallback_key(article)
    return existing_fallback_key


def _row_changed(
    existing: Article,
    article: NormalizedArticle,
    target_fallback_key: str | None,
) -> bool:
    return any(
        [
            existing.url != article.url,
            existing.url_canonical != article.url_canonical,
            existing.url_hash != article.url_hash,
            existing.title != article.title,
            existing.source_domain != article.source_domain,
            not _same_timestamp(existing.published_at, article.published_at),
            existing.language_detected != article.language_detected,
            existing.content_raw != article.content_raw,
            existing.summary_raw != article.summary_raw,
            existing.is_full_content != article.is_full_content,
            existing.clean_text != article.clean_text,
            existing.clean_text_chars != article.clean_text_chars,
            existing.is_truncated != article.is_truncated,
            existing.fallback_key != target_fallback_key,
        ],
    )


def _pack_vector(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _unpack_vector(blob: bytes, dim: int) -> list[float]:
    unpacked = struct.unpack(f"{dim}f", blob)
    return list(unpacked)


def _to_db_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _to_utc_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _same_timestamp(left: datetime, right: datetime) -> bool:
    return _to_utc_aware_datetime(left) == _to_utc_aware_datetime(right)


# ---------------------------------------------------------------------------
# Intelligence view converters
# ---------------------------------------------------------------------------


def _to_story_definition_view(row: UserStoryDefinition) -> StoryDefinitionView:
    return StoryDefinitionView(
        story_id=row.story_id,
        user_id=row.user_id,
        name=row.name,
        description=row.description,
        target_language=row.target_language,
        priority=row.priority,
        enabled=row.enabled,
        created_at=_to_utc_aware_datetime(row.created_at),
        updated_at=_to_utc_aware_datetime(row.updated_at),
    )


def _to_monitor_question_view(row: MonitorQuestion) -> MonitorQuestionView:
    return MonitorQuestionView(
        monitor_id=row.monitor_id,
        user_id=row.user_id,
        name=row.name,
        prompt=row.prompt,
        cadence=row.cadence,
        enabled=row.enabled,
        created_at=_to_utc_aware_datetime(row.created_at),
        updated_at=_to_utc_aware_datetime(row.updated_at),
    )


def _to_daily_story_snapshot_view(row: DailyStorySnapshot) -> DailyStorySnapshotView:
    summary: dict[str, object] = {}
    try:
        parsed = json.loads(row.summary_json)
        if isinstance(parsed, dict):
            summary = parsed
    except json.JSONDecodeError:
        summary = {}
    return DailyStorySnapshotView(
        business_date=row.business_date,
        story_id=row.story_id,
        story_key=row.story_key,
        title=row.title,
        continuity_key=row.continuity_key,
        summary=summary,
        updated_at=_to_utc_aware_datetime(row.updated_at),
    )


def _to_user_output_view(
    row: UserOutput,
    block_rows: Sequence[UserOutputBlock],
) -> UserOutputView:
    payload: dict[str, object] = {}
    try:
        parsed_payload = json.loads(row.payload_json)
        if isinstance(parsed_payload, dict):
            payload = parsed_payload
    except json.JSONDecodeError:
        payload = {}
    blocks: list[UserOutputBlockWrite] = []
    for block_row in block_rows:
        try:
            parsed_source_ids = json.loads(block_row.source_ids_json)
        except json.JSONDecodeError:
            parsed_source_ids = []
        source_ids = tuple(
            value for value in parsed_source_ids if isinstance(value, str) and value.strip()
        )
        blocks.append(
            UserOutputBlockWrite(
                block_order=block_row.block_order,
                text=block_row.text,
                source_ids=source_ids,
            ),
        )
    return UserOutputView(
        output_id=row.output_id,
        user_id=row.user_id,
        kind=row.kind,
        business_date=row.business_date,
        status=row.status,
        story_id=row.story_id,
        monitor_id=row.monitor_id,
        request_id=row.request_id,
        task_id=row.task_id,
        title=row.title,
        payload=payload,
        created_at=_to_utc_aware_datetime(row.created_at),
        updated_at=_to_utc_aware_datetime(row.updated_at),
        blocks=blocks,
    )


def _article_id_from_source_id(source_id: str) -> str | None:
    prefix = "article:"
    if not source_id.startswith(prefix):
        return None
    article_id = source_id[len(prefix) :].strip()
    if not article_id:
        return None
    return article_id

"""Task launcher: DEDUPLICATE — merge duplicate news via embedding pre-filter + LLM."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from news_recap.recap.dedup.cluster import group_similar
from news_recap.recap.dedup.embedder import build_embedder
from news_recap.recap.models import DigestArticle
from news_recap.recap.storage.pipeline_io import materialize_step, next_batch_number
from news_recap.recap.tasks.base import (
    FlowContext,
    RecapPipelineError,
    TaskLauncher,
    log_parse_failure,
    read_agent_stdout,
)
from news_recap.recap.tasks.parallel import submit_and_collect
from news_recap.recap.tasks.prompts import (
    RECAP_DEDUP_MULTI_PROMPT,
    RECAP_DEDUP_PROMPT,
    render_prompt,
)

logger = logging.getLogger(__name__)

_MAX_PARALLEL = 4
_MIN_MERGE_SIZE = 2
_BATCH_THRESHOLD = 8  # clusters above this size get their own task
_MAX_BATCH_ARTICLES = 40  # soft cap on articles per batched task

# A batch is a list of clusters; each cluster is a list of article IDs.
type ClusterBatch = list[list[str]]

_CLUSTER_HEADER_RE = re.compile(r"^CLUSTER\s+\d+:", re.MULTILINE)
_MERGED_RE = re.compile(r"^MERGED:\s*(.+)$", re.IGNORECASE)
_SINGLE_RE = re.compile(r"^SINGLE:\s*(\d+)\s*$", re.IGNORECASE)


@dataclass(slots=True)
class _MergeAction:
    """Parsed merge group from LLM output."""

    merged_text: str
    indices: list[int]


@dataclass(slots=True)
class _DedupResult:
    """Parsed dedup output for one cluster."""

    merges: list[_MergeAction]
    singles: list[int]


def _build_embedding_text(article: DigestArticle) -> str:
    title = (article.enriched_title or article.title).strip()
    body = (article.enriched_text or article.clean_text).strip()
    if title and body:
        return f"{title}. {body}"
    return title or body or f"[article:{article.article_id}]"


def _build_articles_block(articles: list[DigestArticle]) -> str:
    lines: list[str] = []
    for i, a in enumerate(articles, 1):
        title = a.enriched_title or a.title
        lines.append(f"{i}: [{a.source}] {title}")
    return "\n".join(lines)


def _batch_clusters(groups: list[list[str]]) -> list[ClusterBatch]:
    """Pack small clusters into batches; large clusters get their own task.

    Clusters with more than *_BATCH_THRESHOLD* articles each become a
    single-cluster batch. Smaller clusters are accumulated greedily
    (in insertion order) until *_MAX_BATCH_ARTICLES* would be exceeded.

    >>> _batch_clusters([])
    []
    >>> result = _batch_clusters([[str(i) for i in range(10)]])
    >>> len(result) == 1 and len(result[0]) == 1  # solo large cluster
    True
    """
    batches: list[ClusterBatch] = []
    current: ClusterBatch = []
    current_size = 0
    for g in groups:
        if len(g) > _BATCH_THRESHOLD:
            batches.append([g])
            continue
        if current and current_size + len(g) > _MAX_BATCH_ARTICLES:
            batches.append(current)
            current, current_size = [], 0
        current.append(g)
        current_size += len(g)
    if current:
        batches.append(current)
    return batches


def _build_multi_clusters_block(
    batch: ClusterBatch,
    id_to_article: dict[str, DigestArticle],
) -> str:
    parts: list[str] = []
    for i, cluster in enumerate(batch, 1):
        articles = [id_to_article[aid] for aid in cluster]
        header = f"=== CLUSTER {i} ({len(cluster)} articles) ==="
        parts.append(f"{header}\n{_build_articles_block(articles)}")
    return "\n\n".join(parts)


def parse_multi_dedup_output(text: str, batch: ClusterBatch) -> list[_DedupResult]:
    """Parse multi-cluster MERGED/SINGLE output into one ``_DedupResult`` per cluster.

    Raises ``RecapPipelineError`` when the number of ``CLUSTER N:`` headers in
    *text* does not match the number of clusters in *batch*.
    """
    sections = _CLUSTER_HEADER_RE.split(text)
    cluster_sections = sections[1:]  # sections[0] is text before the first header

    if len(cluster_sections) != len(batch):
        log_parse_failure("Dedup", text, log=logger)
        raise RecapPipelineError(
            "recap_dedup",
            f"Expected {len(batch)} CLUSTER header(s) in output, "
            f"found {len(cluster_sections)} — malformed or missing cluster headers",
        )

    return [
        parse_dedup_output(section, len(cluster))
        for section, cluster in zip(cluster_sections, batch, strict=False)
    ]


def parse_dedup_output(text: str, expected_count: int) -> _DedupResult:
    """Parse MERGED/SINGLE lines from LLM dedup stdout.

    Missing numbers are treated as singles with a warning.
    """
    parser = _DedupParser(expected_count)
    parser.parse(text)
    return parser.result()


@dataclass
class _DedupParser:
    """Stateful parser for MERGED/SINGLE dedup output."""

    expected_count: int
    _merges: list[_MergeAction] = dataclass_field(default_factory=list)
    _singles: list[int] = dataclass_field(default_factory=list)
    _seen: set[int] = dataclass_field(default_factory=set)
    _valid: set[int] = dataclass_field(init=False)

    def __post_init__(self) -> None:
        self._valid = set(range(1, self.expected_count + 1))

    def parse(self, text: str) -> None:
        lines = text.splitlines()
        pos = 0
        while pos < len(lines):
            line = lines[pos].strip()
            if not line:
                pos += 1
                continue

            m_merged = _MERGED_RE.match(line)
            if m_merged:
                pos = self._consume_merged(lines, pos, m_merged.group(1).strip())
                continue

            m_single = _SINGLE_RE.match(line)
            if m_single:
                num = int(m_single.group(1))
                if num in self._valid and num not in self._seen:
                    self._singles.append(num)
                    self._seen.add(num)

            pos += 1

    def _consume_merged(self, lines: list[str], pos: int, merged_text: str) -> int:
        pos += 1
        while pos < len(lines) and not lines[pos].strip():
            pos += 1
        if pos < len(lines):
            nums = _parse_numbers(lines[pos].strip(), self._valid)
            new_nums = [n for n in nums if n not in self._seen]
            if len(new_nums) >= _MIN_MERGE_SIZE:
                self._merges.append(_MergeAction(merged_text=merged_text, indices=new_nums))
                self._seen.update(new_nums)
            elif new_nums:
                self._singles.extend(new_nums)
                self._seen.update(new_nums)
        return pos + 1

    def result(self) -> _DedupResult:
        missing = self._valid - self._seen
        if missing:
            logger.warning(
                "[cyan]dedup:[/cyan] LLM output missing %d number(s): %s — treating as singles",
                len(missing),
                sorted(missing),
            )
            self._singles.extend(sorted(missing))
        return _DedupResult(merges=self._merges, singles=self._singles)


def _parse_numbers(text: str, valid: set[int]) -> list[int]:
    nums: list[int] = []
    for raw_token in re.split(r"[,\s]+", text):
        cleaned = raw_token.strip()
        if cleaned.isdigit():
            n = int(cleaned)
            if n in valid:
                nums.append(n)
    return nums


class Deduplicate(TaskLauncher):
    """Merge duplicate news: embedding pre-filter + per-cluster LLM calls."""

    name = "deduplicate"

    def execute(self) -> None:
        ctx = self.ctx
        articles = ctx.digest.articles
        if len(articles) < _MIN_MERGE_SIZE:
            logger.info("[cyan]dedup:[/cyan] Fewer than 2 articles, skipping")
            return

        groups = _compute_groups(ctx, articles)
        if not groups:
            return

        id_to_article = {a.article_id: a for a in articles}
        batch_results, n_failed = _run_llm_dedup(ctx, groups, id_to_article)

        remove_ids: set[str] = set()
        merge_count = 0
        for group_ids, result in batch_results:
            for merge in result.merges:
                _apply_merge(group_ids, merge, id_to_article, remove_ids)
                merge_count += 1

        if remove_ids:
            _update_pipeline_state(ctx, remove_ids, batch_results, id_to_article, merge_count)
        else:
            logger.info("[cyan]dedup:[/cyan] No duplicates found by LLM")

        if n_failed > 0:
            self.fully_completed = False
            logger.warning(
                "[cyan]dedup:[/cyan] %d cluster(s) failed — partial results saved",
                n_failed,
            )


def _compute_groups(ctx: FlowContext, articles: list[DigestArticle]) -> list[list[str]]:
    """Compute embeddings and group articles by similarity."""
    embedder = build_embedder(ctx.inp.dedup_model_name, allow_fallback=True)
    texts = [_build_embedding_text(a) for a in articles]
    ids = [a.article_id for a in articles]

    logger.info("[cyan]dedup:[/cyan] Computing embeddings for %d articles", len(articles))
    vectors = embedder.embed(texts)
    embeddings: dict[str, list[float]] = dict(zip(ids, vectors, strict=True))

    groups = group_similar(ids, embeddings, ctx.inp.dedup_threshold)
    if not groups:
        logger.info("[cyan]dedup:[/cyan] No similar groups found, skipping LLM phase")
        return []

    total_grouped = sum(len(g) for g in groups)
    logger.info(
        "[cyan]dedup:[/cyan] %d groups with %d articles (threshold=%.2f)",
        len(groups),
        total_grouped,
        ctx.inp.dedup_threshold,
    )
    return groups


def _log_batch_result(
    batch_num: int,
    batch: ClusterBatch,
    results: list[_DedupResult],
) -> None:
    """Log a one-line per-batch dedup summary after the agent finishes."""
    total_merges = sum(len(r.merges) for r in results)
    merged_articles = sum(len(m.indices) for r in results for m in r.merges)
    removed = sum(len(m.indices) - 1 for r in results for m in r.merges)
    n_clusters = len(batch)
    if total_merges:
        logger.info(
            "[cyan]dedup:[/cyan] Batch %d result: %d/%d cluster(s) have duplicates"
            " — %d group(s), %d articles merged, %d removed",
            batch_num,
            sum(1 for r in results if r.merges),
            n_clusters,
            total_merges,
            merged_articles,
            removed,
        )
    else:
        logger.info(
            "[cyan]dedup:[/cyan] Batch %d result: no duplicates in %d cluster(s)",
            batch_num,
            n_clusters,
        )


def _run_llm_dedup(
    ctx: FlowContext,
    groups: list[list[str]],
    id_to_article: dict[str, DigestArticle],
) -> tuple[list[tuple[list[str], _DedupResult]], int]:
    """Submit batched LLM calls and return flattened (cluster, result) pairs."""
    batches = _batch_clusters(groups)
    logger.info("[cyan]dedup:[/cyan] %d cluster(s) → %d batch task(s)", len(groups), len(batches))

    def prepare(batch: ClusterBatch, batch_num: int) -> str:
        if len(batch) == 1:
            cluster = batch[0]
            articles = [id_to_article[aid] for aid in cluster]
            prompt = render_prompt(
                RECAP_DEDUP_PROMPT,
                ctx.inp.prompt_backend,
                article_count=str(len(cluster)),
                articles_block=_build_articles_block(articles),
            )
        else:
            prompt = render_prompt(
                RECAP_DEDUP_MULTI_PROMPT,
                ctx.inp.prompt_backend,
                clusters_block=_build_multi_clusters_block(batch, id_to_article),
            )
        task_id = materialize_step(
            ctx.workdir_mgr,
            ctx.inp,
            step_name="recap_dedup",
            batch=batch_num,
            prompt=prompt,
        )
        total = sum(len(c) for c in batch)
        logger.info(
            "[cyan]dedup:[/cyan] Batch %d — %d cluster(s), %d articles",
            batch_num,
            len(batch),
            total,
        )
        return task_id

    def parse(
        task_id: str,
        batch: ClusterBatch,
        batch_num: int,
    ) -> tuple[ClusterBatch, list[_DedupResult]]:
        stdout_path = ctx.pdir / task_id / "output" / "agent_stdout.log"
        text = read_agent_stdout(stdout_path, "recap_dedup")
        if len(batch) == 1:
            result = parse_dedup_output(text, len(batch[0]))
            results = [result]
        else:
            results = parse_multi_dedup_output(text, batch)
        _log_batch_result(batch_num, batch, results)
        return batch, results

    raw_results, n_failed, _ = submit_and_collect(
        ctx,
        batches,
        step_name="recap_dedup",
        step_label="dedup batch",
        start_batch=next_batch_number(ctx.pdir, "recap_dedup") - 1,
        max_parallel=ctx.inp.effective_max_parallel(_MAX_PARALLEL),
        prepare_fn=prepare,
        parse_fn=parse,
        logger=logger,
    )

    flat: list[tuple[list[str], _DedupResult]] = [
        (cluster, result)
        for batch_clusters, results_list in raw_results
        for cluster, result in zip(batch_clusters, results_list, strict=False)
    ]
    return flat, n_failed


def _update_pipeline_state(
    ctx: FlowContext,
    remove_ids: set[str],
    batch_results: list[tuple[list[str], _DedupResult]],
    id_to_article: dict[str, DigestArticle],
    merge_count: int,
) -> None:
    """Remove duplicates from digest and update downstream pipeline state."""
    ctx.digest.articles = [a for a in ctx.digest.articles if a.article_id not in remove_ids]

    if "kept_entries" in ctx.state:
        ctx.state["kept_entries"] = [
            e for e in ctx.state["kept_entries"] if e.source_id not in remove_ids
        ]

    enriched = ctx.state.get("enriched_articles", {})
    for group_ids, result in batch_results:
        for merge in result.merges:
            keeper_id = _find_keeper_id(group_ids, merge, id_to_article, remove_ids)
            if keeper_id:
                enriched[keeper_id] = merge.merged_text
    ctx.state["enriched_articles"] = enriched

    logger.info(
        "[cyan]dedup:[/cyan] %d merge(s) → removed %d duplicate(s), %d articles remain",
        merge_count,
        len(remove_ids),
        len(ctx.digest.articles),
    )


def _resolve_merged_articles(
    group_ids: list[str],
    merge: _MergeAction,
    id_to_article: dict[str, DigestArticle],
) -> list[DigestArticle]:
    merged_article_ids = [group_ids[idx - 1] for idx in merge.indices]
    return [id_to_article[aid] for aid in merged_article_ids if aid in id_to_article]


def _apply_merge(
    group_ids: list[str],
    merge: _MergeAction,
    id_to_article: dict[str, DigestArticle],
    remove_ids: set[str],
) -> None:
    """Apply a single merge: keep the longest article, absorb others."""
    merged_articles = _resolve_merged_articles(group_ids, merge, id_to_article)

    if len(merged_articles) < _MIN_MERGE_SIZE:
        return

    keeper = max(merged_articles, key=lambda a: len(a.clean_text))
    keeper.enriched_title = merge.merged_text

    for other in merged_articles:
        if other.article_id == keeper.article_id:
            continue
        keeper.alt_urls.append({"url": other.url, "source": other.source})
        remove_ids.add(other.article_id)


def _find_keeper_id(
    group_ids: list[str],
    merge: _MergeAction,
    id_to_article: dict[str, DigestArticle],
    remove_ids: set[str],
) -> str | None:
    """Return the article ID of the keeper in a merge group."""
    merged_articles = _resolve_merged_articles(group_ids, merge, id_to_article)
    if len(merged_articles) < _MIN_MERGE_SIZE:
        return None
    kept = [a for a in merged_articles if a.article_id not in remove_ids]
    return kept[0].article_id if kept else None

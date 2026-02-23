#!/usr/bin/env python3
"""Probe article source domains for fetch success/failure.

Samples articles per domain, attempts HTTP fetch + text extraction via
ResourceLoader, and classifies results as open / partial / blocked.
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from news_recap.ingestion.models import Article, DailyStore
from news_recap.recap.loaders.resource_loader import ResourceLoader
from news_recap.storage.io import load_msgspec

SAMPLES_PER_DOMAIN = 5
SHORT_TEXT_THRESHOLD = 200


@dataclass(slots=True)
class ProbeResult:
    url: str
    domain: str
    title: str
    status: str  # open | partial | blocked | error
    extracted_chars: int
    rss_chars: int
    elapsed_ms: int
    error: str | None = None
    content_type: str = ""


@dataclass(slots=True)
class DomainSummary:
    domain: str
    total_articles: int
    probed: int = 0
    open: int = 0
    partial: int = 0
    blocked: int = 0
    error: int = 0
    results: list[ProbeResult] = field(default_factory=list)


def _collect_articles(data_dir: Path) -> dict[str, list[Article]]:
    by_domain: dict[str, list[Article]] = defaultdict(list)
    ingestion_dir = data_dir / "ingestion"
    for p in sorted(ingestion_dir.glob("articles-*.json")):
        ds = load_msgspec(p, DailyStore)
        for a in ds.articles.values():
            by_domain[a.source_domain].append(a)
    return dict(by_domain)


def _classify(extracted_chars: int, rss_chars: int, is_success: bool) -> str:
    if not is_success:
        return "blocked"
    if extracted_chars < SHORT_TEXT_THRESHOLD:
        return "partial" if rss_chars > 0 else "blocked"
    if rss_chars > 0 and extracted_chars < rss_chars * 0.3:
        return "partial"
    return "open"


def run_probe(data_dir: Path) -> list[DomainSummary]:
    articles_by_domain = _collect_articles(data_dir)
    summaries: list[DomainSummary] = []

    with ResourceLoader(max_chars=100_000) as loader:
        for domain in sorted(articles_by_domain, key=lambda d: -len(articles_by_domain[d])):
            articles = articles_by_domain[domain]
            summary = DomainSummary(domain=domain, total_articles=len(articles))
            samples = articles[:SAMPLES_PER_DOMAIN]

            for article in samples:
                if not article.url:
                    continue

                rss_chars = article.clean_text_chars
                t0 = time.monotonic()
                try:
                    loaded = loader.load(article.url)
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    extracted_chars = len(loaded.text) if loaded.text else 0
                    status = _classify(extracted_chars, rss_chars, loaded.is_success)
                    result = ProbeResult(
                        url=article.url,
                        domain=domain,
                        title=article.title[:80],
                        status=status,
                        extracted_chars=extracted_chars,
                        rss_chars=rss_chars,
                        elapsed_ms=elapsed_ms,
                        error=loaded.error,
                        content_type=loaded.content_type,
                    )
                except Exception as exc:  # noqa: BLE001
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    result = ProbeResult(
                        url=article.url,
                        domain=domain,
                        title=article.title[:80],
                        status="error",
                        extracted_chars=0,
                        rss_chars=rss_chars,
                        elapsed_ms=elapsed_ms,
                        error=str(exc),
                    )

                summary.probed += 1
                if result.status == "open":
                    summary.open += 1
                elif result.status == "partial":
                    summary.partial += 1
                elif result.status == "blocked":
                    summary.blocked += 1
                else:
                    summary.error += 1
                summary.results.append(result)

            summaries.append(summary)
    return summaries


def print_report(summaries: list[DomainSummary]) -> None:
    total_articles = sum(s.total_articles for s in summaries)
    total_probed = sum(s.probed for s in summaries)
    total_open = sum(s.open for s in summaries)
    total_partial = sum(s.partial for s in summaries)
    total_blocked = sum(s.blocked for s in summaries)
    total_error = sum(s.error for s in summaries)

    print("=" * 90)
    print("SOURCE FETCH PROBE REPORT")
    print("=" * 90)
    print(f"Domains: {len(summaries)}  |  Articles in DB: {total_articles}")
    print(
        f"Probed: {total_probed}  |  Open: {total_open}  |  "
        f"Partial: {total_partial}  |  Blocked: {total_blocked}  |  Error: {total_error}",
    )
    print()

    print(
        f"{'Domain':<30} {'Articles':>8} {'Probed':>6} "
        f"{'Open':>5} {'Part':>5} {'Block':>5} {'Err':>5}  Status",
    )
    print("-" * 90)

    for s in summaries:
        if s.probed == 0:
            tag = "skipped"
        elif s.blocked + s.error == s.probed:
            tag = "BLOCKED"
        elif s.partial > 0:
            tag = "PARTIAL"
        elif s.open == s.probed:
            tag = "ok"
        else:
            tag = "MIXED"

        print(
            f"{s.domain:<30} {s.total_articles:>8} {s.probed:>6} "
            f"{s.open:>5} {s.partial:>5} {s.blocked:>5} {s.error:>5}  {tag}",
        )

    print()
    print("DETAIL (per-URL results):")
    print("-" * 90)

    for s in summaries:
        for r in s.results:
            flag = {"open": "OK", "partial": "PART", "blocked": "BLOCK", "error": "ERR"}[r.status]
            err = f"  [{r.error}]" if r.error else ""
            print(
                f"  [{flag:>5}] {r.elapsed_ms:>5}ms  "
                f"rss={r.rss_chars:>5}ch  fetched={r.extracted_chars:>6}ch  "
                f"{r.domain:<25} {r.title[:50]}{err}",
            )


if __name__ == "__main__":
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".news_recap_data")
    summaries = run_probe(data_dir)
    print_report(summaries)

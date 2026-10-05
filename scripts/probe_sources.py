#!/usr/bin/env python3
"""Probe article source domains for fetch success/failure.

Samples articles per domain, attempts HTTP fetch + text extraction via
ResourceLoader, and classifies results as open / partial / blocked.

Articles come from the ingestion store in DATA_DIR, or from the
``pipeline_input.json`` of each ``--pipelines`` directory.  Several
``--user-agent`` values probe the same URLs with each UA and print a
per-domain comparison.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from news_recap.http.fetcher import DEFAULT_USER_AGENT, HttpFetcher
from news_recap.ingestion.models import DailyStore
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


@dataclass(slots=True)
class Sample:
    url: str
    title: str
    clean_text_chars: int


def _collect_articles(data_dir: Path) -> dict[str, list[Sample]]:
    by_domain: dict[str, list[Sample]] = defaultdict(list)
    ingestion_dir = data_dir / "ingestion"
    for p in sorted(ingestion_dir.glob("articles-*.json")):
        ds = load_msgspec(p, DailyStore)
        for a in ds.articles.values():
            by_domain[a.source_domain].append(Sample(a.url, a.title, a.clean_text_chars))
    return dict(by_domain)


def _collect_pipeline_articles(pipeline_dirs: list[Path]) -> dict[str, list[Sample]]:
    by_domain: dict[str, list[Sample]] = defaultdict(list)
    for pdir in pipeline_dirs:
        raw = json.loads((pdir / "pipeline_input.json").read_text("utf-8"))
        for a in raw["articles"]:
            url = a.get("url") or ""
            sample = Sample(url, a.get("title", ""), len(a.get("clean_text") or ""))
            by_domain[urlparse(url).netloc].append(sample)
    return dict(by_domain)


def _classify(extracted_chars: int, rss_chars: int, is_success: bool) -> str:
    if not is_success:
        return "blocked"
    if extracted_chars < SHORT_TEXT_THRESHOLD:
        return "partial" if rss_chars > 0 else "blocked"
    if rss_chars > 0 and extracted_chars < rss_chars * 0.3:
        return "partial"
    return "open"


def run_probe(
    articles_by_domain: dict[str, list[Sample]],
    user_agent: str = DEFAULT_USER_AGENT,
    samples_per_domain: int = SAMPLES_PER_DOMAIN,
) -> list[DomainSummary]:
    summaries: list[DomainSummary] = []

    with (
        HttpFetcher(user_agent=user_agent) as fetcher,
        ResourceLoader(fetcher=fetcher, max_chars=100_000) as loader,
    ):
        for domain in sorted(articles_by_domain, key=lambda d: -len(articles_by_domain[d])):
            articles = articles_by_domain[domain]
            summary = DomainSummary(domain=domain, total_articles=len(articles))
            samples = articles[:samples_per_domain]

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


def print_comparison(by_ua: dict[str, list[DomainSummary]]) -> None:
    uas = list(by_ua)
    print("=" * 90)
    print("USER-AGENT COMPARISON (open / probed)")
    print("=" * 90)
    for i, ua in enumerate(uas, 1):
        print(f"  UA{i}: {ua}")
    print()
    print(f"{'Domain':<30} " + " ".join(f"{f'UA{i}':>8}" for i in range(1, len(uas) + 1)))
    print("-" * 90)
    rows = {ua: {s.domain: s for s in summaries} for ua, summaries in by_ua.items()}
    totals = dict.fromkeys(uas, 0)
    for domain in rows[uas[0]]:
        cells = []
        for ua in uas:
            s = rows[ua][domain]
            totals[ua] += s.open
            cells.append(f"{s.open}/{s.probed}")
        print(f"{domain:<30} " + " ".join(f"{c:>8}" for c in cells))
    print("-" * 90)
    print(f"{'TOTAL open':<30} " + " ".join(f"{totals[ua]:>8}" for ua in uas))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", nargs="?", type=Path, default=Path(".news_recap_data"))
    parser.add_argument(
        "--pipelines",
        nargs="+",
        type=Path,
        help="pipeline dirs whose pipeline_input.json supply the articles",
    )
    parser.add_argument("--user-agent", action="append", dest="user_agents")
    parser.add_argument("--samples", type=int, default=SAMPLES_PER_DOMAIN)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    articles = (
        _collect_pipeline_articles(args.pipelines)
        if args.pipelines
        else _collect_articles(args.data_dir)
    )
    user_agents = args.user_agents or [DEFAULT_USER_AGENT]
    results = {ua: run_probe(articles, ua, args.samples) for ua in user_agents}
    if len(results) == 1:
        print_report(next(iter(results.values())))
    else:
        print_comparison(results)

"""Tests for dedup cluster batching and multi-cluster parsing."""

from __future__ import annotations

import pytest

from news_recap.recap.tasks.base import RecapPipelineError
from news_recap.recap.tasks.deduplicate import (
    _BATCH_THRESHOLD,
    _MAX_BATCH_ARTICLES,
    _batch_clusters,
    parse_multi_dedup_output,
)


# ---------------------------------------------------------------------------
# _batch_clusters
# ---------------------------------------------------------------------------


def test_batch_clusters_empty():
    assert _batch_clusters([]) == []


def test_batch_clusters_solo_large():
    """Clusters above the threshold each become their own single-cluster batch."""
    big = [str(i) for i in range(_BATCH_THRESHOLD + 1)]
    result = _batch_clusters([big])
    assert result == [[big]]


def test_batch_clusters_multiple_large_each_solo():
    big1 = [str(i) for i in range(_BATCH_THRESHOLD + 1)]
    big2 = [str(i) for i in range(_BATCH_THRESHOLD + 2)]
    result = _batch_clusters([big1, big2])
    assert result == [[big1], [big2]]


def test_batch_clusters_packs_small():
    """Small clusters are packed greedily up to _MAX_BATCH_ARTICLES."""
    # Two clusters each within the threshold — should land in one batch.
    c1 = [str(i) for i in range(_BATCH_THRESHOLD)]
    c2 = [str(i) for i in range(_BATCH_THRESHOLD, _BATCH_THRESHOLD * 2)]
    result = _batch_clusters([c1, c2])
    assert len(result) == 1
    assert result[0] == [c1, c2]


def test_batch_clusters_splits_when_cap_exceeded():
    """When adding the next cluster would exceed the cap, a new batch starts."""
    # Pack small clusters (size == threshold) until the cap is exactly full,
    # then one more cluster must spill to a new batch.
    cluster_size = _BATCH_THRESHOLD  # largest size that stays in greedy path
    full_count = _MAX_BATCH_ARTICLES // cluster_size  # clusters that fit exactly
    clusters = [
        [str(j + i * cluster_size) for j in range(cluster_size)]
        for i in range(full_count + 1)  # one extra to force the split
    ]
    result = _batch_clusters(clusters)
    assert len(result) == 2
    assert len(result[0]) == full_count
    assert len(result[1]) == 1


def test_batch_clusters_large_and_small_separate():
    """Large clusters get solo batches; small clusters are packed separately."""
    big = [str(i) for i in range(_BATCH_THRESHOLD + 1)]
    small1 = ["a", "b"]
    small2 = ["c", "d"]
    result = _batch_clusters([big, small1, small2])
    # One solo batch for big, one packed batch for small1+small2.
    assert [big] in result
    assert [small1, small2] in result
    assert len(result) == 2


# ---------------------------------------------------------------------------
# parse_multi_dedup_output
# ---------------------------------------------------------------------------

_TWO_CLUSTER_OUTPUT = """\
CLUSTER 1:
MERGED: Combined headline for articles 1 and 3
1, 3
SINGLE: 2

CLUSTER 2:
SINGLE: 1
SINGLE: 2
"""

_SINGLE_CLUSTER_OUTPUT = """\
CLUSTER 1:
MERGED: Merged headline
1, 2
"""


def test_parse_multi_dedup_output_two_clusters():
    batch = [["id-a1", "id-a2", "id-a3"], ["id-b1", "id-b2"]]
    results = parse_multi_dedup_output(_TWO_CLUSTER_OUTPUT, batch)

    assert len(results) == 2

    r0 = results[0]
    assert len(r0.merges) == 1
    assert r0.merges[0].indices == [1, 3]
    assert "Combined headline" in r0.merges[0].merged_text
    assert r0.singles == [2]

    r1 = results[1]
    assert r1.merges == []
    assert sorted(r1.singles) == [1, 2]


def test_parse_multi_dedup_output_single_cluster():
    batch = [["id-x1", "id-x2"]]
    results = parse_multi_dedup_output(_SINGLE_CLUSTER_OUTPUT, batch)

    assert len(results) == 1
    r = results[0]
    assert len(r.merges) == 1
    assert r.merges[0].indices == [1, 2]
    assert r.singles == []


def test_parse_multi_dedup_missing_cluster_header():
    """Output without CLUSTER N: headers must raise RecapPipelineError."""
    batch = [["id-a1", "id-a2"], ["id-b1", "id-b2"]]
    bare_output = "MERGED: something\n1, 2\nSINGLE: 1\nSINGLE: 2\n"

    with pytest.raises(RecapPipelineError):
        parse_multi_dedup_output(bare_output, batch)


def test_parse_multi_dedup_wrong_cluster_count():
    """Fewer CLUSTER headers than clusters in batch raises RecapPipelineError."""
    batch = [["id-a1", "id-a2"], ["id-b1", "id-b2"], ["id-c1", "id-c2"]]
    # Only one cluster in output but batch has three.
    with pytest.raises(RecapPipelineError):
        parse_multi_dedup_output(_SINGLE_CLUSTER_OUTPUT, batch)

"""Tests for _fuzzy_merge_blocks (Phase 3 of oneshot block dedup)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from news_recap.recap.dedup.embedder import Vector
from news_recap.recap.models import DigestBlock, DigestSection
from news_recap.recap.tasks.oneshot_digest import _fuzzy_merge_blocks


# ---------------------------------------------------------------------------
# Mock embedder — returns pre-defined unit vectors for controllable similarity
# ---------------------------------------------------------------------------


@dataclass
class _MockEmbedder:
    """Embedder that maps text to pre-assigned vectors.

    Texts not in the mapping get a unique orthogonal vector so they
    never match anything.
    """

    model_name: str = "mock"
    vectors: dict[str, Vector] = field(default_factory=dict)
    _next_dim: int = field(default=0, init=False)

    _dim: int = 10

    def embed(self, texts: list[str]) -> list[Vector]:
        result: list[Vector] = []
        for text in texts:
            if text in self.vectors:
                v = self.vectors[text]
                if len(v) < self._dim:
                    v = v + [0.0] * (self._dim - len(v))
                result.append(v[: self._dim])
            else:
                vec = [0.0] * self._dim
                vec[self._next_dim % self._dim] = 1.0
                self._next_dim += 1
                self.vectors[text] = vec
                result.append(vec)
        return result


def _unit(dim: int, size: int = 10) -> Vector:
    """Unit vector along *dim* in *size*-dimensional space."""
    v = [0.0] * size
    v[dim] = 1.0
    return v


def _rotated(base: Vector, other: Vector, angle_deg: float) -> Vector:
    """Rotate *base* towards *other* by *angle_deg* degrees.

    Both must be unit vectors in the same space.
    """
    rad = math.radians(angle_deg)
    return [math.cos(rad) * b + math.sin(rad) * o for b, o in zip(base, other, strict=True)]


def _norm(v: Vector) -> Vector:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _block(title: str, articles: list[str], summary: str = "") -> DigestBlock:
    return DigestBlock(title=title, article_ids=articles, summary=summary)


def _section(title: str, indices: list[int], summary: str = "") -> DigestSection:
    return DigestSection(title=title, block_indices=indices, summary=summary)


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class TestFuzzyMergeBlocks:
    def test_single_block_returns_unchanged(self) -> None:
        blocks = [_block("A", ["1"])]
        sections = [_section("S", [0])]
        emb = _MockEmbedder()
        out_b, out_s = _fuzzy_merge_blocks(blocks, sections, emb)
        assert out_b == blocks
        assert out_s == sections

    def test_empty_blocks_returns_unchanged(self) -> None:
        out_b, out_s = _fuzzy_merge_blocks([], [], _MockEmbedder())
        assert out_b == []
        assert out_s == []

    def test_identical_titles_merged(self) -> None:
        """Two blocks with the exact same title should be merged."""
        v = _norm(_unit(0))
        emb = _MockEmbedder(vectors={"Same story": v})
        blocks = [
            _block("Same story", ["a1", "a2"]),
            _block("Same story", ["a3", "a4"]),
        ]
        sections = [_section("S1", [0]), _section("S2", [1])]
        out_b, out_s = _fuzzy_merge_blocks(blocks, sections, emb)
        assert len(out_b) == 1
        assert set(out_b[0].article_ids) == {"a1", "a2", "a3", "a4"}

    def test_dissimilar_titles_not_merged(self) -> None:
        """Blocks with orthogonal embeddings stay separate."""
        emb = _MockEmbedder(
            vectors={
                "EU sanctions on Russia": _unit(0),
                "Earthquake in Japan": _unit(1),
            }
        )
        blocks = [
            _block("EU sanctions on Russia", ["a1"]),
            _block("Earthquake in Japan", ["a2"]),
        ]
        sections = [_section("S", [0, 1])]
        out_b, out_s = _fuzzy_merge_blocks(blocks, sections, emb)
        assert len(out_b) == 2

    def test_threshold_boundary_below(self) -> None:
        """Blocks just below 0.90 similarity should NOT be merged."""
        base = _unit(0)
        other = _unit(1)
        v2 = _norm(_rotated(base, other, 27))  # cos(27°) ≈ 0.891
        emb = _MockEmbedder(vectors={"A": base, "B": v2})
        blocks = [_block("A", ["1"]), _block("B", ["2"])]
        sections = [_section("S", [0, 1])]
        out_b, _ = _fuzzy_merge_blocks(blocks, sections, emb, threshold=0.90)
        assert len(out_b) == 2

    def test_threshold_boundary_above(self) -> None:
        """Blocks just above 0.90 similarity SHOULD be merged."""
        base = _unit(0)
        other = _unit(1)
        v2 = _norm(_rotated(base, other, 23))  # cos(23°) ≈ 0.921
        emb = _MockEmbedder(vectors={"A": base, "B": v2})
        blocks = [_block("A", ["1"]), _block("B", ["2"])]
        sections = [_section("S", [0, 1])]
        out_b, _ = _fuzzy_merge_blocks(blocks, sections, emb, threshold=0.90)
        assert len(out_b) == 1
        assert set(out_b[0].article_ids) == {"1", "2"}

    def test_winner_has_most_articles(self) -> None:
        """The block with more articles should be the merge winner."""
        v = _unit(0)
        emb = _MockEmbedder(vectors={"Short": v, "Longer title text": v})
        blocks = [
            _block("Short", ["a1"]),
            _block("Longer title text", ["a2", "a3", "a4"]),
        ]
        sections = [_section("S", [0, 1])]
        out_b, _ = _fuzzy_merge_blocks(blocks, sections, emb)
        assert len(out_b) == 1
        assert out_b[0].title == "Longer title text"

    def test_winner_summary_preserved(self) -> None:
        v = _unit(0)
        emb = _MockEmbedder(vectors={"A": v, "B": v})
        blocks = [
            _block("A", ["1"], summary="summary-A"),
            _block("B", ["2", "3"], summary="summary-B"),
        ]
        sections = [_section("S", [0, 1])]
        out_b, _ = _fuzzy_merge_blocks(blocks, sections, emb)
        assert out_b[0].summary == "summary-B"

    def test_article_ids_deduplicated(self) -> None:
        """Shared article IDs should not be duplicated in the merged block."""
        v = _unit(0)
        emb = _MockEmbedder(vectors={"A": v, "B": v})
        blocks = [
            _block("A", ["shared", "a1"]),
            _block("B", ["shared", "b1"]),
        ]
        sections = [_section("S", [0, 1])]
        out_b, _ = _fuzzy_merge_blocks(blocks, sections, emb)
        assert out_b[0].article_ids.count("shared") == 1

    def test_singleton_preservation(self) -> None:
        """Blocks not matching any cluster must survive unchanged."""
        v = _unit(0)
        emb = _MockEmbedder(
            vectors={
                "Identical story": v,
                "Unique block": _unit(1),
            }
        )
        blocks = [
            _block("Identical story", ["a1"]),
            _block("Identical story", ["a2"]),
            _block("Unique block", ["a3"]),
        ]
        sections = [_section("S", [0, 1, 2])]
        out_b, _ = _fuzzy_merge_blocks(blocks, sections, emb)
        assert len(out_b) == 2
        titles = {b.title for b in out_b}
        assert "Unique block" in titles
        assert "Identical story" in titles

    def test_section_remapping(self) -> None:
        """Section block_indices are remapped after merge.

        Blocks 0 and 2 ("Dup") merge into winner at new index 0.
        Block 1 ("Solo") becomes new index 1.
        Section "First" [0, 1] → [0, 1], Section "Second" [2] → [0].
        """
        v = _unit(0)
        emb = _MockEmbedder(
            vectors={
                "Dup": v,
                "Solo": _unit(1),
            }
        )
        blocks = [
            _block("Dup", ["a1"]),
            _block("Solo", ["a2"]),
            _block("Dup", ["a3"]),
        ]
        sections = [
            _section("First", [0, 1]),
            _section("Second", [2]),
        ]
        out_b, out_s = _fuzzy_merge_blocks(blocks, sections, emb)
        assert len(out_b) == 2
        assert len(out_s) == 2
        assert out_s[0].block_indices == [0, 1]
        assert out_s[1].block_indices == [0]
        assert max(i for s in out_s for i in s.block_indices) < len(out_b)

    def test_absorbed_section_points_to_winner(self) -> None:
        """A section whose only block was absorbed points to the winner."""
        v = _unit(0)
        emb = _MockEmbedder(vectors={"A": v, "B": v})
        blocks = [
            _block("A", ["a1", "a2", "a3"]),
            _block("B", ["a4"]),
        ]
        sections = [
            _section("Keep", [0]),
            _section("Also keeps", [1]),
        ]
        out_b, out_s = _fuzzy_merge_blocks(blocks, sections, emb)
        assert len(out_b) == 1
        assert len(out_s) == 2
        for s in out_s:
            assert s.block_indices == [0]

    def test_cluster_of_three(self) -> None:
        """Three blocks with identical embeddings form one merged block."""
        v = _unit(0)
        emb = _MockEmbedder(vectors={"X": v})
        blocks = [
            _block("X", ["a1"]),
            _block("X", ["a2"]),
            _block("X", ["a3"]),
        ]
        sections = [_section("S", [0, 1, 2])]
        out_b, out_s = _fuzzy_merge_blocks(blocks, sections, emb)
        assert len(out_b) == 1
        assert set(out_b[0].article_ids) == {"a1", "a2", "a3"}
        assert out_s[0].block_indices == [0]

    def test_section_summary_preserved(self) -> None:
        """Section summaries survive remapping."""
        v = _unit(0)
        emb = _MockEmbedder(vectors={"A": v})
        blocks = [_block("A", ["1"]), _block("A", ["2"])]
        sections = [_section("S", [0, 1], summary="my summary")]
        _, out_s = _fuzzy_merge_blocks(blocks, sections, emb)
        assert out_s[0].summary == "my summary"

    def test_no_merge_returns_original_objects(self) -> None:
        """When nothing merges, input lists are returned as-is."""
        emb = _MockEmbedder(
            vectors={
                "Alpha": _unit(0),
                "Beta": _unit(1),
            }
        )
        blocks = [_block("Alpha", ["1"]), _block("Beta", ["2"])]
        sections = [_section("S", [0, 1])]
        out_b, out_s = _fuzzy_merge_blocks(blocks, sections, emb)
        assert out_b is blocks
        assert out_s is sections

    def test_two_disjoint_clusters_merged_simultaneously(self) -> None:
        """Two independent clusters merge at the same time; singleton survives."""
        emb = _MockEmbedder(
            vectors={
                "Cluster A story": _unit(0),
                "Cluster B story": _unit(1),
                "Standalone": _unit(2),
            }
        )
        blocks = [
            _block("Cluster A story", ["a1"]),  # 0 — cluster A
            _block("Cluster B story", ["b1"]),  # 1 — cluster B
            _block("Standalone", ["c1"]),  # 2 — singleton
            _block("Cluster A story", ["a2"]),  # 3 — cluster A
            _block("Cluster B story", ["b2", "b3"]),  # 4 — cluster B (more articles → winner)
        ]
        sections = [
            _section("S1", [0, 1, 2]),
            _section("S2", [3, 4]),
        ]
        out_b, out_s = _fuzzy_merge_blocks(blocks, sections, emb)

        assert len(out_b) == 3
        titles = {b.title for b in out_b}
        assert titles == {"Cluster A story", "Cluster B story", "Standalone"}

        cluster_a = next(b for b in out_b if b.title == "Cluster A story")
        assert set(cluster_a.article_ids) == {"a1", "a2"}

        cluster_b = next(b for b in out_b if b.title == "Cluster B story")
        assert set(cluster_b.article_ids) == {"b1", "b2", "b3"}

        standalone = next(b for b in out_b if b.title == "Standalone")
        assert standalone.article_ids == ["c1"]

        for s in out_s:
            for idx in s.block_indices:
                assert 0 <= idx < len(out_b)


class TestDedupThenFuzzyMergeIntegration:
    """Verify the _dedup_blocks → _fuzzy_merge_blocks composition.

    This mirrors the call sequence in OneshotDigest.execute() and ensures
    the data contract between the two functions is compatible.
    """

    def test_dedup_then_fuzzy_merge(self) -> None:
        """Exact-duplicate removal followed by fuzzy merge on the survivors."""
        from news_recap.recap.tasks.oneshot_digest import _dedup_blocks

        emb = _MockEmbedder(
            vectors={
                "EU sanctions update": _unit(0),
                "European sanctions on Russia": _unit(0),
                "AI chip export controls": _unit(1),
            }
        )
        blocks = [
            _block("EU sanctions update", ["a1", "a2"]),
            _block("EU sanctions update", ["a1", "a2"]),  # exact dup of 0
            _block("European sanctions on Russia", ["a3", "a4"]),  # fuzzy match with 0
            _block("AI chip export controls", ["a5"]),  # unrelated
        ]
        sections = [_section("World", [0, 1, 2]), _section("Tech", [3])]

        blocks_after_dedup, sections_after_dedup = _dedup_blocks(blocks, sections)
        assert len(blocks_after_dedup) == 3  # exact dup removed

        out_b, out_s = _fuzzy_merge_blocks(
            blocks_after_dedup,
            sections_after_dedup,
            emb,
        )
        assert len(out_b) == 2  # fuzzy merge combined the two sanctions blocks
        sanctions = next(b for b in out_b if "sanction" in b.title.lower())
        assert set(sanctions.article_ids) >= {"a1", "a2", "a3", "a4"}

        for s in out_s:
            for idx in s.block_indices:
                assert 0 <= idx < len(out_b)

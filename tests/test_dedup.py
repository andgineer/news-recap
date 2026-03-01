import allure

from news_recap.recap.dedup.cluster import group_similar

pytestmark = [
    allure.epic("Dedup Quality"),
    allure.feature("Embeddings & Thresholding"),
]


def test_group_similar_groups_similar_items() -> None:
    embeddings = {
        "a1": [1.0, 0.0],
        "a2": [0.99, 0.01],
        "a3": [0.0, 1.0],
    }
    groups = group_similar(
        ids=["a1", "a2", "a3"],
        embeddings=embeddings,
        threshold=0.95,
    )
    assert len(groups) == 1
    assert set(groups[0]) == {"a1", "a2"}


def test_group_similar_empty() -> None:
    assert group_similar([], {}, 0.90) == []


def test_group_similar_no_pairs_above_threshold() -> None:
    embeddings = {
        "a1": [1.0, 0.0],
        "a2": [0.0, 1.0],
    }
    groups = group_similar(ids=["a1", "a2"], embeddings=embeddings, threshold=0.90)
    assert groups == []


def test_group_similar_max_group_size() -> None:
    embeddings = {f"a{i}": [1.0, 0.0] for i in range(10)}
    groups = group_similar(
        ids=[f"a{i}" for i in range(10)],
        embeddings=embeddings,
        threshold=0.90,
        max_group_size=4,
    )
    for g in groups:
        assert len(g) <= 4
    all_ids = {aid for g in groups for aid in g}
    assert all_ids == {f"a{i}" for i in range(10)}

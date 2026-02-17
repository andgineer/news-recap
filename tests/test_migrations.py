from pathlib import Path

from news_recap.ingestion.repository import SQLiteRepository


def test_alembic_schema_is_initialized_to_head(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "migrations.db")
    repository.init_schema()

    row = repository._connection.execute(
        "SELECT version_num FROM alembic_version LIMIT 1"
    ).fetchone()
    assert row is not None
    assert str(row["version_num"]) == "20260217_0005"

    user = repository._connection.execute(
        "SELECT user_id FROM users WHERE user_id = 'default_user'"
    ).fetchone()
    assert user is not None
    repository.close()

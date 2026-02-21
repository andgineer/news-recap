from pathlib import Path

import allure

from news_recap.ingestion.repository import SQLiteRepository

pytestmark = [
    allure.epic("Daily Ingestion"),
    allure.feature("Persist & Run Accounting"),
]


def test_alembic_schema_is_initialized_to_head(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "migrations.db")
    repository.init_schema()

    row = repository._connection.execute(
        "SELECT version_num FROM alembic_version LIMIT 1"
    ).fetchone()
    assert row is not None
    assert str(row["version_num"]) == "20260217_0001"

    user = repository._connection.execute(
        "SELECT user_id FROM users WHERE user_id = 'default_user'"
    ).fetchone()
    assert user is not None

    intelligence_tables = repository._connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name IN ('user_outputs', 'user_output_blocks', 'user_story_definitions',
                       'story_assignments', 'daily_story_snapshots', 'monitor_questions')
        ORDER BY name
        """
    ).fetchall()
    assert [str(row["name"]) for row in intelligence_tables] == [
        "daily_story_snapshots",
        "monitor_questions",
        "story_assignments",
        "user_output_blocks",
        "user_outputs",
        "user_story_definitions",
    ]

    removed = repository._connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name IN ('llm_tasks', 'llm_task_events', 'llm_task_artifacts',
                       'llm_task_attempts', 'output_citation_snapshots')
        """
    ).fetchall()
    assert removed == []
    repository.close()

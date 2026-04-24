"""Flask web server for browsing completed digests."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from flask import Flask, abort, redirect, render_template, url_for
from markupsafe import Markup, escape

from news_recap.config import Settings
from news_recap.recap.models import Digest
from news_recap.recap.pipeline_setup import (
    _find_digest_pipeline_dir,
    _find_latest_digest_pipeline_dir,
)
from news_recap.storage.io import load_msgspec

logger = logging.getLogger(__name__)


def find_latest_digest(workdir_root: Path, date_str: str) -> tuple[Digest, Path] | None:
    """Return the latest completed digest and its path for *date_str*, or ``None``."""
    prefix = f"pipeline-{date_str}-"
    candidates = sorted(
        workdir_root.glob(f"{prefix}*/digest.json"),
        key=lambda p: p.parent.name,
        reverse=True,
    )
    for path in candidates:
        try:
            digest = load_msgspec(path, Digest)
        except Exception:  # noqa: BLE001
            logger.debug("Skipping unreadable digest at %s", path, exc_info=True)
            continue
        if digest.status == "completed" and "oneshot_digest" in digest.completed_phases:
            return digest, path
    return None


class _DigestIndex:
    """Thread-unsafe in-process index: digest_id → on-disk digest.json path."""

    def __init__(self, workdir_root: Path) -> None:
        self._root = workdir_root.resolve()
        self._index: dict[str, Path] = {}

    def add(self, digest: Digest, path: Path) -> None:
        """Index *path* only when it resolves inside the workdir root."""
        resolved = path.resolve()
        if resolved.is_relative_to(self._root):
            self._index[digest.digest_id] = resolved

    def load(self, digest_id: str) -> Digest | None:
        """Return the digest for *digest_id*, or ``None`` if not indexed or unreadable."""
        path = self._index.get(digest_id)
        if path is None or not path.exists():
            return None
        try:
            return load_msgspec(path, Digest)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to reload digest %s", digest_id, exc_info=True)
            return None

    def populate_from_disk(self, workdir_root: Path) -> None:
        """Scan *workdir_root* at startup and index all completed digests."""
        for path in workdir_root.glob("pipeline-*/digest.json"):
            try:
                d = load_msgspec(path, Digest)
                if d.status == "completed" and "oneshot_digest" in d.completed_phases:
                    self.add(d, path)
            except Exception:  # noqa: BLE001
                logger.debug("Skipping unreadable digest at %s", path, exc_info=True)


def _render_digest(digest: Digest, digest_path: Path, index: _DigestIndex) -> str:
    """Render a digest page and update the index."""
    index.add(digest, digest_path)
    article_map = {a.article_id: a for a in digest.articles}
    return render_template("digest.html", digest=digest, article_map=article_map)


def _load_pipeline_digest(workdir_root: Path, pipeline_name: str) -> tuple[Digest, Path]:
    """Load a digest from a pipeline directory name, aborting on errors."""
    pdir = workdir_root / pipeline_name
    if not pdir.resolve().is_relative_to(workdir_root.resolve()) or not pdir.is_dir():
        abort(404, f"Pipeline directory not found: {pipeline_name!r}")

    digest_path = pdir / "digest.json"
    if not digest_path.exists():
        abort(404, f"No digest.json in {pipeline_name!r}")

    try:
        return load_msgspec(digest_path, Digest), digest_path
    except Exception:  # noqa: BLE001
        abort(500, f"Cannot read digest in {pipeline_name!r}")
    raise AssertionError("unreachable")  # abort always raises


def _serve_date_digest(
    workdir_root: Path,
    date_str: str,
    index: _DigestIndex,
) -> str | tuple[str, int]:
    """Validate *date_str*, find the latest digest for it, and render."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        abort(400, f"Invalid date format: {date_str!r}. Expected YYYY-MM-DD.")

    result = find_latest_digest(workdir_root, date_str)
    if result is None:
        return render_template("no_digest.html", date=date_str), 404

    digest, digest_path = result
    return _render_digest(digest, digest_path, index)


def create_app(
    workdir_root: Path,
    pinned_pipeline_dir: Path | None = None,
    settings: Settings | None = None,
) -> Flask:
    """Create and configure the Flask application.

    When *pinned_pipeline_dir* is set the root route serves that exact
    digest instead of searching by today's date.
    """
    app = Flask(__name__, template_folder="templates")
    _settings = settings or Settings.from_env()  # noqa: F841

    @app.template_filter("nl2br")
    def nl2br(value: str) -> Markup:
        return Markup(escape(value).replace("\n", Markup("<br>\n")))  # noqa: S704

    index = _DigestIndex(workdir_root)
    index.populate_from_disk(workdir_root)

    @app.route("/")
    def root():  # type: ignore[return]
        if pinned_pipeline_dir is not None:
            return redirect(url_for("pipeline_digest", pipeline_name=pinned_pipeline_dir.name))
        today = datetime.now(tz=UTC).date().isoformat()
        return redirect(url_for("digest_page", date_str=today))

    @app.route("/pipeline/<pipeline_name>")
    def pipeline_digest(pipeline_name: str):  # type: ignore[return]
        digest, digest_path = _load_pipeline_digest(workdir_root, pipeline_name)
        return _render_digest(digest, digest_path, index)

    @app.route("/digest/<date_str>")
    def digest_page(date_str: str):  # type: ignore[return]
        return _serve_date_digest(workdir_root, date_str, index)

    @app.route("/api/digest/<digest_id>/block/<int:block_idx>/summary")
    def block_summary(digest_id: str, block_idx: int):  # type: ignore[return]
        digest = index.load(digest_id)
        if digest is None:
            abort(404, "Digest not found.")
        assert digest is not None

        if block_idx < 0 or block_idx >= len(digest.blocks):
            abort(404, f"Block index {block_idx} out of range.")

        abort(501, "Block summary generation not yet implemented.")

    return app


@dataclass(slots=True)
class WebServeCommand:
    """CLI parameters for the web server."""

    digest_id: int | None = None
    host: str = "127.0.0.1"
    port: int = 8080


class WebCliController:
    """Launch the Flask digest viewer."""

    def serve(self, command: WebServeCommand) -> Iterator[str]:
        settings = Settings.from_env()
        workdir_root = settings.orchestrator.workdir_root.resolve()

        if command.digest_id is not None:
            pipeline_dir = _find_digest_pipeline_dir(workdir_root, command.digest_id)
            label = f"id={command.digest_id}"
        else:
            pipeline_dir = _find_latest_digest_pipeline_dir(workdir_root)
            label = "latest"

        if pipeline_dir is None:
            yield f"No completed digest found ({label})."
            return

        digest_path = pipeline_dir / "digest.json"
        digest = load_msgspec(digest_path, Digest)

        yield f"Serving digest ({digest.run_date}, {pipeline_dir.name})"
        app = create_app(workdir_root, pinned_pipeline_dir=pipeline_dir, settings=settings)
        app.run(host=command.host, port=command.port)

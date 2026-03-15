"""Flask web server for browsing completed digests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from flask import Flask, abort, redirect, render_template, url_for
from markupsafe import Markup, escape

from news_recap.config import Settings
from news_recap.recap.models import Digest
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
        if digest.status == "completed":
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
                if d.status == "completed":
                    self.add(d, path)
            except Exception:  # noqa: BLE001
                logger.debug("Skipping unreadable digest at %s", path, exc_info=True)


def create_app(
    workdir_root: Path,
    pinned_date: str | None = None,
    settings: Settings | None = None,
) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, template_folder="templates")
    _settings = settings or Settings.from_env()  # noqa: F841

    @app.template_filter("nl2br")
    def nl2br(value: str) -> Markup:
        return Markup(escape(value).replace("\n", Markup("<br>\n")))

    index = _DigestIndex(workdir_root)
    index.populate_from_disk(workdir_root)

    def _default_date() -> str:
        return pinned_date or datetime.now(tz=UTC).date().isoformat()

    @app.route("/")
    def root():  # type: ignore[return]
        return redirect(url_for("digest_page", date_str=_default_date()))

    @app.route("/digest/<date_str>")
    def digest_page(date_str: str):  # type: ignore[return]
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            abort(400, f"Invalid date format: {date_str!r}. Expected YYYY-MM-DD.")

        result = find_latest_digest(workdir_root, date_str)
        if result is None:
            return render_template("no_digest.html", date=date_str), 404

        digest, digest_path = result
        index.add(digest, digest_path)
        article_map = {a.article_id: a for a in digest.articles}
        return render_template("digest.html", digest=digest, article_map=article_map)

    @app.route("/api/digest/<digest_id>/block/<int:block_idx>/summary")
    def block_summary(digest_id: str, block_idx: int):  # type: ignore[return]
        digest = index.load(digest_id)
        if digest is None:
            abort(404, "Digest not found.")
        assert digest is not None

        if block_idx < 0 or block_idx >= len(digest.blocks):
            abort(404, f"Block index {block_idx} out of range.")

        # Phase 2 — not yet implemented
        abort(501, "Block summary generation not yet implemented.")

    return app


@dataclass(slots=True)
class WebServeCommand:
    """CLI parameters for the web server."""

    data_dir: Path | None = None
    date: date | None = None
    host: str = "127.0.0.1"
    port: int = 8080


class WebCliController:
    """Launch the Flask digest viewer."""

    def serve(self, command: WebServeCommand) -> None:
        settings = Settings.from_env(data_dir=command.data_dir)
        workdir_root = settings.orchestrator.workdir_root.resolve()
        pinned = command.date.isoformat() if command.date else None
        app = create_app(workdir_root, pinned_date=pinned, settings=settings)
        app.run(host=command.host, port=command.port)

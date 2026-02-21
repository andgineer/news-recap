"""YouTube video subtitle/transcript extraction."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from youtube_transcript_api import YouTubeTranscriptApi

logger = logging.getLogger(__name__)

_YT_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/)"
    r"([a-zA-Z0-9_-]{11})",
)

PREFERRED_LANGUAGES = ("ru", "en", "sr", "uk", "de", "fr")


@dataclass(slots=True)
class TranscriptResult:
    """Result of YouTube transcript extraction."""

    text: str
    language: str
    is_success: bool
    error: str | None = None


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from URL, or None if not a YouTube URL."""

    match = _YT_VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


def is_youtube_url(url: str) -> bool:
    """Check if URL points to a YouTube video."""

    return extract_video_id(url) is not None


def fetch_transcript(
    url: str,
    *,
    languages: tuple[str, ...] = PREFERRED_LANGUAGES,
    max_chars: int = 0,
) -> TranscriptResult:
    """Fetch transcript/subtitles for a YouTube video URL.

    Uses youtube-transcript-api v1.x: instance-based API with dataclass snippets.
    Tries preferred languages first via the high-level `fetch()` method,
    then falls back to the first available transcript.
    """

    video_id = extract_video_id(url)
    if not video_id:
        return TranscriptResult(
            text="",
            language="",
            is_success=False,
            error=f"not a YouTube URL: {url}",
        )

    api = YouTubeTranscriptApi()

    try:
        fetched = api.fetch(video_id, languages=list(languages))
        text = " ".join(snippet.text for snippet in fetched)
        lang = fetched.language_code if hasattr(fetched, "language_code") else languages[0]
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars].rstrip()
        return TranscriptResult(text=text, language=lang, is_success=True)
    except Exception:  # noqa: BLE001
        logger.debug("Primary transcript fetch failed for %s, trying fallback", video_id)

    try:
        transcript_list = api.list(video_id)
        for transcript in transcript_list:
            try:
                fetched = transcript.fetch()
                text = " ".join(snippet.text for snippet in fetched)
                if max_chars > 0 and len(text) > max_chars:
                    text = text[:max_chars].rstrip()
                return TranscriptResult(
                    text=text,
                    language=transcript.language_code,
                    is_success=True,
                )
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Transcript variant %s failed for %s",
                    transcript.language_code,
                    video_id,
                )
                continue
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to get any transcript for %s: %s", video_id, exc)
        return TranscriptResult(
            text="",
            language="",
            is_success=False,
            error=f"all transcript attempts failed: {exc}",
        )

    return TranscriptResult(
        text="",
        language="",
        is_success=False,
        error="no transcripts available",
    )

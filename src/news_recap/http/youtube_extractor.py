"""YouTube video subtitle/transcript extraction."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import RequestBlocked

logger = logging.getLogger(__name__)

_YT_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/"
    r"|youtube\.com/shorts/)"
    r"([a-zA-Z0-9_-]{11})",
)
_YT_SHORTS_RE = re.compile(r"youtube\.com/shorts/")

PREFERRED_LANGUAGES = ("ru", "en", "sr", "uk", "de", "fr")

IP_BLOCKED_ERROR = "ip_blocked"


@dataclass(slots=True)
class TranscriptResult:
    """Result of YouTube transcript extraction."""

    text: str
    language: str
    is_success: bool
    error: str | None = None

    @property
    def is_blocked(self) -> bool:
        """True when YouTube blocked the request (IP ban / bot detection)."""
        return self.error == IP_BLOCKED_ERROR


def _blocked(video_id: str) -> TranscriptResult:
    logger.warning("YouTube blocked request for %s (IP ban / bot detection)", video_id)
    return TranscriptResult(text="", language="", is_success=False, error=IP_BLOCKED_ERROR)


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from URL, or None if not a YouTube URL.

    >>> extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    'dQw4w9WgXcQ'
    >>> extract_video_id("https://www.youtube.com/shorts/iz4C9oE0wTk")
    'iz4C9oE0wTk'
    >>> extract_video_id("https://example.com") is None
    True
    """
    match = _YT_VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


def is_youtube_url(url: str) -> bool:
    """Check if URL points to a YouTube video (including Shorts)."""
    return extract_video_id(url) is not None


def is_shorts_url(url: str) -> bool:
    """Check if URL points to a YouTube Shorts video (no transcripts)."""
    return bool(_YT_SHORTS_RE.search(url))


def _fetch_preferred(
    api: YouTubeTranscriptApi,
    video_id: str,
    languages: tuple[str, ...],
    max_chars: int,
) -> TranscriptResult | None:
    """Try the high-level ``fetch()`` with preferred languages.

    Returns ``None`` when the preferred languages are not available
    (so the caller can fall back), or a definitive result otherwise.
    """
    try:
        fetched = api.fetch(video_id, languages=list(languages))
        text = " ".join(snippet.text for snippet in fetched)
        lang = fetched.language_code if hasattr(fetched, "language_code") else languages[0]
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars].rstrip()
        return TranscriptResult(text=text, language=lang, is_success=True)
    except RequestBlocked:
        return _blocked(video_id)
    except Exception:  # noqa: BLE001
        logger.debug("Primary transcript fetch failed for %s, trying fallback", video_id)
        return None


def _fetch_any(
    api: YouTubeTranscriptApi,
    video_id: str,
    max_chars: int,
) -> TranscriptResult:
    """Try every available transcript variant as a fallback."""
    try:
        transcript_list = api.list(video_id)
    except RequestBlocked:
        return _blocked(video_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to get any transcript for %s: %s", video_id, exc)
        return TranscriptResult(
            text="",
            language="",
            is_success=False,
            error=f"all transcript attempts failed: {exc}",
        )

    for transcript in transcript_list:
        try:
            fetched = transcript.fetch()
            text = " ".join(snippet.text for snippet in fetched)
            if max_chars > 0 and len(text) > max_chars:
                text = text[:max_chars].rstrip()
            return TranscriptResult(text=text, language=transcript.language_code, is_success=True)
        except RequestBlocked:
            return _blocked(video_id)
        except Exception:  # noqa: BLE001
            logger.debug("Transcript variant %s failed for %s", transcript.language_code, video_id)

    return TranscriptResult(
        text="",
        language="",
        is_success=False,
        error="no transcripts available",
    )


def fetch_transcript(
    url: str,
    *,
    languages: tuple[str, ...] = PREFERRED_LANGUAGES,
    max_chars: int = 0,
) -> TranscriptResult:
    """Fetch transcript/subtitles for a YouTube video URL.

    Uses youtube-transcript-api v1.x: instance-based API with dataclass snippets.
    Tries preferred languages first via the high-level ``fetch()`` method,
    then falls back to the first available transcript.

    On ``RequestBlocked`` / ``IpBlocked`` the result carries
    ``error=IP_BLOCKED_ERROR`` so the caller can abort early.
    """
    video_id = extract_video_id(url)
    if not video_id:
        return TranscriptResult(
            text="",
            language="",
            is_success=False,
            error=f"not a YouTube URL: {url}",
        )

    if is_shorts_url(url):
        return TranscriptResult(
            text="",
            language="",
            is_success=False,
            error="YouTube Shorts do not have transcripts",
        )

    api = YouTubeTranscriptApi()
    result = _fetch_preferred(api, video_id, languages, max_chars)
    if result is not None:
        return result
    return _fetch_any(api, video_id, max_chars)

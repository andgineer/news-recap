import allure

from news_recap.ingestion.cleaning import canonicalize_url, clean_article_text, html_to_text

pytestmark = [
    allure.epic("Daily Ingestion"),
    allure.feature("Feed Intake & Cleaning"),
]


def test_html_to_text_removes_tags_and_scripts() -> None:
    raw = "<html><body><script>alert('x')</script><h1>Title</h1><p>Hello <b>world</b></p></body></html>"
    assert html_to_text(raw) == "Title Hello world"


def test_clean_article_text_marks_summary_only_as_not_full_content() -> None:
    cleaned = clean_article_text(
        content_html=None,
        summary_html="<p>Short summary</p>",
        max_chars=100,
    )
    assert cleaned.text == "Short summary"
    assert cleaned.is_full_content is False
    assert cleaned.needs_enrichment is True


def test_canonicalize_url_normalizes_query_and_fragment() -> None:
    raw = "HTTPS://Example.com:443/news?id=2&a=1#fragment"
    assert canonicalize_url(raw) == "https://example.com/news?a=1&id=2"

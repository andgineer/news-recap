from news_recap.ingestion.language import detect_language


def test_detect_language_ru() -> None:
    assert detect_language("Сегодня произошло важное событие") == "ru"


def test_detect_language_sr_cyrillic() -> None:
    assert detect_language("Ђоковић је освојио титулу") == "sr"


def test_detect_language_sr_latin() -> None:
    assert detect_language("Đoković je osvojio titulu") == "sr"


def test_detect_language_en() -> None:
    assert detect_language("Markets closed higher after earnings reports") == "en"


def test_detect_language_unknown() -> None:
    assert detect_language("12345 !!!") == "unknown"

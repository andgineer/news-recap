from news_recap import __version__
from news_recap.main import news_recap
from click.testing import CliRunner


def test_version():
    assert __version__


def test_version_option():
    runner = CliRunner()
    result = runner.invoke(news_recap, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output

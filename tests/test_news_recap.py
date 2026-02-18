import allure
from click.testing import CliRunner

from news_recap import __version__
from news_recap.main import news_recap

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Routing, Failures, CLI Ops"),
]


def test_version():
    assert __version__


def test_version_option():
    runner = CliRunner()
    result = runner.invoke(news_recap, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output

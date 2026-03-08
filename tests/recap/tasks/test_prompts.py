"""Tests for PromptTemplate / render_prompt."""

from __future__ import annotations


from news_recap.recap.tasks.prompts import (
    PromptBackend,
    PromptTemplate,
    render_prompt,
    RECAP_CLASSIFY_BATCH_PROMPT,
    RECAP_ENRICH_BATCH_PROMPT,
    RECAP_MAP_PROMPT,
    RECAP_REDUCE_PROMPT,
    RECAP_SPLIT_PROMPT,
    RECAP_GROUP_SECTIONS_PROMPT,
    RECAP_DEDUP_PROMPT,
    RECAP_SUMMARIZE_PROMPT,
)


def test_render_prompt_cli_includes_suffix():
    template = PromptTemplate(body="Body {x}.", cli_suffix="\nCLI-only")
    result = render_prompt(template, PromptBackend.CLI, x="hello")
    assert result == "Body hello.\nCLI-only"


def test_render_prompt_api_omits_suffix():
    template = PromptTemplate(body="Body {x}.", cli_suffix="\nCLI-only")
    result = render_prompt(template, PromptBackend.API, x="hello")
    assert result == "Body hello."


def test_render_prompt_placeholder_formatting_both_modes():
    template = PromptTemplate(body="Count={n} name={name}", cli_suffix=" [cli]")
    cli = render_prompt(template, PromptBackend.CLI, n="5", name="test")
    api = render_prompt(template, PromptBackend.API, n="5", name="test")
    assert "Count=5" in cli
    assert "name=test" in cli
    assert "[cli]" in cli
    assert "Count=5" in api
    assert "name=test" in api
    assert "[cli]" not in api


def test_cli_prompts_include_do_not_write_constraint():
    """All CLI prompts must contain the do-not-write-scripts constraint."""
    for template in (
        RECAP_CLASSIFY_BATCH_PROMPT,
        RECAP_ENRICH_BATCH_PROMPT,
        RECAP_MAP_PROMPT,
        RECAP_REDUCE_PROMPT,
        RECAP_SPLIT_PROMPT,
        RECAP_GROUP_SECTIONS_PROMPT,
        RECAP_DEDUP_PROMPT,
        RECAP_SUMMARIZE_PROMPT,
    ):
        rendered = render_prompt(
            template,
            PromptBackend.CLI,
            **_dummy_kwargs(template),
        )
        assert "Do NOT write any scripts" in rendered, (
            f"CLI prompt missing constraint: {template!r}"
        )


def test_api_prompts_omit_do_not_write_constraint():
    """API prompts must NOT contain the do-not-write-scripts constraint."""
    for template in (
        RECAP_CLASSIFY_BATCH_PROMPT,
        RECAP_ENRICH_BATCH_PROMPT,
        RECAP_MAP_PROMPT,
        RECAP_REDUCE_PROMPT,
        RECAP_SPLIT_PROMPT,
        RECAP_GROUP_SECTIONS_PROMPT,
        RECAP_DEDUP_PROMPT,
        RECAP_SUMMARIZE_PROMPT,
    ):
        rendered = render_prompt(
            template,
            PromptBackend.API,
            **_dummy_kwargs(template),
        )
        assert "Do NOT write any scripts" not in rendered, (
            f"API prompt should not contain CLI constraint: {template!r}"
        )


def _dummy_kwargs(template: PromptTemplate) -> dict[str, str]:
    """Return dummy values for all placeholders in a template."""
    import string

    formatter = string.Formatter()
    return {
        field_name: "x"
        for _, field_name, _, _ in formatter.parse(template.body + template.cli_suffix)
        if field_name is not None
    }

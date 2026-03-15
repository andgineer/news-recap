"""Tests for PromptTemplate / render_prompt."""

from __future__ import annotations

import string

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
    RECAP_DEDUP_MULTI_PROMPT,
    RECAP_SUMMARIZE_PROMPT,
)

_ALL_PROMPTS = (
    RECAP_CLASSIFY_BATCH_PROMPT,
    RECAP_ENRICH_BATCH_PROMPT,
    RECAP_MAP_PROMPT,
    RECAP_REDUCE_PROMPT,
    RECAP_SPLIT_PROMPT,
    RECAP_GROUP_SECTIONS_PROMPT,
    RECAP_DEDUP_PROMPT,
    RECAP_DEDUP_MULTI_PROMPT,
    RECAP_SUMMARIZE_PROMPT,
)


def _dummy_kwargs(template: PromptTemplate) -> dict[str, str]:
    """Return dummy values for all placeholders except output_instruction (auto-injected)."""
    formatter = string.Formatter()
    return {
        field_name: "x"
        for _, field_name, _, _ in formatter.parse(template.body)
        if field_name is not None and field_name != "output_instruction"
    }


def test_render_prompt_cli_injects_instruction():
    template = PromptTemplate(body="Intro\n{output_instruction}Data: {x}")
    result = render_prompt(template, PromptBackend.CLI, x="hello")
    assert "Do NOT write any scripts" in result
    assert "Print your output directly to stdout" in result
    assert "Data: hello" in result


def test_render_prompt_api_omits_instruction():
    template = PromptTemplate(body="Intro\n{output_instruction}Data: {x}")
    result = render_prompt(template, PromptBackend.API, x="hello")
    assert "Do NOT write any scripts" not in result
    assert result == "Intro\nData: hello"


def test_render_prompt_instruction_position():
    """Instruction appears between static text and the data placeholder."""
    template = PromptTemplate(body="Format:\nfoo\n\n{output_instruction}=== DATA ===\n{data}")
    result = render_prompt(template, PromptBackend.CLI, data="item1\nitem2")
    instr_pos = result.index("Do NOT write")
    data_pos = result.index("=== DATA ===")
    format_pos = result.index("Format:")
    assert format_pos < instr_pos < data_pos


def test_all_prompts_have_output_instruction_placeholder():
    """Every prompt body must contain the {output_instruction} placeholder."""
    for template in _ALL_PROMPTS:
        assert "{output_instruction}" in template.body, (
            f"Prompt missing {{output_instruction}} placeholder: {template!r}"
        )


def test_cli_prompts_include_do_not_write_constraint():
    """All CLI prompts must contain the do-not-write-scripts constraint."""
    for template in _ALL_PROMPTS:
        rendered = render_prompt(template, PromptBackend.CLI, **_dummy_kwargs(template))
        assert "Do NOT write any scripts" in rendered, (
            f"CLI prompt missing constraint: {template!r}"
        )


def test_api_prompts_omit_do_not_write_constraint():
    """API prompts must NOT contain the do-not-write-scripts constraint."""
    for template in _ALL_PROMPTS:
        rendered = render_prompt(template, PromptBackend.API, **_dummy_kwargs(template))
        assert "Do NOT write any scripts" not in rendered, (
            f"API prompt should not contain CLI constraint: {template!r}"
        )

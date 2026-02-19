from __future__ import annotations

import allure

from news_recap.orchestrator.output_fallback import recover_output_contract_from_stdout

pytestmark = [
    allure.epic("LLM Runtime"),
    allure.feature("Output Contract"),
]


def test_recover_output_contract_from_fenced_json() -> None:
    stdout = """
Some text before.
```json
{
  "blocks": [
    {"text": "Recovered block", "source_ids": ["article:1"]}
  ]
}
```
Some text after.
""".strip()
    recovered = recover_output_contract_from_stdout(
        stdout_text=stdout,
        allowed_source_ids={"article:1", "article:2"},
    )
    assert recovered is not None
    assert len(recovered.blocks) == 1
    assert recovered.blocks[0].text == "Recovered block"
    assert recovered.blocks[0].source_ids == ["article:1"]
    assert recovered.metadata["stdout_parser"] == "json_payload_normalized"

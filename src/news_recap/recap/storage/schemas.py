"""I/O JSON schemas (as hint strings) for each recap pipeline step."""

from __future__ import annotations

RECAP_CLASSIFY_OUTPUT_SCHEMA = """\
{
  "status": "done"
}

Actual per-article verdicts go into output_results_dir as {id}_out.txt files,
each containing exactly one word: ok, enrich, or trash."""

RECAP_ENRICH_OUTPUT_SCHEMA = """\
{
  "enriched": [
    {
      "article_id": "<source_id>",
      "new_title": "<informative headline rewritten from source>",
      "clean_text": "<cleaned and de-duplicated article body>"
    }
  ]
}"""

RECAP_GROUP_OUTPUT_SCHEMA = """\
{
  "events": [
    {
      "event_id": "<generated unique id, e.g. evt_001>",
      "title": "<descriptive event headline>",
      "significance": "high" | "medium" | "low",
      "article_ids": ["<source_id>", "..."],
      "topic_tags": ["<tag1>", "..."]
    }
  ]
}"""

RECAP_ENRICH_FULL_OUTPUT_SCHEMA = RECAP_ENRICH_OUTPUT_SCHEMA

RECAP_SYNTHESIZE_OUTPUT_SCHEMA = """\
{
  "status": "completed",
  "processed": <number of events processed>
}

Additionally, write one JSON file per event to output_results_dir:

event_{event_id}.json:
{
  "event_id": "<id>",
  "synthesis": "<informative factual narrative combining all sources>",
  "summary": "<2-3 sentence overview>",
  "key_facts": ["<fact1>", "..."],
  "sources_used": ["<article_id>", "..."]
}"""

RECAP_COMPOSE_OUTPUT_SCHEMA = """\
{
  "theme_blocks": [
    {
      "theme": "<thematic group name, e.g. 'Ukraine conflict'>",
      "recaps": [
        {
          "headline": "<concise informative headline>",
          "body": "<informative event description, factual not literary>",
          "sources": [
            {
              "title": "<original article title>",
              "url": "<original article URL>"
            }
          ]
        }
      ]
    }
  ],
  "meta": {
    "total_events": <N>,
    "total_themes": <N>,
    "date": "<YYYY-MM-DD>"
  }
}"""

SCHEMAS_BY_TASK_TYPE: dict[str, str] = {
    "recap_classify": RECAP_CLASSIFY_OUTPUT_SCHEMA,
    "recap_enrich": RECAP_ENRICH_OUTPUT_SCHEMA,
    "recap_group": RECAP_GROUP_OUTPUT_SCHEMA,
    "recap_enrich_full": RECAP_ENRICH_FULL_OUTPUT_SCHEMA,
    "recap_synthesize": RECAP_SYNTHESIZE_OUTPUT_SCHEMA,
    "recap_compose": RECAP_COMPOSE_OUTPUT_SCHEMA,
}

"""Prompt templates for each recap pipeline step."""

from __future__ import annotations

_FILE_IO_RULES = """
IMPORTANT — execution rules:
- Read task_manifest.json first to find the paths to input files and the output path.
- Read all input files (articles_index.json, resource files) referenced in the manifest.
- Write the result JSON to the output path specified in the manifest.
- You MAY use short scripts to read/write JSON files if the data volume is large.
- Do NOT write complex multi-file programs, web scrapers, or data pipelines.
- Focus on ANALYSIS and producing the correct JSON output.
"""

RECAP_CLASSIFY_PROMPT = """\
You are a news editor deciding which headlines to keep for a daily digest.

Two reference files describe your editorial policy:
- input/_discard.txt — describes categories of stories to discard
- input/_priority.txt — describes categories where the reader wants deeper coverage

These are topic descriptions, not keyword lists. A headline may relate to a
described category even without sharing any exact words with the description.
Read these files carefully and understand the editorial intent behind each category.

Headline files are in input/resources/ as {{id}}_in.txt (one headline per file).

For each headline, read it and reason: what real-world story does this headline
refer to? Then decide:

1. Is the headline clear enough that you can tell what the story is about
   and whether it relates to any category described in DISCARD or PRIORITY?
   If you cannot tell → verdict is "enrich" (headline needs rewriting).

2. Can the story be attributed to any category described in _discard.txt?
   If yes → verdict is "trash".

3. Otherwise → verdict is "ok".
   PRIORITY categories are NOT a filter. They indicate where the reader wants
   extra detail later. Keep all world news that does not match DISCARD.

Write each verdict (one word: ok, enrich, or trash) to output/results/{{id}}_out.txt.
Process every headline file.
"""

RECAP_ENRICH_PROMPT = """\
You are processing news articles to prepare them for a digest.

For each article file in the input resources directory:
- Read the article content (title, url, text)
- Rewrite the title to be informative and factual (not clickbait)
- Clean the article text: remove boilerplate, ads, navigation fragments
- Preserve all unique factual information

Output format: write a JSON object with an "enriched" array to output_result_path.
Each item must have: article_id, new_title, clean_text.
""" + _FILE_IO_RULES

RECAP_GROUP_PROMPT = """\
You are grouping news articles into real-world events for a daily digest.

Articles are provided in articles_index. Each article has: source_id, title, url, source.
Some articles may also have enriched text available in the input resources.

Your task:
1. Identify distinct real-world events that multiple articles cover
2. Group articles by event — an article can belong to exactly one event
3. Assign significance: "high" for major breaking news, "medium" for noteworthy,
   "low" for minor/local
4. Articles that don't fit any event should be grouped as single-article events

Important: limit events to the most informative articles. For dominant events
(e.g. a major conflict), include no more than 10 of the most informative articles.

Output format: write a JSON object with an "events" array to output_result_path.
Each event must have: event_id, title, significance, article_ids, topic_tags.
""" + _FILE_IO_RULES

RECAP_ENRICH_FULL_PROMPT = """\
You are enriching articles from significant news events with full-text content.

For each article file in the input resources directory:
- Read the full article content (fetched from the original source URL)
- Rewrite the title to be informative and factual
- Clean and structure the full text: remove boilerplate, preserve all factual details
- This is the deep enrichment pass — capture as much factual information as possible

Output format: write a JSON object with an "enriched" array to output_result_path.
Each item must have: article_id, new_title, clean_text.
""" + _FILE_IO_RULES

RECAP_SYNTHESIZE_PROMPT = """\
You are synthesizing news events from multiple source articles.

For each event file in the input resources directory:
- Read all articles belonging to this event
- Build a single INFORMATIVE narrative that combines all sources WITHOUT repetition
- Preserve unique details from each source
- The synthesis must be FACTUAL and INFORMATIVE — not literary or flowery
- If original sources are overly literary, extract the facts and present them clearly
- Create a 2-3 sentence summary and a list of key facts

Write one output file per event to output_results_dir: event_{{event_id}}.json
Each file must have: event_id, synthesis, summary, key_facts, sources_used.

Also write a summary to output_result_path:
{{"status": "completed", "processed": <number of events>}}
""" + _FILE_IO_RULES

RECAP_COMPOSE_PROMPT = """\
You are composing the final daily news digest from synthesized events.

For each event file in the input resources directory:
- Read the event synthesis, summary, and source articles
- Group events into thematic blocks (e.g. "International", "Technology", "Economy")
- For each event, create a recap with:
  - headline: concise, informative (max {max_headline_chars} characters)
  - body: factual informative description of the event
  - sources: list of original article titles with URLs (for reader reference)

Balance the digest:
- Don't let one dominant event overshadow the rest
- Include variety across themes
- Order themes by significance/interest

User preferences:
{preferences}

Output format: write a JSON object with "theme_blocks" array to output_result_path.
Each theme_block has: theme, recaps[]. Each recap has: headline, body, sources[].
Also include a "meta" object with: total_events, total_themes, date.
""" + _FILE_IO_RULES

PROMPTS_BY_TASK_TYPE: dict[str, str] = {
    "recap_classify": RECAP_CLASSIFY_PROMPT,
    "recap_enrich": RECAP_ENRICH_PROMPT,
    "recap_group": RECAP_GROUP_PROMPT,
    "recap_enrich_full": RECAP_ENRICH_FULL_PROMPT,
    "recap_synthesize": RECAP_SYNTHESIZE_PROMPT,
    "recap_compose": RECAP_COMPOSE_PROMPT,
}

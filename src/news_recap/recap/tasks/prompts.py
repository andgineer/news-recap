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
- input/_trash.txt — describes categories of stories to discard
- input/_follow.txt — describes topics the reader wants to follow

These are topic descriptions, not keyword lists. A headline may relate to a
described category even without sharing any exact words with the description.
Read these files carefully and understand the editorial intent behind each category.

Headline files are in input/resources/ as {{id}}_in.txt (one headline per file).

For each headline, read it and decide:

1. Can the story be attributed to a category described in _trash.txt?
   If yes → verdict is "trash".

2. Does the story match a topic described in _follow.txt?
   If yes → verdict is "follow".

3. Is the headline too vague to identify the specific story?
   If yes → verdict is "vague".

4. Otherwise → verdict is "ok".

Write each verdict (one word: ok, vague, follow, or trash) to output/results/{{id}}_out.txt.
Process every headline file.
"""

RECAP_CLASSIFY_BATCH_PROMPT = """\
You are a news editor deciding which headlines to keep for a daily digest.

EDITORIAL POLICY — TRASH:
{trash_policy}

EDITORIAL POLICY — FOLLOW:
{follow_policy}

These are topic descriptions, not keyword lists. A headline may relate to a
described category even without sharing any exact words with the description.

For each headline below, decide:
1. Story matches a TRASH category → trash
2. Story matches a FOLLOW topic → follow
3. Headline too vague to identify the specific story → vague
4. Otherwise → ok

Do NOT write any scripts, use any tools, or read any files.
Read the headlines below and print your verdicts directly to stdout.

Print EXACTLY {expected_count} lines to stdout,
one per headline, in the same order as the list below.
Format: NUMBER: VERDICT  (VERDICT is one of: ok, vague, follow, trash)

Example output (4 headlines):
1: ok
2: trash
3: vague
4: follow

=== HEADLINES ===
{headlines_block}"""

RECAP_ENRICH_BATCH_PROMPT = """\
You are processing news articles to prepare them for a digest.

For each article below:
- Rewrite the title to be informative and factual (not clickbait)
- Clean the article text: remove boilerplate, ads, navigation fragments
- Preserve all unique factual information
- Keep the cleaned text concise — aim for the core facts in 1-3 paragraphs

Do NOT write any scripts, use any tools, or read any files.
Read the articles below and print your results directly to stdout.

Print EXACTLY {expected_count} blocks to stdout,
one per article, in the same order as the list below.
Format: NUMBER<TAB>new_title<TAB>clean_text
(tab-separated, clean_text on one line — replace newlines with spaces)

Example output (2 articles):
1	New factual title for first article	Cleaned article text with key facts preserved.
2	New factual title for second article	Another cleaned article with all boilerplate removed.

=== ARTICLES ===
{articles_block}"""

RECAP_GROUP_PROMPT = (
    """\
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
"""
    + _FILE_IO_RULES
)

RECAP_ENRICH_FULL_PROMPT = RECAP_ENRICH_BATCH_PROMPT

RECAP_SYNTHESIZE_PROMPT = (
    """\
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
"""
    + _FILE_IO_RULES
)

RECAP_COMPOSE_PROMPT = (
    """\
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
"""
    + _FILE_IO_RULES
)

PROMPTS_BY_TASK_TYPE: dict[str, str] = {
    "recap_classify": RECAP_CLASSIFY_PROMPT,
    "recap_enrich": RECAP_ENRICH_BATCH_PROMPT,
    "recap_group": RECAP_GROUP_PROMPT,
    "recap_enrich_full": RECAP_ENRICH_FULL_PROMPT,
    "recap_synthesize": RECAP_SYNTHESIZE_PROMPT,
    "recap_compose": RECAP_COMPOSE_PROMPT,
}

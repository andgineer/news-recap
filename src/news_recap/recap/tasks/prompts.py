"""Prompt templates for each recap pipeline step."""

from __future__ import annotations

RECAP_CLASSIFY_BATCH_PROMPT = """\
You are a news editor deciding which headlines to keep for a daily digest.

EDITORIAL POLICY — EXCLUDE:
{exclude_policy}

EDITORIAL POLICY — FOLLOW:
{follow_policy}

These are topic descriptions, not keyword lists. A headline may relate to a
described category even without sharing any exact words with the description.

For each headline below, decide:
1. Story matches an EXCLUDE category → exclude
2. Story matches a FOLLOW topic → follow
3. Headline too vague to identify the specific story → vague
4. Otherwise → ok

Do NOT write any scripts, use any tools, or read any files.
Read the headlines below and print your verdicts directly to stdout.

Print EXACTLY {expected_count} lines to stdout,
one per headline, in the same order as the list below.
Format: NUMBER: VERDICT  (VERDICT is one of: ok, vague, follow, exclude)

Example output (4 headlines):
1: ok
2: exclude
3: vague
4: follow

=== HEADLINES (format: NUMBER: HEADLINE) ===
{headlines_block}"""

RECAP_ENRICH_BATCH_PROMPT = """\
You are a senior news editor. Your job is to rewrite article headlines so \
the reader gets maximum information without opening the article.

For each article below, write a headline that captures the essence of \
the story — what happened, who is involved, where, when, and why it \
matters. Be specific and factual — no clickbait, no vague teasers. \
Write in the same language as the original article.

Do NOT write any scripts, use any tools, or read any files.
Print your output directly to stdout.

Print EXACTLY {expected_count} entries. For each article, print:
- The article number on its own line
- The new headline on the next line
- Then a blank line

Example output (2 articles):
1
Specific factual headline for first article

2
Specific factual headline for second article

=== ARTICLES ===
{articles_block}"""

RECAP_MAP_PROMPT = """\
You are a senior news editor. Group ALL headlines below into blocks.

Group headlines so that the essential information from all articles in a block \
fits into an informative title of 1-3 sentences. The reader should understand \
what happened from the title alone.

Headlines about the same event, the same country's affairs, or the same ongoing \
story belong in one block if they can be jointly described in 1-3 informative \
sentences.

Do NOT mix genuinely unrelated events. "Swiss resort fire and Venice carnival" \
in one block is unacceptable.
Do NOT create newspaper-section blocks like "Sports and Culture" or "World News". \
Each block must describe specific news, not a topic category.
Do NOT mix genuinely unrelated news in one block.

GOOD title: "Heavy snow hits Serbia; most roads cleared but the Valjevo road \
remains blocked."
BAD title: "Flooding in Nepal" — no details on casualties or scale.
BAD title: "10,000 programmers laid off" — where? why?
BAD: "Serbian news" — not informative.
BAD: "Global politics" — a category, not an event description.
BAD: "Crime and Legal Matters" — this is a newspaper section, not a story.
BAD: "Travel, Culture and Sports" — unrelated topics dumped together.
BAD: "Diverse Global Developments" — meaningless catch-all.
If a headline does not fit any group, it is better as a single-article block \
with an informative title than forced into an unrelated category.

Every headline number must appear in exactly one block.
Do not skip any headline.

FOLLOW (give extra attention): {follow_policy}

Do NOT write any scripts, use any tools, or read any files.
Print your output directly to stdout.

Output format:
BLOCK: <informative title>
<comma-separated headline numbers>

=== HEADLINES ({headline_count} total, format: NUMBER: HEADLINE) ===
{headlines_block}"""

RECAP_REDUCE_PROMPT = """\
You are a senior news editor. Several desks independently produced block lists. \
Your job: merge blocks that overlap, then write a unified list.

Each desk saw only a fraction of today's articles. Merge blocks whose articles \
can be described together in an informative title of up to 5 sentences. \
The reader should understand what happened from the title alone.

Do NOT merge blocks about genuinely unrelated subjects into one.
Do NOT create newspaper-section blocks like "Sports and Culture" or "World News". \
Each block must describe specific news, not a topic category.

GOOD title: "Serbian Interior Minister Dačić hospitalized with severe pneumonia; \
Vučić, Dodik and police unions express support; slight improvement reported."
BAD: "Serbian news" — not informative.
BAD: "Global politics" — a category, not an event description.
BAD: "Crime and Legal Matters" — a newspaper section, not a story.
BAD: "Social and societal issues" — meaningless catch-all.
BAD: "European politics" — too broad, not specific news.

Blocks titled "Uncategorized" — merge into the most relevant block, or mark \
as SPLIT. Never output "Uncategorized".

More than 30 articles in one block — almost certainly too broad, mark as SPLIT.

Too broad for 5 informative sentences — mark as SPLIT.

Do NOT write any scripts, use any tools, or read any files.
Print your output directly to stdout.

CRITICAL: each source block number must appear in exactly one output line. \
Never repeat a block number across multiple lines.

Output format — one of two line types per block:

BLOCK: <informative title>
<comma-separated source block numbers>

SPLIT: <best-effort combined title>
<comma-separated source block numbers>

=== BLOCK TITLES ===
{block_titles}"""

RECAP_SPLIT_PROMPT = """\
You are a senior news editor. The block below is too broad. Split it into \
smaller blocks.

Each block's title — up to 5 informative sentences. The reader should \
understand what happened from the title alone.

Do NOT mix genuinely unrelated articles in one block.
Do NOT create blocks with vague titles like "Political news" or "Various \
developments". Each title must describe specific news.

A single-article block is acceptable when an article has nothing in common \
with the rest.

Every article number must appear in exactly one block.

Do NOT write any scripts, use any tools, or read any files.
Print your output directly to stdout.

Output format:
BLOCK: <informative title>
<comma-separated article numbers>

=== ARTICLES ===
{articles_block}"""

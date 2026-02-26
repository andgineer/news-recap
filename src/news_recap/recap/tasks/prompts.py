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
You are a senior news editor. Compress these headlines into around {max_blocks} \
blocks for a daily digest.

A block = a group of headlines that can be described in one informative title \
without mixing unrelated events. The title is 2-4 sentences telling the reader \
what happened. The reader sees ONLY titles to understand the day's news.

GOOD block: "Heavy snow hits western Serbia, Valjevo road blocked, traffic \
disrupted across the region" — related events, one coherent picture.
BAD block: "Snow in Serbia and 15 infants die in Sarajevo hospital" — unrelated \
events forced into one title.

Merge aggressively when headlines belong together.

FOLLOW: {follow_policy}

Do NOT write any scripts, use any tools, or read any files.
Print your output directly to stdout.

Output format:
BLOCK: <2-4 sentence title>
<comma-separated headline numbers>

=== HEADLINES (format: NUMBER: HEADLINE) ===
{headlines_block}"""

RECAP_REDUCE_PROMPT = """\
You are a senior news editor. Several desks produced block lists independently. \
Review the combined block titles below and produce a unified block list.

Rules:
- Merge all blocks that overlap in topic. If the merged result can be \
described by one informative 2-4 sentence title — keep as one block. \
If too broad for a single title — split so that each part has its own \
informative title.

BLOCK TITLES:
{block_index}

In input/blocks/ there is one file per block. Each file has:
- Line 1: block title
- Remaining lines: article_id: headline

Write final blocks to output/blocks/ in the same format.
Merged blocks = combined article lists with new title.
Split blocks = articles redistributed across new files.
Unchanged blocks = copy as-is."""

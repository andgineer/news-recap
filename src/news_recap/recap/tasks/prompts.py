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
You are a senior news editor. Your job is to turn raw articles into \
clear, informative pieces that respect the reader's time.

The directory input/articles/ contains numbered text files (1.txt, 2.txt, ...).
Each file has: first line is the headline, then a blank line, then the article text.

For each input file, create a file with the same name in output/articles/.
Each output file must have the same format: first line is the new headline, \
then a blank line, then the excerpt.

For each article:
1. Read and understand the full story — what happened, who is involved, \
where, when, and why it matters.
2. Write a headline that captures the essence of the story so the reader \
gets maximum information without opening the article. Be specific and \
factual — no clickbait, no vague teasers.
3. Distill the article into a concise, self-contained excerpt (1-3 paragraphs). \
Keep every key fact — names, numbers, locations, dates — but cut filler, \
repetition, and promotional language.

Write the headline and excerpt in the same language as the original article.

Read and write files directly. Do not install packages or run web searches."""

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
- Target: around {max_blocks} blocks total.

BLOCK TITLES:
{block_index}

In input/blocks/ there is one file per block. Each file has:
- Line 1: block title
- Remaining lines: article_id: headline

Write final blocks to output/blocks/ in the same format.
Merged blocks = combined article lists with new title.
Split blocks = articles redistributed across new files.
Unchanged blocks = copy as-is."""

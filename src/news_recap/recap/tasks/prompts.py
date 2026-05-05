"""Prompt templates for each recap pipeline step."""

from __future__ import annotations

import enum
from dataclasses import dataclass

_CLI_OUTPUT_INSTRUCTION = (
    "Do NOT write any files. Do NOT make any network or web requests.\n"
    "Type your answer as plain text directly in this response — your reply text IS the output.\n"
)


@dataclass(frozen=True)
class PromptTemplate:
    """Backend-aware prompt template.

    The body must contain an ``{output_instruction}`` placeholder at the
    location where backend-specific output instructions should appear
    (typically just before the data section).  ``render_prompt`` fills it
    with the appropriate text for the active backend.
    """

    body: str


class PromptBackend(enum.Enum):
    CLI = "cli"
    API = "api"


def render_prompt(template: PromptTemplate, backend: PromptBackend, **kwargs: str) -> str:
    """Render *template* for the given *backend*, substituting *kwargs* placeholders.

    ``output_instruction`` is injected automatically based on *backend*;
    callers must not pass it explicitly.
    """
    kwargs["output_instruction"] = _CLI_OUTPUT_INSTRUCTION if backend == PromptBackend.CLI else ""
    return template.body.format(**kwargs)


RECAP_CLASSIFY_BATCH_PROMPT = PromptTemplate(
    body="""\
You are a news editor deciding which headlines to keep for a daily digest.

EDITORIAL POLICY — EXCLUDE:
{exclude_policy}

These are topic descriptions, not keyword lists. A headline may relate to a
described category even without sharing any exact words with the description.

For each headline below, decide:
1. Story matches an EXCLUDE category → exclude
2. Headline is vague or clickbait — it hides key facts behind teasers, \
rhetorical questions, or deliberate omissions (e.g. "on a popular \
island…", "one trend…", "the secret of…", "expert revealed…") → vague
3. Otherwise → ok

Read the headlines below and provide your verdicts.

Print EXACTLY {expected_count} lines to stdout,
one per headline, in the same order as the list below.
Format: NUMBER: VERDICT  (VERDICT is one of: ok, vague, exclude)

Example output (3 headlines):
1: ok
2: exclude
3: vague

=== HEADLINES (format: NUMBER: HEADLINE) ===
{output_instruction}{headlines_block}""",
)

RECAP_ENRICH_BATCH_PROMPT = PromptTemplate(
    body="""\
You are a senior news editor. Your job is to rewrite article headlines so \
the reader gets maximum information without opening the article.

For each article below, write a headline that captures the essence of \
the story — what happened, who is involved, where, when, and why it \
matters. Be specific and factual — no clickbait, no vague teasers. \
Write in the same language as the original article.

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
{output_instruction}{articles_block}""",
)

RECAP_DEDUP_PROMPT = PromptTemplate(
    body="""\
You are a senior news editor. Below is a list of news. \
Some of them may describe the same thing — just reported by different sources.

If several news describe the same thing and can be merged into one \
without losing important facts and without the result growing longer \
than the longest original by more than ~25% — merge them into a single \
entry with a new, informative description.

Do NOT merge news that are merely related or happen in the same country. \
Only merge news that a reader would consider the same piece of news.

Requirements for merged entries:
- Key facts from all merged news must be preserved
- The merged text must not be significantly longer than the longest original
- Be specific and factual — no clickbait, no vague teasers

OUTPUT LANGUAGE: {language}.
Write ALL text you produce — MERGED descriptions and any other output — in {language}.

News that cannot be meaningfully merged with others remain as they are.

Output format:

MERGED: <new text>
<comma-separated numbers>

SINGLE: <number>

Every number must appear exactly once — either in a MERGED group \
or as SINGLE.

Example:
MERGED: EU introduces 38% tariffs on Chinese electric vehicles starting July 2025
1, 3, 5
SINGLE: 2
SINGLE: 4

=== NEWS ({article_count} total) ===
{output_instruction}{articles_block}""",
)

RECAP_DEDUP_MULTI_PROMPT = PromptTemplate(
    body="""\
You are a senior news editor. Below are groups of news articles, one group per CLUSTER.
Within each cluster, some articles may describe the same event reported by different sources.

If several articles in a cluster describe the same thing and can be merged without losing \
important facts and without the result growing longer than the longest original by more \
than ~25% — merge them into a single entry with a new, informative description.

Do NOT merge articles that are merely related. \
Only merge articles that a reader would consider the same piece of news.

Requirements for merged entries:
- Key facts from all merged articles must be preserved
- Be specific and factual — no clickbait, no vague teasers
- Write ALL entries in {language}

Articles that cannot be meaningfully merged remain as SINGLE.

Output format — repeat for every cluster, numbers are LOCAL to each cluster:

CLUSTER N:
MERGED: <new text>
<comma-separated local numbers>

SINGLE: <local number>

Every local number must appear exactly once per cluster.

Example with 2 clusters:

CLUSTER 1:
MERGED: EU introduces 38% tariffs on Chinese electric vehicles starting July 2025
1, 3
SINGLE: 2

CLUSTER 2:
SINGLE: 1
SINGLE: 2

REMINDER — ALL output MUST be in {language}.
{output_instruction}{clusters_block}""",
)

_SINGLE_SHOT_BODY = """\
You are a news editor. Below is a list of articles.

OUTPUT LANGUAGE: {language}.
ALL human-readable text you produce — section labels, section summaries, and \
block descriptions — MUST be written in {language}, even when the source \
articles are in different languages. Translate the meaning into {language}; \
do NOT transliterate, copy, or carry over phrases from the source language \
(for example, do not turn Serbian/Croatian Latin into Cyrillic letter-by-letter — \
write in proper {language}). Keywords (SECTION:, SECTION_SUMMARY:, BLOCK:, \
ARTICLES:, EXCLUDED:) stay in English regardless of the content language.

EDITORIAL FOCUS — KEEP SEPARATE:
{follow_policy}

Each topic listed above must have its own dedicated section. \
Do NOT merge them with each other or with broader regional or thematic groups \
(for example, do not fold a "Serbia" section into a "Balkans" section, \
and do not mix Serbian and Ukrainian news in one section).

Your task:
1. Group related articles into thematic blocks.
2. Organize the blocks into broader sections.
3. For each BLOCK write 1-2 complete sentences that tell the reader what \
actually happened: specific actors, specific places, specific events, \
specific outcomes. This text IS the only thing the reader sees about that \
block — it must let them skip opening the block and still know the substance.
   - BAD (a topic / category label, not what we want): \
"Incidents and law enforcement in Serbia"
   - GOOD (describes the actual events): "Belgrade police arrested two \
suspects after a fatal stabbing in Zemun and a 30-day investigative \
detention was ordered for a murder in New Belgrade; in Niš a woman hit a \
16-year-old with her car and fled the scene."
   - Do NOT use Markdown formatting in the BLOCK line — no **bold**, no \
headings, no bullets, no asterisks. Plain prose only.
   - If many distinct events seem to fit one topic, split them into several \
smaller blocks, each describing its own specific events.
4. For each SECTION write a single short label naming the topic area \
(this one IS a label, not a description of events).
5. Articles that do not fit any coherent narrative: list as EXCLUDED. \
Do NOT create a catch-all "miscellaneous" block — unrelated leftovers \
belong in EXCLUDED, not in a junk-drawer block.

Every article number must appear exactly once — either in a BLOCK's ARTICLES list
or in EXCLUDED. Do not skip any article.

Work only from the articles provided. Do not search the web or invent information.
Read all articles first, then organize: start with small topic blocks, then group
blocks into sections.

Output format — repeat for each section, then its blocks:

SECTION: <section label>
SECTION_SUMMARY: <one sentence describing this section>
BLOCK: <1-2 sentence informative description of what happened in this group>
ARTICLES: <comma-separated numbers>
BLOCK: <1-2 sentence informative description of what happened in this group>
ARTICLES: <comma-separated numbers>

(next SECTION starts a new section)

EXCLUDED: <comma-separated numbers>  (omit if none)

REMINDER — ALL output MUST be in {language}.
{output_instruction}Articles:
{articles_block}"""
RECAP_ONESHOT_DIGEST_PROMPT = PromptTemplate(body=_SINGLE_SHOT_BODY)

RECAP_MERGE_SECTIONS_PROMPT = PromptTemplate(
    body="""\
You are a news editor. Articles were processed in batches, producing the sections below.
Some sections from different batches may cover the same or closely related topic.
Input sections may already be in {language} or in other languages — different batches
were processed independently and some may have leaked the source language.

OUTPUT LANGUAGE: {language}.
The canonical section name AND the section summary you produce MUST be in \
{language}, regardless of the language of the input section. Translate the \
meaning into {language}; do NOT transliterate, copy, or carry over phrases \
from the source language (for example, do not turn Serbian/Croatian Latin \
into Cyrillic letter-by-letter — write in proper {language}). The SECTION:, \
SECTION_SUMMARY:, INCLUDES: keywords stay in English.

KEEP-SEPARATE TOPICS:
{follow_policy}

Never merge a section dedicated to one of these topics into a broader regional \
or thematic section. Each listed topic must remain as its own standalone section \
(e.g. a "Serbia" section must NOT be merged into a "Balkans" section).

Your task:
1. Identify sections that cover the same topic.
2. Group them under one canonical name.
3. Write a combined one-sentence summary for each group.

Sections (numbered 1 to {total}):
{sections_block}

{output_instruction}Output format — one entry per final section:

SECTION: <canonical section name>
SECTION_SUMMARY: <one sentence combining coverage of the group>
INCLUDES: <comma-separated input section numbers>

Rules:
- Every input section number must appear exactly once across all INCLUDES lines.
- A section that stands alone has only its own number in INCLUDES.\
""",
)

RECAP_REFINE_LAYOUT_PROMPT = PromptTemplate(
    body="""\
You are a news editor reviewing small sections in today's digest.

OUTPUT LANGUAGE: {language}.
Every SECTION_SUMMARY you write MUST be in {language}. Translate the meaning \
into {language}; do NOT transliterate or carry over phrases from another \
language. Section titles in the input are already in {language} — copy them \
exactly. Keywords (SECTION:, SECTION_SUMMARY:, BLOCKS:) stay in English.

KEEP-SEPARATE TOPICS:
{follow_policy}

Never absorb a [SMALL] section whose subject is one of these topics into \
another section — keep it as its own section even with only 1-2 blocks.

Sections marked [SMALL] have only 1-2 blocks. For each [SMALL] section \
(that is NOT a keep-separate topic), \
decide whether its blocks can be absorbed into an existing larger section \
where they are a clear thematic fit. If no larger section fits, keep the \
small section as-is.

Rules:
- Only move blocks FROM a [SMALL] section INTO a larger section (3+ blocks).
- Do NOT move blocks out of sections that already have 3+ blocks.
- Do NOT merge two large sections together.
- Do NOT rename any section. Titles stay exactly as they were.
- A [SMALL] section should remain unchanged if no larger section is a \
clear thematic match — do not force it into a catch-all.
- [SMALL] is an input-only annotation — never include it in your output.
- Every block number (1 to {total_blocks}) must appear exactly once \
in one BLOCKS line.
- Do not skip, invent, or renumber blocks.

Current layout:
{layout_block}

{output_instruction}Output every section (including unchanged ones) in this format:

SECTION: <section title>
SECTION_SUMMARY: <one sentence>
BLOCKS: <comma-separated block numbers>\
""",
)

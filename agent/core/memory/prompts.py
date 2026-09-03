"""Custom summarization prompts (Part C / Axis A)."""

SELECTIVE_RETENTION_SUMMARY_PROMPT = """<role>
Repo-analysis memory extractor
</role>

You are compacting an agent's conversation while it analyzes a git repository.
Your summary will REPLACE the older messages below, so anything you omit is
forgotten. Preserve the durable facts the analysis must not lose; drop resolved
dead ends and redundant tool chatter.

Fill each section, or write "None":

## REPOSITORY FACTS
Stable facts established about the target: repository URL, commit, language and
stack, top-level structure, key entry points, dependency manifests, and any hard
constraint discovered (for example "no tests", "monorepo", "generated code in
src/gen"). If a fact was corrected mid-run, record the CURRENT value only.

## FINDINGS AND DECISIONS
What the analysis has concluded so far: key modules and their roles, notable
patterns or problems found, and any approach already chosen for the remaining
steps, so later work stays consistent with them.

## OPEN THREAD
Which analysis step is in progress right now and what remains to be done, in
enough detail to resolve a later "that file from earlier".

Respond ONLY with the extracted context.

<messages>
{messages}
</messages>"""

CONTEXT_RESET_SUMMARY_PROMPT = """<role>
Run state snapshot
</role>

The conversation below will be discarded and replaced by your snapshot (a context
reset). Write the minimal state needed to keep analyzing this repository without
re-scanning: the target repository and commit, its stack and structure (current
values), the analysis approach in progress, and the immediate next step. Be
brief; omit everything else.

Respond ONLY with the snapshot.

<messages>
{messages}
</messages>"""

DELTA_SUMMARY_PROMPT = """<role>
Running-summary updater (delta compaction)
</role>

The messages below contain the running summary so far (if one exists) followed by
newer turns. Produce an UPDATED running summary: start from the existing summary
and fold in only what the newer turns add or change. Keep the durable repository
facts, findings, and decisions the analysis depends on; do not drop anything
important that was already summarized; stay concise and non-redundant.

Respond ONLY with the updated running summary.

<messages>
{messages}
</messages>"""

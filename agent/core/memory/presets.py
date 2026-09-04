"""Named preset instances and the production-policy constants."""

from core.memory.config import MemoryConfig
from core.memory.prompts import (
    CONTEXT_RESET_SUMMARY_PROMPT,
    DELTA_SUMMARY_PROMPT,
    SELECTIVE_RETENTION_SUMMARY_PROMPT,
)

MEMORY_PRESETS: dict[str, MemoryConfig] = {
    # No compaction at all: the quality/memory upper bound and the
    # token-cost worst case.
    "full_history": MemoryConfig(name="full_history", summarization=False, context_editing=False),
    # --- DeepSeek long-context compaction experiment ----------------------
    # Four mechanism-isolation arms. All disable age-based context editing;
    # the capped arms instead perform one stable rewrite when tool output first
    # enters history. C200 arms summarize the complete selected prefix at 200k
    # and retain a controlled 50k-token recent tail.
    "exp_fh_raw": MemoryConfig(
        name="exp_fh_raw",
        summarization=False,
        context_editing=False,
        experiment_mode=True,
    ),
    "exp_fh_cap10k": MemoryConfig(
        name="exp_fh_cap10k",
        summarization=False,
        context_editing=False,
        tool_output_cap_bytes=40_000,
        experiment_mode=True,
    ),
    "exp_c200_raw": MemoryConfig(
        name="exp_c200_raw",
        summarization_trigger_tokens=200_000,
        summarization_keep_tokens=50_000,
        summarization_trim_tokens=None,
        summarization_input_guard_tokens=900_000,
        context_editing=False,
        experiment_mode=True,
    ),
    "exp_c200_cap10k": MemoryConfig(
        name="exp_c200_cap10k",
        summarization_trigger_tokens=200_000,
        summarization_keep_tokens=50_000,
        summarization_trim_tokens=None,
        summarization_input_guard_tokens=900_000,
        context_editing=False,
        tool_output_cap_bytes=40_000,
        experiment_mode=True,
    ),
    # Cache-friendly version of exp_c200_cap10k. It deliberately remains a
    # separate arm so the completed XML run stays reproducible and comparable.
    "exp_c200_cap10k_structured": MemoryConfig(
        name="exp_c200_cap10k_structured",
        summarization_trigger_tokens=200_000,
        summarization_keep_tokens=50_000,
        summarization_trim_tokens=None,
        summarization_input_guard_tokens=900_000,
        summarization_strategy="structured_prefix",
        context_editing=False,
        tool_output_cap_bytes=40_000,
        experiment_mode=True,
    ),
    # Stage-2 threshold sensitivity arms share the exact same cap, summary
    # input, and post-compaction retention. Only the trigger changes.
    "exp_c400_cap10k": MemoryConfig(
        name="exp_c400_cap10k",
        summarization_trigger_tokens=400_000,
        summarization_keep_tokens=50_000,
        summarization_trim_tokens=None,
        summarization_input_guard_tokens=900_000,
        context_editing=False,
        tool_output_cap_bytes=40_000,
        experiment_mode=True,
    ),
    "exp_c800_cap10k": MemoryConfig(
        name="exp_c800_cap10k",
        summarization_trigger_tokens=800_000,
        summarization_keep_tokens=50_000,
        summarization_trim_tokens=None,
        summarization_input_guard_tokens=900_000,
        context_editing=False,
        tool_output_cap_bytes=40_000,
        experiment_mode=True,
    ),
    # Historical production baseline. Keep this immutable: existing eval
    # findings and saved run labels named "prod" refer to these exact settings.
    "prod": MemoryConfig(name="prod"),
    # Current long-context production policy. This is the structured-prefix
    # stage-1 arm with its trigger moved from 200k to 800k; every other setting
    # stays identical so the summary call remains a strict cache-prefix
    # extension and tool outputs are capped once at insertion time.
    "prod_v2": MemoryConfig(
        name="prod_v2",
        summarization_trigger_tokens=800_000,
        summarization_keep_tokens=50_000,
        summarization_trim_tokens=None,
        summarization_input_guard_tokens=900_000,
        summarization_strategy="structured_prefix",
        context_editing=False,
        tool_output_cap_bytes=40_000,
        experiment_mode=True,
    ),
    # prod_v2 with the summarization trigger lowered from 800k to 500k (user
    # decision 2026-09-04): the Экземпляр thread lives forever (events + chat),
    # so compaction must fire well before a 128k–262k model window overflows.
    "prod_v3": MemoryConfig(
        name="prod_v3",
        summarization_trigger_tokens=500_000,
        summarization_keep_tokens=50_000,
        summarization_trim_tokens=None,
        summarization_input_guard_tokens=900_000,
        summarization_strategy="structured_prefix",
        context_editing=False,
        tool_output_cap_bytes=40_000,
        experiment_mode=True,
    ),
    "summarization_only": MemoryConfig(name="summarization_only", context_editing=False),
    "editing_only": MemoryConfig(name="editing_only", summarization=False),
    # How bad can cheap get: compaction fires early and keeps little.
    "aggressive": MemoryConfig(
        name="aggressive",
        summarization_trigger_tokens=8_000,
        summarization_keep_messages=8,
        context_editing_trigger_tokens=2_000,
        context_editing_keep=2,
    ),
    # prod compaction + long-term semantic memory (persistent profile store).
    "profile_memory": MemoryConfig(name="profile_memory", longterm_memory=True),
    # Part C / Axis B (F3): prod, but ClearToolUsesEdit also clears retrieval + KB
    # outputs (where the tokens are), so context editing actually fires.
    "clear_retrieval_kb": MemoryConfig(name="clear_retrieval_kb", clear_excludes_retrieval=False),
    # --- Part C / Axis B: retrieval & tool outputs -------------------------
    # prod + head/tail truncation of large tool outputs (incl. KB). Tests F1
    # (tokens live in tool outputs) by trimming the dominant source while
    # keeping the gist + any citation. Summarization/clearing stay on (prod).
    "observation_truncation": MemoryConfig(
        name="observation_truncation", truncate_tool_outputs=True
    ),
    # --- Part C / Axis A: memory & context management ----------------------
    # Each Axis-A arm isolates ONE history-compaction method. The two
    # "alternative to summarization" arms (sliding_window, prompt_compression)
    # turn summarization OFF and keep prod's tool-output clearing ON, so the only
    # change vs prod is how chat history is reduced. The two summarization-style
    # arms (selective_retention, context_reset) keep prod's stack and change only
    # the summary prompt (+ keep/trigger for the reset).
    #
    # Recency-only memory: keep the last N messages, drop older ones from the
    # model's view (no LLM summary). Cuts on a user-turn boundary to avoid
    # orphaning tool results. Expected to be cheap but to drop facts
    # established early in the run (F10).
    "sliding_window": MemoryConfig(
        name="sliding_window",
        summarization=False,
        sliding_window_keep=12,
    ),
    # Deterministic per-call text compaction instead of summarization. A cheap,
    # model-free stand-in for prompt compression: it screens the cost/cache
    # effect of rewriting the prompt prefix each turn (F2) without an extra LLM
    # call. Not a faithful LLMLingua-style compressor.
    "prompt_compression": MemoryConfig(
        name="prompt_compression",
        summarization=False,
        compress_prompt=True,
    ),
    # Quality-preserving compaction: prod, but the summary prompt is told to keep
    # the repository facts/findings/decisions later steps depend on. Isolates
    # "what the summary preserves" from prod's generic summary.
    "selective_retention": MemoryConfig(
        name="selective_retention",
        summary_prompt=SELECTIVE_RETENTION_SUMMARY_PROMPT,
    ),
    # Aggressive context reset seeded with a minimal state snapshot: summarize
    # early and keep few recent messages. A prefix rewrite, so it shares the F2
    # cache confound; the report shows tokens AND dollars to expose it.
    "context_reset": MemoryConfig(
        name="context_reset",
        summary_prompt=CONTEXT_RESET_SUMMARY_PROMPT,
        summarization_trigger_tokens=15_000,
        summarization_keep_messages=4,
    ),
    # The principled answer to F9 (Axis A subsystem): instead of carrying or
    # summarizing all history, keep the last 2 turn-blocks and retrieve only the
    # top-3 most relevant older blocks for the current question. Summarization
    # off (retrieval replaces it); prod clearing stays on.
    "incontext_history_retrieval": MemoryConfig(
        name="incontext_history_retrieval",
        summarization=False,
        history_retrieval_keep_recent=2,
        history_retrieval_top_k=3,
    ),
    # Delta summarization: a single running summary updated each trigger with only
    # what changed (the prompt folds the prior summary + new turns into a fresh
    # running summary). Summarization-style arm; isolates the summary STRATEGY vs
    # prod/selective. Watch the F2 cache confound (prefix rewrite each trigger).
    "delta_summarization": MemoryConfig(
        name="delta_summarization",
        context_editing=False,
        summary_prompt=DELTA_SUMMARY_PROMPT,
    ),
    # Hierarchical summarization: map-reduce the older messages (summarize groups,
    # then summarize the summaries) into one layered summary. Expected to preserve
    # more structure than single-pass on long content; its extra summarization
    # LLM calls are the cost it must justify. Summarization off (this replaces it).
    "hierarchical_summarization": MemoryConfig(
        name="hierarchical_summarization",
        summarization=False,
        hierarchical_summarize=True,
    ),
}

# One switch controls the long-context production policy. Providers outside the
# allowlist stay on the historical, conservative preset until they have a
# provider-appropriate long-context configuration (Claude Haiku 4.5, for
# example, has a 200k input window and cannot safely wait for an 800k trigger).
PRODUCTION_MEMORY_PRESET = "prod_v3"
PRODUCTION_FALLBACK_MEMORY_PRESET = "prod"
# "openrouter" is here for the default DeepSeek-via-OpenRouter chat model.
# The gate is provider-granular, so any openrouter:* model resolves to the
# long-context production preset by default; eval runs pin presets by name,
# so in practice this only decides the served chat path.
PRODUCTION_LONG_CONTEXT_PROVIDERS = frozenset({"deepseek", "google-genai", "openrouter"})

# Backward-compatible import for callers that need a single default name. New
# runtime code should call resolve_memory_preset(..., model_name=...) so model
# compatibility is applied.
DEFAULT_MEMORY_PRESET = PRODUCTION_MEMORY_PRESET

PRESET_PROVIDER_ALLOWLIST: dict[str, frozenset[str]] = {
    "prod_v2": PRODUCTION_LONG_CONTEXT_PROVIDERS,
    "prod_v3": PRODUCTION_LONG_CONTEXT_PROVIDERS,
}

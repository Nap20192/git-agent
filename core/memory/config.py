from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    name: str
    summarization: bool = True
    summarization_trigger_tokens: int = 30_000
    summarization_keep_messages: int = 20
    # Experiment arms use token-based retention so a single large tool message
    # cannot make the post-compaction window vary by hundreds of thousands of
    # tokens. None preserves the historical message-count behavior.
    summarization_keep_tokens: int | None = None
    # LangChain defaults this to 4k. None deliberately sends the entire selected
    # older history to the summarizer (the corrected long-context experiment).
    summarization_trim_tokens: int | None = 4_000
    # Fail rather than silently trim if a full-input experimental summary would
    # approach the provider's context ceiling. None disables the guard.
    summarization_input_guard_tokens: int | None = None
    # Custom SummarizationMiddleware prompt (None = the library default). Used by
    # the selective_retention / context_reset arms; must template {messages}.
    summary_prompt: str | None = None
    # ``xml`` is LangChain's historical behavior: serialize selected messages
    # into one new prompt string. ``structured_prefix`` keeps the original
    # system message, tool schemas, model settings, and selected message prefix
    # byte-for-byte at the message boundary, then appends one checkpoint
    # instruction. The latter is experiment-only because it changes request
    # shape and checkpoint installation semantics.
    summarization_strategy: str = "xml"
    context_editing: bool = True
    context_editing_trigger_tokens: int = 5_000
    context_editing_keep: int = 5
    # When True (legacy prod default), ClearToolUsesEdit leaves retrieval results alone
    # (F3: that is where the tokens are, so clearing rarely fires). False makes
    # the clear_retrieval_kb variant clear retrieval + KB outputs too.
    clear_excludes_retrieval: bool = True
    longterm_memory: bool = False
    # --- Part C / Axis A per-call-view mechanisms --------------------------
    # These reshape only the message list sent to the model (not the checkpoint),
    # so they report via app.telemetry's turn-signal registry rather than a
    # checkpoint marker. Each is a single-axis arm; see the preset notes.
    sliding_window_keep: int | None = None  # keep last N messages, drop older
    truncate_tool_outputs: bool = False  # head/tail-truncate large tool outputs
    truncate_head_chars: int = 2_000
    truncate_tail_chars: int = 500
    truncate_trigger_chars: int = 4_000
    # Persistent insertion-time cap: unlike truncate_tool_outputs, this changes
    # the checkpoint itself, so every later model call and the summarizer see the
    # same stable text. The experiment uses 40k UTF-8 bytes as a nominal 10k-token
    # cap, matching the reproducible approximation used by the Codex harness.
    tool_output_cap_bytes: int | None = None
    # Enables explanatory compaction telemetry and DeepSeek user_id isolation.
    # Kept off for production and historical presets so this study is additive.
    experiment_mode: bool = False
    # Fail before an experimental agent call exceeds this approximate input
    # size. The approximation over-counted the provider-reported input by about
    # 29k near 870k, so 990k preserves real headroom inside DeepSeek's 1M window
    # without prematurely truncating the full-history control.
    experiment_request_guard_tokens: int = 990_000
    compress_prompt: bool = False  # deterministic per-call text compaction
    # In-context history retrieval (Axis A subsystem): keep the last N turn-blocks
    # and retrieve only the top-k most relevant older blocks. None disables it.
    history_retrieval_keep_recent: int | None = None
    history_retrieval_top_k: int = 3
    # Hierarchical summarization (Axis A): map-reduce the older messages
    # (summarize groups, then summarize the group summaries) into one summary in
    # the model's view, cached by content. None/False disables it.
    hierarchical_summarize: bool = False
    hierarchical_trigger_tokens: int = 8_000
    hierarchical_keep_recent: int = 6
    hierarchical_group_size: int = 5

"""resolve_subagent_config: близкое имя типа Сабагента подставляется, а не валит ход."""

from core.subagents.registry import GENERAL_PURPOSE, resolve_subagent_config


def test_exact_name_no_note():
    assert resolve_subagent_config("general-purpose") == (GENERAL_PURPOSE, None)


def test_close_names_resolve_with_note():
    for name in ("general", "General_Purpose", "general purpose", "researcher"):
        config, note = resolve_subagent_config(name)
        assert config is GENERAL_PURPOSE, name
        assert note and "general-purpose" in note

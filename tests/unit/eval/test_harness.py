"""Тесты eval-харнеса: батарея, fingerprint, грейд, гейт, зеркало констант."""

import json
from pathlib import Path

import pytest

from evals.battery import (
    BatteryError,
    check_fact_prose,
    check_fact_structured,
    lint_battery,
    load_battery,
)
from evals.common import (
    PRICING_USD_PER_MILLION,
    canonical_fingerprint,
    fold_events,
    price_run,
    source_tree_sha256,
    stable_row_id,
)
from evals.grade import grade_bundle
from evals.validity import gate_bundle

BATTERY_PATH = Path(__file__).resolve().parents[3] / "evals" / "data" / "repos.v1.jsonl"


# -- battery -------------------------------------------------------------------


def test_frozen_battery_lints_clean():
    units = load_battery(BATTERY_PATH)
    assert len(units) == 4  # счётчик из data/README.md


def test_lint_rejects_unknown_rule_and_duplicates():
    with pytest.raises(BatteryError, match="unknown rule"):
        lint_battery(
            [
                {
                    "unit_id": "u",
                    "repo_url": "x",
                    "commit_sha": "y",
                    "facts": [{"fact_id": "f", "rule": "martian"}],
                }
            ]
        )
    with pytest.raises(BatteryError, match="duplicate unit_id"):
        lint_battery(
            [
                {
                    "unit_id": "u",
                    "repo_url": "x",
                    "commit_sha": "y",
                    "facts": [{"fact_id": "f", "rule": "prose_substring", "prose": "a"}],
                },
                {
                    "unit_id": "u",
                    "repo_url": "x",
                    "commit_sha": "y",
                    "facts": [{"fact_id": "f", "rule": "prose_substring", "prose": "a"}],
                },
            ]
        )
    with pytest.raises(BatteryError, match="bad regex"):
        lint_battery(
            [
                {
                    "unit_id": "u",
                    "repo_url": "x",
                    "commit_sha": "y",
                    "facts": [{"fact_id": "f", "rule": "prose_regex", "prose": "[unclosed"}],
                }
            ]
        )


def test_fact_rules_matrix():
    report = {
        "structure": {
            "file_count": 3,
            "languages": {".py": 2},
            "files": ["a.py", "pyproject.toml"],
        },
        "dependencies": ["langchain>=1.0", "psycopg[binary]"],
    }
    eq = {"fact_id": "f", "rule": "structured_eq", "path": "structure.file_count", "value": "3"}
    assert check_fact_structured(eq, report) is True
    contains = {
        "fact_id": "f",
        "rule": "structured_contains",
        "path": "dependencies",
        "value": "langchain",
    }
    assert check_fact_structured(contains, report) is True
    superset = {
        "fact_id": "f",
        "rule": "structured_set_superset",
        "path": "dependencies",
        "values": ["langchain", "psycopg"],
    }
    assert check_fact_structured(superset, report) is True
    absent = {"fact_id": "f", "rule": "absent", "path": "structure.languages", "value": ".go"}
    assert check_fact_structured(absent, report) is True
    # отсутствующий path → None (неизмеримо), НЕ fail
    missing = {"fact_id": "f", "rule": "structured_contains", "path": "no.such.path", "value": "x"}
    assert check_fact_structured(missing, report) is None
    assert check_fact_structured(eq, None) is None


def test_prose_rules_and_absent():
    prose = "Это Python-проект: CLI-фреймворк на базе click."
    assert (
        check_fact_prose(
            {"fact_id": "f", "rule": "prose_substring", "prose": "cli-фреймворк"}, prose
        )
        is True
    )
    assert (
        check_fact_prose(
            {"fact_id": "f", "rule": "prose_regex", "prose": "command[- ]line|CLI"}, prose
        )
        is True
    )
    assert (
        check_fact_prose({"fact_id": "f", "rule": "absent", "prose": "\\bdjango\\b"}, prose) is True
    )
    assert check_fact_prose({"fact_id": "f", "rule": "absent", "prose": "click"}, prose) is False
    # structured-правило с prose-фолбэком измеримо в прозе
    assert (
        check_fact_prose(
            {
                "fact_id": "f",
                "rule": "structured_contains",
                "path": "x",
                "value": "y",
                "prose": "python",
            },
            prose,
        )
        is True
    )
    assert check_fact_prose({"fact_id": "f", "rule": "prose_substring", "prose": "x"}, None) is None


# -- fingerprint / ids ---------------------------------------------------------


def test_fingerprint_canonical_and_sensitive():
    a = {"b": 1, "a": {"y": 2, "x": 3}}
    b = {"a": {"x": 3, "y": 2}, "b": 1}  # другой порядок ключей
    assert canonical_fingerprint(a) == canonical_fingerprint(b)
    assert canonical_fingerprint(a) != canonical_fingerprint({**a, "b": 2})


def test_source_tree_sha_catches_uncommitted_edit(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "x.py").write_text("a = 1")
    before = source_tree_sha256(tmp_path)
    (tmp_path / "core" / "x.py").write_text("a = 2")  # «незакоммиченная» правка
    assert source_tree_sha256(tmp_path) != before


def test_stable_row_id_deterministic():
    assert stable_row_id("42", "unit") == stable_row_id("42", "unit")
    assert len(stable_row_id("42", "unit")) == 12


# -- pricing -------------------------------------------------------------------


def test_price_run_tristate():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "total_tokens": 1_100_000}
    cost = price_run(usage, "deepseek-chat", PRICING_USD_PER_MILLION)
    assert cost == pytest.approx(0.27 + 0.11)
    assert price_run(usage, "gpt-x-unknown", PRICING_USD_PER_MILLION) is None  # не 0!
    assert price_run(None, "deepseek-chat", PRICING_USD_PER_MILLION) is None


# -- fold_events ---------------------------------------------------------------


def test_fold_events_usage_and_subagents():
    events = [
        {"kind": "updates", "payload": {"data": {"type": "task_started", "task_id": "t1"}}},
        {"kind": "updates", "payload": {"data": {"type": "task_started", "task_id": "t2"}}},
        {
            "kind": "usage",
            "payload": {
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "llm_calls": 3,
                "records": [{"model_name": "deepseek-chat"}],
            },
        },
    ]
    folded = fold_events(events)
    assert folded["subagent_count"] == 2
    assert folded["usage"]["total_tokens"] == 15
    assert folded["served_models"] == ["deepseek-chat"]
    assert fold_events([])["usage"] is None  # tri-state, не нули


# -- validity gate -------------------------------------------------------------


def _bundle(**over):
    base = {
        "unit_key": "u~pipeline~prod~t1",
        "unit_id": "u",
        "error": None,
        "mode": "pipeline",
        "preset": "prod",
        "model": "deepseek-chat",
        "db_status": "succeeded",
        "served_models": ["deepseek-chat"],
        "subagent_count": 0,
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        "report_commit": "abc",
        "pinned_commit": "abc",
    }
    return {**base, **over}


_MANIFEST = {"memory_config": {"name": "prod", "experiment_mode": False}}


def test_gate_clean_and_each_check():
    assert gate_bundle(_bundle(), _MANIFEST) == []
    assert any(
        "served_model_mismatch" in p
        for p in gate_bundle(_bundle(served_models=["gpt-4o"]), _MANIFEST)
    )
    assert any(
        "agent_axis_not_fired" in p
        for p in gate_bundle(_bundle(mode="agent", subagent_count=0), _MANIFEST)
    )
    assert any(
        "pipeline_axis_violated" in p for p in gate_bundle(_bundle(subagent_count=2), _MANIFEST)
    )
    assert any(
        "commit_drift" in p for p in gate_bundle(_bundle(report_commit="fffffffffff1"), _MANIFEST)
    )
    assert any("preset_drift" in p for p in gate_bundle(_bundle(preset="aggressive"), _MANIFEST))
    assert any(
        "usage_missing" in p
        for p in gate_bundle(
            _bundle(usage=None), {"memory_config": {"name": "prod", "experiment_mode": True}}
        )
    )
    assert gate_bundle(_bundle(error="boom"), _MANIFEST) == ["harness_error: boom"]


# -- grade ---------------------------------------------------------------------


_UNIT = {
    "unit_id": "u",
    "repo_url": "x",
    "commit_sha": "abc",
    "facts": [
        {
            "fact_id": "lang",
            "rule": "structured_contains",
            "path": "structure.languages",
            "value": ".py",
            "prose": "python",
        },
        {"fact_id": "purpose", "rule": "prose_regex", "prose": "CLI|командн"},
    ],
}


def test_grade_tool_fair_tristate():
    # pipeline: структурный отчёт — обе оценки измеримы
    pipeline_bundle = _bundle(
        report={
            "structure": {"languages": {".py": 5}},
            "description": "Python CLI tool",
        }
    )
    row = grade_bundle(pipeline_bundle, _UNIT, _MANIFEST)
    assert row["facts_pass_struct"] == 1 and row["facts_measured_struct"] == 1
    assert row["facts_pass_prose"] == 2 and row["facts_measured_prose"] == 2

    # agent: только проза — структурные оценки None, не fail
    agent_bundle = _bundle(
        mode="agent", subagent_count=1, report={"answer": "Это Python CLI утилита", "commit": "abc"}
    )
    row2 = grade_bundle(agent_bundle, _UNIT, _MANIFEST)
    assert row2["facts_measured_struct"] == 0  # None не считается measured
    assert row2["facts_pass_prose"] == 2


def test_grade_gated_bundle_scores_nothing():
    gated = _bundle(report_commit="drifted99999", report={"description": "python CLI"})
    row = grade_bundle(gated, _UNIT, _MANIFEST)
    assert row["gated"] and row["facts_measured_prose"] == 0


def test_grade_error_unit_behavior():
    unit = {
        "unit_id": "u",
        "repo_url": "x",
        "commit_sha": "abc",
        "expected_status": "failed",
        "facts": [],
    }
    ok = grade_bundle(_bundle(db_status="failed", report_commit=None), unit, _MANIFEST)
    assert ok["behavior_pass"] is True
    bad = grade_bundle(_bundle(db_status="succeeded", report_commit=None), unit, _MANIFEST)
    assert bad["behavior_pass"] is False


def test_grade_twice_byte_identical(tmp_path):
    from evals.grade import grade_run

    out = tmp_path / "run1"
    out.mkdir()
    (out / "run_config.json").write_text(json.dumps({"_manifest": _MANIFEST}))
    bundle = _bundle(
        unit_id="hello-world@7fd1a60b",
        run_id=1,
        report={
            "structure": {"file_count": 1, "files": ["README"]},
            "description": "hello world demo",
            "commit": "abc",
        },
        pinned_commit="abc",
    )
    (out / "bundles.jsonl").write_text(json.dumps(bundle) + "\n")
    p1 = grade_run(out, BATTERY_PATH)
    first = p1.read_bytes()
    p2 = grade_run(out, BATTERY_PATH)
    assert p2.read_bytes() == first  # байт-в-байт, гейт фазы grade


# -- зеркало констант (единственный тест, которому МОЖНО импортировать app) ----


def test_signal_mirror_matches_app():
    from core.agents.subagents.task_tool import _terminal_event  # noqa: F401
    from core.runtime.schemas import TERMINAL_STATUSES
    from evals import common

    assert set(common.RUN_TERMINAL_STATUSES) == {s.value for s in TERMINAL_STATUSES}
    # kind usage-события в worker.add_event
    import inspect

    from core.runtime import worker

    source = inspect.getsource(worker)
    assert f'"{common.USAGE_EVENT_KIND}"' in source
    from core.agents.subagents import task_tool

    assert common.TASK_STARTED_TYPE in inspect.getsource(task_tool)

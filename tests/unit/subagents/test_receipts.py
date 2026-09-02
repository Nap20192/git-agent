"""Квитанции, снапшоты, верификация цитат, report contract."""

from langchain_core.messages import AIMessage, ToolMessage

from core.subagents.receipts import (
    CITATION_RE,
    TOOL_RECEIPT_KEY,
    TOOL_RECEIPT_LEDGER_KEY,
    build_report_contract_section,
    extract_citing_turn_receipts,
    extract_tool_receipts,
    format_citation,
    is_valid_receipt,
    make_tool_receipt,
    parse_citations,
    receipt_id,
    render_citation_verdict,
    render_tool_receipts_with_snapshot,
    verify_receipt_citations,
)


def _tool_message(i: int, status: str = "success") -> ToolMessage:
    call = {"id": f"call_{i}", "name": "sandbox_run", "args": {"command": f"cmd{i}"}}
    msg = ToolMessage(content=f"out{i}", tool_call_id=f"call_{i}", name="sandbox_run")
    msg.additional_kwargs = {TOOL_RECEIPT_KEY: {**make_tool_receipt(call, msg), "status": status}}
    return msg


def test_extract_assigns_positional_ids_and_skips_malformed():
    bad = ToolMessage(content="x", tool_call_id="b")
    bad.additional_kwargs = {TOOL_RECEIPT_KEY: {"tool_name": 42}}
    receipts = extract_tool_receipts([_tool_message(1), bad, _tool_message(2)])
    assert [r["id"] for r in receipts] == ["r1", "r2"]


def test_citing_turn_snapshot_fails_closed():
    ok = extract_tool_receipts([_tool_message(1), _tool_message(2)])
    ai = AIMessage(content="done")
    ai.additional_kwargs = {TOOL_RECEIPT_LEDGER_KEY: [dict(r) for r in ok]}
    assert extract_citing_turn_receipts([ai]) == ok

    broken = [dict(ok[0]), {**dict(ok[1]), "id": "r7"}]
    ai2 = AIMessage(content="done")
    ai2.additional_kwargs = {TOOL_RECEIPT_LEDGER_KEY: broken}
    assert extract_citing_turn_receipts([ai2]) is None

    ai3 = AIMessage(content="done")
    ai3.additional_kwargs = {TOOL_RECEIPT_LEDGER_KEY: "junk"}
    assert extract_citing_turn_receipts([ai3]) is None


def test_snapshot_is_rendered_subset_only():
    receipts = extract_tool_receipts([_tool_message(i) for i in range(1, 40)])
    rendered, retained = render_tool_receipts_with_snapshot(receipts, max_chars=800)
    assert 0 < len(retained) < len(receipts)
    assert "older receipts omitted" in rendered
    omitted_id = receipts[0]["id"]
    assert all(r["id"] != omitted_id for r in retained)
    verdict = verify_receipt_citations(f"Ran it [{omitted_id} sandbox_run]", retained)
    assert verdict["unknown"] == [omitted_id]


def test_parse_citations_digit_cap_and_dedup():
    assert parse_citations("[r99999999999999999999]") == []
    assert parse_citations("[r2] and again [r2] and [r2 sandbox_run]") == [
        ("r2", None),
        ("r2", "sandbox_run"),
    ]


def test_is_valid_receipt_output_bytes_not_bool():
    receipt = make_tool_receipt(
        {"id": "c", "name": "t", "args": {}}, ToolMessage(content="x", tool_call_id="c")
    )
    assert is_valid_receipt(receipt)
    assert not is_valid_receipt({**receipt, "output_bytes": True})


def test_verify_matrix():
    receipts = extract_tool_receipts([_tool_message(1), _tool_message(2, status="error")])
    v = verify_receipt_citations(
        "Read the config [r1 sandbox_run]; retry failed [r2]; also [r9].", receipts
    )
    assert v["resolved"] == ["r1"]
    assert v["failed"][0]["id"] == "r2" and "status=error" in v["failed"][0]["reason"]
    assert v["unknown"] == ["r9"]
    assert not v["citation_resolved"]

    anchor = verify_receipt_citations("Did it [r1 read_file]", receipts)
    assert "anchor mismatch" in anchor["failed"][0]["reason"]


def test_unverified_heuristics():
    receipts = extract_tool_receipts([_tool_message(1)])
    v = verify_receipt_citations("I created the file and executed the script.", receipts)
    assert v["no_citation_claims"] and not v["citation_resolved"]
    v_ru = verify_receipt_citations("Я склонировал репозиторий и проверил зависимости.", receipts)
    assert v_ru["no_citation_claims"]
    v_cjk = verify_receipt_citations("已经创建了配置文件。", receipts)
    assert v_cjk["no_citation_claims"]
    v_long = verify_receipt_citations("х" * 300, receipts)
    assert v_long["no_citation_claims"]
    v_short = verify_receipt_citations("Ок.", receipts)
    assert v_short["citation_resolved"] and render_citation_verdict(v_short) == ""
    v_none = verify_receipt_citations("Ок.", [])
    assert v_none["citation_resolved"]


def test_report_contract_examples_match_verifier_regex():
    section = build_report_contract_section()
    assert CITATION_RE.search(section)
    assert format_citation(receipt_id(3), "sandbox_run") in section

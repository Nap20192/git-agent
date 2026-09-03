"""pkg.errors.describe — тип + текст + цепочка причин, без пустых str(exc)."""

from pkg.errors import describe


def test_describe_chain_and_empty_message():
    try:
        try:
            raise ConnectionRefusedError("dial tcp :5673")
        except OSError as inner:
            raise RuntimeError("consumer failed") from inner
    except RuntimeError as exc:
        text = describe(exc)
    assert (
        text == "RuntimeError: consumer failed ← caused by: ConnectionRefusedError: dial tcp :5673"
    )
    assert describe(KeyError()) == "KeyError"
    assert (
        describe(ValueError("x" * 600), limit=50).endswith("…")
        and len(describe(ValueError("x" * 600), limit=50)) == 50
    )

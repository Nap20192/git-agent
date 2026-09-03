"""Формальная модель как часть тестового прогона: pytest проверяет Lean-доказательства."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_LEAN_FILE = Path(__file__).parents[2] / "formal" / "RuntimeCore.lean"


def _lean_bin() -> str | None:
    return shutil.which("lean") or next(
        (str(p) for p in [Path.home() / ".elan/bin/lean"] if p.exists()), None
    )


@pytest.mark.skipif(_lean_bin() is None, reason="lean toolchain not installed")
def test_runtime_core_proofs_check():
    lean = _lean_bin()
    env = {**os.environ, "PATH": f"{Path(lean).parent}:{os.environ['PATH']}"}
    result = subprocess.run(
        [lean, _LEAN_FILE.name],
        cwd=_LEAN_FILE.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"RuntimeCore.lean failed to verify:\n{result.stdout}\n{result.stderr}"
    )
    assert "sorry" not in _LEAN_FILE.read_text()

"""Тулы над портом Sandbox (core/tools/sandbox): команды, клип, ошибки текстом, fallback."""

import asyncio

from core.ports import SandboxCommandError
from core.tools.sandbox import build_sandbox_tools
from core.tools.sandbox.search import MAX_GREP_LINES, grep_command


class FakeSandbox:
    """Записывает команды; ответ — фиксированный текст или исключение."""

    repo_dir = "/repo"
    id = None

    def __init__(self, reply: str | Exception = "out"):
        self.reply = reply
        self.commands: list[str] = []

    async def run(self, command: str, *, timeout_seconds: float | None = None) -> str:
        self.commands.append(command)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    async def close(self) -> None:
        pass


def tools(sandbox):
    return {t.name: t for t in build_sandbox_tools(sandbox)}


def test_toolset_names_both_for_lead_and_subagents():
    assert set(tools(FakeSandbox())) == {
        "sandbox_run",
        "read_file",
        "list_dir",
        "grep_code",
        "git_diff",
        "git_blame",
        "browse",
    }


def test_read_file_paged_with_line_numbers():
    async def run():
        sb = FakeSandbox("3\tx\n(lines 3-4 of 10)\n")
        out = await tools(sb)["read_file"].ainvoke(
            {"path": "/repo/my file.py", "offset": 3, "limit": 2}
        )
        assert out.endswith("(lines 3-4 of 10)\n")
        cmd = sb.commands[0]
        assert cmd.startswith("awk ") and cmd.endswith("'/repo/my file.py'")
        assert "NR>=3 && NR<=4" in cmd and "of %d" in cmd
        # ошибка команды — текстом
        missing = FakeSandbox(SandboxCommandError("awk", 2, "cannot open"))
        assert (await tools(missing)["read_file"].ainvoke({"path": "/nope"})).startswith("exit 2:")

    asyncio.run(run())


def test_list_dir_defaults_to_repo_and_caps_entries():
    async def run():
        sb = FakeSandbox("\n".join(f"/repo/f{i}" for i in range(600)))
        out = await tools(sb)["list_dir"].ainvoke({})
        assert sb.commands[0].startswith("find /repo -maxdepth 2 -name .git -prune")
        assert out.count("\n") == 500 and out.endswith("narrow path or depth]")

    asyncio.run(run())


def test_grep_command_prefers_rg_with_grep_fallback():
    cmd = grep_command("db\\.Query", "/repo", glob="*.go", context=1, fixed=False)
    assert cmd.startswith("if command -v rg >/dev/null 2>&1; then rg -n --no-heading")
    assert "--glob '*.go'" in cmd and "; else grep -rn -I -C 1 -E --include='*.go'" in cmd
    assert cmd.count("-e 'db\\.Query' /repo") == 2
    assert " -F" in grep_command("a(b", "/repo", fixed=True)


def test_grep_code_no_matches_errors_and_cap():
    async def run():
        assert (
            await tools(FakeSandbox(""))["grep_code"].ainvoke({"pattern": "zzz"})
            == "no matches for 'zzz'"
        )
        no_hit = FakeSandbox(SandboxCommandError("rg", 1, ""))
        assert (await tools(no_hit)["grep_code"].ainvoke({"pattern": "zzz"})).startswith(
            "no matches"
        )
        bad = FakeSandbox(SandboxCommandError("rg", 2, "regex parse error"))
        assert "grep failed (exit 2)" in await tools(bad)["grep_code"].ainvoke({"pattern": "("})
        many = FakeSandbox("\n".join(f"/repo/a.py:{i}:x" for i in range(MAX_GREP_LINES + 10)))
        out = await tools(many)["grep_code"].ainvoke({"pattern": "x", "path": "/repo/a.py"})
        assert out.count("\n") == MAX_GREP_LINES and "10 more lines" in out
        assert many.commands[0].endswith("-e x /repo/a.py; fi")

    asyncio.run(run())


def test_git_diff_show_vs_range_and_shallow_hint():
    async def run():
        sb = FakeSandbox("diff --git a/x b/x")
        gd = tools(sb)["git_diff"]
        await gd.ainvoke({"stat": True})
        await gd.ainvoke({"ref": "abc", "base": "def", "path": "src/a.py"})
        assert sb.commands == [
            "git -C /repo show --no-color --format= --stat HEAD",
            "git -C /repo diff --no-color def abc -- src/a.py",
        ]
        assert await tools(FakeSandbox("  \n"))["git_diff"].ainvoke({}) == "(empty diff)"
        shallow = FakeSandbox(SandboxCommandError("git", 128, "fatal: bad revision 'HEAD^'"))
        out = await tools(shallow)["git_diff"].ainvoke({"ref": "HEAD^"})
        assert out.startswith("git diff failed (exit 128)") and "--deepen" in out

    asyncio.run(run())


def test_git_blame_range_defaults():
    async def run():
        sb = FakeSandbox("^abc (a 2026-01-01 1) x")
        await tools(sb)["git_blame"].ainvoke({"path": "sub/b.go", "start_line": 10})
        assert sb.commands == ["git -C /repo blame --date=short -L 10,60 -- sub/b.go"]

    asyncio.run(run())


def test_browse_validates_scheme_runs_in_sandbox_and_clips():
    async def run():
        sb = FakeSandbox("Title: T\nURL: https://x/final\n\nbody")
        browse = tools(sb)["browse"]
        for bad in ("ftp://x/y", "file:///etc/passwd", "javascript:alert(1)", "nvd.nist.gov"):
            assert (await browse.ainvoke({"url": bad})).startswith("browse: only http(s)")
        assert sb.commands == []  # до песочницы невалидный URL не доходит
        out = await browse.ainvoke({"url": " https://nvd.nist.gov/vuln/detail/CVE-2024-1 "})
        assert out.startswith("Title: T\nURL: https://x/final")
        cmd = sb.commands[0]
        assert cmd.startswith("command -v python3") and "python3 -c " in cmd
        assert cmd.endswith(" https://nvd.nist.gov/vuln/detail/CVE-2024-1 160000")
        assert "def extract_text" in cmd  # экстрактор уезжает в песочницу целиком
        long = FakeSandbox("x" * 5000)
        clipped = await tools(long)["browse"].ainvoke({"url": "http://a/b", "max_chars": 1000})
        assert clipped.startswith("x" * 1000) and "truncated at 1000" in clipped
        nopy = FakeSandbox(SandboxCommandError("python3", 3, "browse: python3 is not installed"))
        err = await tools(nopy)["browse"].ainvoke({"url": "https://a/b"})
        assert err.startswith("browse failed (exit 3)") and "not installed" in err

    asyncio.run(run())


def test_html_text_extractor_keeps_structure_and_drops_chrome():
    from core.tools.sandbox.html_text import extract_text

    html = """<html><head><title> CVE-2024-1 &amp; co </title><style>p{}</style>
    <script>alert(1)</script></head><body><nav><a href=/>Home</a></nav>
    <h1>Overview</h1><p>Some   text<br>here</p><ul><li>one</li><li>two</li></ul>
    <pre><code>x = 1
  y = 2</code></pre><footer>c 2026</footer></body></html>"""
    title, text = extract_text(html)
    assert title == "CVE-2024-1 & co"
    assert "Home" not in text and "alert" not in text and "2026" not in text
    assert text.startswith("# Overview\n\nSome text\nhere")
    assert "- one\n- two" in text
    assert "```\nx = 1\ny = 2\n```" in text

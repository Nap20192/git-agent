"""Узлы графа Рана: scan → parse → report.

Зависят от порта core.ports.Sandbox — конкретную песочницу передаёт вызывающий.
Любая ошибка узла попадает в state["error"], граф завершается управляемо.
"""

import ast
import shlex
import tomllib
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from core.agents.state import RepoState
from core.ports import Sandbox
from pkg.logger import get_logger

log = get_logger(__name__)

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
}
KEY_FILE_NAMES = {
    "README.md",
    "README.rst",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
}
MAX_FILES = 5_000
MAX_PARSE_FILES = 40
MAX_FILE_BYTES = 80_000
CLONE_TIMEOUT_SECONDS = 180.0


def _skipped(path: str) -> bool:
    return bool(SKIP_DIRS.intersection(path.split("/")))


async def scan(state: RepoState, sandbox: Sandbox) -> dict[str, Any]:
    repo_url = state["repo_url"]
    repo_dir = shlex.quote(sandbox.repo_dir)
    log.info("scan start", repo_url=repo_url)
    # Клон идемпотентен: в durable-рантайме репо уже готовит profile.prepare
    # (обязательно для resume — свежая песочница, scan не перезапускается);
    # клон здесь — для прямого запуска графа без prepare (тесты, demo).
    present = (await sandbox.run(f"test -d {repo_dir}/.git && echo yes || true")).strip()
    if present != "yes":
        await sandbox.run(
            f"git clone --depth 1 {shlex.quote(repo_url)} {repo_dir}",
            timeout_seconds=CLONE_TIMEOUT_SECONDS,
        )
        checkout_ref = state.get("checkout_ref")
        if checkout_ref:
            # пин коммита (воспроизводимость evals): depth-1 клон не содержит
            # произвольный sha — дотягиваем его точечно и переключаемся
            ref = shlex.quote(checkout_ref)
            await sandbox.run(
                f"git -C {repo_dir} fetch --depth 1 origin {ref}"
                f" && git -C {repo_dir} checkout --detach {ref}",
                timeout_seconds=CLONE_TIMEOUT_SECONDS,
            )
    commit = (await sandbox.run(f"git -C {repo_dir} rev-parse HEAD")).strip()

    listing = await sandbox.run(f"cd {repo_dir} && find . -type f -exec stat -c '%s %n' {{}} \\;")
    files: list[dict[str, Any]] = []
    truncated = False
    for line in listing.splitlines():
        size_str, _, path = line.partition(" ")
        path = path.removeprefix("./")
        if not path or _skipped(path):
            continue
        if len(files) >= MAX_FILES:
            truncated = True
            break
        files.append({"path": path, "size": int(size_str)})

    languages: dict[str, int] = {}
    for f in files:
        ext = "." + f["path"].rsplit(".", 1)[1] if "." in f["path"].rsplit("/", 1)[-1] else "(none)"
        languages[ext] = languages.get(ext, 0) + 1

    result = {
        "commit": commit,
        "files": files,
        "file_count": len(files),
        "truncated": truncated,
        "total_bytes": sum(f["size"] for f in files),
        "languages": dict(sorted(languages.items(), key=lambda kv: -kv[1])),
        "key_files": sorted(
            f["path"] for f in files if f["path"].rsplit("/", 1)[-1] in KEY_FILE_NAMES
        ),
    }
    log.info("scan finish", repo_url=repo_url, files=len(files), commit=commit)
    return {"scan": result}


async def _read_file(sandbox: Sandbox, path: str) -> str:
    return await sandbox.run(f"cat {shlex.quote(f'{sandbox.repo_dir}/{path}')}")


def _parse_python(path: str, source: str) -> dict[str, Any] | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return {
        "path": path,
        "docstring": (ast.get_docstring(tree) or "")[:200] or None,
        "classes": [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)],
        "functions": [
            n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ],
    }


async def _read_dependencies(sandbox: Sandbox, key_files: list[str]) -> list[str]:
    if "pyproject.toml" in key_files:
        try:
            data = tomllib.loads(await _read_file(sandbox, "pyproject.toml"))
            return list(data.get("project", {}).get("dependencies", []))
        except Exception:
            log.warning("pyproject.toml unreadable")
    if "requirements.txt" in key_files:
        raw = await _read_file(sandbox, "requirements.txt")
        return [
            line.strip()
            for line in raw.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    return []


_DESCRIBE_PROMPT = """Ты разбираешь git-репозиторий. По данным ниже опиши в 3-6 предложениях,
что делает проект и из каких основных частей он состоит. Отвечай только описанием.

Ключевые файлы: {key_files}
Статистика по расширениям: {languages}
Модули Python (путь, классы, функции):
{modules}
"""


async def parse(state: RepoState, sandbox: Sandbox, model: BaseChatModel) -> dict[str, Any]:
    scan_result = state["scan"]
    log.info("parse start", repo_url=state["repo_url"])

    py_files = [
        f["path"]
        for f in scan_result["files"]
        if f["path"].endswith(".py") and f["size"] <= MAX_FILE_BYTES
    ][:MAX_PARSE_FILES]

    modules, skipped = [], []
    for path in py_files:
        try:
            module = _parse_python(path, await _read_file(sandbox, path))
        except Exception:
            module = None
            log.warning("file unreadable, skipped", path=path)
        if module is None:
            skipped.append(path)
        else:
            modules.append(module)

    dependencies = await _read_dependencies(sandbox, scan_result["key_files"])

    modules_brief = "\n".join(
        f"- {m['path']}: classes={m['classes']}, functions={m['functions']}" for m in modules
    )
    prompt = _DESCRIBE_PROMPT.format(
        key_files=scan_result["key_files"],
        languages=scan_result["languages"],
        modules=modules_brief or "(нет)",
    )
    description = str((await model.ainvoke(prompt)).content)

    result = {
        "modules": modules,
        "skipped_files": skipped,
        "dependencies": dependencies,
        "description": description,
    }
    log.info("parse finish", repo_url=state["repo_url"], modules=len(modules))
    return {"parse": result}


async def report(state: RepoState) -> dict[str, Any]:
    if state.get("error"):
        final = {"repo_url": state["repo_url"], "error": state["error"]}
        log.error("run failed", repo_url=state["repo_url"], error=state["error"])
        return {"report": final}
    scan_result, parse_result = state["scan"], state["parse"]
    final = {
        "repo_url": state["repo_url"],
        "commit": scan_result["commit"],
        "description": parse_result["description"],
        "structure": {
            "file_count": scan_result["file_count"],
            "total_bytes": scan_result["total_bytes"],
            "truncated": scan_result["truncated"],
            "languages": scan_result["languages"],
            "key_files": scan_result["key_files"],
            "files": [f["path"] for f in scan_result["files"]],
        },
        "modules": parse_result["modules"],
        "dependencies": parse_result["dependencies"],
        "skipped_files": parse_result["skipped_files"],
    }
    log.info("report ready", repo_url=state["repo_url"])
    return {"report": final}

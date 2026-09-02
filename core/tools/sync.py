"""Sync-обёртка для async-only тулов."""

import asyncio
import atexit
import concurrent.futures
import contextvars

from langchain_core.tools import BaseTool

_SYNC_TOOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=10, thread_name_prefix="tool-sync"
)
atexit.register(_SYNC_TOOL_EXECUTOR.shutdown, wait=False)


def make_sync_tool_wrapper(coro, tool_name):
    def run_coroutine(*args, **kwargs):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            ctx = contextvars.copy_context()
            future = _SYNC_TOOL_EXECUTOR.submit(ctx.run, lambda: asyncio.run(coro(*args, **kwargs)))
            return future.result()
        return asyncio.run(coro(*args, **kwargs))

    return run_coroutine


def ensure_sync_invocable_tool(t: BaseTool) -> BaseTool:
    if getattr(t, "func", None) is None and getattr(t, "coroutine", None) is not None:
        t.func = make_sync_tool_wrapper(t.coroutine, t.name)
    return t

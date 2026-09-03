"""Anti-corruption layer: LangChain/LangGraph-объекты → plain JSON на границе."""

from __future__ import annotations

from typing import Any

try:
    from langgraph.types import Interrupt
except ImportError:  # pragma: no cover
    Interrupt = None


def serialize_lc_object(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): serialize_lc_object(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_lc_object(v) for v in obj]
    if hasattr(obj, "model_dump"):
        try:
            return serialize_lc_object(obj.model_dump())
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return serialize_lc_object(obj.dict())
        except Exception:
            pass
    if Interrupt is not None and isinstance(obj, Interrupt):
        return {"value": serialize_lc_object(obj.value), "id": getattr(obj, "id", None)}
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def serialize(obj: Any, *, mode: str = "") -> Any:
    if mode == "messages" and isinstance(obj, tuple) and len(obj) == 2:
        message, metadata = obj
        return [serialize_lc_object(message), serialize_lc_object(metadata) or {}]
    return serialize_lc_object(obj)

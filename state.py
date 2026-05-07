"""
Global in-process state shared between the scheduler, background tasks,
and the API layer.  Using a plain dict avoids circular-import issues that
arise from importing FastAPI app objects in scheduler.py.
"""
from typing import Any, Optional

_store: dict[str, Any] = {"last_result": None}


def set_result(result: dict) -> None:
    _store["last_result"] = result


def get_result() -> Optional[dict]:
    return _store["last_result"]

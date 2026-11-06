"""The per-task log of Anakin API calls, stored as Metaflow task metadata.

Task metadata rather than an artifact because an artifact would hold a
different value in each branch of a foreach, and `merge_artifacts` in the join
would then fail on an artifact the user never created.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

METADATA_FIELD = "anakin-calls"
METADATA_TYPE = "anakin-calls"
MAX_LOGGED_CALLS = 200
_MAX_TEXT_CHARS = 120


def safe_url(url: str) -> str:
    """Drop the query, fragment and any userinfo: they can carry tokens."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[unparseable url]"
    return urlunsplit((parts.scheme, parts.hostname or parts.netloc, parts.path, "", ""))


def short_text(text: str) -> str:
    return text if len(text) <= _MAX_TEXT_CHARS else text[:_MAX_TEXT_CHARS] + "..."


def get_anakin_calls(task: Any) -> dict[str, Any]:
    """Return the Anakin calls one finished task made.

    Args:
        task: A `metaflow.Task` (client API), from a step that used `@anakin`.

    Returns:
        `calls`, one dict per API call with `op`, `target`, `status`,
        `duration_ms` and, where the API returned them, `job_id`, `cached`,
        `credits_used` and `error`; `total`, how many calls were made; and
        `dropped`, how many were left out of `calls` (only the first 200 are
        kept). Query strings are removed from URLs. All empty if the task did
        not use `@anakin`.
    """
    raw = task.metadata_dict.get(METADATA_FIELD)
    if not raw:
        return {"calls": [], "total": 0, "dropped": 0}
    return json.loads(raw)  # type: ignore[no-any-return]

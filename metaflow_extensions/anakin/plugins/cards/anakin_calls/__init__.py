"""`@card(type="anakin_calls")`: which web data a task pulled, and how it went."""

from __future__ import annotations

from html import escape
from typing import Any

from metaflow.cards import MetaflowCard

from ...anakin.calls import get_anakin_calls

_COLUMNS = (
    ("op", "Call"),
    ("target", "Target"),
    ("status", "Status"),
    ("duration_ms", "Time (ms)"),
    ("cached", "Cached"),
    ("credits_used", "Credits"),
    ("job_id", "Job"),
    ("error", "Error"),
)
_STYLE = (
    "body{font:14px system-ui,sans-serif;margin:24px;color:#1a1a1a}"
    "table{border-collapse:collapse;width:100%}"
    "th,td{border-bottom:1px solid #ddd;padding:6px 10px;text-align:left;vertical-align:top}"
    "td{word-break:break-word}"
    ".error{color:#b00020}"
)


def _cell(value: Any) -> str:
    return "" if value is None else escape(str(value))


class AnakinCallsCard(MetaflowCard):
    """Table of the Anakin API calls one task made."""

    type = "anakin_calls"  # type: ignore[assignment]

    def render(self, task: Any) -> str:
        log = get_anakin_calls(task)
        calls = log["calls"]
        failed = sum(1 for call in calls if call.get("status") == "error")
        summary = "%d call(s), %d failed." % (log["total"], failed)
        if log["dropped"]:
            summary += " Showing the first %d; %d not logged." % (len(calls), log["dropped"])

        head = "".join(f"<th>{title}</th>" for _, title in _COLUMNS)
        rows = "".join(
            '<tr class="{}">{}</tr>'.format(
                "error" if call.get("status") == "error" else "",
                "".join(f"<td>{_cell(call.get(key))}</td>" for key, _ in _COLUMNS),
            )
            for call in calls
        )
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>Anakin calls</title>"
            f"<style>{_STYLE}</style></head><body>"
            f"<h2>Anakin calls: {escape(str(task.pathspec))}</h2><p>{summary}</p>"
            f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></body></html>"
        )


CARDS = [AnakinCallsCard]

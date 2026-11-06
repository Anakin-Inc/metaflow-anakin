from __future__ import annotations

import json
from types import SimpleNamespace

from metaflow.plugins.cards.card_modules import MF_EXTERNAL_CARDS


def _card() -> type:
    cards = [c for c in MF_EXTERNAL_CARDS if c.type == "anakin_calls"]
    assert len(cards) == 1
    return cards[0]


def _task(log: dict) -> SimpleNamespace:
    return SimpleNamespace(pathspec="F/1/s/2", metadata_dict={"anakin-calls": json.dumps(log)})


def test_card_escapes_page_controlled_text() -> None:
    log = {
        "calls": [
            {"op": "scrape_url", "target": "<script>x</script>", "status": "error", "error": "<b>"}
        ],
        "total": 1,
        "dropped": 0,
    }
    html = _card()().render(_task(log))
    assert "<script>x" not in html
    assert "&lt;script&gt;" in html
    assert "1 call(s), 1 failed." in html


def test_card_reports_dropped_calls() -> None:
    log = {"calls": [{"op": "search", "status": "ok"}], "total": 3, "dropped": 2}
    assert "2 not logged" in _card()().render(_task(log))


def test_card_for_task_without_calls() -> None:
    assert "0 call(s)" in _card()().render(SimpleNamespace(pathspec="F/1/s/2", metadata_dict={}))

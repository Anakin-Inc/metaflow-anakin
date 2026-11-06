"""Unit tests for `AnakinClient`: argument pass-through and JSON-only return values."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from anakin.models import (
    AgenticSearchData,
    AgenticSearchResult,
    AIVisibilitySearch,
    AIVisibilitySource,
    BatchScrapeResult,
    BrowserSession,
    CrawlResult,
    Document,
    MapResult,
    SearchResult,
    SearchResultItem,
    WireActionMatch,
    WireBuildRequest,
    WireCatalog,
    WireLoginResult,
    WireResult,
)
from metaflow import AnakinClient


@pytest.fixture
def client() -> AnakinClient:
    instance = AnakinClient(api_key="ask_" + "0" * 64)
    instance._sdk = MagicMock()
    return instance


def sdk(client: AnakinClient) -> Any:
    return client._sdk


def _assert_json(value: Any) -> None:
    assert json.loads(json.dumps(value)) == value


def test_scrape_url_returns_plain_data_and_logs(client: AnakinClient) -> None:
    sdk(client).scrape.return_value = Document(
        id="j1", url="https://a.test", status="completed", cached=True, markdown="# hi"
    )

    doc = client.scrape_url("https://a.test/p?key=SECRET", use_browser=True, country="de")

    _assert_json(doc)
    assert doc["markdown"] == "# hi"
    kwargs = sdk(client).scrape.call_args.kwargs
    assert kwargs["use_browser"] is True and kwargs["country"] == "de"
    assert sdk(client).scrape.call_args.args == ("https://a.test/p?key=SECRET",)
    log = client.call_log
    assert log["calls"][0]["target"] == "https://a.test/p"
    assert log["calls"][0]["cached"] is True
    assert log["calls"][0]["job_id"] == "j1"


def test_error_is_logged_and_reraised(client: AnakinClient) -> None:
    sdk(client).search.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        client.search("q")
    entry = client.call_log["calls"][0]
    assert entry["status"] == "error"
    assert entry["error"] == "RuntimeError: boom"


def test_log_is_capped_but_counts_everything(client: AnakinClient) -> None:
    sdk(client).search.return_value = SearchResult(id="s", results=[])
    for _ in range(205):
        client.search("q")
    log = client.call_log
    assert (len(log["calls"]), log["total"], log["dropped"]) == (200, 205, 5)


def test_wire_login_never_logs_params(client: AnakinClient) -> None:
    sdk(client).wire.login.return_value = WireLoginResult(
        status="ok", identity_id="i1", credential_id="c1"
    )
    client.wire_login("site", params={"password": "hunter2"})
    assert "hunter2" not in json.dumps(client.call_log)


@pytest.mark.parametrize(
    ("call", "attr", "value"),
    [
        (
            lambda c: c.scrape_batch(["https://a.test"]),
            "scrape_batch",
            BatchScrapeResult(id="b", status="completed"),
        ),
        (lambda c: c.map("https://a.test"), "map", MapResult(id="m", url="https://a.test")),
        (lambda c: c.crawl("https://a.test"), "crawl", CrawlResult(id="c", url="https://a.test")),
        (
            lambda c: c.search("q"),
            "search",
            SearchResult(id="s", results=[SearchResultItem(url="https://a.test")]),
        ),
        (
            lambda c: c.agentic_search("q"),
            "agentic_search",
            AgenticSearchResult(
                id="a", status="completed", generated_json=AgenticSearchData(summary="x")
            ),
        ),
        (lambda c: c.wire_discover("q"), "wire.discover", [WireActionMatch(action_id="x")]),
        (lambda c: c.wire_catalog(), "wire.catalogs", [WireCatalog(id="1", slug="x", name="X")]),
        (
            lambda c: c.wire_catalog(slug="x"),
            "wire.catalog",
            WireCatalog(id="1", slug="x", name="X"),
        ),
        (lambda c: c.wire_read_action("x"), "wire.run", WireResult(job_id="w", status="completed")),
        (lambda c: c.wire_identities(), "wire.identities", []),
        (
            lambda c: c.wire_build_status("b"),
            "wire.get_build",
            WireBuildRequest(id="b", status="pending"),
        ),
        (
            lambda c: c.wire_build("https://a.test", "get prices"),
            "wire.build",
            WireBuildRequest(id="b", status="pending"),
        ),
        (lambda c: c.monitor_changes("m"), "monitors.changes", []),
        (
            lambda c: c.ai_visibility_sources(),
            "ai_visibility.sources",
            [AIVisibilitySource(slug="x")],
        ),
        (lambda c: c.session_list(), "sessions.list", [BrowserSession(id="s")]),
    ],
)
def test_methods_return_json(client: AnakinClient, call: Any, attr: str, value: Any) -> None:
    target = sdk(client)
    for part in attr.split("."):
        target = getattr(target, part)
    target.return_value = value
    _assert_json(call(client))
    assert target.called


def test_ai_visibility_drops_full_content_by_default(client: AnakinClient) -> None:
    sdk(client).ai_visibility.search.return_value = AIVisibilitySearch(
        search_id="s",
        status="completed",
        results=[{"source": "x", "status": "ok", "summary": "y", "full_content": "z"}],
    )
    result = client.ai_visibility_search("q")
    assert "full_content" not in result["results"][0]


def test_monitor_secret_redacted(client: AnakinClient) -> None:
    monitor = MagicMock()
    monitor.model_dump.return_value = {"id": "m", "alertWebhookSecret": "whsec_1"}
    monitor.id = "m"
    sdk(client).monitors.create.return_value = monitor
    sdk(client).monitors.get.return_value = monitor
    sdk(client).monitors.list.return_value = [monitor]

    assert "whsec_1" not in json.dumps(client.monitor_create("https://a.test", 60))
    assert "whsec_1" not in json.dumps(client.monitor_list(monitor_id="m"))
    assert "whsec_1" not in json.dumps(client.monitor_list())


@pytest.mark.parametrize("action", ["pause", "resume", "run_now"])
def test_monitor_control(client: AnakinClient, action: str) -> None:
    result = MagicMock()
    result.model_dump.return_value = {"id": "m"}
    getattr(sdk(client).monitors, action).return_value = result
    assert client.monitor_control("m", action) == {"id": "m"}


def test_monitor_control_delete_and_unknown(client: AnakinClient) -> None:
    assert client.monitor_control("m", "delete") is None
    sdk(client).monitors.delete.assert_called_once_with("m")
    with pytest.raises(ValueError, match="Unknown monitor action"):
        client.monitor_control("m", "explode")


def test_session_delete(client: AnakinClient) -> None:
    client.session_delete("s1")
    sdk(client).sessions.delete.assert_called_once_with("s1")


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.wire_write_action("amazon_checkout"),
        lambda c: c.wire_build("https://a.test", "complete the purchase"),
        lambda c: c.browser_task("buy now the first item"),
    ],
)
def test_financial_requests_refused_before_any_call(client: AnakinClient, call: Any) -> None:
    with pytest.raises(ValueError, match="payments or fund transfers"):
        call(client)
    assert sdk(client).mock_calls == []


def test_write_refused_on_retry_unless_allowed() -> None:
    refused = AnakinClient(api_key="k", retry_count=1)
    refused._sdk = MagicMock()
    with pytest.raises(ValueError, match="@retry attempt 1"):
        refused.wire_write_action("form_submit")
    assert refused._sdk.mock_calls == []

    allowed = AnakinClient(api_key="k", retry_count=1, allow_write_on_retry=True)
    allowed._sdk = MagicMock()
    allowed._sdk.wire.run.return_value = WireResult(job_id="w", status="completed")
    assert allowed.wire_write_action("form_submit")["job_id"] == "w"


def test_read_allowed_on_retry() -> None:
    client = AnakinClient(api_key="k", retry_count=2)
    client._sdk = MagicMock()
    client._sdk.wire.run.return_value = WireResult(job_id="w", status="completed")
    assert client.wire_read_action("get_price")["job_id"] == "w"


def test_browser_task_needs_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANAKIN_API_KEY", raising=False)
    with pytest.raises(ValueError, match="needs an Anakin API key"):
        AnakinClient().browser_task("read the title")


def test_browser_task_polls_to_result(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    responses = iter(
        [
            {"workflow_id": "wf"},
            {"status": "running"},
            {
                "status": "completed",
                "result": {"success": True, "result": "ok", "steps": [1, 2], "run_id": "r1"},
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "k"
        return httpx.Response(200, json=next(responses))

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr("time.sleep", lambda _s: None)

    client = AnakinClient(api_key="k")
    result = client.browser_task("read the title", url="https://a.test")

    assert result["success"] is True and result["steps_taken"] == 2
    assert client.call_log["calls"][0]["job_id"] == "r1"


def test_browser_task_failure_reports_nested_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    responses = iter(
        [
            {"workflow_id": "wf"},
            {"status": "failed", "result": {"success": False, "result": "planner call failed"}},
        ]
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=next(responses))),
            **kw,
        ),
    )
    client = AnakinClient(api_key="k")
    with pytest.raises(RuntimeError, match="Browser task failed: planner call failed"):
        client.browser_task("read the title")
    assert client.call_log["calls"][0]["status"] == "error"


def test_api_key_env_read_late(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_KEY", raising=False)
    client = AnakinClient(api_key_env="MY_KEY")
    monkeypatch.setenv("MY_KEY", "late")
    assert client.sdk.api_key_configured

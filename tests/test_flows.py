"""Real Metaflow runs (subprocess, local datastore) with the extension installed.

These need the built wheel installed, not an editable install: Metaflow doesn't
discover extensions through setuptools' editable finder. The API is a local fake.
"""

from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flows.fake_server import KEY_SEEN, serve

FLOWS = Path(__file__).parent / "flows"


@pytest.fixture(scope="module")
def api() -> Iterator[str]:
    server, url = serve()
    yield url
    server.shutdown()


@pytest.fixture
def run(api: str, tmp_path: Path) -> Any:
    env = {
        **os.environ,
        "METAFLOW_HOME": str(tmp_path),
        "METAFLOW_DATASTORE_SYSROOT_LOCAL": str(tmp_path),
        "METAFLOW_USER": "tester",
        "FAKE_ANAKIN_URL": api,
        "ANAKIN_API_KEY": "ask_" + "0" * 64,
    }

    def _run(flow: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(FLOWS / flow), "--quiet", "run", *args],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    _run.env = env  # type: ignore[attr-defined]
    return _run


def _client_api(run: Any, code: str) -> str:
    """Read run results in a fresh process, as a user's notebook would."""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=run.env["METAFLOW_HOME"],
        env=run.env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_foreach_join_results_and_call_log(run: Any) -> None:
    result = run("foreach_flow.py")
    assert result.returncode == 0, result.stderr

    out = _client_api(
        run,
        """
import json
from metaflow import Flow, get_anakin_calls, namespace
from metaflow.cards import get_cards
namespace(None)
r = Flow("ForeachFlow").latest_successful_run
print(json.dumps({
    "markdown": sorted(p["markdown"] for p in r.data.pages),
    "logs": sorted(
        (get_anakin_calls(t) for t in r["scrape"]), key=lambda log: log["calls"][0]["target"]
    ),
    "empty": get_anakin_calls(r["start"].task),
    "artifacts": sorted(a.id for a in r["scrape"].task.artifacts),
    "card": [c.get() for c in get_cards(next(iter(r["scrape"])), type="anakin_calls")],
}))
""",
    )
    data = json.loads(out.strip().splitlines()[-1])
    assert data["markdown"] == [
        "# hello from https://a.test/x?token=SECRET",
        "# hello from https://b.test/y",
    ]
    first = data["logs"][0]
    assert first["total"] == 1 and first["dropped"] == 0
    call = first["calls"][0]
    assert call["op"] == "scrape_url"
    assert call["status"] == "ok"
    assert call["target"] == "https://a.test/x"  # query string stripped
    assert call["job_id"].startswith("job-")
    assert data["empty"] == {"calls": [], "total": 0, "dropped": 0}
    assert "anakin_calls" not in data["artifacts"]
    assert len(data["card"]) == 1
    assert "scrape_url" in data["card"][0]
    assert "SECRET" not in data["card"][0]


def test_merge_artifacts_without_exclude_is_not_broken(run: Any) -> None:
    result = run("merge_flow.py")
    assert result.returncode == 0, result.stderr


def test_client_cannot_be_stored_as_artifact(run: Any) -> None:
    result = run("store_client_flow.py")
    assert result.returncode != 0
    assert "client" in result.stderr + result.stdout  # the artifact named in the failure
    assert "ask_" not in result.stderr + result.stdout


def test_write_refused_on_retry(run: Any) -> None:
    result = run("retry_write_flow.py")
    assert result.returncode != 0
    assert "repeating a" in result.stderr + result.stdout


def test_call_log_saved_when_the_call_fails(run: Any) -> None:
    result = run("failing_flow.py")
    assert result.returncode != 0
    out = _client_api(
        run,
        """
from metaflow import Flow, get_anakin_calls, namespace
namespace(None)
log = get_anakin_calls(Flow("FailingFlow").latest_run["start"].task)
print(log["calls"][0]["status"], log["calls"][0]["error"].split(":")[0])
""",
    )
    assert out.strip().splitlines()[-1].startswith("error ")


def test_key_set_during_step_is_used(run: Any) -> None:
    KEY_SEEN.clear()
    result = run("secret_late_flow.py")
    assert result.returncode == 0, result.stderr
    assert KEY_SEEN == ["ask_" + "1" * 64]


def test_key_from_secrets_decorator_in_either_order(run: Any) -> None:
    KEY_SEEN.clear()
    result = run("secrets_flow.py")
    assert result.returncode == 0, result.stderr
    assert KEY_SEEN == ["ask_" + "2" * 64, "ask_" + "3" * 64]


def test_with_flag_attaches_decorator(run: Any) -> None:
    result = run("merge_flow.py", "--with", "anakin:base_url=" + run.env["FAKE_ANAKIN_URL"])
    assert result.returncode == 0, result.stderr


def test_client_refuses_pickle() -> None:
    from metaflow import AnakinClient

    with pytest.raises(TypeError, match="API key"):
        pickle.dumps(AnakinClient(api_key="ask_" + "0" * 64))
    assert "ask_" not in repr(AnakinClient(api_key="ask_" + "0" * 64))

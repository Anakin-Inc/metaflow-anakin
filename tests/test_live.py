"""Live run against api.anakin.io. Skipped unless ANAKIN_LIVE_TESTS=1."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ANAKIN_LIVE_TESTS") != "1",
    reason="set ANAKIN_LIVE_TESTS=1 to call the live API",
)

EXAMPLE = Path(__file__).parent.parent / "examples" / "web_research_flow.py"


def test_example_flow_against_live_api(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "METAFLOW_HOME": str(tmp_path),
        "METAFLOW_DATASTORE_SYSROOT_LOCAL": str(tmp_path),
        "METAFLOW_USER": "tester",
    }
    result = subprocess.run(
        [sys.executable, str(EXAMPLE), "--quiet", "run"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    assert "https://example.com" in result.stdout + result.stderr

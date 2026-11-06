"""`import metaflow` must survive when anakin-sdk isn't installed (remote images)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CODE = """
import sys
sys.modules["anakin"] = None
sys.modules["httpx"] = None
sys.modules["pydantic"] = None
import metaflow
assert hasattr(metaflow, "anakin")
assert hasattr(metaflow, "AnakinClient")
print("ok")
"""


def test_extension_imports_without_sdk(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", CODE], cwd=tmp_path, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")

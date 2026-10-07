"""Lock the internal shared engine snapshot; no second Python compactor."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1] / "third_party/codmes-context-engine"


def test_vendored_engine_matches_locked_shared_source():
    manifest = json.loads((ENGINE / "snapshot.json").read_text())
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((ENGINE / name).read_bytes()).hexdigest() == expected, name
        source = os.environ.get("KNU_CODMES_CONTEXT_SOURCE")
        if source:
            assert (Path(source) / name).read_bytes() == (ENGINE / name).read_bytes(), name


def test_shared_javascript_engine_regressions():
    node = os.environ.get("KNU_CONTEXT_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node.js context runtime required")
    result = subprocess.run([node, "--test", str(ENGINE / "engine.test.mjs")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

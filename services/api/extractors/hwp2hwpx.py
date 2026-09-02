"""선택적 HWP→HWPX 교차 검증 어댑터.

주 추출은 순수 Python 구조 파서가 담당한다. 이 변환본은 독립적인 두 번째
검사 결과이며, 변환기/JRE가 없어도 HWP 수집 자체는 계속된다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _java() -> str | None:
    candidates = [
        shutil.which("java"),
        str(Path(os.environ["JAVA_HOME"]) / "bin/java") if os.getenv("JAVA_HOME") else None,
        "/opt/homebrew/opt/openjdk@21/bin/java",
    ]
    for value in candidates:
        if not value or not Path(value).exists():
            continue
        try:
            probe = subprocess.run(
                [value, "-version"], capture_output=True, timeout=10
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            return value
    return None


def _jar() -> Path | None:
    local_build = (
        Path(__file__).resolve().parents[1]
        / "third_party/hwp2hwpx/build/hwp2hwpx-patched.jar"
    )
    candidates = [
        os.getenv("HWP2HWPX_JAR"),
        "/opt/hwp2hwpx/hwp2hwpx-patched.jar",
        str(local_build),
    ]
    return next((Path(value) for value in candidates if value and Path(value).is_file()), None)


def convert_hwp_to_hwpx(data: bytes, timeout_seconds: int = 180) -> dict:
    java = _java()
    jar = _jar()
    if not java or not jar:
        return {
            "status": "unavailable",
            "reason": "patched_converter_or_java_not_installed",
            "data": None,
        }

    with tempfile.TemporaryDirectory(prefix="hwp2hwpx-") as temp:
        source = Path(temp) / "source.hwp"
        output = Path(temp) / "converted.hwpx"
        source.write_bytes(data)
        process = subprocess.run(
            [java, "-Dfile.encoding=UTF-8", "-jar", str(jar), str(source), str(output)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if process.returncode != 0 or not output.is_file():
            detail = (process.stderr or process.stdout or "no output").strip()
            return {"status": "failed", "reason": detail[-2000:], "data": None}
        converted = output.read_bytes()
        return {
            "status": "converted",
            "bytes": len(converted),
            "data": converted,
        }

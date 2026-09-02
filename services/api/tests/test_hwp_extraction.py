import os
import signal
import struct
import subprocess

import pytest

import extractors.attachments as attachments
from extractors.attachments import _hwp_record_stream_text, run_soffice_convert


def _record(tag_id: int, payload: bytes) -> bytes:
    header = tag_id | (len(payload) << 20)
    return struct.pack("<I", header) + payload


def test_hwp_record_stream_extracts_paragraph_text_and_skips_controls():
    # tab control은 8 UTF-16 units이고 나머지 7개 payload는 본문으로 읽으면 안 된다.
    tab_control = [9, 0xAC00, 0xB098, 0, 0, 0, 0, 0]
    units = [ord("공"), ord("주"), *tab_control, ord("대"), ord("학"), 13, ord("요"), ord("람")]
    paragraph = struct.pack(f"<{len(units)}H", *units)
    stream = _record(66, b"ignored") + _record(67, paragraph)

    assert _hwp_record_stream_text(stream) == "공주 대학\n요람"


def test_hwp_record_stream_combines_utf16_surrogate_pairs():
    payload = "학교 U0001F3EB".encode("utf-16le")

    assert _hwp_record_stream_text(_record(67, payload)) == "학교 U0001F3EB"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
def test_soffice_timeout_kills_the_whole_process_group(monkeypatch, tmp_path):
    calls = []

    class FakeProcess:
        pid = 4321
        returncode = None

        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))
            self.communications = 0

        def communicate(self, timeout=None):
            self.communications += 1
            if self.communications == 1:
                raise subprocess.TimeoutExpired("soffice", timeout)
            self.returncode = -signal.SIGKILL
            return "", ""

    killed = []
    monkeypatch.setattr(attachments, "_find_soffice", lambda: "/fake/soffice")
    monkeypatch.setattr(attachments.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(attachments.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setenv("LIBREOFFICE_TIMEOUT_SECONDS", "1")
    input_path = tmp_path / "input.hwp"
    input_path.write_bytes(b"test")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    assert run_soffice_convert(input_path, out_dir) is None
    assert killed == [(4321, signal.SIGKILL)]
    assert calls[0][1]["start_new_session"] is True

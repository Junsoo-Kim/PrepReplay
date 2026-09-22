"""prepreplay/diagnostics.py 단위 테스트."""

from __future__ import annotations

import pytest

from prepreplay.diagnostics import diagnose_failure


@pytest.mark.parametrize(
    ("raw_text", "expected_substring"),
    [
        ("Error: No space left on device", "디스크"),
        ("bash: audio.wav: Permission denied", "권한"),
        ("Invalid data found when processing input", "손상"),
        ("moov atom not found", "손상"),
        ("Could not load library cudnn_ops64_9.dll", "GPU(CUDA)"),
        ("RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB", "메모리"),
        ("requests.exceptions.ConnectionError: failed to download model", "다운로드"),
        ("ffmpeg: No such file or directory", "경로"),
    ],
)
def test_diagnose_failure_matches_known_patterns(raw_text, expected_substring):
    hint = diagnose_failure(raw_text)
    assert hint is not None
    assert expected_substring in hint


def test_diagnose_failure_returns_none_for_unmatched_text():
    assert diagnose_failure("some completely unrelated log line") is None


def test_diagnose_failure_returns_none_for_empty_or_none_input():
    assert diagnose_failure(None) is None
    assert diagnose_failure("") is None

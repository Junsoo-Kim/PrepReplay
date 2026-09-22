"""prepreplay.utils.ffmpeg 테스트 (ffmpeg 필요, 없으면 스킵)."""

from __future__ import annotations

from pathlib import Path

from prepreplay.utils.ffmpeg import find_ffmpeg, find_ffprobe, probe_video

from .conftest import requires_ffmpeg


@requires_ffmpeg
def test_find_ffmpeg_and_ffprobe_are_detected_when_installed() -> None:
    assert find_ffmpeg() is not None
    assert find_ffprobe() is not None


@requires_ffmpeg
def test_probe_video_reads_duration_and_resolution(sample_video: Path) -> None:
    info = probe_video(sample_video)
    assert 2.5 <= info.duration_seconds <= 3.5
    assert info.width == 320
    assert info.height == 240
    assert info.has_audio is True
    assert info.audio_codec is not None
    assert info.size_bytes > 0


@requires_ffmpeg
def test_probe_video_detects_missing_audio_track(silent_video: Path) -> None:
    info = probe_video(silent_video)
    assert info.has_audio is False
    assert info.audio_codec is None


@requires_ffmpeg
def test_duration_hms_formatting(sample_video: Path) -> None:
    info = probe_video(sample_video)
    assert info.duration_hms in ("00:03", "00:02")  # 인코딩 오차 허용

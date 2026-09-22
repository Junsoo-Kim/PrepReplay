"""prepreplay.steps.frames 테스트."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from prepreplay.errors import FrameExtractionError
from prepreplay.steps.frames import (
    FRAMES_DIRNAME,
    FRAMES_METADATA_FILENAME,
    _evenly_spaced_indices,
    extract_frames,
)
from prepreplay.utils.ffmpeg import VideoInfo, probe_video

from .conftest import requires_ffmpeg

FRAME_FILENAME_RE = re.compile(r"^frame_\d{2,}m\d{2}s(_\d+ms(_\d+)?)?\.jpg$")


def _make_video_info(path: Path, duration: float) -> VideoInfo:
    return VideoInfo(
        path=path,
        duration_seconds=duration,
        width=320,
        height=240,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec="h264",
        audio_codec=None,
        has_audio=False,
        size_bytes=1234,
    )


def test_evenly_spaced_indices_basic() -> None:
    assert _evenly_spaced_indices(10, 10) == list(range(10))
    assert _evenly_spaced_indices(10, 20) == list(range(10))  # want > total
    assert _evenly_spaced_indices(10, 1) == [0]
    assert _evenly_spaced_indices(0, 5) == []
    assert _evenly_spaced_indices(5, 0) == []
    result = _evenly_spaced_indices(10, 3)
    assert result[0] == 0
    assert result[-1] == 9
    assert len(result) == 3


@requires_ffmpeg
def test_extract_frames_detects_scene_changes(
    tmp_path: Path, scene_change_video: Path
) -> None:
    info = probe_video(scene_change_video)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = extract_frames(scene_change_video, output_dir, info, force=False)

    assert result.skipped is False
    assert result.method == "scene_detection"
    assert result.frame_count >= 2  # 빨강->파랑, 파랑->초록 두 번의 전환

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["method"] == "scene_detection"
    assert metadata["frame_count"] == result.frame_count
    assert len(metadata["frames"]) == result.frame_count

    frames_dir = output_dir / FRAMES_DIRNAME
    for frame in metadata["frames"]:
        assert FRAME_FILENAME_RE.match(frame["filename"])
        assert (frames_dir / frame["filename"]).is_file()


@requires_ffmpeg
def test_extract_frames_falls_back_to_uniform_when_no_scene_changes(
    tmp_path: Path, sample_video: Path
) -> None:
    info = probe_video(sample_video)  # testsrc: 연속 변화라 장면 전환이 거의 감지 안 됨
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = extract_frames(
        sample_video, output_dir, info, fallback_interval_seconds=1.0, force=False
    )

    assert result.skipped is False
    assert result.method == "uniform_interval"
    assert result.frame_count >= 1

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["method"] == "uniform_interval"
    assert metadata["interval_seconds"] is not None


@requires_ffmpeg
def test_extract_frames_handles_video_shorter_than_fallback_interval(
    tmp_path: Path, sample_video: Path
) -> None:
    """영상 길이(3초)보다 긴 fallback 간격(60초 기본값)을 줘도 최소 1프레임은 나와야 한다.

    ffmpeg의 fps 필터는 주기가 영상 길이보다 길면 첫 프레임조차 flush하지 않는
    것을 실측으로 확인했다 - extract_frames가 내부적으로 간격을 영상 길이에
    맞춰 클램프해야 한다.
    """
    info = probe_video(sample_video)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = extract_frames(sample_video, output_dir, info, force=False)  # 기본 60초 간격

    assert result.frame_count >= 1


def test_extract_frames_skips_when_cached(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    frames_dir = output_dir / FRAMES_DIRNAME
    frames_dir.mkdir(parents=True)
    (frames_dir / "frame_00m00s.jpg").write_bytes(b"fake-jpg")
    (output_dir / FRAMES_METADATA_FILENAME).write_text("{}", encoding="utf-8")

    dummy_info = _make_video_info(Path("dummy.mp4"), 5.0)

    with patch("prepreplay.steps.frames.subprocess.run") as mock_run:
        result = extract_frames(Path("dummy.mp4"), output_dir, dummy_info, force=False)

    mock_run.assert_not_called()
    assert result.skipped is True
    assert result.frame_count == 1


@requires_ffmpeg
def test_extract_frames_caps_to_max_frames(tmp_path: Path, scene_change_video: Path) -> None:
    info = probe_video(scene_change_video)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = extract_frames(scene_change_video, output_dir, info, max_frames=1, force=False)

    assert result.frame_count == 1
    frames_dir = output_dir / FRAMES_DIRNAME
    jpgs = list(frames_dir.glob("frame_*.jpg"))
    assert len(jpgs) == 1
    # 상한에 걸려 버려진 raw 파일이 남아있지 않아야 한다.
    assert list(frames_dir.glob("raw_*.jpg")) == []


@requires_ffmpeg
def test_extract_frames_force_regenerates(tmp_path: Path, scene_change_video: Path) -> None:
    info = probe_video(scene_change_video)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    first = extract_frames(scene_change_video, output_dir, info, force=False)
    assert first.skipped is False

    second = extract_frames(scene_change_video, output_dir, info, force=False)
    assert second.skipped is True

    third = extract_frames(scene_change_video, output_dir, info, force=True)
    assert third.skipped is False
    assert third.frame_count == first.frame_count


@requires_ffmpeg
def test_extract_frames_raises_on_ffmpeg_failure(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    dummy_info = _make_video_info(tmp_path / "does_not_exist.mp4", 5.0)

    with pytest.raises(FrameExtractionError) as exc_info:
        extract_frames(tmp_path / "does_not_exist.mp4", output_dir, dummy_info, force=False)
    assert exc_info.value.stage == "프레임 추출"

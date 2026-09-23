"""prepreplay.steps.split 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prepreplay.errors import SplitError
from prepreplay.steps.frames import FRAMES_METADATA_FILENAME
from prepreplay.steps.split import (
    CHUNKS_DIRNAME,
    MANIFEST_FILENAME,
    parse_split_seconds,
    split_into_chunks,
)
from prepreplay.steps.transcribe import SEGMENTS_FILENAME


def _write_segments(output_dir: Path, segments: list[dict]) -> None:
    data = {"language": "ko", "model": "large-v3", "device": "cuda", "segments": segments}
    (output_dir / SEGMENTS_FILENAME).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _write_frames(output_dir: Path, frames: list[dict]) -> None:
    data = {"method": "scene_detection", "frame_count": len(frames), "frames": frames}
    (output_dir / FRAMES_METADATA_FILENAME).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


@pytest.mark.parametrize(
    "spec,expected_seconds",
    [
        ("10m", 600.0),
        ("1h", 3600.0),
        ("90s", 90.0),
        ("2.5m", 150.0),
        ("15", 900.0),  # 단위 생략 시 분
    ],
)
def test_parse_split_seconds_valid(spec: str, expected_seconds: float) -> None:
    assert parse_split_seconds(spec) == expected_seconds


@pytest.mark.parametrize("spec", ["", "abc", "10x", "-5m", "0m"])
def test_parse_split_seconds_invalid(spec: str) -> None:
    with pytest.raises(SplitError):
        parse_split_seconds(spec)


def test_split_into_one_hour_video_into_six_chunks(tmp_path: Path) -> None:
    """DoD: 1시간 영상이 10분 단위로 6개 청크로 나뉜다."""
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    # 6개 구간(0,10,20,30,40,50분)에 각각 세그먼트 하나씩, 프레임도 하나씩.
    segments = []
    frames = []
    for i in range(6):
        minute = i * 10
        start = minute * 60 + 5
        segments.append(
            {"id": i, "start": start, "end": start + 3, "text": f"{minute}분대 발언입니다."}
        )
        frames.append({"index": i, "timestamp": start, "filename": f"frame_{i:02d}.jpg"})
    _write_segments(output_dir, segments)
    _write_frames(output_dir, frames)

    result = split_into_chunks(
        output_dir,
        video_name="lecture.mp4",
        duration_seconds=3600.0,
        split_spec="10m",
        mode="lecture",
        force=False,
    )

    assert result.skipped is False
    assert result.chunk_count == 6

    chunk_files = sorted((output_dir / CHUNKS_DIRNAME).glob("part_*.md"))
    assert len(chunk_files) == 6
    assert chunk_files[0].name == "part_01_000m-010m.md"
    assert chunk_files[5].name == "part_06_050m-060m.md"

    first_content = chunk_files[0].read_text(encoding="utf-8")
    assert "0분대 발언입니다." in first_content
    assert "10분대 발언입니다." not in first_content  # 세그먼트가 섞이지 않음
    assert "강의 대체재" in first_content  # lecture.md 지시문 포함


def test_split_does_not_cut_a_segment_across_chunks(tmp_path: Path) -> None:
    """세그먼트는 시작 시각 기준으로 통째로 한 구간에만 배정되어야 한다."""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    # 9분 58초에 시작해 10분 5초에 끝나는, 경계를 가로지르는 세그먼트.
    _write_segments(
        output_dir,
        [{"id": 0, "start": 598.0, "end": 605.0, "text": "경계를 가로지르는 문장입니다."}],
    )
    _write_frames(output_dir, [{"index": 0, "timestamp": 0.0, "filename": "frame_00.jpg"}])

    result = split_into_chunks(
        output_dir, video_name="v.mp4", duration_seconds=650.0, split_spec="10m", force=False
    )

    chunk_files = sorted((output_dir / CHUNKS_DIRNAME).glob("part_*.md"))
    contents = [f.read_text(encoding="utf-8") for f in chunk_files]
    matches = [c for c in contents if "경계를 가로지르는 문장입니다." in c]
    assert len(matches) == 1  # 정확히 한 구간에만 온전히 들어가야 함


def test_split_writes_manifest_and_skips_when_cached(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_segments(output_dir, [{"id": 0, "start": 0.0, "end": 3.0, "text": "안녕하세요."}])
    _write_frames(output_dir, [{"index": 0, "timestamp": 0.0, "filename": "frame_00.jpg"}])

    first = split_into_chunks(
        output_dir, video_name="v.mp4", duration_seconds=5.0, split_spec="10m", force=False
    )
    assert first.skipped is False
    manifest_path = output_dir / CHUNKS_DIRNAME / MANIFEST_FILENAME
    assert manifest_path.is_file()

    second = split_into_chunks(
        output_dir, video_name="v.mp4", duration_seconds=5.0, split_spec="10m", force=False
    )
    assert second.skipped is True
    assert second.chunk_count == first.chunk_count


def test_split_force_regenerates(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_segments(output_dir, [{"id": 0, "start": 0.0, "end": 3.0, "text": "안녕하세요."}])
    _write_frames(output_dir, [{"index": 0, "timestamp": 0.0, "filename": "frame_00.jpg"}])

    split_into_chunks(
        output_dir, video_name="v.mp4", duration_seconds=5.0, split_spec="10m", force=False
    )
    second = split_into_chunks(
        output_dir, video_name="v.mp4", duration_seconds=5.0, split_spec="10m", force=True
    )
    assert second.skipped is False


def test_split_raises_when_segments_missing(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_frames(output_dir, [{"index": 0, "timestamp": 0.0, "filename": "frame_00.jpg"}])

    with pytest.raises(SplitError) as exc_info:
        split_into_chunks(
            output_dir, video_name="v.mp4", duration_seconds=5.0, split_spec="10m", force=False
        )
    assert exc_info.value.stage == "구간 분할"


def test_split_image_paths_use_parent_relative_prefix(tmp_path: Path) -> None:
    """chunks/*.md는 output_dir이 아니라 chunks/ 안에 있으므로 ../frames/를 참조해야 한다."""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_segments(output_dir, [{"id": 0, "start": 0.0, "end": 3.0, "text": "안녕하세요."}])
    _write_frames(output_dir, [{"index": 0, "timestamp": 0.0, "filename": "frame_00m00s.jpg"}])

    split_into_chunks(
        output_dir, video_name="v.mp4", duration_seconds=5.0, split_spec="10m", force=False
    )

    content = (output_dir / CHUNKS_DIRNAME / "part_01_000m-001m.md").read_text(encoding="utf-8")
    assert "![화면](../frames/frame_00m00s.jpg)" in content

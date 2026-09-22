"""prepreplay.steps.index 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prepreplay.errors import IndexGenerationError
from prepreplay.steps.frames import FRAMES_METADATA_FILENAME
from prepreplay.steps.index import INDEX_FILENAME, generate_index
from prepreplay.steps.transcribe import SEGMENTS_FILENAME


def _write_segments(output_dir: Path, segments: list[dict], **extra) -> None:
    data = {
        "language": "ko",
        "model": "large-v3",
        "device": "cuda",
        "segments": segments,
        **extra,
    }
    (output_dir / SEGMENTS_FILENAME).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _write_frames(output_dir: Path, frames: list[dict], method: str = "scene_detection") -> None:
    data = {"method": method, "frame_count": len(frames), "frames": frames}
    (output_dir / FRAMES_METADATA_FILENAME).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def test_generate_index_merges_segments_into_frame_sections(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_segments(
        output_dir,
        [
            {"id": 0, "start": 3.0, "end": 10.0, "text": "먼저 이력서에서 프로젝트 경험을 짚어보겠습니다."},
            # frame 1(137초) 이후 시점이어야 두 번째 섹션에 배정된다.
            {"id": 1, "start": 140.0, "end": 150.0, "text": "포트폴리오는 기술적 깊이가 부족해 보여요."},
        ],
    )
    _write_frames(
        output_dir,
        [
            {"index": 0, "timestamp": 3.0, "filename": "frame_00m03s.jpg"},
            {"index": 1, "timestamp": 137.0, "filename": "frame_02m17s.jpg"},
        ],
    )

    result = generate_index(
        output_dir, video_name="consulting_0921.mp4", duration_seconds=190.0, force=False
    )

    assert result.skipped is False
    assert result.section_count == 2
    assert result.path == output_dir / INDEX_FILENAME

    markdown = result.path.read_text(encoding="utf-8")
    assert "# consulting_0921.mp4 분석 인덱스" in markdown
    assert "- 영상: consulting_0921.mp4" in markdown
    assert "- 프레임: 2개 (장면 감지)" in markdown
    assert "## 00:03 - 02:17" in markdown
    assert "![화면](frames/frame_00m03s.jpg)" in markdown

    first_section = markdown.split("## 00:03 - 02:17")[1].split("## 02:17")[0]
    assert "먼저 이력서에서 프로젝트 경험을 짚어보겠습니다." in first_section
    assert "포트폴리오는" not in first_section  # 두 번째 세그먼트가 섞이지 않아야 함

    assert "## 02:17 - 03:10" in markdown
    assert "![화면](frames/frame_02m17s.jpg)" in markdown
    second_section = markdown.split("## 02:17 - 03:10")[1]
    assert "포트폴리오는 기술적 깊이가 부족해 보여요." in second_section


def test_generate_index_creates_intro_section_before_first_frame(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_segments(
        output_dir,
        [{"id": 0, "start": 0.5, "end": 2.0, "text": "인트로 멘트입니다."}],
    )
    _write_frames(output_dir, [{"index": 0, "timestamp": 5.0, "filename": "frame_00m05s.jpg"}])

    result = generate_index(output_dir, video_name="v.mp4", duration_seconds=20.0, force=False)

    assert result.section_count == 2
    markdown = result.path.read_text(encoding="utf-8")
    assert "## 00:00 - 00:05" in markdown
    assert "인트로 멘트입니다." in markdown
    # 인트로 섹션에는 이미지가 없어야 한다.
    intro_block = markdown.split("## 00:00 - 00:05")[1].split("## 00:05")[0]
    assert "![화면]" not in intro_block


def test_generate_index_marks_sections_without_speech(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_segments(output_dir, [])
    _write_frames(output_dir, [{"index": 0, "timestamp": 0.0, "filename": "frame_00m00s.jpg"}])

    result = generate_index(output_dir, video_name="v.mp4", duration_seconds=5.0, force=False)

    markdown = result.path.read_text(encoding="utf-8")
    assert "(음성 없음)" in markdown


def test_generate_index_handles_no_frames(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_segments(output_dir, [{"id": 0, "start": 0.0, "end": 3.0, "text": "안녕하세요."}])
    _write_frames(output_dir, [])

    result = generate_index(output_dir, video_name="v.mp4", duration_seconds=3.0, force=False)

    assert result.section_count == 1
    markdown = result.path.read_text(encoding="utf-8")
    assert "안녕하세요." in markdown
    assert "![화면]" not in markdown


def test_generate_index_skips_when_cached(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / INDEX_FILENAME).write_text("# 기존 인덱스", encoding="utf-8")
    # segments.json/frames.json이 없어도 캐시 히트면 아예 읽지 않아야 한다.

    result = generate_index(output_dir, video_name="v.mp4", duration_seconds=3.0, force=False)

    assert result.skipped is True
    assert (output_dir / INDEX_FILENAME).read_text(encoding="utf-8") == "# 기존 인덱스"


def test_generate_index_force_regenerates(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / INDEX_FILENAME).write_text("# 기존 인덱스", encoding="utf-8")
    _write_segments(output_dir, [{"id": 0, "start": 0.0, "end": 1.0, "text": "새 내용입니다."}])
    _write_frames(output_dir, [{"index": 0, "timestamp": 0.0, "filename": "frame_00m00s.jpg"}])

    result = generate_index(output_dir, video_name="v.mp4", duration_seconds=1.0, force=True)

    assert result.skipped is False
    markdown = result.path.read_text(encoding="utf-8")
    assert "새 내용입니다." in markdown


def test_generate_index_raises_when_segments_missing(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_frames(output_dir, [{"index": 0, "timestamp": 0.0, "filename": "frame_00m00s.jpg"}])

    with pytest.raises(IndexGenerationError) as exc_info:
        generate_index(output_dir, video_name="v.mp4", duration_seconds=1.0, force=False)
    assert exc_info.value.stage == "인덱스 생성"


def test_generate_index_raises_when_frames_missing(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_segments(output_dir, [{"id": 0, "start": 0.0, "end": 1.0, "text": "안녕하세요."}])

    with pytest.raises(IndexGenerationError):
        generate_index(output_dir, video_name="v.mp4", duration_seconds=1.0, force=False)


def test_generate_index_raises_on_malformed_json(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / SEGMENTS_FILENAME).write_text("{not valid json", encoding="utf-8")
    _write_frames(output_dir, [{"index": 0, "timestamp": 0.0, "filename": "frame_00m00s.jpg"}])

    with pytest.raises(IndexGenerationError):
        generate_index(output_dir, video_name="v.mp4", duration_seconds=1.0, force=False)

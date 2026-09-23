"""prepreplay.steps.summary_prompt 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from prepreplay.config import VALID_MODES
from prepreplay.errors import SummaryPromptError
from prepreplay.steps.summary_prompt import (
    SUMMARY_PROMPT_FILENAME,
    TEMPLATES_DIR,
    generate_summary_prompt,
)

SAMPLE_INDEX_MD = """# sample.mp4 분석 인덱스

- 영상: sample.mp4
- 길이: 00:07
- 프레임: 2개 (장면 감지)
- STT: tiny 모델, 언어=ko, device=cuda
- 생성 시각: 2026-09-22 15:05:50

---

## 00:00 - 00:03

스크립트: "첫번째 화면입니다."

## 00:03 - 00:05

![화면](frames/frame_00m03s.jpg)

스크립트: "두번째 화면입니다."
"""


def _write_index(output_dir: Path, content: str = SAMPLE_INDEX_MD) -> None:
    (output_dir / "index.md").write_text(content, encoding="utf-8")


def test_all_valid_modes_have_a_builtin_template() -> None:
    """config.VALID_MODES의 모든 모드는 내장 템플릿 파일을 가져야 한다."""
    for mode in VALID_MODES:
        assert (TEMPLATES_DIR / f"{mode}.md").is_file(), f"{mode}.md 템플릿이 없습니다"


def test_generate_summary_prompt_includes_instruction_and_index_sections(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_index(output_dir)

    result = generate_summary_prompt(
        output_dir,
        video_name="sample.mp4",
        duration_seconds=7.0,
        mode="consulting",
        force=False,
    )

    assert result.skipped is False
    assert result.mode == "consulting"
    assert result.path == output_dir / SUMMARY_PROMPT_FILENAME

    content = result.path.read_text(encoding="utf-8")
    assert "컨설턴트가 짚어준 피드백" in content  # consulting.md 지시문
    assert "## 00:00 - 00:03" in content  # index.md 섹션이 그대로 포함
    assert "![화면](frames/frame_00m03s.jpg)" in content
    assert "- 파일명: sample.mp4" in content
    # index.md의 헤더(메타정보)는 중복해서 넣지 않는다.
    assert content.count("- 영상: sample.mp4") == 0


def test_generate_summary_prompt_uses_custom_template(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_index(output_dir)

    custom_template = tmp_path / "my_template.md"
    custom_template.write_text("이것은 커스텀 지시문입니다.", encoding="utf-8")

    result = generate_summary_prompt(
        output_dir,
        video_name="sample.mp4",
        duration_seconds=7.0,
        mode="default",
        template_path=custom_template,
        force=False,
    )

    content = result.path.read_text(encoding="utf-8")
    assert "이것은 커스텀 지시문입니다." in content


def test_generate_summary_prompt_raises_when_index_missing(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(SummaryPromptError) as exc_info:
        generate_summary_prompt(
            output_dir, video_name="sample.mp4", duration_seconds=7.0, force=False
        )
    assert exc_info.value.stage == "요약 프롬프트 생성"


def test_generate_summary_prompt_raises_when_custom_template_missing(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_index(output_dir)

    with pytest.raises(SummaryPromptError):
        generate_summary_prompt(
            output_dir,
            video_name="sample.mp4",
            duration_seconds=7.0,
            template_path=tmp_path / "does_not_exist.md",
            force=False,
        )


def test_generate_summary_prompt_raises_on_unknown_mode(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    _write_index(output_dir)

    with pytest.raises(SummaryPromptError):
        generate_summary_prompt(
            output_dir, video_name="sample.mp4", duration_seconds=7.0, mode="nonsense", force=False
        )


def test_generate_summary_prompt_skips_when_cached(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / SUMMARY_PROMPT_FILENAME).write_text("# 기존 프롬프트", encoding="utf-8")
    # index.md가 없어도 캐시 히트면 아예 읽지 않아야 한다.

    result = generate_summary_prompt(
        output_dir, video_name="sample.mp4", duration_seconds=7.0, force=False
    )

    assert result.skipped is True
    assert (output_dir / SUMMARY_PROMPT_FILENAME).read_text(encoding="utf-8") == "# 기존 프롬프트"


def test_generate_summary_prompt_force_regenerates(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / SUMMARY_PROMPT_FILENAME).write_text("# 기존 프롬프트", encoding="utf-8")
    _write_index(output_dir)

    result = generate_summary_prompt(
        output_dir, video_name="sample.mp4", duration_seconds=7.0, mode="lecture", force=True
    )

    assert result.skipped is False
    content = result.path.read_text(encoding="utf-8")
    assert "강의 대체재" in content  # lecture.md 지시문

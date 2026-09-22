"""파이프라인 5단계: summary_prompt.md 생성.

`index.md`(스크립트+프레임 매핑)에 유스케이스별 지시문을 붙여, 복사해서 바로
Claude에 붙여넣을 수 있는 프롬프트 파일을 만든다. 지시문은 `--mode` 값에 따라
내장 템플릿(`prepreplay/templates/*.md`, 기획서 6절)에서 고르거나, `--template`로
사용자가 직접 지정한 파일을 쓸 수 있다.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path
from typing import Optional

from prepreplay.errors import SummaryPromptError
from prepreplay.pipeline import is_cached
from prepreplay.steps.index import INDEX_FILENAME

SUMMARY_PROMPT_FILENAME = "summary_prompt.md"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_INDEX_SECTION_SEPARATOR = "\n---\n\n"


@dataclasses.dataclass
class SummaryPromptResult:
    path: Path
    mode: str
    skipped: bool


def _format_timestamp(seconds: float) -> str:
    total = int(round(max(seconds, 0.0)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _load_instruction(mode: str, template_path: Optional[Path]) -> str:
    if template_path is not None:
        if not template_path.exists():
            raise SummaryPromptError(
                f"템플릿 파일을 찾을 수 없습니다: {template_path}",
                hint="--template 경로를 확인하세요.",
            )
        return template_path.read_text(encoding="utf-8").strip()

    builtin_path = TEMPLATES_DIR / f"{mode}.md"
    if not builtin_path.exists():
        raise SummaryPromptError(
            f"'{mode}' 모드에 해당하는 내장 템플릿이 없습니다: {builtin_path}",
            hint="--template로 직접 템플릿 파일을 지정할 수 있습니다.",
        )
    return builtin_path.read_text(encoding="utf-8").strip()


def _extract_index_sections(index_markdown: str) -> str:
    """index.md에서 헤더(메타정보) 이후 구간별 섹션만 잘라낸다.

    summary_prompt.md 쪽에 별도로 영상 정보를 적으므로, index.md의 헤더를
    그대로 중복하지 않기 위함이다.
    """
    if _INDEX_SECTION_SEPARATOR in index_markdown:
        return index_markdown.split(_INDEX_SECTION_SEPARATOR, 1)[1].strip()
    return index_markdown.strip()


def generate_summary_prompt(
    output_dir: Path,
    *,
    video_name: str,
    duration_seconds: float,
    mode: str = "default",
    template_path: Optional[Path] = None,
    force: bool = False,
) -> SummaryPromptResult:
    """index.md + 모드별 지시문을 합쳐 output_dir/summary_prompt.md를 만든다."""
    prompt_path = output_dir / SUMMARY_PROMPT_FILENAME

    if is_cached(prompt_path, force=force):
        return SummaryPromptResult(path=prompt_path, mode=mode, skipped=True)

    index_path = output_dir / INDEX_FILENAME
    if not index_path.exists():
        raise SummaryPromptError(
            f"{INDEX_FILENAME}을(를) 찾을 수 없습니다: {index_path}",
            hint="index.md 생성 단계가 먼저 성공해야 합니다.",
        )

    instruction = _load_instruction(mode, template_path)
    sections = _extract_index_sections(index_path.read_text(encoding="utf-8"))
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# {video_name} 요약 프롬프트",
        "",
        instruction,
        "",
        "## 영상 정보",
        f"- 파일명: {video_name}",
        f"- 길이: {_format_timestamp(duration_seconds)}",
        f"- 생성 시각: {generated_at}",
        "",
        "## 영상 인덱스 (타임스탬프 - 화면 - 스크립트)",
        "",
        sections,
        "",
    ]
    prompt_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    return SummaryPromptResult(path=prompt_path, mode=mode, skipped=False)

"""파이프라인 6단계(선택): 긴 영상 구간 분할.

`--split 10m`처럼 지정하면 전체 스크립트+프레임을 고정 길이 구간으로 나눠
`chunks/part_01_000m-010m.md` 형태의 파일로 저장한다. 각 파일은 그 구간의
스크립트, 프레임 이미지, 모드별 프롬프트 지시문을 모두 담고 있어 독립적으로
Claude에 붙여넣을 수 있다(긴 영상 전체를 한 번에 넣기엔 스크립트가 너무 길
때를 위함).

자르는 기준은 고정 시간이 아니라 세그먼트다: 각 STT 세그먼트는 자신의 시작
시각이 속한 구간에 통째로 배정되므로, 문장이 구간 경계에서 잘리는 일이 없다.
파일명의 "000m-010m"은 그 구간의 명목상 범위(반올림)일 뿐, 실제 내용은
세그먼트 단위로 깔끔하게 나뉜다.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from pathlib import Path
from typing import Optional

from prepreplay.errors import SplitError
from prepreplay.pipeline import is_cached
from prepreplay.steps.frames import FRAMES_METADATA_FILENAME
from prepreplay.steps.index import Section, build_sections
from prepreplay.steps.summary_prompt import load_instruction
from prepreplay.steps.transcribe import SEGMENTS_FILENAME

CHUNKS_DIRNAME = "chunks"
MANIFEST_FILENAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1

LONG_VIDEO_WARNING_THRESHOLD_SECONDS = 30 * 60

_SPLIT_SPEC_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(h|m|s)?$", re.IGNORECASE)
_UNIT_SECONDS = {"h": 3600.0, "m": 60.0, "s": 1.0}


@dataclasses.dataclass
class SplitResult:
    chunks_dir: Path
    chunk_count: int
    skipped: bool


def parse_split_seconds(spec: str) -> float:
    """'10m'(10분)/'1h'(1시간)/'600s'(600초)/'90'(90분, 단위 생략 시 분) 형태를 초로 변환한다."""
    match = _SPLIT_SPEC_RE.match(spec.strip())
    if not match:
        raise SplitError(
            f"--split 형식이 올바르지 않습니다: {spec!r}",
            hint="예: 10m(10분), 1h(1시간), 600s(600초). 단위를 생략하면 분으로 취급합니다.",
        )
    value = float(match.group(1))
    unit = (match.group(2) or "m").lower()
    seconds = value * _UNIT_SECONDS[unit]
    if seconds <= 0:
        raise SplitError(f"--split 값은 0보다 커야 합니다: {spec!r}")
    return seconds


def _format_timestamp(seconds: float) -> str:
    total = int(round(max(seconds, 0.0)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _render_section(section: Section, *, frames_prefix: str) -> list[str]:
    lines = [f"## {_format_timestamp(section.start)} - {_format_timestamp(section.end)}", ""]
    if section.frame_filename:
        lines.append(f"![화면]({frames_prefix}/{section.frame_filename})")
        lines.append("")
    text = section.text.strip() or "(음성 없음)"
    lines.append(f'스크립트: "{text}"')
    lines.append("")
    return lines


def split_into_chunks(
    output_dir: Path,
    *,
    video_name: str,
    duration_seconds: float,
    split_spec: str,
    mode: str = "default",
    template_path: Optional[Path] = None,
    force: bool = False,
) -> SplitResult:
    """segments.json/frames.json을 --split 간격으로 나눠 chunks/*.md를 생성한다."""
    chunks_dir = output_dir / CHUNKS_DIRNAME
    manifest_path = chunks_dir / MANIFEST_FILENAME

    if is_cached(manifest_path, force=force):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            chunk_count = int(manifest.get("chunk_count", 0))
        except (json.JSONDecodeError, ValueError):
            chunk_count = len(list(chunks_dir.glob("part_*.md")))
        return SplitResult(chunks_dir=chunks_dir, chunk_count=chunk_count, skipped=True)

    segments_path = output_dir / SEGMENTS_FILENAME
    frames_path = output_dir / FRAMES_METADATA_FILENAME
    if not segments_path.exists():
        raise SplitError(
            f"{SEGMENTS_FILENAME}을(를) 찾을 수 없습니다: {segments_path}",
            hint="STT 단계가 먼저 성공해야 합니다.",
        )
    if not frames_path.exists():
        raise SplitError(
            f"{FRAMES_METADATA_FILENAME}을(를) 찾을 수 없습니다: {frames_path}",
            hint="프레임 추출 단계가 먼저 성공해야 합니다.",
        )

    try:
        segments_data = json.loads(segments_path.read_text(encoding="utf-8"))
        frames_data = json.loads(frames_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SplitError(f"segments.json/frames.json을 파싱하지 못했습니다: {exc}") from exc

    segments = segments_data.get("segments", [])
    frames = frames_data.get("frames", [])

    split_seconds = parse_split_seconds(split_spec)
    instruction = load_instruction(mode, template_path)

    total_chunks = max(1, math.ceil(duration_seconds / split_seconds))

    chunks_dir.mkdir(parents=True, exist_ok=True)
    for old in chunks_dir.glob("part_*.md"):
        old.unlink()

    written_files: list[str] = []
    for i in range(total_chunks):
        chunk_start = i * split_seconds
        chunk_end = min((i + 1) * split_seconds, duration_seconds)

        chunk_segments = [s for s in segments if chunk_start <= s["start"] < chunk_end]
        chunk_frames = [f for f in frames if chunk_start <= f["timestamp"] < chunk_end]
        if not chunk_segments and not chunk_frames:
            continue

        # 각 구간을 그 구간만의 "미니 index.md"처럼 다시 섹션화한다 (같은 로직 재사용).
        local_sections = build_sections(
            chunk_segments, chunk_frames, chunk_end, range_start=chunk_start
        )

        start_mm = int(chunk_start // 60)
        end_mm = int(math.ceil(chunk_end / 60))
        filename = f"part_{i + 1:02d}_{start_mm:03d}m-{end_mm:03d}m.md"

        lines = [
            f"# {video_name} 요약 프롬프트 (구간 {i + 1}/{total_chunks}: {start_mm}분~{end_mm}분)",
            "",
            instruction,
            "",
            f"_이 파일은 전체 영상 중 {start_mm}분~{end_mm}분 구간만 담고 있습니다. "
            "다른 구간은 chunks/ 폴더의 나머지 파일을 참고하세요._",
            "",
            "## 영상 정보",
            f"- 파일명: {video_name}",
            f"- 전체 길이: {_format_timestamp(duration_seconds)}",
            f"- 이 구간: {_format_timestamp(chunk_start)} - {_format_timestamp(chunk_end)}",
            "",
            "## 이 구간의 스크립트+화면",
            "",
        ]
        for section in local_sections:
            lines.extend(_render_section(section, frames_prefix="../frames"))

        (chunks_dir / filename).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        written_files.append(filename)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "split_seconds": split_seconds,
        "chunk_count": len(written_files),
        "files": written_files,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return SplitResult(chunks_dir=chunks_dir, chunk_count=len(written_files), skipped=False)

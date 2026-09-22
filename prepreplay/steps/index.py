"""파이프라인 4단계: index.md 생성.

STT 단계의 `segments.json`과 프레임 추출 단계의 `frames.json`을 병합해,
"몇 분 몇 초 - 어떤 프레임 - 그 시점 스크립트"를 한눈에 볼 수 있는 `index.md`를
만든다(기획서 7절 형식). 각 프레임의 타임스탬프부터 다음 프레임 직전까지 등장한
스크립트를 그 프레임의 섹션으로 묶는다. 이미지는 실제 Markdown 이미지 문법으로
상대 경로(`frames/...`)를 참조해 Obsidian/VSCode 등에서 바로 미리보기가 된다.
"""

from __future__ import annotations

import bisect
import dataclasses
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from prepreplay.errors import IndexGenerationError
from prepreplay.pipeline import is_cached
from prepreplay.steps.frames import FRAMES_DIRNAME, FRAMES_METADATA_FILENAME
from prepreplay.steps.transcribe import SEGMENTS_FILENAME

INDEX_FILENAME = "index.md"

_FRAME_METHOD_LABELS = {
    "scene_detection": "장면 감지",
    "uniform_interval": "균등 간격",
}


@dataclasses.dataclass
class IndexResult:
    path: Path
    section_count: int
    skipped: bool


@dataclasses.dataclass
class _Section:
    start: float
    end: float
    frame_filename: Optional[str]
    text: str


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndexGenerationError(f"{path.name}을(를) 파싱하지 못했습니다: {path}", hint=str(exc)) from exc


def _format_timestamp(seconds: float) -> str:
    total = int(round(max(seconds, 0.0)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _build_sections(
    segments: list[dict], frames: list[dict], duration_seconds: float
) -> list[_Section]:
    """frames의 각 타임스탬프를 경계로 segments를 구간별로 묶는다."""
    frames = sorted(frames, key=lambda f: f["timestamp"])
    frame_timestamps = [f["timestamp"] for f in frames]

    # 세그먼트를 구간에 배정: bucket 인덱스 -1은 "첫 프레임 이전(인트로)"을 뜻한다.
    buckets: dict[int, list[str]] = defaultdict(list)
    for seg in segments:
        idx = bisect.bisect_right(frame_timestamps, seg["start"]) - 1
        buckets[idx].append(seg["text"])

    sections: list[_Section] = []

    if frame_timestamps and buckets.get(-1):
        sections.append(
            _Section(
                start=0.0,
                end=frame_timestamps[0],
                frame_filename=None,
                text=" ".join(buckets[-1]),
            )
        )

    for i, frame in enumerate(frames):
        start = frame_timestamps[i]
        end = frame_timestamps[i + 1] if i + 1 < len(frame_timestamps) else max(duration_seconds, start)
        sections.append(
            _Section(
                start=start,
                end=end,
                frame_filename=frame["filename"],
                text=" ".join(buckets.get(i, [])),
            )
        )

    if not frames and segments:
        sections.append(
            _Section(
                start=0.0,
                end=duration_seconds,
                frame_filename=None,
                text=" ".join(seg["text"] for seg in segments),
            )
        )

    return sections


def _render_markdown(
    *,
    video_name: str,
    duration_seconds: float,
    frame_count: int,
    frame_method: str,
    stt_model: str,
    stt_language: str,
    stt_device: str,
    sections: list[_Section],
) -> str:
    method_label = _FRAME_METHOD_LABELS.get(frame_method, frame_method)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# {video_name} 분석 인덱스",
        "",
        f"- 영상: {video_name}",
        f"- 길이: {_format_timestamp(duration_seconds)}",
        f"- 프레임: {frame_count}개 ({method_label})",
        f"- STT: {stt_model} 모델, 언어={stt_language}, device={stt_device}",
        f"- 생성 시각: {generated_at}",
        "",
        "---",
        "",
    ]

    if not sections:
        lines.append("_(추출된 구간이 없습니다.)_")
    else:
        for section in sections:
            lines.append(f"## {_format_timestamp(section.start)} - {_format_timestamp(section.end)}")
            lines.append("")
            if section.frame_filename:
                lines.append(f"![화면]({FRAMES_DIRNAME}/{section.frame_filename})")
                lines.append("")
            text = section.text.strip() or "(음성 없음)"
            lines.append(f'스크립트: "{text}"')
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_index(
    output_dir: Path,
    *,
    video_name: str,
    duration_seconds: float,
    force: bool = False,
) -> IndexResult:
    """segments.json/frames.json을 병합해 output_dir/index.md를 생성한다."""
    index_path = output_dir / INDEX_FILENAME

    if is_cached(index_path, force=force):
        return IndexResult(path=index_path, section_count=0, skipped=True)

    segments_path = output_dir / SEGMENTS_FILENAME
    frames_path = output_dir / FRAMES_METADATA_FILENAME

    if not segments_path.exists():
        raise IndexGenerationError(
            f"{SEGMENTS_FILENAME}을(를) 찾을 수 없습니다: {segments_path}",
            hint="STT 단계가 먼저 성공해야 합니다.",
        )
    if not frames_path.exists():
        raise IndexGenerationError(
            f"{FRAMES_METADATA_FILENAME}을(를) 찾을 수 없습니다: {frames_path}",
            hint="프레임 추출 단계가 먼저 성공해야 합니다.",
        )

    segments_data = _read_json(segments_path)
    frames_data = _read_json(frames_path)

    segments = segments_data.get("segments", [])
    frames = frames_data.get("frames", [])

    sections = _build_sections(segments, frames, duration_seconds)

    markdown = _render_markdown(
        video_name=video_name,
        duration_seconds=duration_seconds,
        frame_count=len(frames),
        frame_method=frames_data.get("method", "unknown"),
        stt_model=segments_data.get("model", "unknown"),
        stt_language=segments_data.get("language", "unknown"),
        stt_device=segments_data.get("device", "unknown"),
        sections=sections,
    )
    index_path.write_text(markdown, encoding="utf-8")

    return IndexResult(path=index_path, section_count=len(sections), skipped=False)

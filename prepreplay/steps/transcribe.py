"""파이프라인 2단계: Whisper STT.

오디오(`audio.wav`)를 텍스트로 변환해 `segments.json`(구조화 데이터, 이후 단계가
의존), `transcript.srt`(타임스탬프 포함), `transcript.txt`(순수 텍스트)로 저장한다.

디바이스 선택: GPU(CUDA)를 우선 시도하고, 모델 로드나 실제 추론 중 실패하면
CPU로 자동 전환한다(경고 출력). faster-whisper는 세그먼트를 지연 생성하므로
"모델 로드는 성공했지만 실제 연산에서 실패"하는 경우(PR #0에서 cuBLAS DLL 문제로
실측)까지 잡아내기 위해, 세그먼트를 순회하는 동안 발생하는 예외도 GPU 실패로
간주해 CPU로 재시도한다.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from prepreplay.diagnostics import diagnose_failure
from prepreplay.errors import DependencyError, TranscriptionError
from prepreplay.pipeline import is_cached
from prepreplay.steps.diarize import DiarizationSegment
from prepreplay.utils.cuda_env import ensure_cuda_libs_discoverable

SEGMENTS_FILENAME = "segments.json"
SRT_FILENAME = "transcript.srt"
TXT_FILENAME = "transcript.txt"

SEGMENTS_SCHEMA_VERSION = 1


@dataclasses.dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str


@dataclasses.dataclass
class TranscriptionResult:
    segments_path: Path
    srt_path: Path
    txt_path: Path
    language: str
    device: str
    skipped: bool


def _load_whisper_model_class():
    """faster_whisper.WhisperModel을 지연 import한다.

    - CUDA DLL 경로 등록(ensure_cuda_libs_discoverable)을 import 직전에 수행한다.
    - 캐시 히트로 아예 STT를 돌릴 필요가 없는 경우 이 무거운 import 자체를 건너뛴다.
    """
    ensure_cuda_libs_discoverable()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - 정상 설치 환경에서는 발생하지 않음
        raise DependencyError(
            "faster-whisper가 설치되어 있지 않습니다.", hint="pip install faster-whisper"
        ) from exc
    return WhisperModel


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = max(int(round(seconds * 1000)), 0)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _write_srt(segments: list[Segment], path: Path) -> None:
    lines: list[str] = []
    for seg in segments:
        lines.append(str(seg.id + 1))
        lines.append(f"{_format_srt_timestamp(seg.start)} --> {_format_srt_timestamp(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_txt(segments: list[Segment], path: Path) -> None:
    path.write_text("\n".join(seg.text for seg in segments), encoding="utf-8")


def _write_segments_json(
    segments: list[Segment],
    path: Path,
    *,
    language: str,
    duration: float,
    model_size: str,
    device: str,
) -> None:
    data: dict[str, Any] = {
        "schema_version": SEGMENTS_SCHEMA_VERSION,
        "language": language,
        "duration": duration,
        "model": model_size,
        "device": device,
        "segments": [dataclasses.asdict(seg) for seg in segments],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_transcription(
    model: Any,
    audio_path: Path,
    *,
    language: str,
    duration: float,
    console: Optional[Console],
) -> tuple[list[Segment], Any]:
    """모델로 오디오를 순회하며 세그먼트를 모으고, 진행률을 표시한다."""
    lang_option = None if language == "auto" else language
    segments_iter, info = model.transcribe(str(audio_path), language=lang_option)

    columns = [
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    ]
    collected: list[Segment] = []
    with Progress(*columns, console=console, transient=True) as progress:
        task = progress.add_task("STT 진행 중", total=max(duration, 0.01))
        for i, seg in enumerate(segments_iter):
            collected.append(Segment(id=i, start=seg.start, end=seg.end, text=seg.text.strip()))
            progress.update(task, completed=min(seg.end, duration))
    return collected, info


def _dominant_speaker(
    segment: Segment, diarization_segments: list[DiarizationSegment]
) -> Optional[str]:
    """`segment`와 시간이 가장 많이 겹치는 화자 라벨을 반환한다(겹침이 전혀 없으면 None)."""
    best_speaker: Optional[str] = None
    best_overlap = 0.0
    for d in diarization_segments:
        overlap = min(segment.end, d.end) - max(segment.start, d.start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = d.speaker
    return best_speaker


def _apply_speaker_labels(
    segments: list[Segment], diarization_segments: list[DiarizationSegment]
) -> list[Segment]:
    """각 세그먼트 텍스트 앞에 `[화자N]` 라벨을 붙인 새 세그먼트 목록을 반환한다."""
    labeled: list[Segment] = []
    for seg in segments:
        speaker = _dominant_speaker(seg, diarization_segments)
        text = f"[{speaker}] {seg.text}" if speaker else seg.text
        labeled.append(dataclasses.replace(seg, text=text))
    return labeled


def transcribe_audio(
    audio_path: Path,
    output_dir: Path,
    *,
    model_size: str = "large-v3",
    language: str = "ko",
    duration_hint: float = 0.0,
    diarization_segments: Optional[list[DiarizationSegment]] = None,
    force: bool = False,
    console: Optional[Console] = None,
) -> TranscriptionResult:
    """오디오를 STT로 변환해 segments.json/transcript.srt/transcript.txt를 생성한다."""
    segments_path = output_dir / SEGMENTS_FILENAME
    srt_path = output_dir / SRT_FILENAME
    txt_path = output_dir / TXT_FILENAME

    if is_cached(segments_path, force=force):
        return TranscriptionResult(
            segments_path=segments_path,
            srt_path=srt_path,
            txt_path=txt_path,
            language=language,
            device="cached",
            skipped=True,
        )

    if not audio_path.exists():
        raise TranscriptionError(
            f"오디오 파일을 찾을 수 없습니다: {audio_path}",
            hint="오디오 추출 단계가 먼저 성공해야 합니다.",
        )

    WhisperModel = _load_whisper_model_class()

    device_used = "cuda"
    try:
        model = WhisperModel(model_size, device="cuda", compute_type="float16")
        segments, info = _run_transcription(
            model, audio_path, language=language, duration=duration_hint, console=console
        )
    except Exception as exc:
        if console:
            console.print(f"[yellow]⚠ GPU 처리에 실패해 CPU로 전환합니다: {exc}[/yellow]")
        device_used = "cpu"
        try:
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            segments, info = _run_transcription(
                model, audio_path, language=language, duration=duration_hint, console=console
            )
        except Exception as cpu_exc:
            hint = diagnose_failure(str(cpu_exc)) or str(cpu_exc)
            raise TranscriptionError(
                f"STT에 실패했습니다: {audio_path}", hint=hint
            ) from cpu_exc

    if not segments:
        raise TranscriptionError(
            f"음성을 인식하지 못했습니다 (세그먼트 0개): {audio_path}",
            hint="오디오에 음성이 없거나 너무 짧을 수 있습니다.",
        )

    resolved_language = getattr(info, "language", None) or language
    resolved_duration = getattr(info, "duration", None) or duration_hint

    if diarization_segments:
        segments = _apply_speaker_labels(segments, diarization_segments)

    _write_segments_json(
        segments,
        segments_path,
        language=resolved_language,
        duration=resolved_duration,
        model_size=model_size,
        device=device_used,
    )
    _write_srt(segments, srt_path)
    _write_txt(segments, txt_path)

    return TranscriptionResult(
        segments_path=segments_path,
        srt_path=srt_path,
        txt_path=txt_path,
        language=resolved_language,
        device=device_used,
        skipped=False,
    )

"""파이프라인 2-b단계(선택): 화자 분리.

pyannote.audio로 오디오에서 "누가 몇 초~몇 초에 말했는지"를 감지해 `diarization.json`으로
저장한다. `--diarize`를 지정했을 때만 실행되며, STT 단계(`transcribe.py`)가 이 결과를
받아 각 세그먼트 텍스트 앞에 `[화자1]`/`[화자2]` 라벨을 붙인다.

pyannote의 화자 분리 모델은 HuggingFace의 게이트(gated) 모델이라 쓰려면:
1. https://huggingface.co/pyannote/speaker-diarization-3.1 에서 모델 사용 약관에 동의
2. https://huggingface.co/settings/tokens 에서 토큰 발급
3. `HF_TOKEN` 환경변수로 넘기거나 `--hf-token` 옵션으로 직접 지정
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

from prepreplay.diagnostics import diagnose_failure
from prepreplay.errors import DependencyError, DiarizationError
from prepreplay.pipeline import is_cached

DIARIZATION_FILENAME = "diarization.json"
DIARIZATION_SCHEMA_VERSION = 1
DEFAULT_MODEL = "pyannote/speaker-diarization-3.1"

_INSTALL_HINT = (
    'pyannote.audio가 설치되어 있지 않습니다. pip install -e ".[diarization]"으로 설치하세요.'
)
_TOKEN_HINT = (
    "https://huggingface.co/pyannote/speaker-diarization-3.1 에서 모델 사용 약관에 동의한 뒤, "
    "https://huggingface.co/settings/tokens 에서 토큰을 발급받아 HF_TOKEN 환경변수로 지정하거나 "
    "--hf-token 옵션으로 넘기세요."
)


@dataclasses.dataclass
class DiarizationSegment:
    start: float
    end: float
    speaker: str


@dataclasses.dataclass
class DiarizationResult:
    path: Path
    segments: list[DiarizationSegment]
    skipped: bool


def _load_pipeline_class() -> Any:
    """pyannote.audio.Pipeline을 지연 import한다 (무거운 torch 의존성이라 캐시 히트 시 스킵)."""
    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:  # pragma: no cover - 정상 설치 환경에서는 발생하지 않음
        raise DependencyError(_INSTALL_HINT) from exc
    return Pipeline


def _resolve_hf_token(explicit_token: Optional[str]) -> Optional[str]:
    return explicit_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")


def _read_diarization_json(path: Path) -> list[DiarizationSegment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [DiarizationSegment(**s) for s in data["segments"]]


def diarize_audio(
    audio_path: Path,
    output_dir: Path,
    *,
    model_name: str = DEFAULT_MODEL,
    hf_token: Optional[str] = None,
    force: bool = False,
    console: Optional[Console] = None,
) -> DiarizationResult:
    """오디오에서 화자 구간을 감지해 `{output_dir}/diarization.json`으로 저장한다."""
    diarization_path = output_dir / DIARIZATION_FILENAME

    if is_cached(diarization_path, force=force):
        return DiarizationResult(
            path=diarization_path,
            segments=_read_diarization_json(diarization_path),
            skipped=True,
        )

    if not audio_path.exists():
        raise DiarizationError(
            f"오디오 파일을 찾을 수 없습니다: {audio_path}",
            hint="오디오 추출 단계가 먼저 성공해야 합니다.",
        )

    token = _resolve_hf_token(hf_token)
    if not token:
        raise DiarizationError(
            "화자 분리를 사용하려면 HuggingFace 토큰이 필요합니다.", hint=_TOKEN_HINT
        )

    Pipeline = _load_pipeline_class()

    try:
        pipeline = Pipeline.from_pretrained(model_name, use_auth_token=token)
    except Exception as exc:
        hint = diagnose_failure(str(exc)) or str(exc)
        raise DiarizationError(
            f"화자 분리 모델을 불러오지 못했습니다: {model_name}", hint=hint
        ) from exc

    if console:
        console.print("[dim]화자 분리 진행 중 (영상 길이에 따라 시간이 걸릴 수 있습니다)...[/dim]")

    try:
        diarization = pipeline(str(audio_path))
    except Exception as exc:
        hint = diagnose_failure(str(exc)) or str(exc)
        raise DiarizationError(f"화자 분리에 실패했습니다: {audio_path}", hint=hint) from exc

    speaker_labels: dict[str, str] = {}
    segments: list[DiarizationSegment] = []
    for turn, _track, speaker in diarization.itertracks(yield_label=True):
        label = speaker_labels.setdefault(speaker, f"화자{len(speaker_labels) + 1}")
        segments.append(DiarizationSegment(start=turn.start, end=turn.end, speaker=label))

    if not segments:
        raise DiarizationError(
            f"화자를 하나도 감지하지 못했습니다: {audio_path}",
            hint="오디오에 음성이 없거나 너무 짧을 수 있습니다.",
        )

    data = {
        "schema_version": DIARIZATION_SCHEMA_VERSION,
        "model": model_name,
        "segments": [dataclasses.asdict(s) for s in segments],
    }
    diarization_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return DiarizationResult(path=diarization_path, segments=segments, skipped=False)

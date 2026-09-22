"""prepreplay.steps.transcribe 테스트.

실제 Whisper 모델(수백MB~수GB 다운로드, GPU/CPU 연산)에 의존하지 않도록
WhisperModel 자체를 가짜(fake)로 대체해 결정론적으로 검증한다. 실제 모델을 이용한
end-to-end 동작은 PR #4 본문에 기록된 수동 검증 결과를 참고.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from prepreplay.errors import TranscriptionError
from prepreplay.steps.diarize import DiarizationSegment
from prepreplay.steps.transcribe import (
    SEGMENTS_FILENAME,
    SRT_FILENAME,
    TXT_FILENAME,
    _format_srt_timestamp,
    transcribe_audio,
)


class _FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class _FakeInfo:
    def __init__(self, language: str = "ko", duration: float = 3.0) -> None:
        self.language = language
        self.duration = duration


class _FakeWhisperModel:
    """실제 faster_whisper.WhisperModel을 대신하는 테스트용 더블."""

    fail_on_device: Optional[str] = None  # 이 device로 생성되면 즉시 예외를 던짐
    fail_during_iteration_on_device: Optional[str] = None  # 순회 도중 예외
    segments_to_return: list[_FakeSegment] = [
        _FakeSegment(0.0, 1.5, " 안녕하세요 "),
        _FakeSegment(1.5, 3.0, " 테스트입니다 "),
    ]

    def __init__(self, model_size: str, device: str, compute_type: str) -> None:
        if device == self.fail_on_device:
            raise RuntimeError(f"fake failure constructing model on {device}")
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, audio_path: str, language: Optional[str] = None):
        info = _FakeInfo(language=language or "ko")

        def _gen():
            for seg in self.segments_to_return:
                if self.device == self.fail_during_iteration_on_device:
                    raise RuntimeError(f"fake failure during iteration on {self.device}")
                yield seg

        return _gen(), info


@pytest.fixture(autouse=True)
def _reset_fake_model():
    _FakeWhisperModel.fail_on_device = None
    _FakeWhisperModel.fail_during_iteration_on_device = None
    _FakeWhisperModel.segments_to_return = [
        _FakeSegment(0.0, 1.5, " 안녕하세요 "),
        _FakeSegment(1.5, 3.0, " 테스트입니다 "),
    ]
    yield


def _patch_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "prepreplay.steps.transcribe._load_whisper_model_class",
        lambda: _FakeWhisperModel,
    )


def test_format_srt_timestamp() -> None:
    assert _format_srt_timestamp(0.0) == "00:00:00,000"
    assert _format_srt_timestamp(1.5) == "00:00:01,500"
    assert _format_srt_timestamp(3661.234) == "01:01:01,234"


def test_transcribe_writes_srt_txt_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_loader(monkeypatch)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = transcribe_audio(
        audio_path, output_dir, model_size="tiny", language="ko", duration_hint=3.0, force=False
    )

    assert result.skipped is False
    assert result.device == "cuda"  # 기본 fake는 실패 없이 cuda로 성공
    assert result.language == "ko"

    assert (output_dir / SEGMENTS_FILENAME).is_file()
    assert (output_dir / SRT_FILENAME).is_file()
    assert (output_dir / TXT_FILENAME).is_file()

    data = json.loads((output_dir / SEGMENTS_FILENAME).read_text(encoding="utf-8"))
    assert data["language"] == "ko"
    assert data["device"] == "cuda"
    assert data["model"] == "tiny"
    assert len(data["segments"]) == 2
    assert data["segments"][0] == {"id": 0, "start": 0.0, "end": 1.5, "text": "안녕하세요"}

    srt_text = (output_dir / SRT_FILENAME).read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,500" in srt_text
    assert "안녕하세요" in srt_text

    txt_text = (output_dir / TXT_FILENAME).read_text(encoding="utf-8")
    assert txt_text == "안녕하세요\n테스트입니다"


def test_transcribe_skips_when_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / SEGMENTS_FILENAME).write_text("{}", encoding="utf-8")

    def _fail_if_called():
        raise AssertionError("캐시 히트인데 모델 로더가 호출되면 안 됨")

    monkeypatch.setattr("prepreplay.steps.transcribe._load_whisper_model_class", _fail_if_called)

    result = transcribe_audio(
        tmp_path / "audio.wav", output_dir, model_size="tiny", language="ko", force=False
    )
    assert result.skipped is True


def test_transcribe_raises_when_audio_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(TranscriptionError):
        transcribe_audio(tmp_path / "does_not_exist.wav", output_dir, force=False)


def test_transcribe_falls_back_to_cpu_when_gpu_construction_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    _FakeWhisperModel.fail_on_device = "cuda"

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = transcribe_audio(audio_path, output_dir, duration_hint=3.0, force=False)

    assert result.device == "cpu"
    data = json.loads((output_dir / SEGMENTS_FILENAME).read_text(encoding="utf-8"))
    assert data["device"] == "cpu"


def test_transcribe_falls_back_to_cpu_when_gpu_iteration_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #0에서 실측한 실패 모드: 모델 로드는 성공하지만 실제 연산(세그먼트 순회)에서 실패."""
    _patch_loader(monkeypatch)
    _FakeWhisperModel.fail_during_iteration_on_device = "cuda"

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = transcribe_audio(audio_path, output_dir, duration_hint=3.0, force=False)

    assert result.device == "cpu"


def test_transcribe_raises_when_both_devices_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    _FakeWhisperModel.fail_on_device = "cuda"

    class _AlwaysFailingModel(_FakeWhisperModel):
        def __init__(self, model_size: str, device: str, compute_type: str) -> None:
            raise RuntimeError(f"fake failure on {device}")

    monkeypatch.setattr(
        "prepreplay.steps.transcribe._load_whisper_model_class", lambda: _AlwaysFailingModel
    )

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(TranscriptionError) as exc_info:
        transcribe_audio(audio_path, output_dir, duration_hint=3.0, force=False)
    assert exc_info.value.stage == "STT"
    assert not (output_dir / SEGMENTS_FILENAME).exists()


def test_transcribe_applies_speaker_labels_when_diarization_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    diarization_segments = [
        DiarizationSegment(start=0.0, end=1.5, speaker="화자1"),
        DiarizationSegment(start=1.5, end=3.0, speaker="화자2"),
    ]

    result = transcribe_audio(
        audio_path,
        output_dir,
        duration_hint=3.0,
        diarization_segments=diarization_segments,
        force=False,
    )

    assert result.skipped is False
    data = json.loads((output_dir / SEGMENTS_FILENAME).read_text(encoding="utf-8"))
    assert data["segments"][0]["text"] == "[화자1] 안녕하세요"
    assert data["segments"][1]["text"] == "[화자2] 테스트입니다"

    txt_text = (output_dir / TXT_FILENAME).read_text(encoding="utf-8")
    assert txt_text == "[화자1] 안녕하세요\n[화자2] 테스트입니다"


def test_transcribe_without_diarization_segments_leaves_text_unlabeled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = transcribe_audio(audio_path, output_dir, duration_hint=3.0, force=False)

    assert result.skipped is False
    data = json.loads((output_dir / SEGMENTS_FILENAME).read_text(encoding="utf-8"))
    assert data["segments"][0]["text"] == "안녕하세요"


def test_transcribe_raises_when_zero_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    _FakeWhisperModel.segments_to_return = []

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(TranscriptionError) as exc_info:
        transcribe_audio(audio_path, output_dir, duration_hint=3.0, force=False)
    assert "세그먼트 0개" in exc_info.value.message
    assert not (output_dir / SEGMENTS_FILENAME).exists()

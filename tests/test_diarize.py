"""prepreplay.steps.diarize 테스트.

실제 pyannote.audio 모델(게이트된 HuggingFace 모델, GPU/CPU 연산)에 의존하지 않도록
Pipeline 자체를 가짜(fake)로 대체해 결정론적으로 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prepreplay.errors import DiarizationError
from prepreplay.steps.diarize import DIARIZATION_FILENAME, diarize_audio


class _FakeTurn:
    def __init__(self, start: float, end: float) -> None:
        self.start = start
        self.end = end


class _FakeAnnotation:
    def __init__(self, tracks: list[tuple]) -> None:
        self._tracks = tracks

    def itertracks(self, yield_label: bool = False):
        yield from self._tracks


class _FakePipeline:
    tracks_to_return: list[tuple] = [
        (_FakeTurn(0.0, 1.5), "_", "SPEAKER_00"),
        (_FakeTurn(1.5, 3.0), "_", "SPEAKER_01"),
    ]
    fail_on_load = False
    fail_on_call = False

    @classmethod
    def from_pretrained(cls, model_name: str, use_auth_token=None) -> "_FakePipeline":
        if cls.fail_on_load:
            raise RuntimeError("fake model load failure")
        return cls()

    def __call__(self, audio_path: str) -> _FakeAnnotation:
        if self.fail_on_call:
            raise RuntimeError("fake diarization failure")
        return _FakeAnnotation(self.tracks_to_return)


@pytest.fixture(autouse=True)
def _reset_fake_pipeline():
    _FakePipeline.tracks_to_return = [
        (_FakeTurn(0.0, 1.5), "_", "SPEAKER_00"),
        (_FakeTurn(1.5, 3.0), "_", "SPEAKER_01"),
    ]
    _FakePipeline.fail_on_load = False
    _FakePipeline.fail_on_call = False
    yield


def _patch_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("prepreplay.steps.diarize._load_pipeline_class", lambda: _FakePipeline)


def test_diarize_writes_json_with_speaker_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = diarize_audio(audio_path, output_dir, hf_token="fake-token", force=False)

    assert result.skipped is False
    assert (output_dir / DIARIZATION_FILENAME).is_file()
    assert len(result.segments) == 2
    assert result.segments[0].speaker == "화자1"
    assert result.segments[1].speaker == "화자2"

    data = json.loads((output_dir / DIARIZATION_FILENAME).read_text(encoding="utf-8"))
    assert data["segments"][0] == {"start": 0.0, "end": 1.5, "speaker": "화자1"}


def test_diarize_skips_when_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / DIARIZATION_FILENAME).write_text(
        json.dumps({"schema_version": 1, "model": "x", "segments": []}), encoding="utf-8"
    )

    def _fail_if_called():
        raise AssertionError("캐시 히트인데 파이프라인 로더가 호출되면 안 됨")

    monkeypatch.setattr("prepreplay.steps.diarize._load_pipeline_class", _fail_if_called)

    result = diarize_audio(tmp_path / "audio.wav", output_dir, hf_token="fake-token", force=False)
    assert result.skipped is True


def test_diarize_raises_when_audio_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(DiarizationError):
        diarize_audio(
            tmp_path / "does_not_exist.wav", output_dir, hf_token="fake-token", force=False
        )


def test_diarize_raises_when_token_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(DiarizationError) as exc_info:
        diarize_audio(audio_path, output_dir, hf_token=None, force=False)
    assert "토큰" in exc_info.value.message
    assert exc_info.value.hint is not None


def test_diarize_uses_env_var_token_when_not_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "env-token")
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = diarize_audio(audio_path, output_dir, hf_token=None, force=False)
    assert result.skipped is False


def test_diarize_raises_when_model_load_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    _FakePipeline.fail_on_load = True
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(DiarizationError):
        diarize_audio(audio_path, output_dir, hf_token="fake-token", force=False)


def test_diarize_raises_when_zero_speakers_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_loader(monkeypatch)
    _FakePipeline.tracks_to_return = []
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-wav-bytes")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(DiarizationError) as exc_info:
        diarize_audio(audio_path, output_dir, hf_token="fake-token", force=False)
    assert "화자를 하나도 감지하지" in exc_info.value.message
    assert not (output_dir / DIARIZATION_FILENAME).exists()

"""pytest 공용 fixture.

실제 사용자 영상은 저장소에 절대 포함하지 않는다. 대신 ffmpeg의 lavfi 입력으로
그때그때 짧은 합성 샘플 영상을 만들어 테스트에 쓴다. ffmpeg가 없는 환경에서는
관련 테스트를 스킵한다.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

requires_ffmpeg = pytest.mark.skipif(
    not FFMPEG_AVAILABLE, reason="ffmpeg가 설치되어 있지 않습니다."
)


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """3초짜리 합성 영상(사인파 오디오 포함)을 생성해 경로를 반환한다."""
    out = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=3",
            "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(out),
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return out


@pytest.fixture
def silent_video(tmp_path: Path) -> Path:
    """오디오 트랙이 없는 2초짜리 합성 영상을 생성해 경로를 반환한다."""
    out = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return out


@pytest.fixture
def scene_change_video(tmp_path: Path) -> Path:
    """색이 뚜렷하게 바뀌는 3구간(각 2초, 총 6초) 합성 영상 - 장면 감지 테스트용.

    빨강 -> 파랑 -> 초록으로 전환되는 지점(약 2초, 4초)에서 장면 전환이 감지되어야
    한다. testsrc처럼 연속적으로 변하는 패턴은 장면 감지가 잘 걸리지 않는다
    (PR #0에서 실측 확인).
    """
    out = tmp_path / "scenes.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
            "-f", "lavfi", "-i", "color=c=green:s=320x240:d=2",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[outv]",
            "-map", "[outv]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25",
            str(out),
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return out


@pytest.fixture
def fake_whisper_model(monkeypatch: pytest.MonkeyPatch):
    """실제 Whisper 모델 다운로드/추론 없이 STT 관련 테스트를 빠르고 결정론적으로 만든다.

    prepreplay.steps.transcribe._load_whisper_model_class를 가짜 모델 클래스로
    교체한다. CLI/파이프라인 결합 테스트에서 사용.
    """

    class _FakeSegment:
        def __init__(self, start: float, end: float, text: str) -> None:
            self.start = start
            self.end = end
            self.text = text

    class _FakeInfo:
        def __init__(self, language: str = "ko") -> None:
            self.language = language
            self.duration = 3.0

    class _FakeModel:
        def __init__(self, model_size: str, device: str, compute_type: str) -> None:
            pass

        def transcribe(self, audio_path: str, language=None):
            segments = [
                _FakeSegment(0.0, 1.5, " 안녕하세요 "),
                _FakeSegment(1.5, 3.0, " 테스트입니다 "),
            ]
            return iter(segments), _FakeInfo(language=language or "ko")

    monkeypatch.setattr(
        "prepreplay.steps.transcribe._load_whisper_model_class", lambda: _FakeModel
    )
    return _FakeModel


@pytest.fixture
def fake_diarization_pipeline(monkeypatch: pytest.MonkeyPatch):
    """실제 pyannote.audio 모델 다운로드/추론 없이 화자 분리 관련 테스트를 빠르고
    결정론적으로 만든다. `fake_whisper_model`의 세그먼트 경계(0.0~1.5초 / 1.5~3.0초)와
    일치하는 화자 2명을 만들어, "안녕하세요"는 화자1, "테스트입니다"는 화자2로
    라벨링되는지까지 검증할 수 있게 한다.

    prepreplay.steps.diarize._load_pipeline_class를 가짜 파이프라인 클래스로 교체한다.
    """

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
        @classmethod
        def from_pretrained(cls, model_name: str, use_auth_token=None) -> "_FakePipeline":
            return cls()

        def __call__(self, audio_path: str) -> _FakeAnnotation:
            return _FakeAnnotation(
                [
                    (_FakeTurn(0.0, 1.5), "_", "SPEAKER_00"),
                    (_FakeTurn(1.5, 3.0), "_", "SPEAKER_01"),
                ]
            )

    monkeypatch.setattr(
        "prepreplay.steps.diarize._load_pipeline_class", lambda: _FakePipeline
    )
    return _FakePipeline

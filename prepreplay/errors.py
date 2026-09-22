"""PrepReplay 커스텀 예외 계층.

각 예외는 어느 파이프라인 단계에서 실패했는지(`stage`)와, 가능하면 사용자가
바로 취할 수 있는 조치(`hint`)를 함께 담는다. CLI는 이 정보를 이용해
"어느 단계에서 왜 실패했는지"를 rich로 사람이 읽을 수 있게 출력한다.
"""

from __future__ import annotations

from typing import Optional


class PrepReplayError(Exception):
    """모든 PrepReplay 도메인 예외의 기반 클래스."""

    stage: str = "알 수 없음"

    def __init__(self, message: str, *, hint: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ConfigError(PrepReplayError):
    """config.yaml 파싱/병합 오류."""

    stage = "설정 로드"


class DependencyError(PrepReplayError):
    """ffmpeg/ffprobe 등 외부 도구를 찾지 못했을 때."""

    stage = "환경 확인"


class InputValidationError(PrepReplayError):
    """입력 영상 파일/옵션이 유효하지 않을 때 (확장자 미지원, 잘못된 모드 등)."""

    stage = "입력 검증"


class ProbeError(PrepReplayError):
    """ffprobe로 영상 메타데이터를 읽지 못했을 때."""

    stage = "메타데이터 분석"


class AudioExtractionError(PrepReplayError):
    """오디오 트랙 추출(ffmpeg) 실패, 또는 오디오 트랙이 아예 없을 때."""

    stage = "오디오 추출"


class TranscriptionError(PrepReplayError):
    """Whisper STT 실패, 또는 인식된 세그먼트가 0개일 때."""

    stage = "STT"


class FrameExtractionError(PrepReplayError):
    """장면 감지/프레임 추출(ffmpeg) 실패."""

    stage = "프레임 추출"


class IndexGenerationError(PrepReplayError):
    """segments.json/frames.json을 병합해 index.md를 만드는 과정의 실패."""

    stage = "인덱스 생성"

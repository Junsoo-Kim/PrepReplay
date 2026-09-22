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

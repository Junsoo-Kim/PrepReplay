"""ffmpeg / ffprobe 실행 래퍼.

이 단계(PR #2)에서는 실행 파일 탐지와 ffprobe 기반 메타데이터 조회만 다룬다.
실제 오디오 추출(PR #3), 장면 감지/프레임 추출(PR #5)은 이후 PR에서 이 모듈을 확장한다.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from prepreplay.diagnostics import diagnose_failure
from prepreplay.errors import DependencyError, ProbeError

_FFMPEG_INSTALL_HINT = (
    "ffmpeg를 설치하세요 (ffprobe는 ffmpeg 패키지에 포함됩니다). "
    "Windows: winget install Gyan.FFmpeg / macOS: brew install ffmpeg"
)


def find_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def find_ffprobe() -> Optional[str]:
    return shutil.which("ffprobe")


def get_version(executable: str) -> Optional[str]:
    """`<executable> -version`의 첫 줄(버전 문자열)을 반환한다. 실패하면 None."""
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not result.stdout:
        return None
    return result.stdout.splitlines()[0]


def require_ffmpeg_tools() -> None:
    """ffmpeg/ffprobe가 모두 있는지 확인하고, 없으면 DependencyError를 던진다."""
    missing = [name for name, found in (("ffmpeg", find_ffmpeg()), ("ffprobe", find_ffprobe())) if not found]
    if missing:
        raise DependencyError(
            f"다음 도구를 찾을 수 없습니다: {', '.join(missing)}",
            hint=_FFMPEG_INSTALL_HINT,
        )


@dataclasses.dataclass
class VideoInfo:
    path: Path
    duration_seconds: float
    width: Optional[int]
    height: Optional[int]
    format_name: str
    video_codec: Optional[str]
    audio_codec: Optional[str]
    has_audio: bool
    size_bytes: int

    @property
    def duration_hms(self) -> str:
        total = int(round(self.duration_seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


def probe_video(path: Path) -> VideoInfo:
    """ffprobe로 영상 메타데이터를 읽어 VideoInfo로 반환한다."""
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise DependencyError("ffprobe를 찾을 수 없습니다.", hint=_FFMPEG_INSTALL_HINT)

    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe 실행이 30초를 초과했습니다: {path}") from exc

    if result.returncode != 0:
        stderr_text = result.stderr.strip() if result.stderr else ""
        stderr_tail = stderr_text.splitlines()[-1] if stderr_text else None
        hint = diagnose_failure(stderr_text) or stderr_tail
        raise ProbeError(f"ffprobe가 영상을 읽지 못했습니다: {path}", hint=hint)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe 출력을 파싱하지 못했습니다: {path}") from exc

    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video_stream is None:
        raise ProbeError(
            f"영상 스트림을 찾을 수 없습니다: {path}",
            hint="파일이 손상되었거나 영상 파일이 아닐 수 있습니다.",
        )

    duration_raw = fmt.get("duration") or video_stream.get("duration")
    if duration_raw is None:
        raise ProbeError(f"영상 길이를 읽을 수 없습니다: {path}")

    return VideoInfo(
        path=path,
        duration_seconds=float(duration_raw),
        width=video_stream.get("width"),
        height=video_stream.get("height"),
        format_name=fmt.get("format_name", "unknown"),
        video_codec=video_stream.get("codec_name"),
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        has_audio=audio_stream is not None,
        size_bytes=int(fmt.get("size", 0)) if fmt.get("size") else path.stat().st_size,
    )

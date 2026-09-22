"""파이프라인 1단계: 오디오 추출.

영상에서 오디오 트랙을 Whisper STT에 적합한 포맷(16kHz mono 16-bit PCM WAV)으로
뽑아낸다. 산출물(`audio.wav`)이 이미 있으면 스킵하고, `--force`로 재생성한다
(이 캐시 규칙은 PR #4의 STT, PR #5의 프레임 추출에서도 동일하게 적용된다).
"""

from __future__ import annotations

import dataclasses
import subprocess
import threading
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from prepreplay.diagnostics import diagnose_failure
from prepreplay.errors import AudioExtractionError, DependencyError
from prepreplay.pipeline import is_cached
from prepreplay.utils.ffmpeg import VideoInfo, find_ffmpeg

AUDIO_FILENAME = "audio.wav"

_FFMPEG_INSTALL_HINT = (
    "ffmpeg를 설치하세요. Windows: winget install Gyan.FFmpeg / macOS: brew install ffmpeg"
)


@dataclasses.dataclass
class AudioExtractionResult:
    path: Path
    skipped: bool


def _parse_ffmpeg_time(value: str) -> Optional[float]:
    """ffmpeg progress의 'HH:MM:SS.ffffff' 형태 시간 문자열을 초 단위 float로 변환."""
    try:
        hours, minutes, seconds = value.strip().split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, AttributeError):
        return None


def _drain_lines(pipe, sink: list[str]) -> None:
    """서브프로세스 파이프를 계속 읽어 sink에 쌓는다 (파이프 버퍼가 차서 멈추는 것 방지)."""
    for line in pipe:
        sink.append(line)
    pipe.close()


def extract_audio(
    video: Path,
    output_dir: Path,
    video_info: VideoInfo,
    *,
    force: bool = False,
    console: Optional[Console] = None,
) -> AudioExtractionResult:
    """영상에서 오디오를 추출해 `{output_dir}/audio.wav`로 저장한다."""
    audio_path = output_dir / AUDIO_FILENAME

    if is_cached(audio_path, force=force):
        return AudioExtractionResult(path=audio_path, skipped=True)

    if not video_info.has_audio:
        raise AudioExtractionError(
            f"오디오 트랙이 없어 스크립트를 추출할 수 없습니다: {video}",
            hint="이 영상에는 오디오가 없습니다. STT 기반 분석 대상이 아닙니다.",
        )

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise DependencyError("ffmpeg를 찾을 수 없습니다.", hint=_FFMPEG_INSTALL_HINT)

    cmd = [
        ffmpeg, "-y",
        "-i", str(video),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        "-progress", "pipe:1",
        "-nostats",
        str(audio_path),
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stderr_lines: list[str] = []
    stderr_thread = threading.Thread(
        target=_drain_lines, args=(process.stderr, stderr_lines), daemon=True
    )
    stderr_thread.start()

    duration = max(video_info.duration_seconds, 0.01)
    columns = [
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    ]
    try:
        with Progress(*columns, console=console, transient=True) as progress:
            task = progress.add_task("오디오 추출 중", total=duration)
            assert process.stdout is not None
            for line in process.stdout:
                line = line.strip()
                if line.startswith("out_time="):
                    current = _parse_ffmpeg_time(line.split("=", 1)[1])
                    if current is not None:
                        progress.update(task, completed=min(current, duration))
                elif line == "progress=end":
                    progress.update(task, completed=duration)
    finally:
        stderr_thread.join(timeout=5)
        try:
            returncode = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            raise AudioExtractionError(f"ffmpeg 프로세스가 응답하지 않아 종료했습니다: {video}")

    if returncode != 0 or not audio_path.exists():
        if audio_path.exists():
            audio_path.unlink(missing_ok=True)
        stderr_text = "".join(stderr_lines).strip()
        hint = diagnose_failure(stderr_text) or (stderr_text.splitlines()[-1] if stderr_text else None)
        raise AudioExtractionError(f"오디오 추출에 실패했습니다: {video}", hint=hint)

    return AudioExtractionResult(path=audio_path, skipped=False)

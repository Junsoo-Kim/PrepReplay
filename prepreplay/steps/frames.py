"""파이프라인 3단계: 장면 전환 감지 및 프레임 추출.

ffmpeg의 `select='gt(scene,X)'` 필터로 장면 전환 시점을 감지해 그 프레임들을
저장한다. 슬라이드가 넘어가는 설명회/강의 영상에는 잘 맞지만, 컨설팅/면접처럼
카메라가 고정된 영상은 장면 전환이 거의 감지되지 않으므로, 전환이 0건이면
일정 간격으로 균등하게 프레임을 뽑는 방식으로 자동 폴백한다.

타임스탬프 확보 방법(PR #0에서 실측 검증):
`-vf "select='gt(scene,X)',showinfo" -fps_mode vfr`로 프레임을 저장하면서,
같은 프레임에 대해 showinfo 필터가 stderr에 남기는 `pts_time:` 값을 순서대로
파싱하면 저장된 파일(`raw_00001.jpg`, `raw_00002.jpg`, ...)과 1:1로 대응한다.
(ffmpeg 9부터 `-vsync vfr`는 제거되었고 `-fps_mode vfr`를 써야 한다.)
"""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console

from prepreplay.diagnostics import diagnose_failure
from prepreplay.errors import DependencyError, FrameExtractionError
from prepreplay.pipeline import is_cached
from prepreplay.utils.ffmpeg import VideoInfo, find_ffmpeg

FRAMES_DIRNAME = "frames"
FRAMES_METADATA_FILENAME = "frames.json"
FRAMES_SCHEMA_VERSION = 1

DEFAULT_MAX_FRAMES = 200
DEFAULT_FALLBACK_INTERVAL_SECONDS = 60.0

_FFMPEG_INSTALL_HINT = (
    "ffmpeg를 설치하세요. Windows: winget install Gyan.FFmpeg / macOS: brew install ffmpeg"
)
_PTS_TIME_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


@dataclasses.dataclass
class FrameInfo:
    index: int
    timestamp: float
    filename: str


@dataclasses.dataclass
class FrameExtractionResult:
    frames_dir: Path
    metadata_path: Path
    frame_count: int
    method: str  # "scene_detection" | "uniform_interval" | "cached"
    skipped: bool


def _clear_dir(directory: Path) -> None:
    for f in directory.glob("*"):
        if f.is_file():
            f.unlink()


def _extract_raw_frames(
    ffmpeg: str, video: Path, frames_dir: Path, vf_filter: str, *, timeout: float
) -> list[float]:
    """vf_filter에 걸리는 프레임을 frames_dir/raw_%05d.jpg로 저장하고, 프레임 순서대로
    타임스탬프 목록을 반환한다."""
    pattern = frames_dir / "raw_%05d.jpg"
    cmd = [
        ffmpeg, "-y",
        "-i", str(video),
        "-vf", f"{vf_filter},showinfo",
        "-fps_mode", "vfr",
        "-q:v", "2",
        # mjpeg 인코더가 일부 입력의 풀레인지 yuv420p를 거부하는 문제 회피
        # ("Non full-range YUV is non-standard" / 인코더 오픈 실패, 실측 확인)
        "-pix_fmt", "yuvj420p",
        str(pattern),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise FrameExtractionError(f"프레임 추출이 시간 초과되었습니다: {video}") from exc

    if result.returncode != 0:
        stderr_text = result.stderr.strip() if result.stderr else ""
        stderr_tail = stderr_text.splitlines()[-1] if stderr_text else None
        hint = diagnose_failure(stderr_text) or stderr_tail
        raise FrameExtractionError(f"ffmpeg가 프레임을 추출하지 못했습니다: {video}", hint=hint)

    return [float(m) for m in _PTS_TIME_RE.findall(result.stderr)]


def _evenly_spaced_indices(total: int, want: int) -> list[int]:
    """0..total-1 범위에서 want개를 균등 간격으로 고른 인덱스(오름차순, 중복 제거)."""
    if want <= 0 or total <= 0:
        return []
    if want >= total:
        return list(range(total))
    if want == 1:
        return [0]
    indices = {round(i * (total - 1) / (want - 1)) for i in range(want)}
    return sorted(indices)


def _format_frame_filename(timestamp: float, used: set[str]) -> str:
    """'frame_00m12s.jpg' 형태의 파일명을 만든다. 같은 초에 여러 프레임이 걸리면
    밀리초를 덧붙여 구분한다."""
    total_seconds = int(timestamp)
    minutes, seconds = divmod(total_seconds, 60)
    base = f"frame_{minutes:02d}m{seconds:02d}s"

    name = f"{base}.jpg"
    if name not in used:
        used.add(name)
        return name

    ms = int(round((timestamp - total_seconds) * 1000))
    name = f"{base}_{ms:03d}ms.jpg"
    suffix = 2
    while name in used:
        name = f"{base}_{ms:03d}ms_{suffix}.jpg"
        suffix += 1
    used.add(name)
    return name


def _write_frames_metadata(
    path: Path,
    frame_infos: list[FrameInfo],
    *,
    method: str,
    scene_threshold: float,
    interval_seconds: Optional[float],
) -> None:
    data = {
        "schema_version": FRAMES_SCHEMA_VERSION,
        "method": method,
        "scene_threshold": scene_threshold,
        "interval_seconds": interval_seconds,
        "frame_count": len(frame_infos),
        "frames": [dataclasses.asdict(f) for f in frame_infos],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_frames(
    video: Path,
    output_dir: Path,
    video_info: VideoInfo,
    *,
    scene_threshold: float = 0.3,
    max_frames: int = DEFAULT_MAX_FRAMES,
    fallback_interval_seconds: float = DEFAULT_FALLBACK_INTERVAL_SECONDS,
    force: bool = False,
    console: Optional[Console] = None,
) -> FrameExtractionResult:
    """영상에서 장면 전환 프레임(또는 균등 간격 프레임)을 뽑아 frames/에 저장한다."""
    frames_dir = output_dir / FRAMES_DIRNAME
    metadata_path = output_dir / FRAMES_METADATA_FILENAME

    if is_cached(metadata_path, force=force):
        existing_count = len(list(frames_dir.glob("frame_*.jpg"))) if frames_dir.is_dir() else 0
        return FrameExtractionResult(
            frames_dir=frames_dir,
            metadata_path=metadata_path,
            frame_count=existing_count,
            method="cached",
            skipped=True,
        )

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise DependencyError("ffmpeg를 찾을 수 없습니다.", hint=_FFMPEG_INSTALL_HINT)

    frames_dir.mkdir(parents=True, exist_ok=True)
    _clear_dir(frames_dir)

    duration = video_info.duration_seconds
    timeout = max(120.0, duration * 5)

    timestamps = _extract_raw_frames(
        ffmpeg, video, frames_dir, f"select='gt(scene,{scene_threshold})'", timeout=timeout
    )
    method = "scene_detection"
    interval: Optional[float] = None

    if not timestamps:
        # ffmpeg의 fps 필터는 주기(interval)가 영상 길이보다 길면 첫 프레임조차
        # flush하지 않고 0개를 반환하는 것을 실측으로 확인했다 - 영상 길이를
        # 넘지 않도록 반드시 클램프해야 한다.
        interval = min(max(fallback_interval_seconds, 0.1), max(duration, 0.1))
        if console:
            console.print(
                "[yellow]⚠ 장면 전환이 감지되지 않았습니다 (고정 카메라 영상일 수 있음). "
                f"{interval:.0f}초 간격 균등 샘플링으로 전환합니다.[/yellow]"
            )
        _clear_dir(frames_dir)
        timestamps = _extract_raw_frames(
            ffmpeg, video, frames_dir, f"fps=1/{interval}", timeout=timeout
        )
        method = "uniform_interval"

    if not timestamps:
        raise FrameExtractionError(
            f"프레임을 추출하지 못했습니다: {video}",
            hint="영상 길이가 너무 짧거나 ffmpeg가 프레임을 생성하지 못했습니다.",
        )

    raw_files = sorted(frames_dir.glob("raw_*.jpg"))
    if len(raw_files) != len(timestamps):
        # 안전장치: ffmpeg 출력 형식이 예상과 어긋나면 더 작은 쪽 개수에 맞춘다.
        n = min(len(raw_files), len(timestamps))
        raw_files, timestamps = raw_files[:n], timestamps[:n]

    paired = list(zip(raw_files, timestamps))

    if len(paired) > max_frames:
        keep_indices = _evenly_spaced_indices(len(paired), max_frames)
        if console:
            console.print(
                f"[yellow]⚠ 감지된 프레임이 {len(paired)}개라 상한({max_frames}개)에 맞춰 "
                "균등하게 솎아냅니다.[/yellow]"
            )
    else:
        keep_indices = list(range(len(paired)))

    keep_set = set(keep_indices)
    used_names: set[str] = set()
    frame_infos: list[FrameInfo] = []
    for new_index, i in enumerate(keep_indices):
        raw_path, ts = paired[i]
        filename = _format_frame_filename(ts, used_names)
        raw_path.rename(frames_dir / filename)
        frame_infos.append(FrameInfo(index=new_index, timestamp=ts, filename=filename))

    for i, (raw_path, _) in enumerate(paired):
        if i not in keep_set and raw_path.exists():
            raw_path.unlink()

    _write_frames_metadata(
        metadata_path,
        frame_infos,
        method=method,
        scene_threshold=scene_threshold,
        interval_seconds=interval,
    )

    return FrameExtractionResult(
        frames_dir=frames_dir,
        metadata_path=metadata_path,
        frame_count=len(frame_infos),
        method=method,
        skipped=False,
    )

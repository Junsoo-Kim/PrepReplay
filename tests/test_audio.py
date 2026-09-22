"""prepreplay.steps.audio 테스트."""

from __future__ import annotations

import wave
from pathlib import Path
from unittest.mock import patch

import pytest

from prepreplay.errors import AudioExtractionError
from prepreplay.steps.audio import AUDIO_FILENAME, extract_audio
from prepreplay.utils.ffmpeg import probe_video

from .conftest import requires_ffmpeg


@requires_ffmpeg
def test_extract_audio_produces_16k_mono_pcm_wav(tmp_path: Path, sample_video: Path) -> None:
    info = probe_video(sample_video)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    result = extract_audio(sample_video, output_dir, info, force=False)

    assert result.skipped is False
    assert result.path == output_dir / AUDIO_FILENAME
    assert result.path.is_file()

    with wave.open(str(result.path), "rb") as wav_file:
        assert wav_file.getframerate() == 16000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2  # 16-bit PCM


def test_extract_audio_skips_when_already_cached(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    existing = output_dir / AUDIO_FILENAME
    existing.write_bytes(b"fake-wav-content")

    # ffmpeg를 아예 호출하지 않아야 하므로, 호출되면 즉시 실패하도록 Popen을 막는다.
    with patch("prepreplay.steps.audio.subprocess.Popen") as mock_popen:
        # video_info는 캐시 히트 시 참조되지 않으므로 None으로 흉내낸 더미를 넣어도 무방하지만,
        # 실제 VideoInfo와의 계약을 지키기 위해 has_audio=True인 값을 만들어 전달한다.
        from prepreplay.utils.ffmpeg import VideoInfo

        dummy_info = VideoInfo(
            path=Path("dummy.mp4"),
            duration_seconds=3.0,
            width=320,
            height=240,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
            size_bytes=1234,
        )

        result = extract_audio(Path("dummy.mp4"), output_dir, dummy_info, force=False)

    mock_popen.assert_not_called()
    assert result.skipped is True
    assert result.path == existing
    assert existing.read_bytes() == b"fake-wav-content"  # 재생성되지 않고 그대로


@requires_ffmpeg
def test_extract_audio_force_regenerates_even_if_cached(
    tmp_path: Path, sample_video: Path
) -> None:
    info = probe_video(sample_video)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    existing = output_dir / AUDIO_FILENAME
    existing.write_bytes(b"stale-placeholder")

    result = extract_audio(sample_video, output_dir, info, force=True)

    assert result.skipped is False
    assert result.path.read_bytes() != b"stale-placeholder"
    with wave.open(str(result.path), "rb") as wav_file:
        assert wav_file.getframerate() == 16000


def test_extract_audio_raises_when_no_audio_track(tmp_path: Path) -> None:
    from prepreplay.utils.ffmpeg import VideoInfo

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    silent_info = VideoInfo(
        path=Path("silent.mp4"),
        duration_seconds=2.0,
        width=320,
        height=240,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec="h264",
        audio_codec=None,
        has_audio=False,
        size_bytes=999,
    )

    with pytest.raises(AudioExtractionError) as exc_info:
        extract_audio(Path("silent.mp4"), output_dir, silent_info, force=False)

    assert exc_info.value.stage == "오디오 추출"
    assert not (output_dir / AUDIO_FILENAME).exists()


@requires_ffmpeg
def test_extract_audio_raises_with_hint_when_ffmpeg_fails(
    tmp_path: Path, sample_video: Path
) -> None:
    info = probe_video(sample_video)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    # 존재하지 않는 입력 경로로 ffmpeg 자체를 실패시켜 에러 처리 경로를 검증한다.
    broken_path = tmp_path / "does_not_exist.mp4"

    with pytest.raises(AudioExtractionError) as exc_info:
        extract_audio(broken_path, output_dir, info, force=False)

    assert exc_info.value.stage == "오디오 추출"
    assert not (output_dir / AUDIO_FILENAME).exists()

"""PR #9 안정화: run.log / state.json 재개(resume) / --verbose·--quiet E2E 테스트.

`prepreplay run`을 `CliRunner`로 실제 실행하며, 합성 샘플 영상 + `fake_whisper_model`
(conftest.py)을 사용해 빠르고 결정론적으로 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from prepreplay.errors import TranscriptionError
from prepreplay.cli import app

from .conftest import requires_ffmpeg

runner = CliRunner()


@requires_ffmpeg
def test_run_writes_run_log_with_stage_entries(
    tmp_path: Path, sample_video: Path, fake_whisper_model
) -> None:
    output_root = tmp_path / "out"
    result = runner.invoke(app, ["run", str(sample_video), "--output", str(output_root)])
    assert result.exit_code == 0, result.output

    log_path = output_root / sample_video.stem / "run.log"
    assert log_path.is_file()
    log_text = log_path.read_text(encoding="utf-8")
    for label in ["오디오 추출", "STT", "프레임 추출", "index.md 생성", "summary_prompt.md 생성"]:
        assert label in log_text
    assert "실행 시작" in log_text
    assert "실행 완료" in log_text


@requires_ffmpeg
def test_run_creates_state_json_marking_ran_stages_complete(
    tmp_path: Path, sample_video: Path, fake_whisper_model
) -> None:
    output_root = tmp_path / "out"
    result = runner.invoke(app, ["run", str(sample_video), "--output", str(output_root)])
    assert result.exit_code == 0, result.output

    state_path = output_root / sample_video.stem / "state.json"
    assert state_path.is_file()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(state["stages"].keys()) == {
        "audio",
        "transcribe",
        "frames",
        "index",
        "summary_prompt",
    }
    assert "split" not in state["stages"]  # --split을 쓰지 않았으므로


@requires_ffmpeg
def test_resume_skips_completed_audio_but_reruns_interrupted_transcribe(
    tmp_path: Path, sample_video: Path, fake_whisper_model, monkeypatch
) -> None:
    """DoD: STT 도중 중단 후 재실행하면 오디오 추출은 다시 하지 않는다."""
    import prepreplay.cli as cli_module

    output_root = tmp_path / "out"
    real_transcribe_audio = cli_module.transcribe_audio

    def _fail_transcription(*args, **kwargs):
        raise TranscriptionError("테스트용 STT 중단")

    monkeypatch.setattr(cli_module, "transcribe_audio", _fail_transcription)
    first_result = runner.invoke(app, ["run", str(sample_video), "--output", str(output_root)])
    assert first_result.exit_code == 1, first_result.output

    video_output_dir = output_root / sample_video.stem
    audio_path = video_output_dir / "audio.wav"
    assert audio_path.is_file()  # 실패 시에는 재개를 위해 보존
    audio_mtime_before = audio_path.stat().st_mtime_ns

    monkeypatch.setattr(cli_module, "transcribe_audio", real_transcribe_audio)
    result = runner.invoke(app, ["run", str(sample_video), "--output", str(output_root)])

    assert result.exit_code == 0, result.output
    assert "오디오 추출 스킵" in result.output
    assert "STT 완료" in result.output
    assert "임시 오디오 삭제 완료" in result.output
    assert not audio_path.exists()
    assert audio_mtime_before > 0
    assert (video_output_dir / "segments.json").is_file()


@requires_ffmpeg
def test_resume_regenerates_when_file_present_but_state_unmarked(
    tmp_path: Path, sample_video: Path, fake_whisper_model
) -> None:
    """완료 마커 없이 파일만 남아있으면(중단으로 인한 부분 쓰기 가정) 신뢰하지 않고 재생성한다."""
    output_root = tmp_path / "out"
    result = runner.invoke(app, ["run", str(sample_video), "--output", str(output_root)])
    assert result.exit_code == 0, result.output

    video_output_dir = output_root / sample_video.stem
    audio_path = video_output_dir / "audio.wav"
    audio_path.write_bytes(b"not a real wav file")

    state_path = video_output_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    del state["stages"]["audio"]
    del state["stages"]["transcribe"]
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    (video_output_dir / "segments.json").unlink()
    (video_output_dir / "transcript.srt").unlink()
    (video_output_dir / "transcript.txt").unlink()

    result = runner.invoke(app, ["run", str(sample_video), "--output", str(output_root)])
    assert result.exit_code == 0, result.output
    assert "오디오 추출 완료" in result.output  # 스킵이 아니라 재생성됨
    assert "임시 오디오 삭제 완료" in result.output
    assert not audio_path.exists()


@requires_ffmpeg
def test_quiet_suppresses_progress_output_errors_still_shown(
    tmp_path: Path, sample_video: Path, fake_whisper_model, silent_video: Path
) -> None:
    output_root = tmp_path / "out"
    result = runner.invoke(
        app, ["run", str(sample_video), "--output", str(output_root), "--quiet"]
    )
    assert result.exit_code == 0, result.output
    assert "오디오 추출 완료" not in result.output
    assert "영상 메타데이터" not in result.output

    error_result = runner.invoke(
        app, ["run", str(silent_video), "--output", str(tmp_path / "out2"), "--quiet"]
    )
    assert error_result.exit_code == 1
    assert "오디오 추출" in error_result.output


@requires_ffmpeg
def test_verbose_adds_debug_detail_absent_by_default(
    tmp_path: Path, sample_video: Path, fake_whisper_model
) -> None:
    default_result = runner.invoke(
        app, ["run", str(sample_video), "--output", str(tmp_path / "out1")]
    )
    assert default_result.exit_code == 0, default_result.output
    assert "resolved config" not in default_result.output

    verbose_result = runner.invoke(
        app, ["run", str(sample_video), "--output", str(tmp_path / "out2"), "--verbose"]
    )
    assert verbose_result.exit_code == 0, verbose_result.output
    assert "resolved config" in verbose_result.output


def test_verbose_and_quiet_together_rejected(tmp_path: Path) -> None:
    bogus = tmp_path / "video.mp4"
    bogus.write_bytes(b"not a real mp4 but extension is fine for this check")
    result = runner.invoke(app, ["run", str(bogus), "--verbose", "--quiet"])
    assert result.exit_code == 1
    assert "동시에 사용할 수 없습니다" in result.output


@requires_ffmpeg
def test_ffmpeg_failure_hint_is_curated_not_raw_stderr(tmp_path: Path) -> None:
    corrupted = tmp_path / "corrupted.mp4"
    corrupted.write_bytes(b"this is not a real video file, just garbage bytes" * 10)
    result = runner.invoke(app, ["run", str(corrupted), "--output", str(tmp_path / "out")])
    assert result.exit_code == 1
    assert "손상" in result.output

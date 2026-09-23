"""PR #10 배치 처리(디렉터리 입력) E2E 테스트."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from prepreplay.cli import app

from .conftest import requires_ffmpeg

runner = CliRunner()


def _make_video(path: Path, *, with_audio: bool, duration: float = 2.0) -> None:
    """`with_audio`에 따라 오디오 트랙이 있거나 없는 짧은 합성 영상을 `path`에 만든다."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={duration}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac"] if with_audio else ["-an"]
    cmd.append(str(path))
    subprocess.run(cmd, capture_output=True, check=True, timeout=60)


@requires_ffmpeg
def test_run_batch_processes_all_videos_in_directory(
    tmp_path: Path, fake_whisper_model
) -> None:
    video_dir = tmp_path / "lectures"
    video_dir.mkdir()
    _make_video(video_dir / "01_intro.mp4", with_audio=True)
    _make_video(video_dir / "02_body.mp4", with_audio=True)

    output_root = tmp_path / "out"
    result = runner.invoke(app, ["run", str(video_dir), "--output", str(output_root)])

    assert result.exit_code == 0, result.output
    assert "[1/2]" in result.output
    assert "[2/2]" in result.output
    assert "배치 완료: 성공 2/2" in result.output
    assert (output_root / "01_intro" / "summary_prompt.md").is_file()
    assert (output_root / "02_body" / "summary_prompt.md").is_file()


@requires_ffmpeg
def test_run_batch_continues_after_one_failure_and_reports_summary(
    tmp_path: Path, fake_whisper_model
) -> None:
    video_dir = tmp_path / "lectures"
    video_dir.mkdir()
    _make_video(video_dir / "01_good.mp4", with_audio=True)
    _make_video(video_dir / "02_no_audio.mp4", with_audio=False)
    _make_video(video_dir / "03_good.mp4", with_audio=True)

    output_root = tmp_path / "out"
    result = runner.invoke(app, ["run", str(video_dir), "--output", str(output_root)])

    assert result.exit_code == 1, result.output
    assert "배치 처리 요약" in result.output
    assert "배치 완료: 성공 2/3" in result.output
    assert (output_root / "01_good" / "summary_prompt.md").is_file()
    assert (output_root / "03_good" / "summary_prompt.md").is_file()
    assert not (output_root / "02_no_audio").exists() or not (
        output_root / "02_no_audio" / "summary_prompt.md"
    ).exists()


@requires_ffmpeg
def test_run_rejects_directory_with_no_video_files(tmp_path: Path) -> None:
    empty_dir = tmp_path / "not_videos"
    empty_dir.mkdir()
    (empty_dir / "notes.txt").write_text("hello", encoding="utf-8")

    result = runner.invoke(app, ["run", str(empty_dir)])
    assert result.exit_code == 1
    assert "처리할 수 있는 영상 파일이 없습니다" in result.output


@requires_ffmpeg
def test_run_batch_resumes_only_failed_video_after_fix(
    tmp_path: Path, fake_whisper_model
) -> None:
    """PR #9 시너지: 배치 중 실패한 영상만 재실행되고, 이미 성공한 영상은 재실행되지 않는다."""
    video_dir = tmp_path / "lectures"
    video_dir.mkdir()
    good_path = video_dir / "01_good.mp4"
    bad_path = video_dir / "02_bad.mp4"
    _make_video(good_path, with_audio=True)
    _make_video(bad_path, with_audio=False)  # 처음엔 오디오 없어 실패하게 함

    output_root = tmp_path / "out"
    first_result = runner.invoke(app, ["run", str(video_dir), "--output", str(output_root)])
    assert first_result.exit_code == 1, first_result.output

    good_prompt_path = output_root / "01_good" / "summary_prompt.md"
    assert good_prompt_path.is_file()
    good_prompt_mtime_before = good_prompt_path.stat().st_mtime_ns
    assert not (output_root / "01_good" / "audio.wav").exists()

    # "고쳐서" 재실행: 오디오 트랙이 있는 영상으로 같은 파일명을 덮어씀
    _make_video(bad_path, with_audio=True)
    second_result = runner.invoke(app, ["run", str(video_dir), "--output", str(output_root)])

    assert second_result.exit_code == 0, second_result.output
    assert "배치 완료: 성공 2/2" in second_result.output
    assert "오디오 추출 생략" in second_result.output
    assert good_prompt_path.stat().st_mtime_ns == good_prompt_mtime_before
    assert not (output_root / "01_good" / "audio.wav").exists()
    assert not (output_root / "02_bad" / "audio.wav").exists()
    assert (output_root / "02_bad" / "summary_prompt.md").is_file()


@requires_ffmpeg
def test_run_directory_with_single_video_behaves_like_single_file(
    tmp_path: Path, fake_whisper_model
) -> None:
    video_dir = tmp_path / "lectures"
    video_dir.mkdir()
    _make_video(video_dir / "only.mp4", with_audio=True)

    output_root = tmp_path / "out"
    result = runner.invoke(app, ["run", str(video_dir), "--output", str(output_root)])

    assert result.exit_code == 0, result.output
    assert "배치 처리 요약" not in result.output
    assert "summary_prompt.md 생성 완료" in result.output

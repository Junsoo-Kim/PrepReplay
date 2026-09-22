"""CLI 스모크 테스트 (typer.testing.CliRunner 사용)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from prepreplay.cli import app

from .conftest import requires_ffmpeg

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "prepreplay" in result.output


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "doctor" in result.output


def test_doctor_runs_without_crashing() -> None:
    result = runner.invoke(app, ["doctor"])
    # ffmpeg 미설치 환경에서는 exit_code 1(필수 도구 누락)일 수 있으므로,
    # "예외 없이 진단 표가 출력됐는지"만 검증한다.
    assert result.exit_code in (0, 1)
    assert "환경 진단" in result.output


def test_run_rejects_unsupported_extension(tmp_path: Path) -> None:
    bogus = tmp_path / "not_a_video.txt"
    bogus.write_text("hello", encoding="utf-8")
    result = runner.invoke(app, ["run", str(bogus)])
    assert result.exit_code == 1
    assert "지원하지 않는" in result.output


def test_run_rejects_unknown_mode(tmp_path: Path) -> None:
    bogus = tmp_path / "video.mp4"
    bogus.write_bytes(b"not a real mp4 but extension is fine for this check")
    result = runner.invoke(app, ["run", str(bogus), "--mode", "nonsense"])
    assert result.exit_code == 1
    assert "알 수 없는 모드" in result.output


def test_run_rejects_missing_file() -> None:
    result = runner.invoke(app, ["run", "/no/such/file.mp4"])
    assert result.exit_code != 0


@requires_ffmpeg
def test_run_end_to_end_creates_output_dir_and_prints_metadata(
    tmp_path: Path, sample_video: Path
) -> None:
    output_root = tmp_path / "out"
    result = runner.invoke(
        app,
        ["run", str(sample_video), "--output", str(output_root)],
    )
    assert result.exit_code == 0, result.output
    assert "영상 메타데이터" in result.output
    expected_dir = output_root / sample_video.stem
    assert expected_dir.is_dir()

"""PR #11 화자 분리(--diarize) E2E 테스트."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from prepreplay.cli import app

from .conftest import requires_ffmpeg

runner = CliRunner()


@requires_ffmpeg
def test_run_with_diarize_labels_segments_and_index(
    tmp_path: Path, sample_video: Path, fake_whisper_model, fake_diarization_pipeline
) -> None:
    output_root = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run", str(sample_video),
            "--output", str(output_root),
            "--diarize",
            "--hf-token", "fake-token",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "화자 분리 완료" in result.output

    video_output_dir = output_root / sample_video.stem
    assert (video_output_dir / "diarization.json").is_file()

    segments_data = json.loads((video_output_dir / "segments.json").read_text(encoding="utf-8"))
    assert segments_data["segments"][0]["text"] == "[화자1] 안녕하세요"
    assert segments_data["segments"][1]["text"] == "[화자2] 테스트입니다"

    index_text = (video_output_dir / "index.md").read_text(encoding="utf-8")
    assert "[화자1]" in index_text
    assert "[화자2]" in index_text


@requires_ffmpeg
def test_run_diarize_without_token_fails_with_hint(
    tmp_path: Path, sample_video: Path, fake_whisper_model, fake_diarization_pipeline, monkeypatch
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)

    result = runner.invoke(
        app,
        ["run", str(sample_video), "--output", str(tmp_path / "out"), "--diarize"],
    )

    assert result.exit_code == 1
    assert "화자 분리" in result.output
    assert "토큰" in result.output


@requires_ffmpeg
def test_run_without_diarize_flag_produces_unlabeled_transcript(
    tmp_path: Path, sample_video: Path, fake_whisper_model
) -> None:
    output_root = tmp_path / "out"
    result = runner.invoke(app, ["run", str(sample_video), "--output", str(output_root)])

    assert result.exit_code == 0, result.output
    assert not (output_root / sample_video.stem / "diarization.json").exists()
    segments_data = json.loads(
        (output_root / sample_video.stem / "segments.json").read_text(encoding="utf-8")
    )
    assert segments_data["segments"][0]["text"] == "안녕하세요"

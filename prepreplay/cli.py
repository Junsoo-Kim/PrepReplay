"""PrepReplay CLI 엔트리포인트."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from prepreplay import __version__
from prepreplay.config import (
    SUPPORTED_VIDEO_EXTENSIONS,
    VALID_MODES,
    Config,
    resolve_config,
)
from prepreplay.errors import DependencyError, InputValidationError, PrepReplayError
from prepreplay.logging_setup import configure_logging
from prepreplay.state import is_stage_complete, mark_stage_complete
from prepreplay.steps.audio import extract_audio
from prepreplay.steps.diarize import diarize_audio
from prepreplay.steps.frames import extract_frames
from prepreplay.steps.index import generate_index
from prepreplay.steps.split import (
    LONG_VIDEO_WARNING_THRESHOLD_SECONDS,
    parse_split_seconds,
    split_into_chunks,
)
from prepreplay.steps.summary_prompt import generate_summary_prompt
from prepreplay.steps.transcribe import transcribe_audio
from prepreplay.utils.ffmpeg import find_ffmpeg, find_ffprobe, get_version, probe_video
from prepreplay.utils.gpu import detect_gpu

app = typer.Typer(
    name="prepreplay",
    help="로컬 영상을 분석하여 스크립트+프레임+Claude용 프롬프트로 변환하는 CLI 도구.",
    no_args_is_help=True,
)
console = Console()
error_console = Console(stderr=True)

MIN_RECOMMENDED_FREE_GB = 5.0


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"prepreplay {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="버전 정보를 출력하고 종료합니다.",
    ),
) -> None:
    """PrepReplay: 로컬 영상 분석 CLI."""


def _print_error(exc: PrepReplayError) -> None:
    error_console.print(f"[bold red]✗ [{exc.stage}] 실패[/bold red]: {exc.message}")
    if exc.hint:
        error_console.print(f"  [yellow]조치:[/yellow] {exc.hint}")


def _log_error(exc: PrepReplayError) -> None:
    logger = logging.getLogger("prepreplay")
    logger.error("[%s] 실패: %s", exc.stage, exc.message)
    if exc.hint:
        logger.error("  조치: %s", exc.hint)


@app.command()
def doctor() -> None:
    """실행 환경(ffmpeg, GPU, 디스크 여유 공간 등)을 점검합니다."""
    table = Table(title="PrepReplay 환경 진단")
    table.add_column("항목")
    table.add_column("상태")
    table.add_column("세부 정보")

    required_ok = True

    ffmpeg_path = find_ffmpeg()
    if ffmpeg_path:
        table.add_row("ffmpeg", "[green]OK[/green]", get_version(ffmpeg_path) or ffmpeg_path)
    else:
        table.add_row("ffmpeg", "[bold red]누락[/bold red]", "winget install Gyan.FFmpeg (Windows)")
        required_ok = False

    ffprobe_path = find_ffprobe()
    if ffprobe_path:
        table.add_row("ffprobe", "[green]OK[/green]", get_version(ffprobe_path) or ffprobe_path)
    else:
        table.add_row("ffprobe", "[bold red]누락[/bold red]", "ffmpeg 설치에 포함되어 있습니다")
        required_ok = False

    gpu = detect_gpu()
    if gpu:
        table.add_row(
            "GPU",
            "[green]감지됨[/green]",
            f"{gpu.name} (driver {gpu.driver_version}, {gpu.memory_total})",
        )
    else:
        table.add_row("GPU", "[yellow]미감지[/yellow]", "CPU 모드로 동작합니다 (STT 속도 저하 예상)")

    _, _, free_bytes = shutil.disk_usage(Path.cwd())
    free_gb = free_bytes / (1024**3)
    disk_status = "[green]OK[/green]" if free_gb >= MIN_RECOMMENDED_FREE_GB else "[yellow]부족 가능[/yellow]"
    table.add_row("디스크 여유 공간", disk_status, f"{free_gb:.1f} GB (현재 디렉터리 기준)")

    console.print(table)

    if not required_ok:
        error_console.print(
            "[bold red]필수 도구가 누락되어 파이프라인을 실행할 수 없습니다. "
            "위 안내에 따라 설치 후 다시 실행하세요.[/bold red]"
        )
        raise typer.Exit(code=1)


def _collect_videos(input_path: Path) -> list[Path]:
    """`input_path`가 파일이면 그대로, 디렉터리면 그 안의 지원 확장자 영상들을
    파일명 오름차순으로 모아 반환한다(하위 폴더는 재귀하지 않음)."""
    if input_path.is_file():
        return [input_path]

    videos = sorted(
        p
        for p in input_path.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
    )
    if not videos:
        raise InputValidationError(
            f"디렉터리에 처리할 수 있는 영상 파일이 없습니다: {input_path}",
            hint=f"지원 형식: {', '.join(SUPPORTED_VIDEO_EXTENSIONS)}",
        )
    return videos


def _run_single_video(
    video: Path,
    cfg: Config,
    *,
    active_console: Console,
    verbose: bool,
) -> None:
    """영상 하나에 대해 오디오 추출 ~ (옵션) 구간 분할까지 전체 파이프라인을 실행한다.

    실패하면 `PrepReplayError`를 던진다. 호출부(`run()`)가 단일 파일 입력이면 그대로
    전파시키고, 디렉터리 배치 입력이면 잡아서 다음 영상으로 계속 진행한다.
    """
    active_console.print(f"[bold]입력 영상:[/bold] {video}")
    info = probe_video(video)

    meta_table = Table(title="영상 메타데이터")
    meta_table.add_column("항목")
    meta_table.add_column("값")
    meta_table.add_row("길이", info.duration_hms)
    meta_table.add_row("해상도", f"{info.width}x{info.height}" if info.width else "알 수 없음")
    meta_table.add_row("비디오 코덱", info.video_codec or "알 수 없음")
    meta_table.add_row("오디오 코덱", info.audio_codec or "(오디오 트랙 없음)")
    meta_table.add_row("파일 크기", f"{info.size_bytes / (1024**2):.1f} MB")
    active_console.print(meta_table)

    if cfg.split is None and info.duration_seconds > LONG_VIDEO_WARNING_THRESHOLD_SECONDS:
        active_console.print(
            "[yellow]⚠ 30분을 넘는 영상입니다. --split 10m 같은 옵션으로 구간을 "
            "나누는 것을 권장합니다 (한 번에 붙여넣기엔 스크립트가 길어질 수 있습니다).[/yellow]"
        )

    output_dir = cfg.output / video.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = configure_logging(output_dir, verbose=verbose, error_console=error_console)
    logger.info("=== 실행 시작: %s ===", video)
    logger.debug("resolved config: %s", cfg)

    def _stage_force(stage: str) -> bool:
        return cfg.force or not is_stage_complete(output_dir, stage)

    stage_start = time.perf_counter()
    audio_result = extract_audio(
        video, output_dir, info, force=_stage_force("audio"), console=active_console
    )
    if audio_result.skipped:
        active_console.print(
            f"[dim]오디오 추출 스킵 (캐시됨): {audio_result.path} (--force로 재생성 가능)[/dim]"
        )
        logger.info("[오디오 추출] 스킵 (캐시됨): %s", audio_result.path)
    else:
        active_console.print(f"[green]오디오 추출 완료:[/green] {audio_result.path}")
        logger.info(
            "[오디오 추출] 완료 (%.1fs): %s", time.perf_counter() - stage_start, audio_result.path
        )
    mark_stage_complete(output_dir, "audio")

    diarization_segments = None
    if cfg.diarize:
        stage_start = time.perf_counter()
        diarize_result = diarize_audio(
            audio_result.path,
            output_dir,
            model_name=cfg.diarization_model,
            hf_token=cfg.hf_token,
            force=_stage_force("diarize"),
            console=active_console,
        )
        diarization_segments = diarize_result.segments
        if diarize_result.skipped:
            active_console.print(
                f"[dim]화자 분리 스킵 (캐시됨): {diarize_result.path} (--force로 재생성 가능)[/dim]"
            )
            logger.info("[화자 분리] 스킵 (캐시됨): %s", diarize_result.path)
        else:
            speaker_count = len({s.speaker for s in diarize_result.segments})
            active_console.print(
                f"[green]화자 분리 완료[/green] ({speaker_count}명 감지): {diarize_result.path}"
            )
            logger.info(
                "[화자 분리] 완료 (%.1fs, %d명 감지): %s",
                time.perf_counter() - stage_start,
                speaker_count,
                diarize_result.path,
            )
        mark_stage_complete(output_dir, "diarize")

    stage_start = time.perf_counter()
    transcript_result = transcribe_audio(
        audio_result.path,
        output_dir,
        model_size=cfg.model,
        language=cfg.language,
        duration_hint=info.duration_seconds,
        diarization_segments=diarization_segments,
        force=_stage_force("transcribe"),
        console=active_console,
    )
    if transcript_result.skipped:
        active_console.print(
            f"[dim]STT 스킵 (캐시됨): {transcript_result.segments_path} (--force로 재생성 가능)[/dim]"
        )
        logger.info("[STT] 스킵 (캐시됨): %s", transcript_result.segments_path)
    else:
        active_console.print(
            f"[green]STT 완료[/green] (device={transcript_result.device}, "
            f"language={transcript_result.language}): "
            f"{transcript_result.srt_path.name}, {transcript_result.txt_path.name}, "
            f"{transcript_result.segments_path.name}"
        )
        logger.info(
            "[STT] 완료 (%.1fs, device=%s): %s",
            time.perf_counter() - stage_start,
            transcript_result.device,
            transcript_result.segments_path.name,
        )
    mark_stage_complete(output_dir, "transcribe")

    stage_start = time.perf_counter()
    frames_result = extract_frames(
        video,
        output_dir,
        info,
        scene_threshold=cfg.scene_threshold,
        max_frames=cfg.max_frames,
        force=_stage_force("frames"),
        console=active_console,
    )
    if frames_result.skipped:
        active_console.print(
            f"[dim]프레임 추출 스킵 (캐시됨): {frames_result.metadata_path} "
            "(--force로 재생성 가능)[/dim]"
        )
        logger.info("[프레임 추출] 스킵 (캐시됨): %s", frames_result.metadata_path)
    else:
        method_label = "장면 감지" if frames_result.method == "scene_detection" else "균등 간격"
        active_console.print(
            f"[green]프레임 추출 완료[/green] ({method_label}, {frames_result.frame_count}개): "
            f"{frames_result.frames_dir}"
        )
        logger.info(
            "[프레임 추출] 완료 (%.1fs, %s, %d개): %s",
            time.perf_counter() - stage_start,
            method_label,
            frames_result.frame_count,
            frames_result.frames_dir,
        )
    mark_stage_complete(output_dir, "frames")

    stage_start = time.perf_counter()
    index_result = generate_index(
        output_dir,
        video_name=video.name,
        duration_seconds=info.duration_seconds,
        force=_stage_force("index"),
    )
    if index_result.skipped:
        active_console.print(
            f"[dim]index.md 생성 스킵 (캐시됨): {index_result.path} (--force로 재생성 가능)[/dim]"
        )
        logger.info("[index.md 생성] 스킵 (캐시됨): %s", index_result.path)
    else:
        active_console.print(
            f"[green]index.md 생성 완료[/green] ({index_result.section_count}개 구간): "
            f"{index_result.path}"
        )
        logger.info(
            "[index.md 생성] 완료 (%.1fs, %d개 구간): %s",
            time.perf_counter() - stage_start,
            index_result.section_count,
            index_result.path,
        )
    mark_stage_complete(output_dir, "index")

    stage_start = time.perf_counter()
    prompt_result = generate_summary_prompt(
        output_dir,
        video_name=video.name,
        duration_seconds=info.duration_seconds,
        mode=cfg.mode,
        template_path=cfg.template,
        force=_stage_force("summary_prompt"),
    )
    if prompt_result.skipped:
        active_console.print(
            f"[dim]summary_prompt.md 생성 스킵 (캐시됨): {prompt_result.path} "
            "(--force로 재생성 가능)[/dim]"
        )
        logger.info("[summary_prompt.md 생성] 스킵 (캐시됨): %s", prompt_result.path)
    else:
        active_console.print(
            f"[green]summary_prompt.md 생성 완료[/green] (mode={prompt_result.mode}): "
            f"{prompt_result.path}"
        )
        logger.info(
            "[summary_prompt.md 생성] 완료 (%.1fs, mode=%s): %s",
            time.perf_counter() - stage_start,
            prompt_result.mode,
            prompt_result.path,
        )
    mark_stage_complete(output_dir, "summary_prompt")

    if cfg.split is not None:
        stage_start = time.perf_counter()
        split_result = split_into_chunks(
            output_dir,
            video_name=video.name,
            duration_seconds=info.duration_seconds,
            split_spec=cfg.split,
            mode=cfg.mode,
            template_path=cfg.template,
            force=_stage_force("split"),
        )
        if split_result.skipped:
            active_console.print(
                f"[dim]구간 분할 스킵 (캐시됨): {split_result.chunks_dir} "
                "(--force로 재생성 가능)[/dim]"
            )
            logger.info("[구간 분할] 스킵 (캐시됨): %s", split_result.chunks_dir)
        else:
            active_console.print(
                f"[green]구간 분할 완료[/green] ({split_result.chunk_count}개 파일): "
                f"{split_result.chunks_dir}"
            )
            logger.info(
                "[구간 분할] 완료 (%.1fs, %d개 파일): %s",
                time.perf_counter() - stage_start,
                split_result.chunk_count,
                split_result.chunks_dir,
            )
        mark_stage_complete(output_dir, "split")

    logger.info("=== 실행 완료 ===")


@app.command()
def run(
    video: Path = typer.Argument(
        ...,
        help="분석할 로컬 영상 파일 또는 영상이 담긴 디렉터리 경로 (디렉터리면 안의 영상을 파일명순으로 일괄 처리)",
        exists=True,
        dir_okay=True,
        readable=True,
    ),
    mode: Optional[str] = typer.Option(
        None, "--mode", help=f"유스케이스 모드 ({', '.join(VALID_MODES)}). 기본: default"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", help="결과물을 저장할 상위 디렉터리. 기본: ./output"
    ),
    scene_threshold: Optional[float] = typer.Option(
        None, "--scene-threshold", help="장면 전환 감지 임계값 (0.0~1.0). 기본: 0.3"
    ),
    max_frames: Optional[int] = typer.Option(
        None, "--max-frames", help="추출할 프레임 수 상한 (넘으면 균등하게 솎아냄). 기본: 200"
    ),
    split: Optional[str] = typer.Option(
        None, "--split", help="긴 영상 구간 분할 단위 (예: 10m). 기본: 분할 안 함"
    ),
    language: Optional[str] = typer.Option(None, "--language", help="STT 언어 코드. 기본: ko"),
    model: Optional[str] = typer.Option(None, "--model", help="Whisper 모델 크기. 기본: large-v3"),
    force: Optional[bool] = typer.Option(
        None, "--force/--no-force", help="캐시된 산출물이 있어도 강제로 재생성"
    ),
    template_path: Optional[Path] = typer.Option(
        None,
        "--template",
        help="사용자 정의 요약 프롬프트 템플릿 파일 경로 (지정 시 --mode의 내장 템플릿 대신 사용)",
    ),
    config_path: Optional[Path] = typer.Option(
        None, "--config", help="설정 파일 경로. 기본: ./config.yaml (있는 경우)"
    ),
    diarize: Optional[bool] = typer.Option(
        None,
        "--diarize/--no-diarize",
        help="화자 분리 활성화 (pyannote.audio 필요: pip install -e \".[diarization]\", HF 토큰 필요)",
    ),
    hf_token: Optional[str] = typer.Option(
        None,
        "--hf-token",
        help="화자 분리용 HuggingFace 토큰. 기본: HF_TOKEN 환경변수",
    ),
    diarization_model: Optional[str] = typer.Option(
        None,
        "--diarization-model",
        help="화자 분리 모델. 기본: pyannote/speaker-diarization-3.1",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="상세 로그를 stderr에도 함께 출력합니다."
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="진행 상황 출력을 억제합니다 (에러는 계속 출력됩니다)."
    ),
) -> None:
    """영상을 분석하여 output/{video_name}/ 에 결과물을 생성합니다.

    입력 검증, 영상 메타데이터 확인, 오디오 추출, STT, 프레임 추출, index.md,
    summary_prompt.md 생성까지 전체 파이프라인이 동작합니다. `--split`을 지정하면
    긴 영상을 chunks/*.md로 나눠 구간별로도 붙여넣을 수 있게 만듭니다. `video`에
    디렉터리를 넘기면 그 안의 영상들을 파일명순으로 일괄 처리합니다 — 영상 하나가
    실패해도 나머지는 계속 처리하고, 끝에 성공/실패 요약을 보여줍니다.
    """
    try:
        if verbose and quiet:
            raise InputValidationError(
                "--verbose와 --quiet는 동시에 사용할 수 없습니다.",
                hint="둘 중 하나만 지정하세요.",
            )
        active_console = Console(quiet=True) if quiet else console

        cfg = resolve_config(
            config_path=config_path,
            cli_overrides={
                "mode": mode,
                "output": output,
                "scene_threshold": scene_threshold,
                "max_frames": max_frames,
                "split": split,
                "language": language,
                "model": model,
                "template": template_path,
                "force": force,
                "diarize": diarize,
                "hf_token": hf_token,
                "diarization_model": diarization_model,
            },
        )

        if cfg.mode not in VALID_MODES:
            raise InputValidationError(
                f"알 수 없는 모드입니다: {cfg.mode}",
                hint=f"다음 중 하나를 사용하세요: {', '.join(VALID_MODES)}",
            )

        if video.is_file() and video.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            raise InputValidationError(
                f"지원하지 않는 파일 확장자입니다: {video.suffix}",
                hint=f"지원 형식: {', '.join(SUPPORTED_VIDEO_EXTENSIONS)}",
            )

        if cfg.split is not None:
            parse_split_seconds(cfg.split)  # 형식 검증만 미리 수행 (나머지 단계 전에 빨리 실패)

        if find_ffmpeg() is None or find_ffprobe() is None:
            raise DependencyError(
                "ffmpeg/ffprobe를 찾을 수 없습니다.",
                hint="`prepreplay doctor`로 환경을 점검하세요.",
            )

        videos = _collect_videos(video)
        is_batch = len(videos) > 1

        batch_results: list[tuple[Path, bool, Optional[str]]] = []
        for idx, current_video in enumerate(videos, start=1):
            if is_batch:
                active_console.print(
                    f"\n[bold]\\[{idx}/{len(videos)}][/bold] 처리 중: {current_video.name}"
                )
                try:
                    _run_single_video(
                        current_video, cfg, active_console=active_console, verbose=verbose
                    )
                except PrepReplayError as exc:
                    _log_error(exc)
                    _print_error(exc)
                    batch_results.append((current_video, False, exc.message))
                else:
                    batch_results.append((current_video, True, None))
            else:
                _run_single_video(current_video, cfg, active_console=active_console, verbose=verbose)

        active_console.print(
            f"\n[bold]적용된 설정:[/bold] mode={cfg.mode}, scene_threshold={cfg.scene_threshold}, "
            f"max_frames={cfg.max_frames}, language={cfg.language}, model={cfg.model}, "
            f"split={cfg.split or '(없음)'}"
        )

        if is_batch:
            summary_table = Table(title="배치 처리 요약")
            summary_table.add_column("영상")
            summary_table.add_column("상태")
            summary_table.add_column("사유")
            for batch_video, succeeded, error_message in batch_results:
                status = "[green]성공[/green]" if succeeded else "[bold red]실패[/bold red]"
                summary_table.add_row(batch_video.name, status, error_message or "")
            active_console.print(summary_table)

            succeeded_count = sum(1 for _, succeeded, _ in batch_results if succeeded)
            active_console.print(
                f"[bold]배치 완료:[/bold] 성공 {succeeded_count}/{len(batch_results)}"
            )
            if succeeded_count < len(batch_results):
                raise typer.Exit(code=1)

    except PrepReplayError as exc:
        _log_error(exc)
        _print_error(exc)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()

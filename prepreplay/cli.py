"""PrepReplay CLI 엔트리포인트.

실제 명령(run, doctor 등)은 PR #2 이후 단계에서 채워진다.
이 파일은 `prepreplay --help`가 동작하는 최소 골격만 담는다.
"""

import typer

from prepreplay import __version__

app = typer.Typer(
    name="prepreplay",
    help="로컬 영상을 분석하여 스크립트+프레임+Claude용 프롬프트로 변환하는 CLI 도구.",
    no_args_is_help=True,
)


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


if __name__ == "__main__":
    app()

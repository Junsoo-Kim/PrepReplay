"""`output_dir/run.log` 파일 로깅 설정.

기존 사용자 대면 출력은 `cli.py`의 rich `Console.print` 호출이 그대로 담당한다.
이 모듈은 그 옆에서, 같은 내용을 파일(`run.log`, 항상 append)에 단계별로 남기고,
`--verbose`가 지정됐을 때만 stderr에도 DEBUG 상세를 함께 뿌린다.

모듈 로드 시 `NullHandler`를 미리 붙여 두는 이유: `output_dir`가 아직 만들어지기
전(입력 검증 실패 등)에 로거가 호출돼도 Python의 "handler 없음" 기본 동작(stderr에
경고를 찍는 lastResort 핸들러)이 발동하지 않도록 하기 위함.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

LOGGER_NAME = "prepreplay"
LOG_FILENAME = "run.log"

logging.getLogger(LOGGER_NAME).addHandler(logging.NullHandler())


class _DebugOnlyFilter(logging.Filter):
    """INFO(단계 완료/스킵)·ERROR 레코드는 이미 콘솔에 rich로 출력되므로 제외하고,
    DEBUG 레코드(설정 덤프 등 run.log 전용 상세)만 통과시켜 중복 출력을 막는다."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == logging.DEBUG


def configure_logging(output_dir: Path, *, verbose: bool, error_console: Console) -> logging.Logger:
    """`output_dir/run.log`에 파일 핸들러를 붙이고(항상, append 모드), `verbose`면
    `error_console`(stderr)에도 DEBUG 상세를 출력하는 핸들러를 추가로 붙인다."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    file_handler = logging.FileHandler(output_dir / LOG_FILENAME, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(file_handler)

    if verbose:
        rich_handler = RichHandler(
            console=error_console, show_time=False, show_path=False, markup=False
        )
        rich_handler.setLevel(logging.DEBUG)
        rich_handler.addFilter(_DebugOnlyFilter())
        logger.addHandler(rich_handler)

    return logger

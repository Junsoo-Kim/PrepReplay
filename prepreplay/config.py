"""설정 로드 및 병합.

우선순위: CLI 옵션(명시적으로 지정된 것) > config.yaml > 내장 기본값.
CLI 옵션은 지정되지 않으면 None으로 넘어오도록 cli.py에서 구성하며,
이 모듈은 None인 값을 "지정 안 됨"으로 취급해 하위 우선순위 값을 그대로 둔다.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Optional

import yaml

from prepreplay.errors import ConfigError

DEFAULT_CONFIG_FILENAME = "config.yaml"

VALID_MODES = ("default", "consulting", "jobfair", "lecture", "interview")
SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".avi", ".webm")


@dataclasses.dataclass
class Config:
    mode: str = "default"
    output: Path = Path("output")
    scene_threshold: float = 0.3
    split: Optional[str] = None
    language: str = "ko"
    model: str = "large-v3"
    force: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.output, str):
            self.output = Path(self.output)


def load_config_file(path: Optional[Path]) -> dict[str, Any]:
    """YAML 설정 파일을 읽어 dict로 반환한다.

    `path`가 None이면 현재 디렉터리의 `config.yaml`을 찾고, 그마저도 없으면
    빈 dict를 반환한다(설정 파일은 선택 사항).
    명시적으로 `path`를 지정했는데 그 파일이 없으면 에러로 취급한다.
    """
    explicit = path is not None
    if path is None:
        path = Path(DEFAULT_CONFIG_FILENAME)

    if not path.exists():
        if explicit:
            raise ConfigError(f"설정 파일을 찾을 수 없습니다: {path}")
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"설정 파일을 파싱하지 못했습니다: {path}", hint=str(exc)) from exc

    if not isinstance(data, dict):
        raise ConfigError(
            f"설정 파일 형식이 올바르지 않습니다: {path}",
            hint="최상위는 key: value 매핑(dict) 형태여야 합니다.",
        )
    return data


def resolve_config(*, config_path: Optional[Path], cli_overrides: dict[str, Any]) -> Config:
    """기본값 -> config.yaml -> CLI 옵션(None이 아닌 것만) 순으로 병합해 Config를 만든다."""
    merged: dict[str, Any] = dataclasses.asdict(Config())

    file_values = load_config_file(config_path)
    unknown_keys = set(file_values) - set(merged)
    if unknown_keys:
        raise ConfigError(
            f"설정 파일에 알 수 없는 항목이 있습니다: {', '.join(sorted(unknown_keys))}",
            hint=f"허용된 항목: {', '.join(sorted(merged))}",
        )
    merged.update(file_values)

    merged.update({k: v for k, v in cli_overrides.items() if v is not None})

    try:
        return Config(**merged)
    except TypeError as exc:
        raise ConfigError(f"설정 값을 적용하지 못했습니다: {exc}") from exc

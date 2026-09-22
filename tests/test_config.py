"""설정 병합 로직(config.py) 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from prepreplay.config import Config, load_config_file, resolve_config
from prepreplay.errors import ConfigError


def test_default_config_values() -> None:
    cfg = Config()
    assert cfg.mode == "default"
    assert cfg.output == Path("output")
    assert cfg.scene_threshold == 0.3
    assert cfg.split is None
    assert cfg.language == "ko"
    assert cfg.model == "large-v3"
    assert cfg.force is False


def test_resolve_config_uses_defaults_when_nothing_given(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # cwd에 config.yaml이 없는 상태
    cfg = resolve_config(config_path=None, cli_overrides={})
    assert cfg == Config()


def test_resolve_config_file_overrides_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("mode: lecture\nscene_threshold: 0.15\n", encoding="utf-8")

    cfg = resolve_config(config_path=config_file, cli_overrides={})
    assert cfg.mode == "lecture"
    assert cfg.scene_threshold == 0.15
    assert cfg.language == "ko"  # 파일에 없는 값은 기본값 유지


def test_cli_overrides_beat_config_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("mode: lecture\n", encoding="utf-8")

    cfg = resolve_config(config_path=config_file, cli_overrides={"mode": "jobfair"})
    assert cfg.mode == "jobfair"


def test_none_cli_overrides_do_not_clobber_file_values(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("language: en\n", encoding="utf-8")

    cfg = resolve_config(config_path=config_file, cli_overrides={"language": None, "mode": "consulting"})
    assert cfg.language == "en"
    assert cfg.mode == "consulting"


def test_explicit_missing_config_path_raises(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.yaml"
    with pytest.raises(ConfigError):
        load_config_file(missing)


def test_unknown_config_key_raises(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("totally_unknown_key: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        resolve_config(config_path=config_file, cli_overrides={})


def test_non_mapping_config_raises(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config_file(config_file)

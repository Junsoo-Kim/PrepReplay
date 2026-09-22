"""prepreplay.pipeline (캐시 규칙) 테스트."""

from __future__ import annotations

from pathlib import Path

from prepreplay.pipeline import is_cached


def test_is_cached_false_when_missing(tmp_path: Path) -> None:
    assert is_cached(tmp_path / "nope.txt", force=False) is False


def test_is_cached_true_when_exists_and_not_forced(tmp_path: Path) -> None:
    p = tmp_path / "exists.txt"
    p.write_text("x", encoding="utf-8")
    assert is_cached(p, force=False) is True


def test_is_cached_false_when_forced_even_if_exists(tmp_path: Path) -> None:
    p = tmp_path / "exists.txt"
    p.write_text("x", encoding="utf-8")
    assert is_cached(p, force=True) is False

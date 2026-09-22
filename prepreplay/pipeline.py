"""파이프라인 공통 규칙.

각 단계(steps/*.py)는 산출물이 이미 있으면 재계산하지 않고 스킵하고, `--force`가
지정되면 무시하고 다시 만든다. STT(PR #4)·프레임 추출(PR #5) 등 이후 모든 단계가
이 규칙을 그대로 따른다. 여러 단계를 순서대로 실행하는 오케스트레이션은 규모가
커지는 이후 PR에서 이 모듈에 추가한다.
"""

from __future__ import annotations

from pathlib import Path


def is_cached(output_path: Path, *, force: bool) -> bool:
    """output_path가 이미 존재하고 force가 아니면 True(=스킵해도 됨)를 반환한다."""
    return output_path.exists() and not force

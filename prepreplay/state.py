"""파이프라인 재개(resume) 상태 추적: `output_dir/state.json`.

각 단계는 성공적으로 끝난 뒤에만 `mark_stage_complete()`로 완료 마커를 남긴다.
중단(Ctrl+C, 크래시)되면 해당 단계의 마커가 기록되지 않으므로, 다음 실행에서
산출물 파일이 남아 있어도 캐시로 신뢰하지 않고 처음부터 다시 만든다 — 부분적으로
쓰이다 중단된 산출물이 캐시로 오인되는 것을 막기 위함. `cli.py`가 이 마커를 보고
`pipeline.is_cached()`에 넘길 `force` 값을 단계별로 계산한다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

STATE_FILENAME = "state.json"
STATE_SCHEMA_VERSION = 1


def _state_path(output_dir: Path) -> Path:
    return output_dir / STATE_FILENAME


def load_state(output_dir: Path) -> dict:
    """state.json을 읽는다. 없거나 손상되었으면 빈 상태를 반환한다(관용적)."""
    path = _state_path(output_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"schema_version": STATE_SCHEMA_VERSION, "stages": {}}
    if not isinstance(data, dict) or not isinstance(data.get("stages"), dict):
        return {"schema_version": STATE_SCHEMA_VERSION, "stages": {}}
    return data


def is_stage_complete(output_dir: Path, stage: str) -> bool:
    return stage in load_state(output_dir).get("stages", {})


def mark_stage_complete(output_dir: Path, stage: str) -> None:
    """`stage`를 완료로 표시한다. 다른 단계의 기존 기록은 보존하고, 원자적으로 쓴다."""
    state = load_state(output_dir)
    state["schema_version"] = STATE_SCHEMA_VERSION
    state.setdefault("stages", {})[stage] = {
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds")
    }

    final_path = _state_path(output_dir)
    tmp_path = final_path.with_suffix(final_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, final_path)

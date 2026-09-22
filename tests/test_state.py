"""prepreplay/state.py 단위 테스트."""

from __future__ import annotations

import json

from prepreplay.state import is_stage_complete, load_state, mark_stage_complete


def test_is_stage_complete_false_when_state_missing(tmp_path):
    assert is_stage_complete(tmp_path, "audio") is False


def test_is_stage_complete_false_when_state_corrupt(tmp_path):
    (tmp_path / "state.json").write_text("{not valid json", encoding="utf-8")
    assert is_stage_complete(tmp_path, "audio") is False


def test_is_stage_complete_false_when_state_not_a_dict(tmp_path):
    (tmp_path / "state.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert is_stage_complete(tmp_path, "audio") is False


def test_mark_stage_complete_roundtrip(tmp_path):
    assert is_stage_complete(tmp_path, "audio") is False
    mark_stage_complete(tmp_path, "audio")
    assert is_stage_complete(tmp_path, "audio") is True


def test_mark_stage_complete_preserves_other_stages(tmp_path):
    mark_stage_complete(tmp_path, "audio")
    mark_stage_complete(tmp_path, "transcribe")

    assert is_stage_complete(tmp_path, "audio") is True
    assert is_stage_complete(tmp_path, "transcribe") is True

    state = load_state(tmp_path)
    assert set(state["stages"].keys()) == {"audio", "transcribe"}
    assert "completed_at" in state["stages"]["audio"]


def test_mark_stage_complete_writes_atomically_no_tmp_left_over(tmp_path):
    mark_stage_complete(tmp_path, "audio")

    assert not (tmp_path / "state.json.tmp").exists()
    state_path = tmp_path / "state.json"
    assert state_path.exists()
    json.loads(state_path.read_text(encoding="utf-8"))  # 유효한 JSON이어야 함

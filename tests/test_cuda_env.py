"""prepreplay.utils.cuda_env 테스트."""

from __future__ import annotations

import prepreplay.utils.cuda_env as cuda_env


def test_ensure_cuda_libs_discoverable_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(cuda_env, "_already_applied", False)
    # 두 번 호출해도 예외 없이 동작해야 한다 (설치 환경에 따라 아무 것도 안 할 수도 있음).
    cuda_env.ensure_cuda_libs_discoverable()
    cuda_env.ensure_cuda_libs_discoverable()
    assert cuda_env._already_applied is True

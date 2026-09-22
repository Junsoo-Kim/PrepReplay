"""pip로 설치된 nvidia-*-cu12 CUDA 런타임 라이브러리를 OS가 찾을 수 있게 등록한다.

Windows에서 CTranslate2(faster-whisper의 내부 추론 엔진)는 cublas64_12.dll 등을
PATH 기반으로 탐색한다. `os.add_dll_directory()`는 효과가 없다는 것을 PR #0에서
실측으로 확인했다 - PATH 맨 앞에 직접 넣어야 한다. 이 함수는 `faster_whisper`를
import하기 **전에** 호출해야 한다 (지연 로딩이라 늦어도 첫 추론 전이면 되지만,
안전하게 import 직전에 호출하는 것을 원칙으로 한다).

nvidia-cublas-cu12 / nvidia-cudnn-cu12가 설치되어 있지 않은 환경(GPU 없음, CPU
전용 설치)에서는 아무 것도 하지 않고 조용히 넘어간다 - CPU 모드로는 이 라이브러리가
필요 없다.
"""

from __future__ import annotations

import glob
import importlib.util
import os
import sys

_already_applied = False


def _nvidia_package_roots() -> list[str]:
    """설치된 `nvidia` 네임스페이스 패키지의 디렉터리 목록을 반환한다. 없으면 빈 리스트."""
    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return []
    return list(spec.submodule_search_locations)


def ensure_cuda_libs_discoverable() -> None:
    """nvidia-*-cu12 패키지의 라이브러리 디렉터리를 PATH(Windows)/LD_LIBRARY_PATH(그 외)에 등록한다.

    여러 번 호출해도 안전하다(멱등 - 두 번째 호출부터는 아무 일도 하지 않음).
    """
    global _already_applied
    if _already_applied:
        return
    _already_applied = True

    roots = _nvidia_package_roots()
    if not roots:
        return

    # Windows wheel은 nvidia/<pkg>/bin/*.dll, Linux wheel은 nvidia/<pkg>/lib/*.so
    subdir = "bin" if sys.platform == "win32" else "lib"
    lib_dirs: list[str] = []
    for root in roots:
        lib_dirs.extend(sorted(glob.glob(os.path.join(root, "*", subdir))))

    if not lib_dirs:
        return

    env_var = "PATH" if sys.platform == "win32" else "LD_LIBRARY_PATH"
    prefix = os.pathsep.join(lib_dirs)
    os.environ[env_var] = prefix + os.pathsep + os.environ.get(env_var, "")

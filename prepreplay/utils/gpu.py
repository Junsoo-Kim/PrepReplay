"""GPU(NVIDIA) 감지 - `nvidia-smi` 기반 경량 체크.

`prepreplay doctor`에서 하드웨어/드라이버 존재 여부만 빠르게 확인하는 용도다.
faster-whisper가 실제로 CUDA 추론을 할 수 있는지(cuBLAS/cuDNN DLL 로드 등)는
STT를 붙이는 PR #4에서 별도로 검증한다 - 여기서 통과해도 그쪽에서 실패할 수 있다.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
from typing import Optional


@dataclasses.dataclass
class GpuInfo:
    name: str
    driver_version: str
    memory_total: str


def detect_gpu() -> Optional[GpuInfo]:
    """첫 번째 NVIDIA GPU 정보를 반환한다. 없거나 nvidia-smi가 없으면 None."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return None

    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    first_line = result.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in first_line.split(",")]
    if len(parts) < 3:
        return None

    return GpuInfo(name=parts[0], driver_version=parts[1], memory_total=parts[2])

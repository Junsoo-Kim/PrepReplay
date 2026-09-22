"""ffmpeg stderr / 예외 문자열에서 알려진 실패 패턴을 찾아 사람이 읽을 수 있는
한국어 조치 힌트로 번역한다.

`errors.py`의 각 예외는 `hint` 필드를 갖지만, 지금까지는 대부분 ffmpeg stderr의
마지막 줄이나 Python 예외 문자열을 그대로 넣어왔다 (예: `AudioExtractionError`).
이 모듈은 자주 보는 실패 패턴에 한해 실제 조치를 안내하고, 매칭되는 패턴이 없으면
`None`을 반환해 호출부가 기존처럼 raw 텍스트로 폴백하게 한다 (힌트가 아예 사라지는
회귀를 막기 위함).
"""

from __future__ import annotations

import re
from typing import Optional

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"no space left on device", re.IGNORECASE),
        "디스크 여유 공간이 부족합니다. 공간을 확보한 뒤 다시 시도하세요.",
    ),
    (
        re.compile(r"permission denied", re.IGNORECASE),
        "파일에 접근할 권한이 없습니다. 다른 프로그램이 파일을 사용 중이지 않은지 확인하세요.",
    ),
    (
        re.compile(r"invalid data found when processing input|moov atom not found", re.IGNORECASE),
        "영상 파일이 손상되었거나 ffmpeg가 지원하지 않는 코덱입니다.",
    ),
    (
        re.compile(r"out of memory", re.IGNORECASE),
        "GPU/시스템 메모리가 부족합니다. 더 작은 모델(--model medium/small)을 사용해 보세요.",
    ),
    (
        re.compile(r"cu(da|blas|dnn)", re.IGNORECASE),
        '''GPU(CUDA) 런타임 문제입니다. `pip install -e ".[gpu]"`로 CUDA 라이브러리를 '''
        "설치하거나 CPU로 자동 폴백을 기다리세요.",
    ),
    (
        re.compile(r"connection|timed out|certificate|failed to download", re.IGNORECASE),
        "모델 다운로드에 실패했습니다. 네트워크 연결 또는 캐시된 모델 손상 여부를 확인하세요.",
    ),
    (
        re.compile(r"no such file or directory", re.IGNORECASE),
        "경로를 찾을 수 없습니다. 파일/디렉터리 경로를 확인하세요.",
    ),
]


def diagnose_failure(raw_text: Optional[str]) -> Optional[str]:
    """`raw_text`에서 알려진 실패 패턴을 찾아 조치 힌트를 반환한다.

    매칭되는 패턴이 없거나 `raw_text`가 비어 있으면 `None`을 반환한다.
    """
    if not raw_text:
        return None
    for pattern, hint in _PATTERNS:
        if pattern.search(raw_text):
            return hint
    return None

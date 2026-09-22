# PrepReplay 개발 계획 (PR 단위)

기획서(`PROPOSAL.md`)를 PR/커밋 단위 작업으로 분해한 실행 계획서.

---

## 0. 프로젝트 이해 요약

**한 줄 정의**: 로컬 영상 파일 → `스크립트(타임스탬프) + 장면 전환 프레임 + 매핑 인덱스`로 변환하여, Claude에게 "영상을 본 것처럼" 붙여넣을 수 있는 패키지를 만드는 로컬 CLI 도구.

**핵심 설계 원칙**
- 유스케이스(컨설팅/잡페어/강의/면접)별로 파이프라인을 분기하지 않는다. 파이프라인은 하나, **달라지는 건 마지막에 생성되는 프롬프트 템플릿뿐**이다.
- 모든 단계는 독립 실행 가능해야 한다 (STT는 느리므로, 프레임 추출 수정 때마다 STT를 다시 돌리면 안 된다 → **단계별 캐싱/스킵이 사실상 필수 요구사항**).
- 개인정보가 포함된 영상을 다루므로 산출물은 로컬에만 두고, `output/`은 절대 커밋하지 않는다.

**최종 산출물**
```
output/{video_name}/
├── transcript.srt / transcript.txt
├── frames/frame_00m12s.jpg ...
├── index.md          ← 타임스탬프 × 프레임 × 스크립트 매핑 (사람이 읽는 핵심 결과물)
└── summary_prompt.md ← 모드별 프롬프트 + index 내용 (Claude에 복붙용)
```

---

## 1. 기술 스택 확정안

| 항목 | 선택 | 근거 |
|---|---|---|
| 언어 | Python 3.12 (현재 로컬 버전) | 기획서 3.10+ 요구 충족 |
| 패키징 | `pyproject.toml` + venv, 콘솔 스크립트 `prepreplay` | `python analyze_video.py` 보다 확장성 good |
| CLI | **typer** | 서브커맨드/옵션 자동 도움말, argparse보다 유지보수 쉬움 |
| ffmpeg | CLI 직접 호출 (`subprocess`) | `ffmpeg-python`은 얇은 래퍼라 의존성 대비 이득 적음. 에러 메시지 파싱을 직접 통제 |
| STT | **faster-whisper** (CUDA) | 로컬에 RTX 5060 Ti 존재 → large-v3 실사용 가능. CPU 폴백 지원 |
| 진행 표시 | rich | 단계별 progress + 예쁜 에러 출력 |
| 설정 | YAML (`config.yaml`) + CLI 옵션 오버라이드 | 기획서 5절 반영 |
| 테스트 | pytest, ffmpeg로 생성한 5초짜리 합성 샘플 영상 사용 | 실제 개인 영상은 저장소에 넣지 않음 |

### 환경 검증 결과 (PR #0 완료, 2026-09-22)

로컬 머신에서 실제로 확인한 사실. 이후 PR은 이 결과를 전제로 진행한다.

| 항목 | 결과 |
|---|---|
| ffmpeg / ffprobe | 9.0.2 (Gyan build, winget) 설치 완료 |
| Python venv | `.venv` (Python 3.12.10, pip 26.2.1) |
| GPU | RTX 5060 Ti 16GB, 드라이버 596.49, CUDA 13.2 |
| CTranslate2 | 4.8.2, CUDA 디바이스 1개 인식, `float16`/`int8_float16` 지원 |
| faster-whisper | 1.2.1, GPU 추론 동작 확인 (`tiny`, `large-v3` 모두) |
| large-v3 모델 | 다운로드 완료 (HF 캐시 2.9GB), 최초 로드 42s / 이후 캐시 로드, 5초 오디오 추론 0.6s |
| CUDA 런타임 | `nvidia-cublas-cu12` 12.9.2.10, `nvidia-cudnn-cu12` 9.26.0.51 |
| 기본 브랜치 | `master` → `main` 으로 변경 |

#### 검증하며 확인된 구현 제약 (PR #4 / #5에 반영 필수)

1. **Windows CUDA DLL 탐색 — PATH로만 해결된다.**
   CTranslate2가 `cublas64_12.dll`을 로드할 때 `os.add_dll_directory()`는 **효과가 없다**(실측 확인).
   `faster_whisper` import **이전에** `os.environ["PATH"]` 앞쪽에 nvidia 패키지의 `bin` 경로들을 붙여야 한다:
   ```python
   dll_dirs = sorted(glob.glob(os.path.join(site_packages, "nvidia", "*", "bin")))
   os.environ["PATH"] = os.pathsep.join(dll_dirs) + os.pathsep + os.environ["PATH"]
   ```
   → 이 처리를 안 하면 모델 로드는 성공하고 **추론 시점에** `RuntimeError: Library cublas64_12.dll is not found`로 죽는다.
   PR #4에서 이 경로 주입을 모듈 최상단에 두고, `prepreplay doctor`가 DLL 탐색 가능 여부까지 점검하도록 한다.

2. **ffmpeg 9에서 `-vsync vfr`는 쓸 수 없다.** `-fps_mode vfr`로 대체해야 프레임 추출이 동작한다.

3. **장면 감지 타임스탬프는 `showinfo` 필터의 stderr 출력에서 `pts_time:`을 파싱**해 얻는다.
   `-vf "select='gt(scene,0.3)',showinfo" -fps_mode vfr` 조합으로 전환 지점 검출 + 프레임 저장이 한 번에 된다 (합성 영상으로 동작 확인).

4. **GPU 실패 시 CPU 폴백은 그대로 필요하다.** 위 PATH 주입이 빠지거나 CUDA 런타임 패키지가 없는 환경에서 그대로 크래시하므로, PR #4에서 추론 단계를 try/except로 감싸 CPU 재시도한다.

### 디렉터리 구조 (목표)
```
prepreplay/
├── cli.py            # typer 엔트리포인트
├── config.py         # 설정 로드/병합
├── pipeline.py       # 단계 오케스트레이션 + 캐시 스킵
├── steps/
│   ├── audio.py      # 오디오 추출
│   ├── transcribe.py # STT
│   ├── frames.py     # 장면 감지/프레임 추출
│   └── package.py    # index.md / summary_prompt.md
├── templates/        # 모드별 프롬프트 템플릿
└── utils/ffmpeg.py, utils/timecode.py
tests/
```

---

## 2. PR 로드맵

각 PR = 브랜치 1개 = 리뷰 가능한 단위. **모든 PR은 그 자체로 실행 가능한 상태**로 끝난다(빌드만 되고 안 돌아가는 중간 상태 금지).

> 저장소에 커밋이 없고 현재 브랜치가 `master`다. PR #1 전에 기본 브랜치를 `main`으로 할지 `master`로 둘지 먼저 정한다.

---

### PR #1 — 저장소 초기화 및 프로젝트 스캐폴딩
**브랜치**: `chore/project-init`

- `.gitignore` (venv, `__pycache__`, `output/`, `*.mp4`, `*.wav`, 모델 캐시)
- `pyproject.toml` — 패키지 메타 + 의존성(typer, rich, pyyaml) + `prepreplay` 콘솔 스크립트
- `README.md` — 설치/사용법 뼈대, ffmpeg 사전 설치 안내
- `PROPOSAL.md`(구 기획서.md), `DEVELOPMENT_PLAN.md` → `docs/` 로 이동
- 빈 패키지 구조(`prepreplay/__init__.py`, `steps/`, `tests/`)

**DoD**: `pip install -e .` 성공, `prepreplay --help` 출력됨.

---

### PR #2 — CLI 골격 + 설정 시스템 + 환경 진단
**브랜치**: `feat/cli-skeleton`

- `prepreplay run <video>` 명령: 옵션 `--mode`, `--output`, `--scene-threshold`, `--split`, `--language`, `--model`, `--force`
- `config.yaml` 로딩 → CLI 옵션이 파일 값을 덮어쓰는 병합 규칙
- `prepreplay doctor`: ffmpeg/ffprobe 존재 여부, CUDA 사용 가능 여부, 디스크 여유 체크
- 입력 검증: 파일 존재, 확장자(mp4/mov/mkv/avi/webm), ffprobe로 길이·해상도 읽기
- 출력 폴더 규칙(`output/{video_stem}/`) 생성
- 커스텀 예외 계층 + rich 기반 "어느 단계에서 왜 실패했는지" 에러 포맷 (기획서 4.2)

**DoD**: `prepreplay doctor`가 현재 환경을 정확히 진단. `prepreplay run sample.mp4` 실행 시 영상 메타 정보를 출력하고 빈 출력 폴더를 만든다.

---

### PR #3 — 오디오 추출 (파이프라인 1단계)
**브랜치**: `feat/audio-extract`

- ffmpeg로 `audio.wav` 추출 (16kHz mono PCM — Whisper 입력 최적 포맷)
- 무음/오디오 트랙 없음 케이스 감지 후 명확한 에러
- ffmpeg 진행률(`-progress pipe:1`) 파싱 → rich progress bar
- 이미 산출물이 있으면 스킵, `--force`로 재생성 (**캐시 규칙 확립 — 이후 모든 단계가 이 패턴 따름**)

**DoD**: 샘플 영상 → `audio.wav` 생성, 재실행 시 "skipped (cached)" 출력.

---

### PR #4 — Whisper STT → transcript.srt / transcript.txt (파이프라인 2단계)
**브랜치**: `feat/whisper-transcribe`

- faster-whisper 통합, 모델 크기 옵션(`--model large-v3` 기본, small/medium 선택 가능)
- 디바이스 자동 선택: CUDA 시도 → 실패 시 CPU 폴백 + 경고
- 한국어 우선: `language` 기본 `ko`, `auto` 지정 시 자동 감지
- 출력: `transcript.srt`(타임스탬프), `transcript.txt`(순수 텍스트), `segments.json`(다음 단계용 구조화 데이터)
- 세그먼트 단위 진행률 표시 (총 길이 대비 %)

**DoD**: 10분 한국어 샘플에서 실사용 가능한 정확도 확인(기획서 10절). `segments.json` 스키마 확정 — 이후 단계가 여기에 의존.

> 여기까지가 기획서의 **마일스톤 1단계(MVP)**.

---

### PR #5 — 장면 전환 감지 및 프레임 추출 (파이프라인 3단계)
**브랜치**: `feat/scene-frames`

- ffmpeg `select='gt(scene,X)'` + `showinfo` 로그 파싱 → 장면 전환 타임스탬프 목록
- `frames/frame_00m12s.jpg` 명명 규칙 (기획서 4.1)
- `--scene-threshold` 노출(기본 0.3), `--max-frames` 상한으로 폭증 방지
- 장면 전환이 0건일 때(고정 카메라 컨설팅 영상 등) **N분 간격 균등 샘플링으로 폴백** — 기획서에 없지만 컨설팅/면접 유스케이스에서 반드시 발생
- `frames.json`에 타임스탬프 메타 저장

**DoD**: 슬라이드 있는 영상은 슬라이드 전환마다, 고정 카메라 영상은 균등 간격으로 프레임이 뽑힌다.

> 기획서 **마일스톤 2단계**.

---

### PR #6 — index.md 생성 (파이프라인 4단계)
**브랜치**: `feat/index-generation`

- `segments.json` × `frames.json` 병합: 각 프레임 시점부터 다음 프레임 직전까지의 스크립트를 한 섹션으로 묶음
- 기획서 7절 예시 포맷 그대로 출력 (`## 00:03 - 00:45` / `[화면: frame_00m03s.jpg]` / 스크립트)
- 상대 경로 이미지 링크 → Obsidian/VSCode 프리뷰에서 바로 보임
- 헤더에 메타 정보(영상명, 길이, 프레임 수, 모델, 생성 시각)

**DoD**: `index.md`만 읽고 영상 흐름 파악 가능 (기획서 10절 완료 기준).

---

### PR #7 — summary_prompt.md + 모드별 템플릿
**브랜치**: `feat/mode-prompts`

- `templates/{consulting,jobfair,lecture,interview,default}.md`
- `--mode` 값에 따라 템플릿 선택, 기획서 6절 문구를 기본값으로 탑재
- `summary_prompt.md` = 모드 지시문 + 영상 메타 + 스크립트(또는 index) 본문 → **복붙 즉시 사용 가능**
- 사용자 정의 템플릿 경로 지정 옵션(`--template`)

**DoD**: `summary_prompt.md` 그대로 Claude에 붙여 유효한 결과 획득 (기획서 10절).

> 기획서 **마일스톤 3단계** 완료. 여기서 한 번 태그(`v0.1.0`) 권장.

---

### PR #8 — 긴 영상 구간 분할
**브랜치**: `feat/split-chunks`

- `--split 10m` → `chunks/part_01_000m-010m.md` 형태로 스크립트 분할 저장
- 각 청크마다 해당 구간 프레임 목록 + 개별 프롬프트 동봉
- 문장 중간이 아니라 **세그먼트 경계에서** 자르기
- 30분 초과 영상은 분할을 권장하는 경고 출력

**DoD**: 1시간 영상이 6개 청크로 쪼개지고, 각 청크를 독립적으로 Claude에 넣을 수 있다.

---

### PR #9 — 안정화: 로깅 / 에러 / 재개
**브랜치**: `chore/robustness`

- `run.log` 단계별 기록, `--verbose` / `--quiet`
- 중단 후 재실행 시 완료 단계 스킵하고 이어서 진행 (`state.json`)
- ffmpeg/whisper 실패 시 원인별 사람이 읽을 수 있는 메시지 + 조치 안내
- 전체 파이프라인 E2E 테스트 (합성 샘플 영상 생성 fixture)

**DoD**: STT 도중 Ctrl+C → 재실행 시 오디오 추출부터 다시 하지 않는다.

> 기획서 **마일스톤 4단계** 완료 → `v1.0.0`.

---

### PR #10+ — 선택 확장 (기획서 4.3 / 마일스톤 5단계)
각각 독립 PR로. 우선순위 순:

1. `feat/batch-processing` — 디렉터리 입력으로 강의 시리즈 일괄 처리
2. `feat/diarization` — pyannote.audio 화자 분리, `[화자1]` 라벨 삽입 (컨설팅/스터디 복기 가치 큼, 단 HuggingFace 토큰 필요)
3. `feat/obsidian-export` — Obsidian vault 포맷 export
4. `feat/frame-dedup` — 유사 프레임 제거로 이미지 수 압축

---

## 3. PR 순서 의존성

```
#1 init
 └─ #2 CLI/설정/doctor
     ├─ #3 오디오 ──▶ #4 STT ──┐
     └─ #5 프레임 ─────────────┴─▶ #6 index ─▶ #7 프롬프트 ─▶ #8 분할 ─▶ #9 안정화
```
`#3/#4`(오디오·STT 라인)와 `#5`(프레임 라인)는 서로 독립이라 병렬 작업 가능. `#6`이 둘을 합치는 지점이므로 `segments.json` / `frames.json` 스키마를 `#4`, `#5`에서 확정해 둔다.

## 4. 공통 규칙

- 커밋 메시지: `feat|fix|chore|docs|test: 요약` (한국어 본문 허용)
- 각 PR 본문에 **직접 실행한 명령어와 실제 출력**을 붙인다 (영상 도구는 유닛 테스트만으론 검증이 안 됨)
- 실제 개인 영상·산출물은 절대 커밋 금지 (`output/`, `*.mp4` ignore)
- 새 산출물 파일 스키마가 생기면 `README.md`의 출력 구조 섹션을 같은 PR에서 갱신

# PrepReplay

ChatGPT, Claude 등 LLM이 로컬에 있는 내 동영상의 내용을 완벽하게 이해시킨 채로 답변을 생성하고 싶어 이 프로젝트를 만들었습니다.
기존에는 유튜브 링크를 통한 전달밖에 안되고, 그 마저도 자동 생성 자막이나 스크립트만 읽을 수 있었습니다.

이 프로젝트는 로컬에 저장된 영상 파일(취업 컨설팅, 채용설명회, 기술 강의, 면접/코딩테스트 스터디 녹화 등)을
자동으로 분석하여, **음성 스크립트(타임스탬프 포함) + 장면 전환 핵심 프레임 이미지**로 분해하는
로컬 CLI 도구입니다. 결과물은 Claude에게 "영상을 본 것처럼" 붙여넣을 수 있는 형태로 정리됩니다.

LLM이 프로젝트 처리 결과물을 받으면 영상의 전체 내용과 화면 변화를 이해한 채로 답변을 생성할 수 있게 됩니다.

자세한 사용법은 [docs/MANUAL.md](docs/MANUAL.md), 배경과 설계는
[docs/PROPOSAL.md](docs/PROPOSAL.md), 개발 단계별 계획은
[docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md), 현재 진행 상황은
[docs/MILESTONE.md](docs/MILESTONE.md)를 참고하세요.

## 필수 사전 설치

이 도구는 로컬 실행 전용이며, 아래 두 가지가 시스템에 설치되어 있어야 합니다.

- **[ffmpeg](https://ffmpeg.org/)** (오디오 추출, 장면 감지, 프레임 추출)
  - Windows: `winget install Gyan.FFmpeg`
  - macOS: `brew install ffmpeg`
  - Linux: 배포판 패키지 매니저 사용 (`apt install ffmpeg` 등)
- **Python 3.10 이상**

GPU(NVIDIA)가 있으면 음성 인식(faster-whisper) 속도가 크게 빨라집니다. 없어도 CPU로 자동
전환되어 동작합니다 (속도는 영상 길이의 1~2배 예상).

## 설치

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -e .

# GPU(NVIDIA)를 사용하려면 CUDA 런타임 라이브러리도 함께 설치
pip install -e ".[gpu]"

# 화자 분리(--diarize)를 쓰려면 pyannote.audio도 함께 설치
pip install -e ".[diarization]"
```

## 사용법

핵심 파이프라인(오디오 추출 → STT → 프레임 추출 → index.md → summary_prompt.md)이 모두
동작합니다. 각 실행은 `output/{video_name}/run.log`에 단계별 로그를 남기고,
`output/{video_name}/state.json`으로 완료된 단계를 추적합니다 — 중단(Ctrl+C, 크래시)
후 `prepreplay run`을 그대로 다시 실행하면 완료된 단계는 건너뛰고 중단된 단계부터
이어서 진행합니다. `run`에 영상 파일 대신 디렉터리를 넘기면 그 안의 영상들을 파일명순으로
일괄 처리합니다 — 하나가 실패해도 나머지는 계속 처리되고, 끝에 성공/실패 요약이 나옵니다.
`--diarize`로 화자 분리(누가 말했는지 `[화자1]`/`[화자2]` 라벨)도 켤 수 있습니다(별도 설치와
HuggingFace 토큰 필요, 아래 참고). 그 밖의 편의 기능은
[docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)의 PR 로드맵에 따라 계속 추가됩니다.

```bash
prepreplay --version

# 기본 실행
prepreplay run ~/videos/consulting_0921.mp4

# 유스케이스 지정 (요약 프롬프트 템플릿에 반영: consulting/jobfair/lecture/interview)
prepreplay run ~/videos/jobfair_kakao.mp4 --mode jobfair

# 직접 작성한 프롬프트 템플릿 사용
prepreplay run ~/videos/lecture_algo.mp4 --template ./my_template.md

# 장면 감지 민감도, 프레임 수 상한 조절
prepreplay run ~/videos/interview_practice.mp4 --scene-threshold 0.2 --max-frames 50

# 긴 영상(30분+)은 10분 단위로 구간 분할 - chunks/part_01_000m-010m.md 형태로 생성
prepreplay run ~/videos/lecture_algo.mp4 --split 10m

# 상세 로그를 stderr에도 함께 출력 (run.log에는 항상 기록됨)
prepreplay run ~/videos/lecture_algo.mp4 --verbose

# 진행 상황 출력을 억제 (에러는 계속 출력됨)
prepreplay run ~/videos/lecture_algo.mp4 --quiet

# 디렉터리를 넘기면 안의 영상들을 파일명순으로 일괄 처리 (하나가 실패해도 나머지는 계속 진행)
prepreplay run ~/videos/lecture_series/ --mode lecture

# 화자 분리 활성화 (컨설팅/스터디처럼 여러 명이 대화하는 영상에 유용)
export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx   # https://huggingface.co/settings/tokens 에서 발급
prepreplay run ~/videos/consulting_0921.mp4 --mode consulting --diarize

# 환경 진단 (ffmpeg/CUDA 등 확인)
prepreplay doctor
```

실행이 끝나면 `output/{video_name}/summary_prompt.md`를 그대로 복사해 Claude에 붙여넣으면
됩니다. `--split`을 쓰면 `chunks/` 폴더의 파일들을 구간별로 각각 붙여넣을 수도 있습니다
(한 번에 넣기엔 스크립트가 너무 긴 긴 영상용).

## 출력 구조

```
output/{video_name}/
├── audio.wav                # 추출된 오디오 (16kHz mono 16-bit PCM WAV)
├── segments.json             # STT 결과 구조화 데이터 (이후 단계가 의존)
├── transcript.srt           # 타임스탬프 포함 스크립트
├── transcript.txt           # 순수 텍스트
├── frames/                  # 장면 전환 시점 프레임 이미지
├── frames.json               # 프레임 메타데이터
├── index.md                 # 타임스탬프-프레임-스크립트 매핑
├── summary_prompt.md        # Claude에 바로 붙여넣을 요약 프롬프트
├── state.json                # 재개(resume)용 단계별 완료 상태 (커밋 금지)
├── run.log                   # 실행 단계별 로그 (커밋 금지)
├── diarization.json          # --diarize 사용 시: 화자별 발화 구간
└── chunks/                  # --split 사용 시: 구간별 요약 프롬프트
    ├── part_01_000m-010m.md
    └── manifest.json
```

`--diarize`를 쓰면 `segments.json`/`transcript.srt`/`transcript.txt`/`index.md`의 각 문장
앞에 `[화자1]`, `[화자2]` 같은 라벨이 붙습니다.

**화자 분리 사용 전 준비**: [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
모델 사용 약관에 동의하고, [HuggingFace 토큰](https://huggingface.co/settings/tokens)을
발급받아 `HF_TOKEN` 환경변수로 지정하거나 `--hf-token`으로 넘겨야 합니다.

## 개발

```bash
pip install -e ".[dev]"
pytest
```

## 주의사항

- 컨설팅/면접 세션처럼 개인정보가 포함된 영상을 다룰 수 있습니다. `output/` 폴더는 로컬에만
  보관하고 외부 업로드 시 주의하세요 (`.gitignore`에 기본 제외 처리되어 있습니다).

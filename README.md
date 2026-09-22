# PrepReplay

로컬에 저장된 영상 파일(취업 컨설팅, 채용설명회, 기술 강의, 면접/코딩테스트 스터디 녹화 등)을
자동으로 분석하여, **음성 스크립트(타임스탬프 포함) + 장면 전환 핵심 프레임 이미지**로 분해하는
로컬 CLI 도구입니다. 결과물은 Claude에게 "영상을 본 것처럼" 붙여넣을 수 있는 형태로 정리됩니다.

자세한 배경과 설계는 [docs/기획서.md](docs/기획서.md), 개발 단계별 계획은
[docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)를 참고하세요.

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
```

## 사용법

핵심 파이프라인(오디오 추출 → STT → 프레임 추출 → index.md → summary_prompt.md)이 모두
동작합니다. 구간 분할(`--split`) 등 일부 편의 기능은 아직 없으며,
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

# 환경 진단 (ffmpeg/CUDA 등 확인)
prepreplay doctor
```

실행이 끝나면 `output/{video_name}/summary_prompt.md`를 그대로 복사해 Claude에 붙여넣으면
됩니다.

## 출력 구조

```
output/{video_name}/
├── transcript.srt          # 타임스탬프 포함 스크립트
├── transcript.txt          # 순수 텍스트
├── frames/                 # 장면 전환 시점 프레임 이미지
├── index.md                # 타임스탬프-프레임-스크립트 매핑
└── summary_prompt.md        # Claude에 바로 붙여넣을 요약 프롬프트
```

## 개발

```bash
pip install -e ".[dev]"
pytest
```

## 주의사항

- 컨설팅/면접 세션처럼 개인정보가 포함된 영상을 다룰 수 있습니다. `output/` 폴더는 로컬에만
  보관하고 외부 업로드 시 주의하세요 (`.gitignore`에 기본 제외 처리되어 있습니다).

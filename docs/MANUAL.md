# MANUAL

PrepReplay 사용 설명서. 설치부터 옵션, 출력물 해석, 문제 해결까지 담는다.
프로젝트 배경은 [PROPOSAL.md](PROPOSAL.md), 진행 상황은 [MILESTONE.md](MILESTONE.md) 참고.

---

## 1. 설치

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -e .              # 기본 설치 (CPU로 동작)
pip install -e ".[gpu]"       # GPU(NVIDIA) 가속용 CUDA 런타임까지 함께 설치
pip install -e ".[dev]"       # 개발용 (pytest 포함)
```

**사전 요구사항**
- ffmpeg (Windows: `winget install Gyan.FFmpeg`, macOS: `brew install ffmpeg`)
- Python 3.10 이상
- (선택) NVIDIA GPU + 드라이버 — 없으면 자동으로 CPU 모드로 동작

설치 후 `prepreplay doctor`로 환경이 제대로 잡혔는지 먼저 확인하는 것을 권장한다.

---

## 2. 빠른 시작

```bash
prepreplay run ~/videos/consulting_0921.mp4
```

이 한 줄로 다음이 순서대로 실행된다:

1. 입력 영상 검증 (확장자, 존재 여부)
2. ffprobe로 메타데이터 확인 (길이/해상도/코덱)
3. 오디오 추출 (`audio.wav`)
4. Whisper STT (`transcript.srt`, `transcript.txt`, `segments.json`)
5. 장면 감지 프레임 추출 (`frames/`, `frames.json`)
6. `index.md` 생성 (스크립트+프레임 매핑)
7. `summary_prompt.md` 생성 (Claude에 바로 붙여넣을 프롬프트)

끝나면 `output/consulting_0921/summary_prompt.md`를 열어 전체를 복사해 Claude에 붙여넣으면 된다.

---

## 3. 명령어

### `prepreplay doctor`

ffmpeg/ffprobe/GPU/디스크 여유공간을 점검한다. 필수 도구(ffmpeg/ffprobe)가 없으면
설치 안내와 함께 exit code 1로 종료한다. 문제가 생겼을 때 제일 먼저 실행해볼 명령.

### `prepreplay run <video> [옵션...]`

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `<video>` (필수) | - | 분석할 로컬 영상 경로. mp4/mov/mkv/avi/webm 지원 |
| `--mode` | `default` | 요약 프롬프트 지시문 선택. `consulting`/`jobfair`/`lecture`/`interview`/`default` |
| `--output` | `./output` | 결과물 상위 폴더. 실제로는 `{output}/{영상파일명}/` 에 저장됨 |
| `--scene-threshold` | `0.3` | 장면 전환 감지 민감도(0.0~1.0). 낮을수록 프레임이 더 많이 잡힘 |
| `--max-frames` | `200` | 프레임 수 상한. 넘으면 균등한 간격으로 솎아냄 |
| `--split` | (없음) | 긴 영상을 구간별로 나눔. 예: `10m`, `1h`, `600s`, 숫자만 쓰면 분 단위 |
| `--language` | `ko` | STT 언어 코드. `en`, 자동 감지는 `auto` |
| `--model` | `large-v3` | Whisper 모델 크기: `tiny`/`base`/`small`/`medium`/`large-v3` (작을수록 빠르지만 부정확) |
| `--template` | (없음) | 커스텀 프롬프트 템플릿 파일 경로. 지정하면 `--mode`의 내장 지시문 대신 사용 |
| `--force` / `--no-force` | `--no-force` | 이미 만들어진 산출물이 있어도 강제로 다시 생성 |
| `--config` | `./config.yaml` (있으면) | 설정 파일 경로 직접 지정 |

**옵션 우선순위**: CLI 옵션(명시적으로 지정한 것) > `config.yaml` > 내장 기본값.

**예시**
```bash
# 채용설명회 영상, 요약 프롬프트를 jobfair 형식으로
prepreplay run ~/videos/jobfair_kakao.mp4 --mode jobfair

# 1시간짜리 강의, 10분 단위로 나눠서
prepreplay run ~/videos/lecture_algo.mp4 --mode lecture --split 10m

# 고정 카메라 면접 연습 영상, 장면 감지를 더 촘촘하게
prepreplay run ~/videos/interview_practice.mp4 --scene-threshold 0.2

# 빠르게 미리보기만 (정확도보다 속도 우선)
prepreplay run ~/videos/sample.mp4 --model tiny

# 직접 쓴 지시문으로
prepreplay run ~/videos/mystery.mp4 --template ./my_prompt.md
```

---

## 4. 설정 파일 (`config.yaml`)

매번 같은 옵션을 치기 귀찮다면 프로젝트 루트에 `config.yaml`을 두면 된다.
`config.example.yaml`을 복사해서 시작하면 편하다.

```bash
cp config.example.yaml config.yaml   # Windows: copy config.example.yaml config.yaml
```

```yaml
mode: lecture
output: output
scene_threshold: 0.3
max_frames: 200
split: 10m
language: ko
model: large-v3
template: null
force: false
```

CLI에서 옵션을 따로 안 주면 이 값들이 쓰인다. CLI로 값을 주면 그 값이 이긴다.
`config.yaml`은 개인 로컬 설정이라 `.gitignore`에 이미 제외되어 있다.

---

## 5. 결과물 구조와 읽는 법

```
output/{영상파일명}/
├── audio.wav            # 16kHz mono WAV (중간 산출물, 안 봐도 됨)
├── transcript.srt       # 타임스탬프 있는 자막 형식 스크립트
├── transcript.txt       # 순수 텍스트 스크립트 (세그먼트별 한 줄)
├── segments.json        # STT 구조화 데이터 (언어/모델/디바이스/세그먼트 목록)
├── frames/               # 장면 전환 시점 프레임 이미지 (frame_00m12s.jpg 형식)
├── frames.json           # 프레임 메타데이터 (추출 방식/타임스탬프)
├── index.md              # ★ 가장 먼저 열어볼 파일 - 화면+스크립트가 시간순으로 매핑됨
├── summary_prompt.md     # ★ 이걸 복사해서 Claude에 붙여넣으면 됨
└── chunks/                # --split 지정 시에만 생성
    ├── manifest.json
    ├── part_01_000m-010m.md   # 구간별로 독립된 요약 프롬프트
    └── ...
```

- **`index.md`**: 사람이 훑어보는 용도. 어느 화면에서 무슨 말을 했는지 한눈에 파악하려면 이 파일.
- **`summary_prompt.md`**: Claude에게 시킬 요청 문구(모드별 지시문) + 영상 정보 + `index.md`의
  본문을 합친 파일. 그대로 복사해서 붙여넣으면 된다.
- **`chunks/*.md`**: `summary_prompt.md`가 너무 길 때(긴 영상) 구간별로 나눠 쓸 수 있는 버전.
  각 파일이 그 자체로 완결된 프롬프트라 구간 하나만 떼서 붙여넣어도 된다.

두 번째 파일 모두 **세그먼트(문장) 단위로만 나뉘고 문장 중간이 잘리지 않는다.**

---

## 6. 캐시와 재실행

각 단계(오디오 추출/STT/프레임 추출/index.md/summary_prompt.md/구간 분할)는 결과 파일이
이미 있으면 그 단계를 건너뛴다. 즉 같은 영상으로 `--mode`만 바꿔서 다시 실행하면
오디오 추출과 STT(가장 오래 걸리는 두 단계)는 재사용되고 `summary_prompt.md`만 새로 만들어진다.

```bash
# 최초 실행 (오래 걸림)
prepreplay run video.mp4 --mode default

# mode만 바꿔서 재실행 (오디오/STT/프레임은 스킵, summary_prompt.md만 재생성)
prepreplay run video.mp4 --mode consulting

# 전부 강제로 다시 만들기
prepreplay run video.mp4 --mode consulting --force
```

`--scene-threshold`나 `--model`처럼 이전 단계의 산출물에 영향을 주는 옵션을 바꿨다면
`--force`를 꼭 같이 써야 한다 (그렇지 않으면 예전 값으로 만든 결과가 그대로 재사용된다).

---

## 7. 모드별 프롬프트

`--mode`는 `summary_prompt.md`/`chunks/*.md`에 들어갈 지시문만 바꾼다(분석 파이프라인
자체는 모든 모드에서 동일하다).

| 모드 | 용도 | 기본 지시문 요지 |
|---|---|---|
| `consulting` | 취업 컨설팅 세션 복기 | 피드백을 항목별로 정리, 액션아이템 추출 |
| `jobfair` | 채용설명회 요약 | 회사/직무/기술스택/연봉복지/지원프로세스를 표로 정리 |
| `lecture` | 기술 강의 정리 | 개념별 타임스탬프 목차, 헷갈리는 부분 짚기 |
| `interview` | 면접/코딩테스트 스터디 복기 | 답변의 부족한 점과 개선 방향 제안 |
| `default` | 그 외 전부 | 핵심 위주 요약 + 타임스탬프 정리 |

지시문을 직접 쓰고 싶으면 `.md` 파일 하나 만들어서 `--template 경로`로 넘기면 된다.
(`prepreplay/templates/*.md`를 참고해서 비슷한 톤으로 쓰면 무난하다.)

---

## 8. 문제 해결

**`prepreplay doctor`가 ffmpeg 누락이라고 함**
→ `winget install Gyan.FFmpeg`(Windows) 또는 `brew install ffmpeg`(macOS) 후 터미널을
  새로 열어 PATH를 갱신한다.

**GPU가 있는데 CPU로만 도는 것 같음**
→ `pip install -e ".[gpu]"`로 CUDA 런타임을 설치했는지 확인. 그래도 안 되면 `run` 실행 중
  `⚠ GPU 처리에 실패해 CPU로 전환합니다` 메시지가 뜨는지 확인 — 뜬다면 GPU/드라이버/CUDA
  런타임 버전 문제이며, CPU로는 정상 동작하니 급하지 않으면 그냥 둬도 된다.

**"오디오 트랙이 없어 스크립트를 추출할 수 없습니다"**
→ 영상에 소리가 없다는 뜻. 화면 녹화만 하고 마이크를 안 켰거나, 무음 구간만 있는 영상.
  이 도구는 음성 기반 분석이 핵심이라 오디오가 필수다.

**"음성을 인식하지 못했습니다 (세그먼트 0개)"**
→ 오디오는 있지만 Whisper가 말소리를 하나도 못 찾은 경우(배경음악만 있거나 너무 조용함).
  `--language`를 확인하거나(`ko`인데 실제로는 영어라면 오작동 가능), `--model`을 더 큰
  것으로 바꿔 재시도.

**장면 전환 프레임이 하나도 안 뽑히는 것 같음**
→ 정상이다. 고정 카메라 영상(컨설팅/면접 등)은 장면 전환이 거의 없어서 자동으로 일정
  간격(기본 60초)으로 프레임을 뽑는 방식으로 전환된다. 실행 중 `⚠ 장면 전환이 감지되지
  않았습니다` 메시지로 알려준다.

**프레임이 너무 많이/적게 나옴**
→ `--scene-threshold`를 조절한다(낮추면 더 많이, 높이면 더 적게). 그래도 너무 많으면
  `--max-frames`로 상한을 걸면 된다.

**설정 파일 오류(`ConfigError`)**
→ `config.yaml`의 들여쓰기/키 이름을 확인. 허용된 키는 `config.example.yaml`에 있는 것들
  (`mode`, `output`, `scene_threshold`, `max_frames`, `split`, `language`, `model`,
  `template`, `force`)뿐이며 오타가 있으면 에러 메시지에 허용된 목록이 함께 뜬다.

**개인정보가 걱정됨**
→ 컨설팅/면접처럼 민감한 내용을 다루는 영상이 많다면, `output/` 폴더(그리고 `config.yaml`
  이 있다면 그 안의 경로들)를 외부에 업로드하지 않도록 주의한다. `.gitignore`에는 이미
  `output/`이 기본 제외되어 있다.

---

## 9. 개발자용

```bash
pip install -e ".[dev]"
pytest -q
```

테스트는 ffmpeg로 즉석에서 만든 합성 영상을 사용하며, 실제 사용자 영상은 저장소에 절대
포함하지 않는다. 기여/구조에 대한 자세한 내용은 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)를
참고.

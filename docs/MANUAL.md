# PrepReplay 사용 설명서

로컬에 저장된 영상을 음성 스크립트와 화면 캡처로 분해해, LLM(Claude 등)에 그대로 붙여넣을 수
있는 프롬프트 파일까지 만들어 주는 프로그램입니다. 영상을 다시 보지 않고도 내용을 파악하거나,
LLM에게 "영상을 본 것처럼" 맥락을 넘기는 것이 목적입니다.

> 본인이 열람·보관할 권한이 있는 영상에만 사용하세요. 컨설팅 세션이나 면접 녹화처럼 개인정보가
> 담긴 영상을 다룰 수 있으므로, `output/` 폴더를 외부에 업로드할 때는 주의해야 합니다.

프로젝트 배경은 [PROPOSAL.md](PROPOSAL.md), 진행 상황은 [MILESTONE.md](MILESTONE.md)를
참고하세요.

## 프로그램이 하는 일

명령 한 번(`prepreplay run 영상파일`)으로 다음이 순서대로 실행됩니다.

1. 입력 영상의 존재와 확장자를 확인하고, ffprobe로 길이·해상도·코덱을 읽습니다.
2. 영상에서 오디오만 뽑아 `audio.wav`로 저장합니다.
3. (선택) 화자 분리를 켰다면 누가 언제 말했는지 감지합니다.
4. Whisper로 음성을 텍스트로 바꿔 `transcript.srt`, `transcript.txt`, `segments.json`을 만듭니다.
5. 화면이 크게 바뀌는 시점을 찾아 그 장면을 `frames/` 폴더에 이미지로 저장합니다.
6. 스크립트와 화면을 시간순으로 짝지어 `index.md`를 만듭니다.
7. 용도별 지시문을 앞에 붙여 `summary_prompt.md`를 만듭니다.
8. (선택) 구간 분할을 켰다면 `chunks/` 폴더에 구간별 프롬프트 파일을 나눠 만듭니다.

결과물은 모두 아래 위치에 생성됩니다.

```
output/영상파일명/
```

예를 들어 `강의.mp4`를 처리하면 `output/강의/` 폴더가 만들어집니다.

## 준비 사항

- Python 3.10 이상
- ffmpeg (ffprobe 포함) — 오디오 추출, 장면 감지, 프레임 추출에 사용
- NVIDIA GPU와 드라이버 (선택) — 없으면 자동으로 CPU로 동작하며, 그만큼 느려집니다
- 처리할 영상 파일

ffmpeg가 없다면 설치합니다.

```bash
winget install Gyan.FFmpeg      # Windows
brew install ffmpeg             # macOS
sudo apt install ffmpeg         # Linux (Debian/Ubuntu)
```

Windows에서 winget으로 설치했다면, **터미널을 새로 열어야** PATH가 반영됩니다.

프로그램 설치는 저장소 폴더에서 다음과 같이 합니다.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

pip install -e .
```

용도에 따라 추가 설치가 필요합니다.

```bash
pip install -e ".[gpu]"           # NVIDIA GPU 가속 (CUDA 런타임)
pip install -e ".[diarization]"   # 화자 분리 기능
pip install -e ".[dev]"           # 테스트 실행용
```

`[gpu]`는 용량이 큽니다(1GB 이상). GPU가 없으면 설치할 필요가 없습니다.

## 사용 방법

### 1. 환경이 준비됐는지 확인하기

```bash
prepreplay doctor
```

ffmpeg, ffprobe, GPU, 디스크 여유 공간을 점검해 표로 보여 줍니다.

```
┌──────────────────┬────────┬──────────────────────────────────┐
│ 항목             │ 상태   │ 세부 정보                        │
├──────────────────┼────────┼──────────────────────────────────┤
│ ffmpeg           │ OK     │ ffmpeg version 9.0.2-full_build  │
│ ffprobe          │ OK     │ ffprobe version 9.0.2-full_build │
│ GPU              │ 감지됨 │ NVIDIA GeForce RTX 5060 Ti       │
│ 디스크 여유 공간 │ OK     │ 704.8 GB (현재 디렉터리 기준)    │
└──────────────────┴────────┴──────────────────────────────────┘
```

ffmpeg나 ffprobe가 "누락"으로 나오면 종료 코드 1로 끝납니다. 설치 후 다시 실행하세요.
GPU가 "미감지"여도 CPU로 동작하므로 진행에는 문제가 없습니다.

### 2. 영상 파일 준비하기

저장소 폴더 안에 `video/` 폴더를 만들고 영상을 넣어 두면, 실행할 때 **파일명만** 써도 됩니다.

```
PrepReplay/
├── video/
│   ├── 강의.mp4
│   └── 채용설명회.mp4
└── output/            (실행하면 자동 생성)
```

`video/` 폴더를 쓰지 않아도 됩니다. 그 경우 경로를 직접 적으면 됩니다.

지원 확장자는 `.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`입니다. 한글 파일명도 정상 동작합니다.

### 3. 용도(모드) 정하기

`--mode`는 마지막에 만들어지는 프롬프트의 **지시문만** 바꿉니다. 분석 과정 자체는 모든 모드가
동일합니다.

| 모드 | 어떤 영상에 쓰나 | 어떤 결과를 요구하나 |
|---|---|---|
| `lecture` | 강의, 특강, 인강 | 요약이 아니라 **강의 대체재**. 강의를 안 듣고도 이해되게 흐름대로 상세 서술 + 핵심 정리 + 문제 유형·풀이법 |
| `jobfair` | 채용설명회, 기업설명회 | 기본 정보 표 + **공고에는 없는 정보**(조직문화, Q&A, 숨은 채용 기준) + 다음 액션 |
| `consulting` | 취업 컨설팅, 멘토링 | 피드백을 항목별로 정리하고 실행 가능한 액션아이템 추출 |
| `interview` | 면접 연습, 스터디 복기 | 답변의 부족한 점과 개선 방향, 더 나은 답변 예시 |
| `default` | 그 외 전부 | 핵심 위주 요약 + 타임스탬프 정리 |

지시문 전문은 `prepreplay/templates/*.md`에서 직접 읽고 고칠 수 있습니다.

### 4. 실행하기

```bash
prepreplay run 강의.mp4 --mode lecture
```

50분 분량 영상 기준으로, GPU가 있고 `--model tiny`를 쓰면 1분 30초 내외가 걸립니다.
기본값인 `large-v3`는 정확도가 훨씬 높은 대신 몇 배 더 걸립니다.

실행 중에는 각 단계의 진행 상황이 순서대로 출력됩니다.

```
오디오 추출 완료: output\강의\audio.wav
STT 완료 (device=cuda, language=ko): transcript.srt, transcript.txt, segments.json
프레임 추출 완료 (장면 감지, 101개): output\강의\frames
index.md 생성 완료 (101개 구간): output\강의\index.md
summary_prompt.md 생성 완료 (mode=lecture): output\강의\summary_prompt.md
```

30분이 넘는 영상인데 `--split`을 지정하지 않으면 구간 분할을 권장하는 경고가 표시됩니다.

### 5. 긴 영상은 구간으로 나누기

```bash
prepreplay run 강의.mp4 --mode lecture --split 10m
```

`chunks/` 폴더에 10분 단위 파일이 생깁니다.

```
chunks/
├── part_01_000m-010m.md
├── part_02_010m-020m.md
├── ...
└── manifest.json
```

각 파일은 그 자체로 완결된 프롬프트라서, 하나만 떼서 붙여넣어도 동작합니다. 자르는 기준은
시간이 아니라 **문장(세그먼트)** 단위라서 말이 중간에 끊기지 않습니다.

`--split` 값은 `10m`(10분), `1h`(1시간), `600s`(600초)처럼 씁니다. 단위를 생략하면 분으로
취급합니다.

### 6. 결과물을 LLM에 넘기기

`output/영상파일명/summary_prompt.md`를 열어 **전체를 복사해 붙여넣으면 됩니다.** 파일 자체가
지시문 + 영상 정보 + 타임스탬프별 스크립트를 모두 담은 완성된 프롬프트라서, 따로 요청 문구를
쓸 필요가 없습니다.

파일을 직접 읽을 수 있는 에이전트(Claude Code 등)를 쓴다면 경로만 알려줘도 됩니다.

```
output/강의/summary_prompt.md 를 읽고 정리해줘.
결과는 같은 폴더에 analysis.md로 저장해줘.
```

프롬프트가 너무 길거나 구간별로 보고 싶으면 `chunks/` 안의 파일을 하나씩 넘기면 됩니다.

### 7. 여러 영상 한 번에 처리하기

파일 대신 폴더를 넘기면 그 안의 영상을 파일명 순서대로 전부 처리합니다.

```bash
prepreplay run video/ --mode lecture --split 10m
```

영상 하나가 실패해도 멈추지 않고 다음 영상으로 넘어가며, 끝에 성공/실패 요약이 표로 나옵니다.
하나라도 실패하면 종료 코드는 1이 됩니다.

## 결과물 읽는 법

```
output/영상파일명/
├── summary_prompt.md    ← LLM에 붙여넣을 파일 (이걸 쓰면 됩니다)
├── index.md             ← 사람이 훑어볼 파일 (화면+스크립트 시간순 매핑)
├── chunks/              ← --split 사용 시: 구간별 프롬프트
│   ├── part_01_000m-010m.md
│   └── manifest.json
├── frames/              ← 장면 전환 시점 캡처 (frame_00m12s.jpg 형식)
├── transcript.srt       ← 자막 형식 스크립트 (영상 플레이어에 물릴 수 있음)
├── transcript.txt       ← 순수 텍스트 스크립트
├── segments.json        ← STT 원본 데이터 (프로그램이 쓰는 중간 산출물)
├── frames.json          ← 프레임 메타데이터 (중간 산출물)
├── audio.wav            ← 추출된 오디오 (중간 산출물, 용량이 큽니다)
├── diarization.json     ← --diarize 사용 시: 화자별 발화 구간
├── state.json           ← 재개용 단계별 완료 기록
└── run.log              ← 실행 로그 (문제가 생겼을 때 확인)
```

평소에 열어볼 파일은 `summary_prompt.md`와 `index.md` 두 개면 충분합니다. 나머지는 프로그램이
쓰는 중간 산출물이거나 문제 해결용입니다.

`audio.wav`는 용량이 크므로(50분 영상 기준 약 97MB), 분석이 끝난 뒤 지워도 됩니다. 다만 지운
뒤 다시 실행하면 오디오 추출부터 다시 합니다.

## 자주 쓰는 실행 예시

```bash
# 강의 영상을 10분 단위로 나눠서
prepreplay run 강의.mp4 --mode lecture --split 10m

# 빠르게 결과만 보고 싶을 때 (정확도 낮음)
prepreplay run 강의.mp4 --model tiny

# 슬라이드가 자주 바뀌는 강의 - 화면을 더 촘촘히 잡기
prepreplay run 강의.mp4 --scene-threshold 0.12

# 프레임이 너무 많이 나올 때 상한 걸기
prepreplay run 강의.mp4 --max-frames 50

# 지시문을 직접 써서 쓰기
prepreplay run 강의.mp4 --template ./내_지시문.md

# 여러 명이 대화하는 영상에서 화자 구분하기
prepreplay run 컨설팅.mp4 --mode consulting --diarize

# 영어 강의
prepreplay run lecture.mp4 --language en

# 로그를 자세히 보면서 실행
prepreplay run 강의.mp4 --verbose
```

## 옵션 전체 목록

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `<video>` (필수) | - | 영상 파일 경로 또는 영상이 담긴 폴더. 경로에서 못 찾으면 `./video/` 안에서도 찾습니다 |
| `--mode` | `default` | 프롬프트 지시문 선택 (`lecture`/`jobfair`/`consulting`/`interview`/`default`) |
| `--template` | (없음) | 직접 쓴 지시문 파일 경로. 지정하면 `--mode` 대신 이 파일을 씁니다 |
| `--output` | `./output` | 결과물 상위 폴더 |
| `--model` | `large-v3` | Whisper 모델 (`tiny`/`base`/`small`/`medium`/`large-v3`). 작을수록 빠르고 부정확 |
| `--language` | `ko` | 음성 언어 코드. 자동 감지는 `auto` |
| `--scene-threshold` | `0.3` | 장면 전환 감지 민감도(0.0~1.0). 낮출수록 화면을 더 많이 잡습니다 |
| `--max-frames` | `200` | 프레임 개수 상한. 넘으면 균등하게 솎아냅니다 |
| `--split` | (없음) | 구간 분할 단위 (`10m`, `1h`, `600s`) |
| `--force` / `--no-force` | `--no-force` | 캐시를 무시하고 처음부터 전부 다시 생성 |
| `--config` | `./config.yaml` | 설정 파일 경로 |
| `--diarize` / `--no-diarize` | 꺼짐 | 화자 분리 활성화 (별도 설치와 토큰 필요) |
| `--hf-token` | (없음) | 화자 분리용 HuggingFace 토큰. 기본은 `HF_TOKEN` 환경변수 |
| `--diarization-model` | `pyannote/speaker-diarization-3.1` | 화자 분리 모델 |
| `--verbose` / `-v` | 꺼짐 | 상세 로그를 화면에도 출력 |
| `--quiet` / `-q` | 꺼짐 | 진행 상황 출력 억제 (에러는 계속 출력). `--verbose`와 함께 못 씁니다 |

## 설정 파일로 기본값 바꾸기

매번 같은 옵션을 치기 번거롭다면, 저장소 폴더에 `config.yaml`을 두면 됩니다.

```bash
copy config.example.yaml config.yaml    # Windows
cp config.example.yaml config.yaml      # macOS/Linux
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
diarize: false
diarization_model: pyannote/speaker-diarization-3.1
```

적용 우선순위는 **CLI 옵션 > config.yaml > 내장 기본값** 순입니다. CLI에서 값을 주면 설정
파일 값을 덮어씁니다.

`config.yaml`은 실행한 폴더 기준으로 찾습니다. 개인 설정이라 `.gitignore`에 이미 제외되어
있습니다.

`hf_token`도 설정 파일에 적을 수 있지만 권장하지 않습니다. 설정 파일이 실수로 공유되면 토큰도
같이 새어 나갑니다. `HF_TOKEN` 환경변수를 쓰세요.

## 캐시와 다시 실행하기

각 단계는 결과 파일이 이미 있으면 건너뜁니다. 그래서 같은 영상을 다시 실행해도 오래 걸리는
STT를 반복하지 않습니다.

```
오디오 추출 스킵 (캐시됨): output\강의\audio.wav (--force로 재생성 가능)
STT 스킵 (캐시됨): output\강의\segments.json (--force로 재생성 가능)
```

**이것이 함정이 되는 경우가 있습니다.** `--mode`나 `--scene-threshold`를 바꿔서 다시 실행해도,
해당 산출물이 이미 있으면 그대로 건너뛰어 **옵션이 반영되지 않습니다.**

전부 다시 만들려면 `--force`를 씁니다.

```bash
prepreplay run 강의.mp4 --mode lecture --force
```

다만 `--force`는 **모든 단계**에 적용되므로 STT까지 다시 돌립니다. 특정 단계만 다시 만들고
싶다면, **그 단계의 산출물 파일만 지우고** 옵션 없이 그냥 다시 실행하는 것이 훨씬 빠릅니다.

| 다시 만들고 싶은 것 | 지울 파일 |
|---|---|
| 프롬프트만 (`--mode` 변경 등) | `summary_prompt.md`, `chunks/` |
| 프레임부터 (`--scene-threshold` 변경 등) | `frames/`, `frames.json`, `index.md`, `summary_prompt.md`, `chunks/` |
| STT부터 (`--model`, `--diarize` 변경 등) | `segments.json` 이하 전부 (= `--force`와 동일) |

**중단된 경우**는 신경 쓸 필요가 없습니다. STT 도중에 Ctrl+C를 누르거나 프로그램이 죽었다면,
그 단계는 완료로 기록되지 않으므로 다시 실행할 때 이미 끝난 단계는 건너뛰고 중단된 단계부터
다시 합니다. 무슨 일이 있었는지는 `run.log`에서 확인할 수 있습니다.

폴더 단위 배치 처리도 마찬가지입니다. 20개짜리 강의 폴더를 처리하다 중단되면, 다시 실행할 때
이미 끝난 영상은 건너뜁니다.

## 화자 분리 사용하기

컨설팅이나 스터디처럼 여러 사람이 대화하는 영상에서 "누가 말했는지" 구분하고 싶을 때 씁니다.
스크립트의 각 문장 앞에 `[화자1]`, `[화자2]` 라벨이 붙습니다.

준비는 한 번만 하면 됩니다.

1. 패키지를 설치합니다.
   ```bash
   pip install -e ".[diarization]"
   ```
2. [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   페이지에서 모델 사용 약관에 동의합니다. (게이트된 모델이라 동의하지 않으면 다운로드가
   거부됩니다.)
3. [HuggingFace 토큰](https://huggingface.co/settings/tokens)을 발급받아 환경변수로 등록합니다.
   ```bash
   set HF_TOKEN=hf_xxxxxxxx           # Windows (cmd)
   $env:HF_TOKEN="hf_xxxxxxxx"        # Windows (PowerShell)
   export HF_TOKEN=hf_xxxxxxxx        # macOS/Linux
   ```

이후 `--diarize`를 붙여 실행합니다.

```bash
prepreplay run 컨설팅.mp4 --mode consulting --diarize
```

라벨은 스크립트 텍스트 자체에 들어가므로 `index.md`와 `summary_prompt.md`에도 그대로 반영됩니다.
화자 이름은 실제 이름이 아니라 등장 순서대로 붙는 `화자1`, `화자2`입니다.

이미 화자 분리 없이 STT를 돌린 영상이라면, `segments.json`이 캐시되어 있어서 라벨이 붙지
않습니다. `--force`로 다시 돌려야 합니다.

## 실패했을 때

### `✗ [환경 확인] 실패: ffmpeg/ffprobe를 찾을 수 없습니다.`

ffmpeg가 설치되지 않았거나 PATH에 없습니다. `prepreplay doctor`로 상태를 확인하고, 설치한
뒤에는 터미널을 새로 열어 PATH를 갱신하세요. Windows에서 winget으로 설치한 경우 기존 터미널
세션에는 PATH가 반영되지 않습니다.

### `✗ [입력 검증] 실패: 영상(또는 디렉터리)을 찾을 수 없습니다`

파일명이나 경로를 확인하세요. 프로그램은 두 곳을 찾습니다.

1. 입력한 경로 그대로 (현재 폴더 기준)
2. `./video/` 폴더 안

둘 다 없으면 이 오류가 납니다. 다른 곳에 있는 파일이라면 전체 경로를 적으면 됩니다.

### `✗ [입력 검증] 실패: 지원하지 않는 파일 확장자입니다`

`.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`만 지원합니다. 다른 형식이라면 ffmpeg로 먼저 변환하세요.

```bash
ffmpeg -i 원본.wmv 변환본.mp4
```

### `✗ [입력 검증] 실패: 알 수 없는 모드입니다`

`--mode`에는 `default`, `consulting`, `jobfair`, `lecture`, `interview`만 쓸 수 있습니다.
직접 만든 지시문을 쓰려면 `--mode`가 아니라 `--template 파일경로`를 사용하세요.

### `✗ [오디오 추출] 실패: 오디오 트랙이 없어 스크립트를 추출할 수 없습니다`

영상에 소리가 없습니다. 화면만 녹화하고 마이크를 켜지 않은 경우입니다. 이 프로그램은 음성
분석이 핵심이라 오디오가 없으면 진행할 수 없습니다.

### `✗ [STT] 실패: 음성을 인식하지 못했습니다 (세그먼트 0개)`

오디오는 있지만 Whisper가 말소리를 하나도 찾지 못했습니다. 다음을 확인하세요.

- 배경음악이나 잡음만 있는 영상은 아닌지
- `--language` 설정이 실제 언어와 맞는지 (기본값은 `ko`입니다. 영어 영상이면 `--language en`)
- 소리가 너무 작지는 않은지

`--model`을 더 큰 것으로 바꿔 재시도해 볼 수도 있습니다.

### `✗ [구간 분할] 실패: --split 형식이 올바르지 않습니다`

`10m`, `1h`, `600s` 형태로 적어야 합니다. 숫자만 쓰면 분으로 취급합니다. `10분`, `10 min`,
`0m` 같은 값은 사용할 수 없습니다.

### `✗ [화자 분리] 실패: 화자 분리를 사용하려면 HuggingFace 토큰이 필요합니다.`

`HF_TOKEN` 환경변수를 등록했는지 확인하세요. 환경변수를 등록한 뒤에는 터미널을 새로 열어야
반영됩니다. `--hf-token` 옵션으로 직접 넘길 수도 있습니다.

### `✗ [화자 분리] 실패: 화자 분리 모델을 불러오지 못했습니다`

토큰은 있지만 모델 접근 권한이 없는 경우가 대부분입니다. HuggingFace의 모델 페이지에서 사용
약관에 동의했는지 확인하세요.

### `⚠ GPU 처리에 실패해 CPU로 전환합니다`

오류가 아니라 경고입니다. 그대로 두면 CPU로 계속 진행되며, 결과물은 동일하고 속도만 느려집니다.
GPU를 쓰고 싶다면 `pip install -e ".[gpu]"`로 CUDA 런타임을 설치한 뒤 다시 실행하세요.

### `⚠ 장면 전환이 감지되지 않았습니다`

이것도 경고입니다. 카메라가 고정된 영상(컨설팅, 면접 등)은 장면 전환이 없어서, 일정 간격으로
프레임을 뽑는 방식으로 자동 전환됩니다.

슬라이드 강의인데 이 경고가 나온다면 `--scene-threshold`를 낮춰 보세요(예: `0.12`). 단,
프레임을 다시 뽑으려면 앞의 "캐시와 다시 실행하기"를 참고해 기존 프레임을 지워야 합니다.

### 결과물이 "핵심만" 나와서 원본을 이해하기 어렵다

모드 선택 문제일 가능성이 큽니다. 강의 영상을 `default`로 돌리면 요약 위주로 나옵니다.
강의는 `--mode lecture`를 쓰세요. 이 지시문은 "요약이 아니라 강의 대체재를 만들라"고 요구합니다.

그래도 부족하면 `prepreplay/templates/lecture.md`를 직접 고치거나, 원하는 지시문을 파일로 써서
`--template`으로 넘기면 됩니다.

### 옵션을 바꿨는데 결과가 그대로다

캐시 때문입니다. "캐시와 다시 실행하기" 절을 참고해 해당 산출물을 지우고 다시 실행하거나
`--force`를 쓰세요. 이 프로그램은 옵션이 바뀌었는지 비교하지 않고, 파일이 있으면 건너뜁니다.

### 스크립트에 오타가 많다

Whisper의 인식 한계입니다. `--model tiny`로 돌렸다면 특히 그렇습니다. `--model large-v3`
(기본값)로 다시 돌리면 크게 개선됩니다. `--force`가 필요합니다.

고유명사(회사명, 강사명, 전문 용어)는 큰 모델에서도 자주 틀립니다. 기본 지시문에는 "문맥상
맞는 용어로 추정해서 정리하라"는 문구가 들어 있어, LLM 단계에서 어느 정도 보정됩니다.

## 코드 기준 주요 주의사항

문서의 설명과 실제 동작이 다를 때를 대비해, 코드가 실제로 어떻게 동작하는지 적어 둡니다.

- 결과물 폴더 이름은 영상 파일명에서 확장자를 뺀 값입니다. 다른 폴더에 있는 같은 이름의 영상을
  처리하면 결과가 덮어써집니다.
- 오디오는 항상 16kHz 모노 16비트 PCM WAV로 추출합니다. 포맷을 바꾸는 옵션은 없습니다.
- STT는 GPU(`cuda`/`float16`)를 먼저 시도하고, 모델 로드나 실제 추론 중 실패하면 CPU
  (`cpu`/`int8`)로 자동 재시도합니다. 이때 GPU에서 진행하던 작업은 버리고 처음부터 다시 합니다.
- 인식된 문장이 하나도 없으면 실패로 처리하고 결과 파일을 만들지 않습니다.
- 장면 전환이 하나도 감지되지 않으면 60초 간격 균등 샘플링으로 넘어갑니다. 이때 간격은 영상
  길이를 넘지 않도록 줄여서 적용합니다(짧은 영상에서 프레임이 0개가 되는 것을 막기 위함).
- 프레임 수가 `--max-frames`를 넘으면 처음과 끝을 포함해 균등한 간격으로 골라냅니다. 버려진
  프레임 파일은 삭제됩니다.
- 프레임 파일명은 `frame_분m초s.jpg` 형식입니다. 같은 초에 두 장이 걸리면 밀리초를 덧붙여
  구분합니다.
- 캐시 판단은 산출물 파일의 존재 **그리고** `state.json`의 완료 기록을 함께 봅니다. 중단되어
  완료 기록이 없으면 파일이 남아 있어도 다시 만듭니다.
- `--force`는 단계를 가리지 않고 전부 적용됩니다. 특정 단계만 강제할 옵션은 없습니다.
- 구간 분할은 문장(세그먼트) 단위로 나눕니다. 파일명의 `000m-010m`은 명목상 범위이며, 실제
  내용 경계는 문장 경계에 맞춰집니다.
- `chunks/` 안의 파일은 이미지를 `../frames/`로 참조합니다. 이 파일들을 다른 폴더로 옮기면
  이미지 링크가 깨집니다.
- 폴더를 입력하면 하위 폴더는 뒤지지 않습니다. 해당 폴더 바로 아래의 영상만, 파일명 오름차순으로
  처리합니다.
- 배치 처리 중 영상 하나가 실패해도 계속 진행하며, 하나라도 실패하면 최종 종료 코드는 1입니다.
- 화자 라벨은 별도 필드가 아니라 문장 텍스트 앞에 직접 붙습니다. 그래서 이후 모든 산출물에
  자동으로 반영됩니다.
- `config.yaml`과 `./video/` 폴더는 모두 **명령을 실행한 폴더** 기준으로 찾습니다. 다른 폴더에서
  실행하면 찾지 못합니다.
- ffprobe 호출은 30초, 프레임 추출은 (영상 길이 × 5초) 또는 최소 120초에서 시간 초과됩니다.
- `run.log`는 실행할 때마다 이어 쓰기 때문에, 여러 번 실행한 기록이 한 파일에 쌓입니다.
- `--quiet`를 써도 오류 메시지는 출력됩니다. 로그는 화면 출력 설정과 무관하게 항상 `run.log`에
  기록됩니다.

## 전체 흐름 요약

```
ffmpeg 설치 확인 (prepreplay doctor)
→ video/ 폴더에 영상 넣기
→ 용도에 맞는 --mode 고르기
→ prepreplay run 파일명 --mode 모드 [--split 10m]
→ 오디오 추출 → STT → 프레임 추출 → index.md → summary_prompt.md
→ output/영상파일명/summary_prompt.md 열기
→ 전체 복사해서 LLM에 붙여넣기
→ (필요하면) 옵션 바꿔 산출물 일부만 지우고 다시 실행
```

## 개발자용

```bash
pip install -e ".[dev]"
pytest -q
```

테스트는 ffmpeg로 즉석에서 만든 합성 영상을 사용하며, 실제 사용자 영상은 저장소에 포함하지
않습니다. Whisper와 화자 분리 모델은 가짜 객체로 대체해 네트워크 없이 검증합니다.

구조와 개발 이력은 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md), [MILESTONE.md](MILESTONE.md)를
참고하세요.

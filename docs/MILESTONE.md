# MILESTONE

PrepReplay의 진행 현황을 추적하는 문서. 원래 계획은 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md),
배경/설계는 [PROPOSAL.md](PROPOSAL.md) 참고. 이 문서는 "지금 어디까지 됐고, 다음은 뭔지"만 담는다.

마지막 갱신: 2026-09-22 (PR #8 머지 직후)

---

## 한눈에 보기

| 항목 | 상태 |
|---|---|
| 현재 버전 | `v0.1.0` (태그) |
| 핵심 파이프라인 | ✅ 완주 (오디오 추출 → STT → 프레임 추출 → index.md → summary_prompt.md) |
| 머지된 PR | #1 ~ #8 (총 8개) |
| 테스트 | 82 passed (`pytest -q`) |
| 다음 목표 | PR #9 안정화 → `v1.0.0` |

---

## 전체 로드맵

```
#1 초기화
 └─ #2 CLI/설정/doctor
     ├─ #3 오디오 ──▶ #4 STT ──┐
     └─ #5 프레임 ─────────────┴─▶ #6 index ─▶ #7 프롬프트 ─▶ #8 분할 ─▶ #9 안정화
                                                                            │
                                                                     #10+ 선택 확장
                                                              (배치 처리 / 화자 분리 /
                                                               Obsidian export / 중복 제거)
```

기획서 마일스톤 기준:
1. **1단계(MVP)**: 오디오 추출 → STT → 스크립트 저장 — PR #3~#4에서 완료
2. **2단계**: 장면 감지 기반 프레임 추출 — PR #5에서 완료
3. **3단계**: index.md + summary_prompt.md — PR #6~#7에서 완료, `v0.1.0` 태그
4. **4단계**: 구간 분할, 편의 기능 — PR #8 완료, PR #9 진행 중
5. **5단계(선택)**: 화자 분리, 배치 처리, 지식관리 도구 연동 — 미착수

---

## 완료된 작업

### PR #1 — 프로젝트 초기 스캐폴딩 (`chore/project-init`)
`pyproject.toml`, `.gitignore`, 최소 CLI 골격(`prepreplay --help`), `README.md`, 기획 문서를
`docs/`로 이동. 저장소를 처음부터 세팅(기본 브랜치 `main`, gh CLI 인증 등)한 PR이기도 하다.

### PR #2 — CLI 확장 + 설정 시스템 + 환경 진단 (`feat/cli-skeleton`)
`prepreplay doctor`(ffmpeg/GPU/디스크 진단), `prepreplay run`(입력 검증 + 메타데이터 확인),
`config.yaml` 병합(CLI 옵션 > config.yaml > 기본값), 커스텀 예외 계층(`stage`/`hint` 포함
rich 에러 출력)을 만들었다.

### PR #3 — 오디오 추출 (`feat/audio-extract`)
ffmpeg로 16kHz mono 16-bit PCM WAV 추출. **이후 모든 단계가 따르는 캐시 규칙**
(`is_cached()`: 산출물 있으면 스킵, `--force`로 재생성)을 여기서 확립했다.

### PR #4 — Whisper STT (`feat/whisper-transcribe`)
faster-whisper로 `segments.json`/`transcript.srt`/`transcript.txt` 생성. GPU 우선 시도 →
로드/추론 실패 시 CPU 자동 전환. **기획서 마일스�트 1단계(MVP) 완료 지점.**

> 실측 이슈: Windows에서 CTranslate2가 cuBLAS DLL을 PATH 기반으로 찾는데,
> `os.add_dll_directory()`는 효과가 없었다 — `nvidia-*-cu12` 패키지의 `bin/` 경로를
> `PATH` 앞쪽에 직접 넣어야 했다(`prepreplay/utils/cuda_env.py`).

### PR #5 — 장면 전환 감지 및 프레임 추출 (`feat/scene-frames`)
`select='gt(scene,X)'` + `showinfo`로 장면 전환 시점 감지, 0건이면 균등 간격 샘플링으로
자동 폴백, `--max-frames` 상한.

> 실측 이슈 2건: (1) mjpeg 인코더가 일부 입력의 풀레인지 yuv420p를 거부 →
> `-pix_fmt yuvj420p` 명시로 해결. (2) ffmpeg `fps` 필터는 주기가 영상 길이보다 길면
> 첫 프레임조차 flush하지 않음 → fallback interval을 `min(interval, duration)`으로 클램프.

### PR #6 — index.md 생성 (`feat/index-generation`)
`segments.json` × `frames.json`을 프레임 경계로 병합해 기획서 7절 형식의 `index.md` 생성.
실제 Markdown 이미지 문법(`![화면](frames/xxx.jpg)`)으로 Obsidian/VSCode 미리보기 지원.

### PR #7 — summary_prompt.md + 모드별 템플릿 (`feat/mode-prompts`)
`consulting`/`jobfair`/`lecture`/`interview`/`default` 5개 내장 템플릿(기획서 6절) +
`--template`으로 커스텀 지시문 지정. **기획서 마일스톤 3단계 완료 → `v0.1.0` 태그.**
`prepreplay run <video>` 한 번으로 Claude에 바로 붙여넣을 수 있는 `summary_prompt.md`까지
나오는 전체 파이프라인이 이때 처음 완주됐다.

### PR #8 — 긴 영상 구간 분할 (`feat/split-chunks`)
`--split 10m` → `chunks/part_01_000m-010m.md` 형태로 구간별 독립 프롬프트 생성. 시간이 아니라
**세그먼트 단위**로 잘라 문장이 구간 경계에서 끊기지 않는다. 30분 초과 영상엔 `--split` 권장
경고를 띄운다.

---

## 검증 방식

거의 모든 PR에서 자동화 테스트(pytest, ffmpeg로 즉석 합성한 샘플 영상 사용)에 더해
**실제 GPU + 실제 모델 + Windows TTS로 만든 진짜 한국어 음성**으로 전체 파이프라인을
수동 실행해 산출물을 직접 눈으로 확인했다 (예: PR #4에서 TTS 음성 STT 결과가 원문과 완전히
일치, PR #6에서 발화 시점과 장면 전환 시점이 어긋나는 실제 케이스를 인트로 섹션 로직이
정확히 처리하는 것 확인 등). 각 PR의 상세 검증 로그는 해당 GitHub PR 설명에 남아 있다.

---

## 앞으로 할 일

### PR #9 — 안정화 (`chore/robustness`, 다음 작업)
- `run.log` 단계별 기록, `--verbose`/`--quiet`
- 중단 후 재실행 시 완료된 단계는 스킵하고 이어서 진행 (`state.json`)
- ffmpeg/whisper 실패 원인별 사람이 읽을 수 있는 메시지 + 조치 안내 보강
- 전체 파이프라인 E2E 테스트 (합성 샘플 영상 fixture로)
- 완료 시 **`v1.0.0`** 태그 예정

### PR #10+ — 선택 확장 (기획서 4.3절, 우선순위 순)
1. `feat/batch-processing` — 디렉터리 입력으로 강의 시리즈 일괄 처리
2. `feat/diarization` — pyannote.audio 화자 분리 (`[화자1]` 라벨). 컨설팅/스터디 복기에서
   가치가 크지만 HuggingFace 토큰이 필요해 별도 설정 문서화가 필요함
3. `feat/obsidian-export` — Obsidian vault 포맷 export
4. `feat/frame-dedup` — 유사 프레임 제거로 이미지 수 압축

### 아직 손대지 않은 기획서 항목
- 실제 사용자 영상(취업 컨설팅/설명회/강의/면접 녹화)으로의 실전 검증 — 지금까지는 합성
  영상 + TTS 음성으로만 검증했다. `v1.0.0` 전후로 실제 영상 1개 이상으로 기획서 10절
  완료 기준을 다시 확인하는 것을 권장.
- 개인정보 처리 관련 추가 안내(README에 기본 경고는 있으나, 컨설팅 세션처럼 민감한 내용을
  다룰 때의 구체적 운영 가이드는 아직 없음)

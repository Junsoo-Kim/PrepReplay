# PrepReplay 작업 지침

- `output/{video_name}/summary_prompt.md`를 바탕으로 분석 문서를 만들 때는
  `output/analysis/{video_name}_analysis.md`에 저장한다.
- 분석 문서에서 원본 프레임을 참조할 때는 분석 문서의 위치를 기준으로
  `../{video_name}/frames/{frame_file}` 상대 경로를 사용한다.
- 새 `analysis.md`를 개별 영상 폴더 안에 만들지 않는다.

# V2.5 영상 30일 자동삭제 SQL 버그 수정

- `purge_expired_videos()`의 빈 문자열 비교 조건을 파라미터 바인딩으로 변경.
- 수정 전: `video_path != ''`가 Python 작은따옴표 문자열과 충돌하여 SQLite syntax error 발생.
- 수정 후: `video_path != ?` + `('', cutoff)` 바인딩.
- 회귀 테스트 추가: 31일 지난 영상은 파일 삭제 + DB 경로 NULL, 29일 영상은 유지, 빈 문자열/NULL 경로는 무시.
- 표준 라이브러리 `unittest`로 실제 삭제 테스트 통과.

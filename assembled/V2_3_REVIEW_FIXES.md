# V2.3 검토사항 반영

1. 이름/전화번호 필수 입력 + projects DB 저장 + 기존 DB 자동 마이그레이션
2. restoration_scopes를 estimator가 실제 금액에 반영
3. SMTP 이메일 새 리드 알림 추가(.env 설정 필요)
4. /admin 관리자 목록 + 고객/현장/견적/영상 확인, 비밀번호 보호
5. 개인정보 필수 동의 + /privacy 페이지 + 외부 분석 API 전송 고지
6. 상호 확정 전 임시 브랜드 영역/색상 팔레트 적용
7. 브라우저 기본 파일 버튼 숨김 + 커스텀 업로드 UI
8. 하단 임시 '철거비 계산기' 제거
9. 주요 CTA 시각적 위계 강화
10. 자주 나오는 미확정 항목에 provisional rate 별도 계층 추가

## 단가 안전 원칙
- 사용자 확정 단가와 외부조사 가견적단가를 JSON에서 status/note로 분리.
- 미확정 외부조사 단가는 결과에 '외부조사 가견적'으로 표시.
- 기타 원상복구는 임의 금액을 만들지 않고 수동확인.

## 오픈 전 필수 환경변수
- ADMIN_PASSWORD
- FLASK_SECRET_KEY
- GEMINI_API_KEY (Gemini 사용 시)
- SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM / LEAD_NOTIFY_EMAIL

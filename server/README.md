# 서버와 운영 도구

- [api](api/docs/architecture.md): FastAPI, 인증, 수집·검색, 포털/LMS 동기화,
  공유 대화 저장과 MCP. 현재 ARQ 워커도 이 프로젝트에 포함한다.
- [manager](manager/README.md): 서버와 데이터·모델·수집 설정을 관리하는
  운영자용 데스크톱 앱. 학생용 웹·모바일과 역할을 구분한다.

개발 실행은 [API 실행 안내](api/docs/dev-run.md)를 참고한다.
폴더 구조와 실제 운영 데이터 저장 위치는 별개이며 기존 DB·자산을 이동하거나 초기화하지 않는다.

# 학생용 클라이언트

- [web](web/README.md): React 기반 KNU PICK 웹.
- [mobile](mobile/README.md): Kotlin·Compose Multiplatform 공통 코드와 Android 실행 앱.
  Android Studio에서는 이 `client` 폴더가 아닌 `client/mobile`을 연다.
  iOS 실행 앱은 추후 같은 프로젝트에 추가한다.

두 클라이언트는 [공통 KNU API](../server/api/docs/api.md)를 호출한다.
PostgreSQL·Redis·크롤러·모델 실행 프로세스를 학생 기기에 포함하지 않는다.

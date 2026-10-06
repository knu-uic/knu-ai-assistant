-- 015_portal_accounts_only: 학교 포털 계정을 유일한 사용자 계정으로 사용한다.
-- users.student_id가 인증 주체이므로 별도 서비스 가입 및 이메일 인증 저장소는 제거한다.

DROP TABLE IF EXISTS email_verifications;
DROP TABLE IF EXISTS accounts;

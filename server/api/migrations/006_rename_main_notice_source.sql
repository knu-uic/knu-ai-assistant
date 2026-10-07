-- 공주대학교 공통 게시판의 공식 의미에 맞춰 사용자 표시명을 정정한다.
-- main_notice 코드는 기존 크롤링 이력과 API 호환성을 위해 유지한다.
UPDATE source
SET name = '공주대학교 학생 공지'
WHERE code = 'main_notice';

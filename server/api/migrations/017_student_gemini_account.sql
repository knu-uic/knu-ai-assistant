-- 학생 본인의 Gemini API 키를 대화 모델에 사용할 수 있게 한다.
ALTER TABLE student_llm_account
    DROP CONSTRAINT IF EXISTS student_llm_account_provider_check;
ALTER TABLE student_llm_account
    ADD CONSTRAINT student_llm_account_provider_check
    CHECK (provider IN ('openai', 'openai-codex', 'google'));

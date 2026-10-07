-- Engine checkpoints are server-owned and isolated from Codmes sessions.
ALTER TABLE student_chat_conversation
    ADD COLUMN IF NOT EXISTS context_state JSONB,
    ADD COLUMN IF NOT EXISTS last_request_id UUID;
-- A storage guard is not a model-context message-count policy.
ALTER TABLE student_chat_conversation DROP CONSTRAINT IF EXISTS student_chat_conversation_messages_check;
ALTER TABLE student_chat_conversation ADD CONSTRAINT student_chat_conversation_messages_check
    CHECK (jsonb_typeof(messages) = 'array' AND jsonb_array_length(messages) <= 10000);

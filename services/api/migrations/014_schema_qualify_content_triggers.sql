-- 014_schema_qualify_content_triggers: pg_dump/psql 복원처럼 search_path가 비어 있는
-- 세션에서도 콘텐츠 서브타입 트리거가 안전하게 동작하도록 참조를 한정한다.

CREATE OR REPLACE FUNCTION sync_content_type() RETURNS trigger AS $$
BEGIN
    SELECT kind INTO NEW.content_type
    FROM public.source
    WHERE source_id = NEW.source_id;
    IF NEW.content_type IS NULL THEN
        RAISE EXCEPTION 'unknown content source: %', NEW.source_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sync_content_subtype() RETURNS trigger AS $$
BEGIN
    DELETE FROM public.notice WHERE notice_id = NEW.content_id;
    DELETE FROM public.academic_document WHERE academic_document_id = NEW.content_id;
    IF NEW.content_type = 'academic' THEN
        INSERT INTO public.academic_document(academic_document_id)
        VALUES (NEW.content_id);
    ELSE
        INSERT INTO public.notice(notice_id) VALUES (NEW.content_id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

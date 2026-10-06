from db.migrate import MIGRATIONS_DIR, list_migrations, pending_migrations


def test_list_migrations_sorted_by_name(tmp_path):
    (tmp_path / "002_b.sql").write_text("-- b")
    (tmp_path / "001_a.sql").write_text("-- a")
    (tmp_path / "010_c.sql").write_text("-- c")
    (tmp_path / "readme.txt").write_text("ignored")

    names = [f.name for f in list_migrations(tmp_path)]

    assert names == ["001_a.sql", "002_b.sql", "010_c.sql"]


def test_pending_skips_applied(tmp_path):
    a = tmp_path / "001_a.sql"
    b = tmp_path / "002_b.sql"
    a.write_text("-- a")
    b.write_text("-- b")

    pending = pending_migrations({"001_a.sql"}, [a, b])

    assert [f.name for f in pending] == ["002_b.sql"]


def test_baseline_exists_and_covers_static_tables():
    baseline = MIGRATIONS_DIR / "001_baseline.sql"
    assert baseline.exists()

    body = baseline.read_text(encoding="utf-8")
    for table in (
        "source",
        "document_asset",
        "users",
        "lms_tasks",
        "lms_courses",
        "accounts",
        "email_verifications",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in body
    # 추적 테이블은 러너가 만든다 — 마이그레이션 파일에 있으면 안 됨
    assert "schema_migrations" not in body


def test_notice_v2_migration_covers_structured_scan_metadata():
    migration = MIGRATIONS_DIR / "002_notice_v2.sql"
    assert migration.exists()

    body = migration.read_text(encoding="utf-8")
    for table in (
        "notice",
        "notice_period",
        "notice_audience",
        "notice_application",
        "notice_asset",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in body

    assert "archived_at" in body
    assert "series_key" in body
    assert "source_text" in body
    assert "extraction_confidence" in body


def test_content_v3_migration_normalizes_content_and_domain_keys():
    migration = MIGRATIONS_DIR / "012_content_model.sql"
    assert migration.exists()

    body = migration.read_text(encoding="utf-8")
    assert "ALTER TABLE notice RENAME TO content" in body
    assert "ALTER TABLE content RENAME COLUMN id TO content_id" in body
    assert "ALTER TABLE source RENAME COLUMN id TO source_id" in body
    assert "CREATE TABLE notice (" in body
    assert "CREATE TABLE academic_document (" in body
    assert "CREATE TABLE category (" in body
    assert "CREATE TABLE topic (" in body
    assert "CREATE TABLE content_topic (" in body
    assert "ALTER TABLE notice_asset RENAME TO content_asset" in body
    assert "ALTER TABLE notice_chunk RENAME TO content_chunk" in body


def test_content_v4_migration_removes_legacy_compatibility_schema():
    migration = MIGRATIONS_DIR / "013_remove_content_legacy_compat.sql"
    assert migration.exists()

    body = migration.read_text(encoding="utf-8")
    assert "REFERENCES notice(notice_id)" in body
    assert "DROP VIEW IF EXISTS notice_audience" in body
    assert "DROP VIEW IF EXISTS notice_asset" in body
    assert "DROP VIEW IF EXISTS notice_chunk" in body
    assert "ALTER TABLE content DROP COLUMN category" in body
    assert "ALTER TABLE content DROP COLUMN topics" in body
    assert "ALTER TABLE content DROP COLUMN id" in body


def test_content_triggers_are_schema_qualified_for_archive_restore():
    migration = MIGRATIONS_DIR / "014_schema_qualify_content_triggers.sql"
    assert migration.exists()

    body = migration.read_text(encoding="utf-8")
    assert "FROM public.source" in body
    assert "DELETE FROM public.notice" in body
    assert "INSERT INTO public.academic_document" in body


def test_portal_accounts_migration_removes_service_signup_tables():
    migration = MIGRATIONS_DIR / "015_portal_accounts_only.sql"
    assert migration.exists()

    body = migration.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS email_verifications" in body
    assert "DROP TABLE IF EXISTS accounts" in body

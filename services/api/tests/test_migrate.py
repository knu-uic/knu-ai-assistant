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

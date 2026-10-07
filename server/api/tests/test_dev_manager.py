import json

import pytest

import dev_manager


def data_root(tmp_path):
    root = tmp_path / "manager"
    (root / "postgres").mkdir(parents=True)
    (root / "postgres/PG_VERSION").write_text("16")
    (root / "config").mkdir()
    (root / "config/runtime-secrets.json").write_text(json.dumps({
        "postgres_password": "test-only:@/", "auth_jwt_secret": "test-auth",
        "portal_sync_enc_key": "test-encryption", "mcp_auth_token": "test-mcp",
    }))
    return root


def test_local_helper_targets_manager_not_developer_db(monkeypatch, tmp_path, capsys):
    root = data_root(tmp_path)
    (root / "config/runtime-ports.json").write_text(json.dumps({"postgres": 55533, "redis": 56479}))
    env = {"DATABASE_URL": "must-not-use-the-developer-db", "KNU_CONTEXT_NODE": "/selected/node"}
    monkeypatch.setattr(dev_manager.os, "environ", env)
    monkeypatch.setattr(dev_manager, "load_dotenv", lambda *a: None)
    dev_manager.configure(root, tmp_path / "runtime")
    assert env["DATABASE_URL"] == "postgresql://knu:test-only%3A%40%2F@127.0.0.1:55533/knu"
    assert env["REDIS_URL"] == "redis://127.0.0.1:56479"
    assert env["AUTH_JWT_SECRET"] == "test-auth"
    assert env["KNU_CONTEXT_NODE"] == "/selected/node"
    assert env["KNU_MANAGER_SETTINGS_PATH"] == str(root / "runtime-settings.json")
    assert capsys.readouterr().out == ""


def test_local_helper_refuses_missing_database_and_invalid_ports(tmp_path):
    with pytest.raises(ValueError, match="existing"):
        dev_manager.configure(tmp_path, tmp_path)
    root = data_root(tmp_path)
    (root / "config/runtime-ports.json").write_text('{"postgres":0}')
    with pytest.raises(ValueError, match="ports"):
        dev_manager.configure(root, tmp_path)


def test_migration_refuses_unreviewed_versions_before_backup_or_write(monkeypatch, tmp_path):
    monkeypatch.setattr(dev_manager, "inspect_database", lambda: {"pending": ["020_unreviewed.sql"]})
    monkeypatch.setattr(dev_manager.subprocess, "run", lambda *a, **kw: pytest.fail("Must not execute"))
    with pytest.raises(ValueError, match="separate review"):
        dev_manager.migrate_context(tmp_path, tmp_path)


def test_migration_requires_cold_backup_before_any_write(monkeypatch, tmp_path):
    monkeypatch.setattr(dev_manager, "inspect_database", lambda: {"pending": ["018_student_chat_history.sql"]})
    monkeypatch.setattr(dev_manager.subprocess, "run", lambda *a, **kw: pytest.fail("Must not execute"))
    with pytest.raises(ValueError, match="backup"):
        dev_manager.migrate_context(tmp_path, tmp_path)

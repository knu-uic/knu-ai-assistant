"""Run current source against an existing, explicitly selected Manager database.

Development only. Does not start/stop native services, mint student tokens, reset
data, or print credentials. Close Server Manager while using this process.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from urllib.parse import quote

from dotenv import load_dotenv


def configure(data: Path, runtime: Path):
    data, runtime = data.resolve(), runtime.resolve()
    if not (data / "postgres/PG_VERSION").is_file():
        raise ValueError("An existing Manager PostgreSQL directory is required")
    stored = json.loads((data / "config/runtime-secrets.json").read_text())
    ports_file = data / "config/runtime-ports.json"
    ports = json.loads(ports_file.read_text()) if ports_file.exists() else {}
    postgres, redis = int(ports.get("postgres", 55433)), int(ports.get("redis", 56379))
    if not (1024 <= postgres <= 65535 and 1024 <= redis <= 65535):
        raise ValueError("Invalid local service ports")
    load_dotenv(Path(__file__).parent / ".env")
    values = {
        "RUNTIME_ENV": "local", "DB_HOST": "127.0.0.1", "DB_PORT": str(postgres),
        "DB_NAME": "knu", "DB_USER": "knu", "DB_PASSWORD": stored["postgres_password"],
        "DATABASE_URL": f"postgresql://knu:{quote(stored['postgres_password'], safe='')}@127.0.0.1:{postgres}/knu",
        "REDIS_URL": f"redis://127.0.0.1:{redis}",
        "AUTH_JWT_SECRET": stored["auth_jwt_secret"],
        "PORTAL_SYNC_ENC_KEY": stored["portal_sync_enc_key"], "MCP_AUTH_TOKEN": stored["mcp_auth_token"],
        "KNU_ADMIN_TOKEN": secrets.token_urlsafe(32),
        "KNU_MANAGER_SETTINGS_PATH": str(data / "runtime-settings.json"),
        "KNU_CODEX_AUTH_PATH": str(data / "config/codex-auth.json"),
        "DOCUMENT_ASSETS_ROOT": str(data / "assets"), "HWP_ASSETS_ROOT": str(data / "assets"),
        "EMBEDDING_DIM": "1024", "EMBEDDING_PROVIDER": "local", "EMBEDDING_MODEL": "bge-m3:latest",
        "OPENAI_COMPAT_BASE_URL": "http://127.0.0.1:11434/v1", "NOTICE_POLL_ENABLED": "false",
        "HF_HOME": str(data / "models/huggingface"),
    }
    node = os.environ.get("KNU_CONTEXT_NODE") or (str(runtime / "node/bin/node") if (runtime / "node/bin/node").is_file() else shutil.which("node"))
    if node:
        values["KNU_CONTEXT_NODE"] = node
    os.environ.update(values)
    return data, runtime


def inspect_database():
    import psycopg
    from psycopg import sql
    from db.schema import DB_URL
    from db.migrate import list_migrations, pending_migrations
    from api.runtime_settings import load_settings

    with psycopg.connect(DB_URL, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
        counts = {table: conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
                  for table in sorted(tables)}
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    school = load_settings()["school_chat"]
    return {"database": "knu", "counts": counts,
            "pending": [p.name for p in pending_migrations(applied, list_migrations())],
            "school_model": {k: school.get(k) for k in ("enabled", "provider", "model")}}


def migrate_context(runtime: Path, backup: Path):
    from db.migrate import migrate
    before = inspect_database()
    permitted = {"018_student_chat_history.sql", "019_student_chat_context.sql"}
    if set(before["pending"]) - permitted:
        raise ValueError("Other pending migrations require separate review")
    backup = backup.resolve()
    if not (backup / "postgres/PG_VERSION").is_file():
        raise ValueError("A verified cold PostgreSQL backup is required first")
    dump = backup / "knu-before-context.dump"
    if dump.exists():
        raise ValueError("Never overwrite a previous backup")
    # PGPASSWORD is passed in the subprocess environment, never the command line.
    env = {**os.environ, "PGPASSWORD": os.environ["DB_PASSWORD"],
           "DYLD_LIBRARY_PATH": str(runtime / "postgres/lib")}
    subprocess.run([str(runtime / "postgres/bin/pg_dump"), "-h", "127.0.0.1", "-p", os.environ["DB_PORT"],
                    "-U", "knu", "-d", "knu", "-Fc", "-f", str(dump)], env=env, check=True)
    dump.chmod(0o600)
    ran = migrate()
    after = inspect_database()
    if any(after["counts"].get(t) != count for t, count in before["counts"].items() if t != "schema_migrations"):
        raise RuntimeError("Unexpected original-table row count change; preserve backup and investigate")
    print(json.dumps({"applied": ran, "original_row_counts_preserved": True,
                      "backup": str(backup), "pending": after["pending"]}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "migrate", "api", "worker"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path)
    args = parser.parse_args()
    _, runtime = configure(args.data_root, args.runtime_root)
    if args.mode == "inspect":
        print(json.dumps(inspect_database(), ensure_ascii=False))
    elif args.mode == "migrate":
        if not args.backup_root:
            parser.error("migrate requires --backup-root")
        migrate_context(runtime, args.backup_root)
    elif args.mode == "api":
        import uvicorn
        uvicorn.run("api.main:app", host="127.0.0.1", port=8000)
    else:
        # Local integration tests need login/sync jobs, not periodic school crawling.
        from workers.arq_worker import WorkerSettings
        WorkerSettings.cron_jobs = []
        from arq import run_worker
        run_worker(WorkerSettings)


if __name__ == "__main__":
    main()

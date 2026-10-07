"""Export and restore portable KNU notice-only archives."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg


FORMAT = "knu-notice-data"
VERSION = 2
TABLE_PATTERNS = (
    "public.source*",
    "public.content*",
    "public.notice*",
    "public.academic_document*",
    "public.category*",
    "public.topic*",
    "public.embedding_dataset*",
    "public.crawl_url_state*",
    "public.crawl_run_state*",
    "public.extraction_review*",
)
TRUNCATE_SQL = """
TRUNCATE TABLE
    crawl_run_state,
    crawl_url_state,
    extraction_review,
    embedding_dataset,
    content,
    source
RESTART IDENTITY CASCADE;
"""


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def asset_root() -> Path:
    value = os.getenv("DOCUMENT_ASSETS_ROOT") or os.getenv("HWP_ASSETS_ROOT")
    if not value:
        raise RuntimeError("DOCUMENT_ASSETS_ROOT is required")
    return Path(value).expanduser().resolve()


def run(command: list[str]) -> None:
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"{Path(command[0]).name} failed: {detail}")


def counts() -> dict[str, int]:
    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            result = {}
            for key, table in (
                ("notices", "content"),
                ("assets", "content_asset"),
                ("chunks", "content_chunk"),
                ("datasets", "embedding_dataset"),
            ):
                cursor.execute(f"SELECT count(*) FROM {table}")
                result[key] = int(cursor.fetchone()[0])
            return result


def create_archive(destination: Path) -> dict:
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    root = asset_root()
    with tempfile.TemporaryDirectory(prefix="knu-notice-export-") as temporary:
        staging = Path(temporary)
        dump = staging / "notices.sql"
        command = [
            "pg_dump",
            f"--dbname={database_url()}",
            "--data-only",
            "--inserts",
            "--column-inserts",
            "--on-conflict-do-nothing",
            "--no-owner",
            "--no-privileges",
            f"--file={dump}",
        ]
        for pattern in TABLE_PATTERNS:
            command.append(f"--table={pattern}")
        run(command)

        manifest = {
            "format": FORMAT,
            "version": VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "asset_root": str(root),
            "counts": counts(),
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_archive = destination.with_name(f".{destination.name}.partial")
        temporary_archive.unlink(missing_ok=True)
        try:
            with zipfile.ZipFile(
                temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                archive.write(staging / "manifest.json", "manifest.json")
                archive.write(dump, "notices.sql")
                if root.is_dir():
                    for path in root.rglob("*"):
                        if path.is_file():
                            archive.write(path, Path("assets") / path.relative_to(root))
            temporary_archive.replace(destination)
        finally:
            temporary_archive.unlink(missing_ok=True)
    return {"path": str(destination), **manifest["counts"]}


def safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for item in archive.infolist():
        target = (destination / item.filename).resolve()
        if root != target and root not in target.parents:
            raise RuntimeError("Backup contains an unsafe path")
    archive.extractall(destination)


def sql_literal(value: str) -> str:
    if "\0" in value:
        raise RuntimeError("Backup contains an invalid asset path")
    return "'" + value.replace("'", "''") + "'"


def restore_archive(source: Path) -> dict:
    source = source.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="knu-notice-import-") as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(source) as archive:
            safe_extract(archive, staging)
        manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
            raise RuntimeError("지원하지 않는 KNU 공지 데이터 파일입니다.")
        dump = staging / "notices.sql"
        if not dump.is_file():
            raise RuntimeError("공지 데이터 덤프가 없습니다.")

        existing = counts()
        safety_backup = None
        if existing["notices"]:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safety_path = (
                asset_root().parent
                / "backups"
                / f"KNU-Notices-before-import-{stamp}.knudata"
            )
            safety_backup = create_archive(safety_path)["path"]

        target_assets = asset_root()
        imported_assets = staging / "assets"
        old_root = str(manifest.get("asset_root") or "")
        target_assets.parent.mkdir(parents=True, exist_ok=True)
        replacement = target_assets.with_name(f".{target_assets.name}.import")
        previous = target_assets.with_name(f".{target_assets.name}.before-import")
        shutil.rmtree(replacement, ignore_errors=True)
        shutil.rmtree(previous, ignore_errors=True)
        if imported_assets.is_dir():
            shutil.copytree(imported_assets, replacement)
        else:
            replacement.mkdir(parents=True)

        combined = staging / "restore.sql"
        with combined.open("wb") as output:
            output.write(TRUNCATE_SQL.encode("utf-8"))
            output.write(dump.read_bytes())
            if old_root and old_root != str(target_assets):
                old_value = sql_literal(old_root)
                new_value = sql_literal(str(target_assets))
                start = len(old_root) + 1
                output.write(
                    f"""
UPDATE public.content_asset
SET storage_path = {new_value} || substring(storage_path FROM {start})
WHERE storage_path LIKE {sql_literal(old_root + '%')};
UPDATE public.extraction_review
SET artifact_path = {new_value} || substring(artifact_path FROM {start})
WHERE artifact_path LIKE {sql_literal(old_root + '%')};
""".encode("utf-8")
                )

        assets_swapped = False
        try:
            if target_assets.exists():
                target_assets.replace(previous)
            replacement.replace(target_assets)
            assets_swapped = True
            run(
                [
                    "psql",
                    database_url(),
                    "--set=ON_ERROR_STOP=1",
                    "--single-transaction",
                    f"--file={combined}",
                ]
            )
        except Exception:
            if assets_swapped:
                shutil.rmtree(target_assets, ignore_errors=True)
            if previous.exists():
                previous.replace(target_assets)
            raise
        else:
            shutil.rmtree(previous, ignore_errors=True)
        finally:
            shutil.rmtree(replacement, ignore_errors=True)

        return {"path": str(source), "safety_backup": safety_backup, **counts()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("export", "import"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    result = create_archive(args.path) if args.mode == "export" else restore_archive(args.path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

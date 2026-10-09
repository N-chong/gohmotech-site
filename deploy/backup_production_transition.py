"""Create a private, checksummed recovery package before beta cleanup.

The script prints only the backup directory and artifact sizes. It never prints
database credentials or environment-file contents.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values


PROJECT = Path(__file__).resolve().parents[1]
ENV_FILE = Path("/home/gohmotech/.config/gohmotech/beta.env")
BACKUP_ROOT = Path("/home/gohmotech/.local/share/gohmotech-transition-backups")
EXPECTED_DATABASE = "gohmotech_beta"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_tree(archive, source, archive_name):
    if source.is_dir():
        archive.add(source, arcname=archive_name, recursive=True)


os.umask(0o077)
config = dotenv_values(ENV_FILE)
database = (config.get("BETA_DB_NAME") or "").strip()
if database != EXPECTED_DATABASE:
    raise SystemExit("Refusing backup: unexpected beta database name.")
required = ("BETA_DB_USER", "BETA_DB_PASSWORD", "BETA_DB_HOST", "BETA_DATA_ROOT")
if any(not (config.get(name) or "").strip() for name in required):
    raise SystemExit("Refusing backup: required private beta configuration is missing.")

stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
BACKUP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
target = BACKUP_ROOT / stamp
target.mkdir(mode=0o700)

database_dump = target / "database.sql"
with tempfile.NamedTemporaryFile(mode="w", prefix="gohmotech-db-", delete=True) as defaults:
    defaults.write("[client]\n")
    defaults.write(f"user={config['BETA_DB_USER']}\n")
    defaults.write(f"host={config['BETA_DB_HOST']}\n")
    defaults.write(f"port={config.get('BETA_DB_PORT') or '3306'}\n")
    defaults.write(f"password={config['BETA_DB_PASSWORD']}\n")
    defaults.flush()
    os.chmod(defaults.name, 0o600)
    with database_dump.open("wb") as output:
        subprocess.run(
            [
                "mysqldump", f"--defaults-extra-file={defaults.name}",
                "--single-transaction", "--skip-lock-tables",
                "--default-character-set=utf8mb4", EXPECTED_DATABASE,
            ],
            check=True,
            stdout=output,
            stderr=subprocess.PIPE,
        )
if database_dump.stat().st_size == 0:
    raise SystemExit("Database dump is empty; backup is incomplete.")

data_root = Path(config["BETA_DATA_ROOT"]).resolve()
uploads = target / "uploads.tar.gz"
with tarfile.open(uploads, "w:gz") as archive:
    add_tree(archive, data_root / "media", "media")
    add_tree(archive, data_root / "private_support", "private_support")
    add_tree(archive, data_root / "private_inquiries", "private_inquiries")
    add_tree(archive, data_root / "protected_models", "protected_models")

private_environment = target / "environment.env"
shutil.copyfile(ENV_FILE, private_environment)
private_environment.chmod(0o600)

deployment = target / "deployment-config.tar.gz"
with tarfile.open(deployment, "w:gz") as archive:
    for source in (
        PROJECT / "config" / "settings.py",
        PROJECT / "config" / "beta.py",
        PROJECT / "config" / "beta_access.py",
        PROJECT / "config" / "beta_urls.py",
        PROJECT / "deploy" / "gohmotech-beta.service",
        PROJECT / "deploy" / "nginx-beta.conf",
        PROJECT / "requirements.txt",
    ):
        archive.add(source, arcname=str(source.relative_to(PROJECT)))

artifacts = {}
for path in (database_dump, uploads, private_environment, deployment):
    artifacts[path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}

manifest = {
    "format": "gohmotech-production-transition-backup-v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "database": EXPECTED_DATABASE,
    "artifacts": artifacts,
    "restore_tested": False,
}
manifest_path = target / "backup.json"
with manifest_path.open("x", encoding="utf-8") as stream:
    json.dump(manifest, stream, indent=2, sort_keys=True)
    stream.write("\n")
manifest_path.chmod(0o600)

print(f"Backup created: {target}")
for name, metadata in artifacts.items():
    print(f"  {name}: {metadata['bytes']} bytes")
print("Restore rehearsal status: NOT TESTED")

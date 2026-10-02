"""Move all GoHMoTech data into a preallocated ext4 image on the attached drive.

Default: read-only preview. --apply requires root. The existing NTFS partition is
preserved. Only a newly created regular image file is formatted.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from dotenv import dotenv_values


PROJECT = Path(__file__).resolve().parents[1]
PYTHON = PROJECT / ".venv/bin/python"
ACCOUNT = "gohmotech"
DRIVE_UUID = "C8CA20CFCA20BC16"
MOUNT = Path("/media/gohmotech/GOHMOTECH HARD DRIVE")
IMAGE = MOUNT / "GoHMoTech/data.ext4"
VOLUME = Path("/srv/gohmotech-data")
SOURCE = Path("/home/gohmotech/.local/share/gohmotech-production")
ENV_FILE = Path("/home/gohmotech/.config/gohmotech/production.env")
SYSTEM_UNITS = Path("/etc/systemd/system")
SERVICES = ("gohmotech-production", "gohmotech-beta", "gohmotech-celery-worker", "gohmotech-celery-beat")
DEPENDENCIES = ("mariadb", "redis-server")
GIB = 1024 ** 3


@dataclass(frozen=True)
class Target:
    source: Path
    name: str

    @property
    def destination(self):
        return VOLUME / self.name


TARGETS = (
    Target(SOURCE, "production"),
    Target(Path("/var/lib/mysql"), "mysql"),
    Target(Path("/var/lib/redis"), "redis"),
    Target(Path("/var/log/redis"), "logs/redis"),
    Target(Path("/var/www/gohmotech-production"), "www/production"),
    Target(Path("/var/www/gohmotech-beta"), "www/beta"),
    Target(Path("/home/gohmotech/.local/share/gohmotech-beta"), "beta"),
    Target(Path("/home/gohmotech/.local/share/gohmotech-transition-backups"), "backups/transition"),
    Target(Path("/home/gohmotech/.local/share/gohmotech-transition-quarantine"), "quarantine"),
    Target(Path("/var/backups/gohmotech-beta"), "backups/beta"),
    Target(Path("/var/backups/gohmotech-production-cutover"), "backups/production-cutover"),
    Target(Path("/var/backups/gohmotech-camera-realtime"), "backups/camera-realtime"),
    Target(PROJECT / "media", "development/media"),
    Target(PROJECT / "protected_media", "development/protected_media"),
    Target(PROJECT / "private_support_uploads", "development/private_support_uploads"),
    Target(PROJECT / "staticfiles", "development/staticfiles"),
)


def run(*args, capture=False, check=True):
    return subprocess.run(
        [str(arg) for arg in args], check=check, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def manifest(root):
    """Compare content, permissions, ownership, empty directories and inert links."""
    result = {}
    for path in [root, *sorted(root.rglob("*"))]:
        metadata = path.lstat()
        mode = metadata.st_mode
        common = (stat.S_IMODE(mode), metadata.st_uid, metadata.st_gid)
        if stat.S_ISDIR(mode):
            value = ("directory", *common)
        elif stat.S_ISREG(mode):
            with path.open("rb") as handle:
                value = ("file", *common, hashlib.file_digest(handle, "sha256").hexdigest())
        elif stat.S_ISLNK(mode):
            value = ("link", *common, str(path.readlink()))
        else:
            raise RuntimeError(f"Unsupported special file: {path}")
        result[path.relative_to(root).as_posix()] = value
    return result


def write_atomic(path, content, mode=0o644):
    if not path.parent.exists():
        path.parent.mkdir(parents=True)
        path.parent.chmod(0o755)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def mount_name(path):
    return run("systemd-escape", "--path", "--suffix=mount", path, capture=True).stdout.strip()


def mount_unit(what, where, filesystem, options, dependency=None):
    requires = f"Requires={dependency}\nAfter={dependency}\nBindsTo={dependency}\n" if dependency else ""
    return (
        "[Unit]\nDescription=GoHMoTech data storage\nJobTimeoutSec=60s\n" + requires
        + f"\n[Mount]\nWhat={what}\nWhere={where}\nType={filesystem}\nOptions={options}\n"
        "TimeoutSec=60s\nDirectoryMode=0755\n\n[Install]\nWantedBy=local-fs.target\n"
    )


def service_guard(paths, *, user=False):
    if user:
        return "[Service]\n" + "".join(
            f"ExecStartPre=/usr/bin/mountpoint --quiet {json.dumps(str(path))}\n" for path in paths
        )
    return (
        "[Unit]\nRequiresMountsFor=" + " ".join(json.dumps(str(path)) for path in paths)
        + "\nBindsTo=" + " ".join(mount_name(path) for path in paths) + "\n"
        + "".join(f"ConditionPathIsMountPoint={path}\n" for path in paths)
    )


def configurations(account, targets):
    outer, inner = mount_name(MOUNT), mount_name(VOLUME)
    edits = {
        SYSTEM_UNITS / outer: mount_unit(
            f"/dev/disk/by-uuid/{DRIVE_UUID}", MOUNT, "ntfs3",
            f"rw,nosuid,nodev,uid={account.pw_uid},gid={account.pw_gid},umask=0077",
        ),
        SYSTEM_UNITS / inner: mount_unit(IMAGE, VOLUME, "ext4", "loop,noatime,nosuid,nodev", outer),
    }
    for target in targets:
        edits[SYSTEM_UNITS / mount_name(target.source)] = mount_unit(
            target.destination, target.source, "none", "bind", inner,
        )
    paths = [target.source for target in targets]
    for service in SERVICES:
        app_root = SOURCE if service != "gohmotech-beta" else Path("/home/gohmotech/.local/share/gohmotech-beta")
        needed = [p for p in (app_root, Path("/var/lib/mysql"), Path("/var/lib/redis")) if p in paths]
        edits[SYSTEM_UNITS / f"{service}.service.d/40-all-data-storage.conf"] = service_guard(needed)
    for service, prefix in (("mariadb", "/var/lib/mysql"), ("redis-server", "/var/lib/redis"), ("nginx", "/var/www/")):
        needed = [path for path in paths if str(path).startswith(prefix)]
        if service == "redis-server":
            needed += [path for path in paths if path == Path("/var/log/redis")]
        edits[SYSTEM_UNITS / f"{service}.service.d/40-all-data-storage.conf"] = service_guard(needed)
    user_units = Path(account.pw_dir) / ".config/systemd/user"
    for service in SERVICES:
        if (user_units / f"{service}.service").exists():
            app_root = SOURCE if service != "gohmotech-beta" else Path("/home/gohmotech/.local/share/gohmotech-beta")
            edits[user_units / f"{service}.service.d/40-all-data-storage.conf"] = service_guard([app_root], user=True)
    return edits


def check_site():
    for path, expected in (
        ("/marketplace/", 200), ("/accounts/login/", 200),
        ("/static/admin/css/base.css", 200), ("/media/seller_documents/missing.pdf", 404),
    ):
        actual = None
        for attempt in range(10):
            request = urllib.request.Request("http://127.0.0.1:8080" + path, headers={"Host": "gohmotech.site"})
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    actual = response.status
            except urllib.error.HTTPError as exc:
                actual = exc.code
                exc.close()
            except urllib.error.URLError:
                actual = None
            if actual == expected or actual not in (None, 502, 503):
                break
            time.sleep(1)
        if actual != expected:
            raise RuntimeError(f"HTTP check failed for {path}: expected {expected}, got {actual}")
        print(f"PASS HTTP {actual} {path}", flush=True)


def inspect(size_gib):
    if size_gib < 8:
        raise RuntimeError("The Linux storage volume must be at least 8 GiB.")
    if Path(dotenv_values(ENV_FILE).get("PRODUCTION_DATA_ROOT") or "").resolve() != SOURCE:
        raise RuntimeError("Unexpected production data root; refusing to migrate.")
    mount = json.loads(run(
        "findmnt", "--json", "--mountpoint", MOUNT, "--output", "UUID,FSTYPE,OPTIONS", capture=True,
    ).stdout)["filesystems"][0]
    if mount["uuid"] != DRIVE_UUID or mount["fstype"] != "ntfs3":
        raise RuntimeError("The expected NTFS drive is not mounted at the expected path.")
    if "rw" not in mount["options"].split(","):
        raise RuntimeError("The drive is read-only; run the preview outside the sandbox.")
    if IMAGE.exists() or IMAGE.is_symlink() or IMAGE.parent.is_symlink():
        raise RuntimeError(f"Refusing to overwrite an existing image or follow a link: {IMAGE}")
    if VOLUME.is_symlink() or (VOLUME.exists() and any(VOLUME.iterdir())):
        raise RuntimeError(f"The volume mountpoint must be absent or empty: {VOLUME}")
    if shutil.disk_usage(MOUNT).free < (size_gib + 8) * GIB:
        raise RuntimeError("Insufficient space for the volume plus an 8 GiB reserve on the drive.")
    for line in Path("/etc/fstab").read_text().splitlines():
        if line.lstrip().startswith("#") or not line.split():
            continue
        fields = line.split()
        device = Path(f"/dev/disk/by-uuid/{DRIVE_UUID}").resolve()
        if (DRIVE_UUID in line or str(MOUNT).replace(" ", r"\040") in line
                or (fields[0].startswith("/dev/") and Path(fields[0]).resolve() == device)):
            raise RuntimeError("An existing fstab entry for this drive needs review first.")
    targets = []
    for target in TARGETS:
        if target.source.is_symlink():
            raise RuntimeError(f"An existing storage symlink needs review: {target.source}")
        if not target.source.exists():
            if target.source in (SOURCE, Path("/var/lib/mysql"), Path("/var/lib/redis")):
                raise RuntimeError(f"Required storage directory is missing: {target.source}")
            continue
        if not target.source.is_dir() or target.source.resolve() != target.source:
            raise RuntimeError(f"Expected a real, local directory: {target.source}")
        if run("findmnt", "--mountpoint", target.source, capture=True, check=False).returncode == 0:
            raise RuntimeError(f"Storage directory is already a mountpoint: {target.source}")
        targets.append(target)
    account = pwd.getpwnam(ACCOUNT)
    edits = configurations(account, targets)
    for path in edits:
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"Existing storage configuration needs review: {path}")
    print(f"Drive: {MOUNT} (UUID {DRIVE_UUID})", flush=True)
    print(f"New Linux storage image: {IMAGE} ({size_gib} GiB)", flush=True)
    print(f"Mounted at: {VOLUME}; existing paths will use bind mounts.", flush=True)
    for target in targets:
        print(f"  {target.source} -> {target.destination}", flush=True)
    print("Existing drive files and original SD-card data are retained.", flush=True)
    print("OS, source code, installed software, private configuration and system journal stay on SD.", flush=True)
    return account, targets, edits


MYSQL = ("mariadb", "--no-defaults", "--protocol=socket", "--socket=/run/mysqld/mysqld.sock", "--user=root")


def sql(query):
    return run(*MYSQL, "--batch", "--skip-column-names", "--execute", query, capture=True).stdout.strip()


def database_counts():
    application = sorted(set(sql("SHOW DATABASES").splitlines()) - {"information_schema", "performance_schema", "mysql", "sys"})
    if not set(application) <= {"gohmotech", "gohmotech_beta", "goat_monitoring"}:
        raise RuntimeError("MariaDB contains an unexpected database; review its migration scope first.")
    counts = {}
    for database in application:
        tables = sql(f"SHOW FULL TABLES FROM `{database}` WHERE Table_type = 'BASE TABLE'")
        for row in tables.splitlines():
            table = row.split("\t")[0]
            identifier = table.replace("`", "``")
            counts[f"{database}.{table}"] = int(sql(f"SELECT COUNT(*) FROM `{database}`.`{identifier}`"))
    return counts


def create_image(size_gib):
    IMAGE.parent.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(IMAGE, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("The new image must be a regular file, never a block device.")
        print(f"Reserving {size_gib} GiB on the hard drive; existing files are retained.", flush=True)
        os.posix_fallocate(descriptor, 0, size_gib * GIB)
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if metadata.st_blocks * 512 < metadata.st_size:
            raise RuntimeError("The image is sparse; database storage requires reserved disk space.")
    finally:
        os.close(descriptor)
    # -F formats only the regular file created exclusively above, never a /dev path.
    run("mkfs.ext4", "-F", "-m", "1", "-i", "65536", "-L", "gohmotech-data",
        "-E", "nodiscard,lazy_itable_init=0,lazy_journal_init=0", IMAGE)


def copy_verified(target):
    target.destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    print(f"Copying and checking {target.source}", flush=True)
    run("rsync", "-aHAX", "--numeric-ids", "--checksum", f"{target.source}/", f"{target.destination}/")
    if manifest(target.source) != manifest(target.destination):
        raise RuntimeError(f"File content or permission verification failed: {target.source}")


def park_original(target, backup):
    original = backup / "originals" / target.name
    original.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.source.rename(original)
    try:
        # With the drive absent, ordinary service users must not write fallback data.
        target.source.mkdir(mode=0o000)
    except BaseException:
        original.rename(target.source)
        raise


def restore_original(target, backup):
    # rmdir refuses unexpected contents rather than deleting them.
    target.source.rmdir()
    (backup / "originals" / target.name).rename(target.source)


def verify_storage():
    mounted = json.loads(run(
        "findmnt", "--json", "--mountpoint", MOUNT, "--output", "UUID", capture=True,
    ).stdout)["filesystems"][0]
    if mounted["uuid"] != DRIVE_UUID:
        raise RuntimeError("The expected drive is not mounted.")
    volume = json.loads(run(
        "findmnt", "--json", "--mountpoint", VOLUME, "--output", "SOURCE,FSTYPE,OPTIONS", capture=True,
    ).stdout)["filesystems"][0]
    if volume["fstype"] != "ext4" or "rw" not in volume["options"].split(","):
        raise RuntimeError("The Linux data volume is not mounted read-write.")
    loops = json.loads(run(
        "losetup", "--json", "--output", "BACK-FILE", volume["source"], capture=True,
    ).stdout)["loopdevices"]
    backing = loops[0]["back-file"] if len(loops) == 1 else None
    if backing != str(IMAGE):
        raise RuntimeError("The Linux volume uses an unexpected backing file.")
    for target in TARGETS:
        if not target.destination.exists():
            if target.source in (SOURCE, Path("/var/lib/mysql"), Path("/var/lib/redis")):
                raise RuntimeError(f"Required destination is missing: {target.destination}")
            continue
        src, dst = target.source.stat(), target.destination.stat()
        if (src.st_dev, src.st_ino) != (dst.st_dev, dst.st_ino):
            raise RuntimeError(f"Path is not using hard-drive storage: {target.source}")
        print(f"PASS hard-drive storage: {target.source}", flush=True)
    for service in (*DEPENDENCIES, "gohmotech-production", "nginx"):
        run("systemctl", "is-active", "--quiet", service)
    check_site()


def migrate(size_gib, account, targets, edits):
    if os.geteuid() != 0:
        raise RuntimeError("Administrator access is required; run this command with sudo.")
    os.umask(0o077)
    for program in ("rsync", "mkfs.ext4", "mariadb", "mariadb-dump", "redis-cli", "systemd-analyze", "losetup"):
        if not shutil.which(program):
            raise RuntimeError(f"Required program is missing: {program}")
    if sql("SELECT @@datadir").rstrip("/") != "/var/lib/mysql":
        raise RuntimeError("MariaDB uses an unexpected data directory.")
    if sql("SELECT @@event_scheduler").upper() == "ON":
        raise RuntimeError("MariaDB events are running; coordinate them before migration.")
    for path in Path("/var/lib/mysql").rglob("*"):
        if path.is_symlink() or path.suffix == ".isl":
            raise RuntimeError("MariaDB has linked or external tablespaces; review before migration.")
    variables = sql("SHOW VARIABLES WHERE Variable_name IN ('innodb_data_home_dir','innodb_log_group_home_dir','aria_log_dir_path','log_bin_basename')")
    for row in variables.splitlines():
        _, _, value = row.partition("\t")
        if value and Path(value).is_absolute() and not Path(value).is_relative_to("/var/lib/mysql"):
            raise RuntimeError("MariaDB has storage outside its data directory; review before migration.")
    redis_directory = run("redis-cli", "--raw", "CONFIG", "GET", "dir", capture=True).stdout.splitlines()
    if redis_directory != ["dir", "/var/lib/redis"]:
        raise RuntimeError("Redis uses an unexpected data directory or requires credentials.")
    for service in DEPENDENCIES:
        run("systemctl", "is-active", "--quiet", service)
    user_run = ["runuser", "-u", ACCOUNT, "--"]
    user_manager = user_run + ["env", f"XDG_RUNTIME_DIR=/run/user/{account.pw_uid}", "systemctl", "--user"]
    user_bus = Path(f"/run/user/{account.pw_uid}/bus").exists()
    active = []
    for manager, services in [(["systemctl"], SERVICES), (user_manager, SERVICES if user_bus else ())]:
        active.extend((manager, name) for name in services if run(*manager, "is-active", "--quiet", name, check=False).returncode == 0)
    if (["systemctl"], SERVICES[0]) not in active:
        raise RuntimeError("Production must be running before migration.")
    if run("systemctl", "is-active", "--quiet", "nginx", check=False).returncode == 0:
        active.append((["systemctl"], "nginx"))
    check_site()
    total = 0
    sd_device = Path("/var/backups").stat().st_dev
    for target in targets:
        if target.source.stat().st_dev != sd_device:
            raise RuntimeError(f"Recovery requires source data on the SD filesystem: {target.source}")
        result = run("du", "--summarize", "--bytes", "--one-file-system", target.source, capture=True)
        total += int(result.stdout.split()[0])
    if total > (size_gib - 4) * GIB:
        raise RuntimeError("The Linux volume is too small for all selected data.")
    print(f"Source data size: {total / GIB:.2f} GiB.", flush=True)
    database_counts()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = Path("/var/backups/gohmotech-storage") / stamp
    backup.mkdir(parents=True, mode=0o700)
    backup.chmod(0o700)
    write_atomic(backup / "plan.json", json.dumps({
        "image": str(IMAGE), "size_gib": size_gib,
        "targets": [{"source": str(t.source), "destination": str(t.destination), "name": t.name} for t in targets],
        "configuration": {str(path): content for path, content in edits.items()},
        "original_services": [name for _, name in active],
    }, indent=2), 0o600)
    create_image(size_gib)
    installed, started_mounts, parked = [], [], []
    stopping = committed = False
    mount_units = [path.name for path in edits if path.suffix == ".mount"]
    outer, inner = mount_units[:2]

    def install(path, content):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"Configuration appeared during preparation: {path}")
        installed.append(path)
        write_atomic(path, content)
        if path.is_relative_to(Path(account.pw_dir)):
            os.chown(path.parent, account.pw_uid, account.pw_gid)
            os.chown(path, account.pw_uid, account.pw_gid)

    try:
        # Install mount definitions first; service requirements are added after the switch.
        for path, content in edits.items():
            if path.suffix == ".mount":
                install(path, content)
        run("systemd-analyze", "verify", *(SYSTEM_UNITS / name for name in mount_units))
        run("systemctl", "daemon-reload")
        started_mounts.append(inner)
        run("systemctl", "start", inner)
        VOLUME.chmod(0o755)
        stopping = True
        for manager, service in reversed(active):
            run(*manager, "stop", service)
        expected_counts = database_counts()
        with (backup / "all-databases.sql").open("xb") as output:
            subprocess.run([
                "mariadb-dump", *MYSQL[1:], "--all-databases", "--single-transaction",
                "--routines", "--events", "--triggers", "--hex-blob",
            ], check=True, stdout=output, stderr=subprocess.PIPE)
            output.flush()
            os.fsync(output.fileno())
        if (backup / "all-databases.sql").stat().st_size == 0:
            raise RuntimeError("Database backup is empty.")
        if run("redis-cli", "SAVE", capture=True).stdout.strip() != "OK":
            raise RuntimeError("Redis could not save its queue state.")
        for service in reversed(DEPENDENCIES):
            run("systemctl", "stop", service)
        for target in targets:
            copy_verified(target)
        run("sync", "--file-system", VOLUME)
        for target in targets:
            park_original(target, backup)
            parked.append(target)
            name = mount_name(target.source)
            started_mounts.append(name)
            run("systemctl", "start", name)
        for path, content in edits.items():
            if path.suffix != ".mount":
                install(path, content)
        run("systemctl", "daemon-reload")
        if user_bus:
            run(*user_manager, "daemon-reload")
        for name in mount_units:
            run("systemctl", "enable", name)
        run("sync", "--file-system", backup)
        for service in DEPENDENCIES:
            run("systemctl", "start", service)
        if database_counts() != expected_counts:
            raise RuntimeError("Database row counts changed during migration.")
        if run("redis-cli", "PING", capture=True).stdout.strip() != "PONG":
            raise RuntimeError("Redis failed its health check.")
        for target in targets:
            src, dst = target.source.stat(), target.destination.stat()
            if (src.st_dev, src.st_ino) != (dst.st_dev, dst.st_ino):
                raise RuntimeError(f"Storage path is not using the new volume: {target.source}")
        run(*user_run, PYTHON, PROJECT / "manage.py", "check", "--deploy", "--settings=config.production")
        # Once writers resume, the drive is authoritative. Never roll back to stale SD data.
        committed = True
        write_atomic(backup / "state", "drive is authoritative; writers may resume\n", 0o600)
        for manager, service in active:
            run(*manager, "start", service)
        verify_storage()
        for manager, service in active:
            run(*manager, "is-active", "--quiet", service)
        write_atomic(backup / "state", "migration complete\n", 0o600)
    except BaseException:
        if committed:
            print("Storage has switched. New writes may exist on the drive; automatic rollback is disabled.", flush=True)
            print(f"Review service failures and {backup}. Do not restore stale SD copies.", flush=True)
            raise
        print("Restoring original SD-card storage before application writes resume.", flush=True)
        if stopping:
            for manager, service in reversed(active):
                run(*manager, "stop", service)
            for service in reversed(DEPENDENCIES):
                run("systemctl", "stop", service)
        for name in reversed(started_mounts):
            run("systemctl", "stop", name)
        for target in reversed(parked):
            restore_original(target, backup)
        for name in mount_units:
            run("systemctl", "disable", name, check=False)
        for path in reversed(installed):
            path.unlink(missing_ok=True)
        run("systemctl", "daemon-reload")
        if user_bus:
            run(*user_manager, "daemon-reload")
        if stopping:
            for service in DEPENDENCIES:
                run("systemctl", "start", service)
            for manager, service in active:
                run(*manager, "start", service)
        print(f"Retained migration artifacts: {IMAGE}; {backup}", flush=True)
        raise
    print(f"GoHMoTech files, MariaDB, and Redis now use {IMAGE}.")
    print(f"Original SD-card data, database dump and migration records: {backup}")
    print("Keep the drive connected. Verify storage after a reboot before removing any recovery copies.")


def interrupted(signum, frame):
    raise KeyboardInterrupt(f"Received signal {signum}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="perform the all-data migration (requires sudo)")
    mode.add_argument("--verify", action="store_true", help="verify an already migrated installation (use sudo)")
    parser.add_argument("--size-gib", type=int, default=400, help="preallocated ext4 volume size (default: 400 GiB)")
    parser.add_argument("--check-site", action="store_true", help="also check live HTTP pages and private-file rejection")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.verify:
            verify_storage()
            return 0
        configuration = inspect(args.size_gib)
        if args.check_site:
            check_site()
        if args.apply:
            migrate(args.size_gib, *configuration)
        else:
            print("Preview only: no data, mounts, or services changed. Root database checks run before apply.")
    except (OSError, RuntimeError, subprocess.CalledProcessError, KeyboardInterrupt) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

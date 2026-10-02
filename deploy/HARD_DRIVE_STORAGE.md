# GoHMoTech data on the attached drive

The installer now includes **MariaDB and Redis**, in addition to uploaded files.
It targets the connected drive labeled `GOHMOTECH HARD DRIVE`, UUID
`C8CA20CFCA20BC16`. It preserves the drive's existing NTFS filesystem and files.
Only a newly created regular file is formatted as ext4:

```text
/media/gohmotech/GOHMOTECH HARD DRIVE/GoHMoTech/data.ext4
```

The image reserves **400 GiB** by default and mounts at `/srv/gohmotech-data`.
Use `--size-gib N` on both preview and apply to choose another size. At least
8 GiB must remain free on the outer drive. Allocation must be fully reserved;
the installer refuses sparse storage. Allocation and filesystem preparation can
take time, but occur before stopping the live services.

The storage scope includes:

- All GoHMoTech MariaDB databases and the database server's supporting files.
- Redis saved queue/cache state and its file logs.
- Production and beta uploads, private support evidence, model files, static
  assets, and the Celery scheduler state.
- Development media, protected models, private support uploads, and static output.
- Existing GoHMoTech transition, deployment, and camera configuration backups.

The OS, repository source, installed software, private environment configuration,
and system journal remain on the SD card. The script prints every selected
source/destination pair. An unrelated database, external tablespace, existing
storage mount, or existing destination causes it to stop for review.

## Run

Preview from the Raspberry Pi terminal; this changes no files or services:

```bash
cd /home/gohmotech/capstone
.venv/bin/python deploy/use_hard_drive_storage.py --check-site
```

Apply in the Pi terminal and enter the Pi sudo password there:

```bash
sudo /home/gohmotech/capstone/.venv/bin/python /home/gohmotech/capstone/deploy/use_hard_drive_storage.py --apply
```

The previous command now performs the full data migration; it is no longer an
uploads-only installer. The website and scheduled automation pause while services
are stopped and files are copied. MariaDB is shut down cleanly before its files
are copied. The installer also saves a logical database dump and Redis state.

It verifies file checksums, ownership and modes, then exposes the new locations
at the original paths using bind mounts. Original SD-card directories move into
`/var/backups/gohmotech-storage/<timestamp>/originals/`, and the old locations
become empty root-owned mountpoints with mode `000`. This prevents service users
from writing fallback data to the SD card if a drive mount disappears.

Systemd mount units provide drive → ext4 image → application directory ordering
at boot. Service drop-ins require their storage mounts; user services check their
application mount before starting. The installer preserves existing service
settings and database connection settings. The existing `/etc/fstab` is untouched.

## Verification and recovery

```bash
.venv/bin/python -m unittest deploy.test_hard_drive_storage
sudo /home/gohmotech/capstone/.venv/bin/python /home/gohmotech/capstone/deploy/use_hard_drive_storage.py --verify
```

Systemd unit validation needs to run outside the restricted workspace sandbox.
`--verify` checks the actual image backing the ext4 mount, every migrated path,
services, HTTP pages, static delivery, and private-file rejection. Application
database row counts are compared during migration before writers resume. A reboot
is **not** performed automatically: repeat `--verify` after a planned reboot.

Keep the drive connected and retain the original SD data and database dump until
verification after reboot succeeds. The copies on the same physical hard drive
are not protection against drive failure; retain an independent backup as well.

Before application writers resume, a migration error restores the original
SD-card directories and service configuration. The new image remains available
for inspection. Once writers resume, the hard drive is authoritative: a later
health-check error leaves that data in place and reports the issue rather than
restoring stale SD copies. Do not unmount the new data volume to roll back after
new writes have occurred. The private `plan.json` and `state` in the recovery
directory record the selected paths and cutover status.

The repository's broader `smoke_production.py` currently expects HTTP 403 for a
device request that returns HTTP 401. The storage checks use the relevant page
and file-delivery checks and do not change device authentication.

References: MariaDB lists ext4 among suitable Linux filesystems in its
[filesystem guidance](https://mariadb.com/docs/server/ha-and-performance/optimization-and-tuning/operating-system-optimizations/filesystem-optimizations).
Mount ordering follows the installed `systemd.mount(5)` and `systemd.unit(5)`
documentation. A file-backed ext4 filesystem adds another storage layer; it
preserves the existing NTFS data without repartitioning the drive.

"""Offline checks for data integrity, recovery and generated mount configuration."""

from pathlib import Path
import json
import os
import pwd
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from deploy import use_hard_drive_storage as storage


class StorageMigrationTests(unittest.TestCase):
    def test_checksum_detects_same_size_corruption_permissions_and_empty_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source", Path(directory) / "target"
            source.mkdir()
            target.mkdir()
            (source / "photo").write_bytes(b"original")
            (target / "photo").write_bytes(b"original")
            self.assertEqual(storage.manifest(source), storage.manifest(target))
            (target / "photo").write_bytes(b"tampered")
            self.assertNotEqual(storage.manifest(source), storage.manifest(target))
            (target / "photo").write_bytes(b"original")
            (target / "photo").chmod(0o600)
            self.assertNotEqual(storage.manifest(source), storage.manifest(target))
            (source / "photo").chmod(0o600)
            (source / "empty").mkdir()
            self.assertNotEqual(storage.manifest(source), storage.manifest(target))

    def test_symlink_content_is_compared_without_reading_external_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "link").symlink_to("/nonexistent/private-file")
            record = storage.manifest(root)["link"]
            self.assertEqual(record[0], "link")
            self.assertEqual(record[-1], "/nonexistent/private-file")

    def test_special_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.mkfifo(root / "pipe")
            with self.assertRaises(RuntimeError):
                storage.manifest(root)

    def test_copy_preserves_real_file_bytes_and_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir(mode=0o750)
            (source / "database").write_bytes(b"simulated database pages\x00\x01")
            (source / "database").chmod(0o640)
            (source / "empty").mkdir()
            with patch.object(storage, "VOLUME", root / "volume"):
                target = storage.Target(source, "mysql")
                storage.copy_verified(target)
                self.assertEqual(storage.manifest(source), storage.manifest(target.destination))

    def test_parking_and_restoring_originals_is_lossless_and_blocks_fallback_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "important").write_bytes(b"keep this original")
            before = storage.manifest(source)
            target, backup = storage.Target(source, "production"), root / "backup"
            storage.park_original(target, backup)
            self.assertEqual(source.stat().st_mode & 0o777, 0)
            self.assertEqual(storage.manifest(backup / "originals/production"), before)
            storage.restore_original(target, backup)
            self.assertEqual(storage.manifest(source), before)

    def test_restore_refuses_unexpected_new_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "original").write_text("original")
            target, backup = storage.Target(source, "production"), root / "backup"
            storage.park_original(target, backup)
            source.chmod(0o700)
            (source / "unexpected").write_text("must be kept")
            with self.assertRaises(OSError):
                storage.restore_original(target, backup)
            self.assertEqual((source / "unexpected").read_text(), "must be kept")
            self.assertEqual((backup / "originals/production/original").read_text(), "original")

    def test_existing_image_is_never_formatted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.ext4"
            path.write_bytes(b"existing drive data")
            with patch.object(storage, "IMAGE", path), patch.object(storage, "run") as run:
                with self.assertRaises(FileExistsError):
                    storage.create_image(8)
                run.assert_not_called()
            self.assertEqual(path.read_bytes(), b"existing drive data")

    def test_all_mount_units_pass_systemd_validation_including_paths_with_spaces(self):
        account = pwd.getpwuid(os.getuid())
        edits = storage.configurations(account, storage.TARGETS)
        with tempfile.TemporaryDirectory() as directory:
            units = []
            for path, content in edits.items():
                if path.suffix == ".mount":
                    target = Path(directory) / path.name
                    target.write_text(content)
                    units.append(str(target))
            result = subprocess.run(["systemd-analyze", "verify", *units], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        volume = edits[storage.SYSTEM_UNITS / storage.mount_name(storage.VOLUME)]
        self.assertIn("BindsTo=" + storage.mount_name(storage.MOUNT), volume)
        mysql = edits[storage.SYSTEM_UNITS / storage.mount_name(Path("/var/lib/mysql"))]
        self.assertIn("BindsTo=" + storage.mount_name(storage.VOLUME), mysql)

    def test_user_guard_does_not_require_access_to_private_database_directories(self):
        guard = storage.service_guard([storage.SOURCE], user=True)
        self.assertIn("mountpoint", guard)
        self.assertNotIn("/var/lib/redis", guard)
        self.assertNotIn("/var/lib/mysql", guard)

    def test_database_scope_refuses_unrelated_schemas(self):
        with patch.object(storage, "sql", return_value="mysql\ngohmotech_beta\nunrelated_database"):
            with self.assertRaises(RuntimeError):
                storage.database_counts()

    def test_verification_rejects_a_volume_backed_by_a_different_file(self):
        outputs = (
            {"filesystems": [{"uuid": storage.DRIVE_UUID}]},
            {"filesystems": [{"source": "/dev/loop1", "fstype": "ext4", "options": "rw,noatime"}]},
            {"loopdevices": [{"back-file": "/tmp/unrelated.ext4"}]},
        )
        responses = [subprocess.CompletedProcess([], 0, json.dumps(output)) for output in outputs]
        with patch.object(storage, "run", side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, "unexpected backing file"):
                storage.verify_storage()

    def test_atomic_configuration_replacement_preserves_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config"
            storage.write_atomic(path, "old\n", 0o600)
            storage.write_atomic(path, "new\n", 0o600)
            self.assertEqual(path.read_text(), "new\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()

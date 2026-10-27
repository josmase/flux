import gzip
import os
import tempfile
import unittest
from pathlib import Path

from check_backup import BackupCheckError, check_backup


class BackupHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.now = 1_800_000_000.0

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, name="immich-db-backup-20261027T020000-v1.sql.gz", content=b"database"):
        path = self.directory / name
        with gzip.open(path, "wb") as target:
            target.write(content)
        os.utime(path, (self.now - 60, self.now - 60))
        return path

    def test_recent_complete_archive_passes_and_is_decompressed_for_integrity(self):
        path = self.archive()
        self.assertEqual(check_backup(self.directory, 36 * 3600, 90 * 60, self.now), path)

    def test_tmp_only_is_never_counted_as_success(self):
        partial = self.directory / "immich-db-backup-20261027T020000-v1.sql.gz.tmp"
        partial.write_bytes(b"partial")
        os.utime(partial, (self.now - 60, self.now - 60))
        with self.assertRaisesRegex(BackupCheckError, r"no completed .*\.tmp files do not count"):
            check_backup(self.directory, 36 * 3600, 90 * 60, self.now)

    def test_stale_tmp_fails_even_if_an_older_final_archive_exists(self):
        self.archive()
        partial = self.directory / "immich-db-backup-20261027T020000-v1.sql.gz.tmp"
        partial.write_bytes(b"partial")
        os.utime(partial, (self.now - 2 * 3600, self.now - 2 * 3600))
        partial.touch()
        with self.assertRaisesRegex(BackupCheckError, "stale incomplete"):
            check_backup(self.directory, 36 * 3600, 90 * 60, self.now)

    def test_fresh_tmp_does_not_hide_valid_final_archive(self):
        path = self.archive()
        partial = self.directory / "immich-db-backup-20261027T020000-v1.sql.gz.tmp"
        partial.write_bytes(b"partial")
        os.utime(partial, (self.now - 60, self.now - 60))
        self.assertEqual(check_backup(self.directory, 36 * 3600, 90 * 60, self.now), path)

    def test_stale_final_archive_fails(self):
        path = self.archive()
        path.touch()
        # A timestamp older than the configured 36-hour acceptance window.
        os.utime(path, (self.now - 37 * 3600, self.now - 37 * 3600))
        with self.assertRaisesRegex(BackupCheckError, "latest completed archive is stale"):
            check_backup(self.directory, 36 * 3600, 90 * 60, self.now)

    def test_corrupt_final_archive_fails(self):
        path = self.directory / "immich-db-backup-20261027T020000-v1.sql.gz"
        path.write_bytes(b"not gzip")
        os.utime(path, (self.now - 60, self.now - 60))
        with self.assertRaisesRegex(BackupCheckError, "unreadable or corrupt"):
            check_backup(self.directory, 36 * 3600, 90 * 60, self.now)

    def test_missing_directory_fails(self):
        with self.assertRaisesRegex(BackupCheckError, "directory is unavailable"):
            check_backup(self.directory / "missing", 36 * 3600, 90 * 60, self.now)


if __name__ == "__main__":
    unittest.main()

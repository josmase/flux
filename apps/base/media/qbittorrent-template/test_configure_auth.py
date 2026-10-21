"""Regression tests for qBittorrent WebUI auth configuration."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("configure-auth.py")
SPEC = importlib.util.spec_from_file_location("configure_auth", SCRIPT)
configure_auth = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configure_auth)


class ConfigureAuthTests(unittest.TestCase):
    def test_updates_existing_backslash_keys_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "qBittorrent.conf"
            password_file = Path(directory) / "password"
            config.write_text(
                "[Preferences]\n"
                "WebUI\\Username=old-user\n"
                "WebUI\\Password_PBKDF2=old-hash\n"
                "WebUI\\Address=*\n"
                "\n[BitTorrent]\n"
                "Session\\DefaultSavePath=/config/Downloads\n"
            )
            password_file.write_text("new-password\n")
            environment = {
                "QBITTORRENT_CONFIG": str(config),
                "QBITTORRENT_USERNAME": "new-user",
                "QBITTORRENT_PASSWORD_FILE": str(password_file),
                "PUID": "1000",
                "PGID": "1000",
            }

            with patch.dict(os.environ, environment, clear=False), patch.object(
                configure_auth.os, "chown"
            ):
                configure_auth.main()

            result = config.read_text()
            self.assertEqual(result.count("WebUI\\Username="), 1)
            self.assertIn("WebUI\\Username=new-user\n", result)
            self.assertEqual(result.count("WebUI\\Password_PBKDF2="), 1)
            self.assertIn("WebUI\\Password_PBKDF2=@ByteArray(", result)
            self.assertIn("WebUI\\Address=*\n", result)
            self.assertIn("\n[BitTorrent]\nSession\\DefaultSavePath=/mnt/storage/downloads/complete\n", result)
            self.assertIn("Session\\TempPath=/mnt/storage/downloads/incomplete\n", result)
            self.assertIn("Session\\TempPathEnabled=true\n", result)


if __name__ == "__main__":
    unittest.main()

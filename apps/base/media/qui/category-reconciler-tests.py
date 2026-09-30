import importlib.util
import io
import logging
import os
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = os.path.join(os.path.dirname(__file__), "category_reconciler.py")
SPEC = importlib.util.spec_from_file_location("category_reconciler", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeClient:
    def __init__(self, categories):
        self._categories = categories
        self.created = []
        self.updated = []

    def login(self):
        pass

    def categories(self):
        return self._categories

    def create_category(self, category, save_path):
        self.created.append((category, save_path))

    def edit_category(self, category, save_path):
        self.updated.append((category, save_path))


class CategoryReconcilerTests(unittest.TestCase):
    def test_load_categories_ignores_comments_and_blank_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as categories:
            categories.write("# comment\n\nseriessix\n")
            categories.flush()
            self.assertEqual(MODULE.load_categories(categories.name), ["seriessix"])

    def test_desired_paths(self):
        self.assertEqual(
            MODULE.desired_paths(["seriessix"]),
            {"seriessix": "/mnt/storage/downloads/complete/seriessix"},
        )

    def test_reconcile_creates_missing_and_updates_wrong_paths(self):
        client = FakeClient({"seriessix": {"save_path": ""}})
        created, updated = MODULE.reconcile(
            client,
            {
                "seriessix": "/mnt/storage/downloads/complete/seriessix",
                "radarrone": "/mnt/storage/downloads/complete/radarrone",
            },
        )
        self.assertEqual((created, updated), (1, 1))
        self.assertEqual(client.created, [("radarrone", "/mnt/storage/downloads/complete/radarrone")])
        self.assertEqual(client.updated, [("seriessix", "/mnt/storage/downloads/complete/seriessix")])

    def test_reconcile_is_idempotent(self):
        client = FakeClient({"seriessix": {"savePath": "/mnt/storage/downloads/complete/seriessix"}})
        self.assertEqual(MODULE.reconcile(client, {"seriessix": "/mnt/storage/downloads/complete/seriessix"}), (0, 0))

    def test_proxy_base_supports_path_and_absolute_url(self):
        self.assertEqual(MODULE.proxy_base("/proxy/key"), "http://127.0.0.1:7476/proxy/key")
        self.assertEqual(MODULE.proxy_base("https://qui.example/proxy/key"), "https://qui.example/proxy/key")

    def test_failure_log_does_not_include_secret(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("secret-test")
        logger.addHandler(handler)
        try:
            secret = "do-not-log-this"
            with patch.object(MODULE, "reconcile_once", side_effect=RuntimeError(secret)):
                try:
                    MODULE.reconcile_once()
                except RuntimeError as error:
                    logger.error("Category reconciliation failed: %s", error.__class__.__name__)
            self.assertNotIn(secret, stream.getvalue())
        finally:
            logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()

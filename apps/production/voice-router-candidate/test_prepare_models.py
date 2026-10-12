"""Tests for checksum-gated model replacement and cleanup."""
import hashlib
from io import BytesIO
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

prepare_model = runpy.run_path(str(Path(__file__).with_name('prepare-models.py')))['prepare_model']


class PrepareModelTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.target = self.root / 'large-v3-turbo-pinned'
        self.previous = self.root / 'medium-pinned'
        self.previous.mkdir()
        (self.previous / 'model.bin').write_bytes(b'old model')
        self.payload = b'new pinned model data'
        self.model = {
            'repository': 'example/whisper',
            'revision': '0123456789abcdef',
            'files': {'model.bin': hashlib.sha256(self.payload).hexdigest()},
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def test_verified_replacement_removes_only_old_model_directory(self):
        with patch('urllib.request.urlopen', return_value=BytesIO(self.payload)):
            prepare_model(self.model, self.target, self.previous)

        self.assertEqual((self.target / 'model.bin').read_bytes(), self.payload)
        self.assertFalse(self.previous.exists())

    def test_checksum_failure_preserves_old_model(self):
        self.model['files']['model.bin'] = '0' * 64
        with patch('urllib.request.urlopen', return_value=BytesIO(self.payload)):
            with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                prepare_model(self.model, self.target, self.previous)

        self.assertEqual((self.previous / 'model.bin').read_bytes(), b'old model')

    def test_unexpected_cleanup_path_is_rejected(self):
        unexpected = self.root / 'keep-me'
        unexpected.mkdir()
        with patch('urllib.request.urlopen', return_value=BytesIO(self.payload)):
            with self.assertRaisesRegex(ValueError, 'unexpected model directory'):
                prepare_model(self.model, self.target, unexpected)

        self.assertTrue(unexpected.is_dir())
        self.assertTrue(self.previous.is_dir())


if __name__ == '__main__':
    unittest.main()

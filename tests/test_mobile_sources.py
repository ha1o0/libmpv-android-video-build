import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fetch_mobile_sources import fetch


class SourceTests(unittest.TestCase):
    def archive(self, name='source/code.c'):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as tar:
            entry = tarfile.TarInfo(name)
            entry.size = 4
            tar.addfile(entry, io.BytesIO(b'code'))
        return output.getvalue()

    def test_verified_archive_and_no_patched_source_reuse(self):
        data = self.archive()
        with tempfile.TemporaryDirectory() as tmp, patch('fetch_mobile_sources.urlopen', return_value=io.BytesIO(data)):
            target = Path(tmp) / 'mpv'
            fetch(dict(url='https://example.test/source', sha256=hashlib.sha256(data).hexdigest()), target)
            self.assertEqual((target / 'code.c').read_text(), 'code')
            with self.assertRaises(ValueError):
                fetch({}, target)

    def test_mismatched_hash_never_extracts(self):
        with tempfile.TemporaryDirectory() as tmp, patch('fetch_mobile_sources.urlopen', return_value=io.BytesIO(self.archive())):
            target = Path(tmp) / 'mpv'
            with self.assertRaisesRegex(ValueError, 'checksum'):
                fetch(dict(url='https://example.test/source', sha256='0' * 64), target)
            self.assertFalse(target.exists())

    def test_unsafe_paths_never_extract(self):
        data = self.archive('source/../../escape')
        with tempfile.TemporaryDirectory() as tmp, patch('fetch_mobile_sources.urlopen', return_value=io.BytesIO(data)):
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                fetch(dict(url='https://example.test/source', sha256=hashlib.sha256(data).hexdigest()), Path(tmp) / 'mpv')

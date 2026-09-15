from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from research_lab.serde import atomic_write


class ArtifactTests(unittest.TestCase):
    def test_atomic_write_recovers_from_transient_windows_file_lock(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "artifact.json"
            atomic_write(path, b"old")
            original = Path.replace
            attempts = []

            def replace(source, target):
                attempts.append(source)
                if len(attempts) == 1:
                    error = PermissionError("Transient sharing violation")
                    error.winerror = 32
                    raise error
                return original(source, target)

            with patch.object(Path, "replace", replace), patch("research_lab.serde.time.sleep"):
                atomic_write(path, b"new")
            self.assertEqual(path.read_bytes(), b"new")
            self.assertEqual(len(attempts), 2)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_permanent_replace_error_preserves_old_artifact(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "artifact.json"
            atomic_write(path, b"old")
            with patch.object(Path, "replace", side_effect=PermissionError("Denied")):
                with self.assertRaises(PermissionError):
                    atomic_write(path, b"new")
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

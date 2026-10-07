"""Run with unittest too, so native smoke needs no test-only dependencies."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from process_lock import exclusive_file_lock


class ProcessLockTests(unittest.TestCase):
    def test_releases_on_error_and_can_be_reused(self):
        with tempfile.TemporaryDirectory(prefix="knu-process-lock-") as directory:
            lock = Path(directory) / "inference.lock"
            with self.assertRaisesRegex(ValueError, "test error"):
                with exclusive_file_lock(lock):
                    raise ValueError("test error")
            with exclusive_file_lock(lock):
                pass

    def test_another_process_waits_until_lock_is_released(self):
        with tempfile.TemporaryDirectory(prefix="knu-process-lock-") as directory:
            lock = Path(directory) / "inference.lock"
            code = (
                "import sys; from process_lock import exclusive_file_lock; "
                "print('ready',flush=True)\n"
                "with exclusive_file_lock(sys.argv[1]): print('acquired',flush=True)\n"
            )
            child = None
            try:
                with exclusive_file_lock(lock):
                    child = subprocess.Popen(
                        [sys.executable, "-B", "-c", code, str(lock)],
                        cwd=Path(__file__).resolve().parents[1],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True,
                    )
                    self.assertEqual(child.stdout.readline().strip(), "ready")
                    with self.assertRaises(subprocess.TimeoutExpired):
                        child.wait(timeout=0.4)
                stdout, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, stderr)
                self.assertEqual(stdout.strip(), "acquired")
            finally:
                if child is not None:
                    if child.poll() is None:
                        child.kill()
                    child.communicate()

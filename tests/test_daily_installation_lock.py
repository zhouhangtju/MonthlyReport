import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import daily_installation as task


class LockTests(unittest.TestCase):
    def test_native_lock_excludes_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.lock'
            with task.task_lock(path):
                with self.assertRaises(RuntimeError):
                    with task.task_lock(path):
                        self.fail('duplicate lock acquired')
            with task.task_lock(path):
                pass

    def test_windows_unlocks_on_exception(self):
        api = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=Mock())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.lock'
            with patch.object(task.os, 'name', 'nt'), patch.dict(sys.modules, msvcrt=api):
                with self.assertRaises(ValueError):
                    with task.task_lock(path):
                        raise ValueError('test')
            self.assertEqual([call.args[1:] for call in api.locking.call_args_list], [(1, 1), (2, 1)])
            self.assertEqual(path.read_bytes(), b'0')

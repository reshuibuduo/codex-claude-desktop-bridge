import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'bridge'))
from platform_support import data_directory, lock_exclusive, windows_path_is_private
from live_service import atomic_json
import desktop_setup as setup


class PlatformTests(unittest.TestCase):
    def test_data_override(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'CODEX_CLAUDE_BRIDGE_DATA': folder}):
            self.assertEqual(data_directory(), Path(folder).resolve())

    def test_default_data_directory(self):
        with patch.dict(os.environ):
            os.environ.pop('CODEX_CLAUDE_BRIDGE_DATA', None)
            if os.name == 'nt':
                self.assertEqual(data_directory(), Path(os.environ['LOCALAPPDATA'])/'CodexClaudeBridge')
            else:
                self.assertEqual(data_directory(), Path.home()/'Library/Application Support/CodexClaudeBridge')

    def test_cross_process_lock_and_release(self):
        # A separate interpreter must be excluded; closing the original file restores access.
        code = """import sys
sys.path.insert(0, sys.argv[1])
from platform_support import lock_exclusive
with open(sys.argv[2], 'a') as f:
    try: lock_exclusive(f)
    except BlockingIOError: print('LOCK_BUSY'); sys.exit(3)
    print('LOCK_ACQUIRED')
"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'test.lock'
            def attempt():
                return subprocess.run([sys.executable, '-c', code, str(ROOT/'bridge'), str(path)],
                                      capture_output=True, text=True, timeout=10)
            with path.open('a') as f:
                lock_exclusive(f)
                r = attempt(); self.assertEqual((r.returncode, r.stdout.strip()), (3, 'LOCK_BUSY'), r.stderr)
            r = attempt(); self.assertEqual((r.returncode, r.stdout.strip()), (0, 'LOCK_ACQUIRED'), r.stderr)

    @unittest.skipUnless(os.name == 'nt', 'native Windows DACL readback')
    def test_state_json_has_private_dacl(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'state.json'
            atomic_json(path, {'text': 'fixture'})
            self.assertTrue(windows_path_is_private(path))

    def test_unicode_config_and_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); project = root/'项目 with spaces'; project.mkdir()
            config = root/'设置.json'
            value = {'enabled': False, 'thread_id': 'test', 'cwd': str(project), 'state_dir': str(root/'状态')}
            atomic_json(config, value)
            self.assertEqual(setup.read(config), value)
            record = setup.install_mcp(project, config, ROOT/'bridge/desktop_mcp.py', root/'audit', 'test')
            entry = setup.read(project/'.mcp.json')['mcpServers'][setup.SERVER_NAME]
            self.assertIn(str(project), entry['args'])
            setup.uninstall_mcp(record['manifest'])
            self.assertNotIn(setup.SERVER_NAME, setup.read(project/'.mcp.json')['mcpServers'])


if __name__ == '__main__': unittest.main()

import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bridge'));sys.path.insert(0,str(ROOT/'scripts'))
import desktop_setup as setup
from prepare_runtime import validate_members

class ReleasePackageTests(unittest.TestCase):
    def test_mcp_uses_running_interpreter_and_isolation_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project=root/'project';project.mkdir();script=root/'desktop_mcp.py'
            setup.install_mcp(project,root/'config.json',script,root/'audit','test')
            entry=json.loads((project/'.mcp.json').read_text())['mcpServers'][setup.SERVER_NAME]
            self.assertEqual(entry['command'],str(Path(sys.executable).resolve()))
            self.assertEqual(entry['args'][:4],['-E','-s','-B',str(script.resolve())])
            # Reinstall understands the flags; it does not treat them as the script path.
            setup.install_mcp(project,root/'config.json',script,root/'audit','test')
    def test_legacy_connector_can_be_updated_and_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();script=root/'desktop_mcp.py'
            old={'command':'/usr/bin/python3','args':[str(script),'--config',str(root/'config.json')]}
            path=root/'.mcp.json';path.write_text(json.dumps({'mcpServers':{setup.SERVER_NAME:old}}))
            record=setup.install_mcp(root,root/'config.json',script,root/'audit','test')
            setup.uninstall_mcp(record['manifest'])
            self.assertEqual(json.loads(path.read_text())['mcpServers'][setup.SERVER_NAME],old)
    def test_archive_rejects_traversal(self):
        for name in ['../outside','/absolute','python/../../outside']:
            with self.assertRaises(ValueError):validate_members([tarfile.TarInfo(name)])
    def test_archive_rejects_escaping_link(self):
        m=tarfile.TarInfo('python/bin/python3');m.type=tarfile.SYMTYPE;m.linkname='../../outside'
        with self.assertRaises(ValueError):validate_members([m])
    def test_archive_allows_internal_link(self):
        m=tarfile.TarInfo('python/bin/python3');m.type=tarfile.SYMTYPE;m.linkname='python3.12'
        validate_members([m])
    def test_runtime_is_pinned_for_both_architectures(self):
        lock=json.loads((ROOT/'menu/python-runtime.lock.json').read_text())
        self.assertEqual(set(lock['archives']),{'arm64','x86_64'})
        for value in lock['archives'].values():
            self.assertTrue(value['url'].startswith('https://github.com/astral-sh/python-build-standalone/releases/download/'))
            self.assertRegex(value['sha256'],r'^[a-f0-9]{64}$')
    def test_native_helper_has_no_system_python_fallback(self):
        source=(ROOT/'menu/MenuApp.swift').read_text()
        self.assertIn('process.executableURL=bundledPythonURL()',source)
        self.assertNotIn('/usr/bin/python3',source)

if __name__=='__main__':unittest.main()

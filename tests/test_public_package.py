import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bridge'))
import desktop_setup

class PublicPackageTests(unittest.TestCase):
    def test_default_admin_path_matches_native_app(self):
        self.assertEqual(desktop_setup.DEFAULT_CONFIG,Path.home()/'Library/Application Support/CodexClaudeBridge/config.json')
        swift=(ROOT/'menu/MenuApp.swift').read_text()
        self.assertIn('.applicationSupportDirectory',swift)
        self.assertIn('CODEX_CLAUDE_BRIDGE_DATA',swift)
        self.assertNotIn('acceptance/independent-recheck.json',swift)
    def test_mcp_rejects_wrong_actual_cwd_before_connection(self):
        with tempfile.TemporaryDirectory() as name:
            cwd=Path(name).resolve();config=cwd/'config.json'
            config.write_text(json.dumps({'enabled':True,'thread_id':'test','cwd':str(cwd),'state_dir':str(cwd/'state')}))
            result=subprocess.run([sys.executable,str(ROOT/'bridge/desktop_mcp.py'),'--config',str(config),
                '--expected-cwd',str(cwd),'--expected-thread','test'],cwd=ROOT,input='',capture_output=True,text=True,timeout=5)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('actual working directory differs',result.stderr)
            self.assertFalse((cwd/'state').exists())
    def test_clean_public_tree(self):
        result=subprocess.run([sys.executable,str(ROOT/'scripts/check_public_tree.py')],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PUBLIC_TREE_OK',result.stdout)

if __name__=='__main__':unittest.main()

"""Offline installed-bundle smoke test. Never contacts either model or a real binding."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import zlib

sys.dont_write_bytecode = True
import desktop_setup as setup


def main():
    resources = Path(__file__).resolve().parents[2]
    python = Path(sys.executable).resolve()
    if resources/'python' not in python.parents:
        raise RuntimeError('test must use this app\'s embedded Python')
    with sqlite3.connect(':memory:') as db:
        assert db.execute('select 1').fetchone() == (1,)
    assert ssl.OPENSSL_VERSION and hashlib.sha256(b'bridge').hexdigest()
    assert zlib.decompress(zlib.compress(b'bridge')) == b'bridge'
    assert ctypes.sizeof(ctypes.c_int) >= 4
    with tempfile.TemporaryDirectory(prefix='bridge-bundle-') as temp:
        root = Path(temp).resolve(); project = root/'project with spaces'; project.mkdir()
        config = root/'config.json'
        config.write_text(json.dumps({'enabled':False,'thread_id':'bundle-smoke',
            'cwd':str(project),'state_dir':str(root/'state')}))
        script = Path(__file__).with_name('desktop_mcp.py')
        record = setup.install_mcp(project, config, script, root/'audit', 'bundle-smoke')
        entry = json.loads((project/'.mcp.json').read_text())['mcpServers'][setup.SERVER_NAME]
        assert Path(entry['command']).resolve() == python
        request = '\n'.join(json.dumps(value) for value in [
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'ping'},
        ])+'\n'
        # A deliberately hostile Python environment must not change the selected runtime.
        env=dict(os.environ, PYTHONHOME='/nonexistent-runtime', PYTHONPATH='/nonexistent-modules')
        result=subprocess.run([entry['command']]+entry['args'], cwd=project, input=request,
                              capture_output=True,text=True,timeout=15,env=env)
        assert result.returncode == 0, result.stderr
        replies={item['id']:item for item in map(json.loads,result.stdout.splitlines())}
        assert replies[1]['result']['serverInfo']['name']=='codex-desktop-bridge'
        assert 'await_codex_failure' in {t['name'] for t in replies[2]['result']['tools']}
        assert replies[3]['result']=={}
        setup.uninstall_mcp(record['manifest'])
        assert setup.SERVER_NAME not in json.loads((project/'.mcp.json').read_text())['mcpServers']
    print('BUNDLE_SMOKE_OK python=embedded mcp=stdio install_restore=passed external_runs=0')


if __name__=='__main__':
    main()

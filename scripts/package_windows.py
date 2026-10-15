#!/usr/bin/env python3
"""Build/install/relocate/uninstall the Windows release with no model requests."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=kwargs.pop('timeout', 180), **kwargs)
    if result.stdout: print(result.stdout.strip(), flush=True)
    if result.returncode:
        raise RuntimeError('command failed: '+repr(args)+'\n'+result.stdout+'\n'+result.stderr)
    return result.stdout.strip()


def verify(app, env):
    exe = app/'CodexClaudeBridge.exe'
    checks = {'native':run([exe,'--self-test'],env=env),
              'bundled_runtime_mcp':run([exe,'--bundle-self-test'],env=env),
              'ui':run([exe,'--ui-smoke-test'],env=env,timeout=30)}
    assert 'TRAY_SELF_TEST_OK checks=10' in checks['native']
    assert 'BUNDLE_SMOKE_OK' in checks['bundled_runtime_mcp']
    assert 'UI_STARTUP_OK window=visible tray=ready' in checks['ui']
    python = app/'Resources/python/python.exe'; disabled = python.with_suffix('.disabled')
    python.rename(disabled)
    try:
        result = subprocess.run([exe,'--bundle-self-test'],env=env,capture_output=True,text=True,timeout=20)
        assert result.returncode != 0 and 'BUNDLE_RUNTIME_ERROR' in result.stdout
        checks['missing_runtime'] = 'nonzero exit; no system Python fallback'
    finally: disabled.rename(python)
    return checks


def main():
    if os.name != 'nt': raise SystemExit('build this release on native Windows x64')
    version = (ROOT/'VERSION').read_text(encoding='utf-8').strip()
    powershell = shutil.which('pwsh') or str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
    run([powershell,'-NoProfile','-ExecutionPolicy','Bypass','-File',ROOT/'windows/build.ps1'],timeout=600)
    app = ROOT/'dist/Codex Claude Bridge'; output = ROOT/'dist/release'; output.mkdir(exist_ok=True)
    iscc = shutil.which('ISCC.exe') or str(Path(os.environ['ProgramFiles(x86)'])/'Inno Setup 6/ISCC.exe')
    run([iscc, '/DAppVersion='+version, ROOT/'windows/installer.iss'],timeout=600)
    installer = output/('Codex-Claude-Bridge-'+version+'-Windows-x64-Setup.exe')
    portable = output/('Codex-Claude-Bridge-'+version+'-Windows-x64-Portable.zip')
    with zipfile.ZipFile(portable,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file(): archive.write(path,Path(app.name)/path.relative_to(app))
    result = {'version':version,'arch':'windows-x64','python':'3.12.15','authenticode':False,
              'source_commit':run(['git','rev-parse','HEAD'],cwd=ROOT),
              'source_dirty':bool(run(['git','status','--porcelain'],cwd=ROOT)),
              'model_requests':0,'windows_vendor_app_e2e':'not tested','checks':{}}
    with tempfile.TemporaryDirectory(prefix='bridge-win-release-') as name:
        root = Path(name); home = root/'home'; home.mkdir(); temp = root/'tmp'; temp.mkdir()
        data = root/'isolated data'; data.mkdir(); sentinel = data/'keep.txt'; sentinel.write_text('keep user data')
        env = dict(os.environ,PATH=str(root/'no-python-or-compiler'),HOME=str(home),USERPROFILE=str(home),
                   LOCALAPPDATA=str(home/'AppData/Local'),TEMP=str(temp),TMP=str(temp),
                   CODEX_CLAUDE_BRIDGE_DATA=str(data),CODEX_CLAUDE_BRIDGE_UI_CAPTURE=str(output/'windows-preview.png'),PYTHONHOME=str(root/'nonexistent-python'),PYTHONPATH=str(root/'nonexistent-modules'))
        relocated = root/'解压 folder with spaces'; relocated.mkdir()
        with zipfile.ZipFile(portable) as archive:
            assert archive.testzip() is None; archive.extractall(relocated)
        result['checks']['portable'] = verify(relocated/app.name, env)
        installed = root/'installed folder with spaces'
        run([installer,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/DIR='+str(installed),
             '/LOG='+str(root/'install.log')],env=env)
        result['checks']['installed'] = verify(installed, env)
        # A disabled fixture config must remain after uninstall; no real project or binding is touched.
        project = root/'fixture project'; project.mkdir()
        config = data/'config.json'
        config.write_text(json.dumps({'enabled':True,'thread_id':'fixture','cwd':str(project),'state_dir':str(data/'state')}),encoding='utf-8')
        run([installed/'unins000.exe','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LOG='+str(root/'uninstall.log')],env=env)
        # Inno's uninstaller may finish in a spawned process. Wait for observed removal, bounded.
        import time
        deadline = time.monotonic()+30
        while (installed/'CodexClaudeBridge.exe').exists() and time.monotonic()<deadline: time.sleep(0.2)
        assert not (installed/'CodexClaudeBridge.exe').exists(), 'installer did not remove app'
        assert sentinel.read_text() == 'keep user data'
        assert json.loads(config.read_text(encoding='utf-8'))['enabled'] is False
        result['checks']['installer_uninstall'] = 'app removed; fixture binding paused; user data retained'
        # Inno's self-deleting cleanup child can briefly outlive the main uninstaller.
        # Wait for its real file handles to close instead of suppressing cleanup errors.
        deadline = time.monotonic()+30
        while True:
            try:
                shutil.rmtree(temp)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if time.monotonic() >= deadline: raise
                time.sleep(0.2)
        result['checks']['uninstaller_cleanup'] = 'temporary executable handles released'
        assert (output/'windows-preview.png').is_file()

    result['assets'] = []
    for path in [installer,portable,output/'windows-preview.png']:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        result['assets'].append({'name':path.name,'bytes':path.stat().st_size,'sha256':sha})
        (output/(path.name+'.sha256')).write_text(sha+'  '+path.name+'\n',encoding='utf-8')
    (output/'validation-windows-x64.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('WINDOWS_RELEASE_OK x64 installer=passed portable=passed uninstall=passed real_desktop_e2e=not_tested')


if __name__ == '__main__': main()

#!/usr/bin/env python3
"""Build a DMG and verify its installed copy with an empty PATH and temporary HOME."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def run(args, **kwargs):
    result=subprocess.run([str(x) for x in args],check=True,text=True,capture_output=True,**kwargs)
    if result.stdout: print(result.stdout.strip(),flush=True)
    return result.stdout.strip()


def package():
    arch=platform.machine(); version=(ROOT/'VERSION').read_text().strip()
    app=ROOT/'dist/Codex Claude Bridge.app'
    destination=ROOT/'dist/release';destination.mkdir(parents=True,exist_ok=True)
    dmg=destination/('Codex-Claude-Bridge-'+version+'-macOS-'+arch+'.dmg')
    subprocess.run([str(ROOT/'menu/build.sh')],check=True)
    result={'version':version,'arch':arch,'minimum_macos':'13.0','signing':'ad-hoc',
            'notarized':False,'python':'3.12.15','model_requests':0,'checks':{}}
    try:
        result['source_commit']=run(['git','rev-parse','HEAD'],cwd=ROOT)
        result['source_dirty']=bool(run(['git','status','--porcelain'],cwd=ROOT))
    except subprocess.CalledProcessError: result['source_commit']='unavailable'
    with tempfile.TemporaryDirectory(prefix='bridge-package-') as temp:
        root=Path(temp);stage=root/'stage';stage.mkdir()
        shutil.copytree(app,stage/app.name,symlinks=True)
        (stage/'Applications').symlink_to('/Applications')
        shutil.copy2(ROOT/'docs/INSTALL.txt',stage/'INSTALL.txt')
        run(['/usr/bin/hdiutil','create','-volname','Codex Claude Bridge','-srcfolder',stage,
             '-format','UDZO','-ov',dmg])
        run(['/usr/bin/hdiutil','verify',dmg])
        mount=root/'mounted';mount.mkdir()
        run(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,dmg])
        try:
            assert (mount/'Applications').is_symlink()
            installed=root/'relocated folder with spaces'/app.name
            installed.parent.mkdir();shutil.copytree(mount/app.name,installed,symlinks=True)
            (root/'home').mkdir();(root/'tmp').mkdir()
            env={'HOME':str(root/'home'),'PATH':'/no-python-or-compiler-on-path','TMPDIR':str(root/'tmp')+'/',
                 'CODEX_CLAUDE_BRIDGE_DATA':str(root/'test-config')}
            binary=installed/'Contents/MacOS/CodexClaudeBridge'
            result['checks']['native']=run([binary,'--self-test'],env=env)
            result['checks']['bundled_runtime_mcp']=run([binary,'--bundle-self-test'],env=env)
            result['checks']['ui']=run([binary,'--ui-smoke-test'],env=env,timeout=20)
            run(['/usr/bin/codesign','--verify','--deep','--strict',installed])
            result['checks']['signature_after_execution']='passed'
            python=installed/'Contents/Resources/python/bin/python3.12'
            disabled=python.with_suffix('.disabled');python.rename(disabled)
            try:
                missing=subprocess.run([binary,'--bundle-self-test'],env=env,text=True,capture_output=True,timeout=15)
                assert missing.returncode != 0 and 'BUNDLE_RUNTIME_ERROR' in missing.stderr
                result['checks']['missing_runtime']='nonzero exit; no system Python fallback'
            finally: disabled.rename(python)
        finally: run(['/usr/bin/hdiutil','detach',mount])
    result['asset']=dmg.name
    result['sha256']=hashlib.sha256(dmg.read_bytes()).hexdigest()
    result['bytes']=dmg.stat().st_size
    (destination/('validation-'+arch+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    (destination/(dmg.name+'.sha256')).write_text(result['sha256']+'  '+dmg.name+'\n')
    print('RELEASE_PACKAGE_OK arch='+arch+' isolated_home=true path_without_python=true relocated=true')

if __name__=='__main__': package()

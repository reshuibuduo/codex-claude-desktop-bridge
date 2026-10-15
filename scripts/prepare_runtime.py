#!/usr/bin/env python3
"""Download a hash-pinned, relocatable CPython for the app. Build-time only."""
import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def validate_members(members):
    for member in members:
        name = posixpath.normpath(member.name)
        if not (name == 'python' or name.startswith('python/')):
            raise ValueError('archive path outside python root')
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ValueError('unsupported archive member')
        if member.issym() or member.islnk():
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), member.linkname)
                                       if member.issym() else member.linkname)
            if not target.startswith('python/'):
                raise ValueError('archive link outside python root')


def prepare(arch, destination):
    lock = json.loads((ROOT/'menu/python-runtime.lock.json').read_text())
    entry = lock['archives'][arch]
    cache = ROOT/'build/downloads'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache/entry['url'].rsplit('/', 1)[1]
    if not archive.exists():
        partial = archive.with_suffix('.partial')
        subprocess.run(['/usr/bin/curl', '--fail', '--location', '--retry', '3',
                        '--silent', '--show-error', entry['url'], '-o', str(partial)], check=True)
        partial.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != entry['sha256']:
        raise ValueError('runtime archive SHA256 mismatch; remove the cache file before retrying')
    if destination.exists():
        raise ValueError('runtime destination already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        with tarfile.open(archive) as package:
            validate_members(package.getmembers())
            # Pinned upstream archive; validated paths and links support Python 3.9 builders.
            package.extractall(temp)
        shutil.move(str(Path(temp)/'python'), destination)
    # Preserve all upstream library and license contents; do not generate bytecode in the bundle.
    for path in destination.rglob('__pycache__'):
        shutil.rmtree(path)
    print('PYTHON_RUNTIME_OK version='+lock['python']+' arch='+arch+' sha256='+entry['sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', choices=['arm64', 'x86_64'], required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.arch, args.destination)

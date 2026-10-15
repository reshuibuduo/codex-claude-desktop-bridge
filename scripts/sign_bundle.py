#!/usr/bin/env python3
"""Ad-hoc sign nested Mach-O files, then the app. This is not notarization."""
from pathlib import Path
import subprocess
import sys

app = Path(sys.argv[1]).resolve()
magic = {bytes.fromhex(x) for x in ['feedface','cefaedfe','feedfacf','cffaedfe','cafebabe','bebafeca','cafebabf','bfbafeca']}
count = 0
for path in sorted(app.rglob('*')):
    if path.is_file() and not path.is_symlink():
        with path.open('rb') as stream:
            is_macho = stream.read(4) in magic
        if is_macho:
            subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(path)], check=True, capture_output=True)
            count += 1
subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(app)], check=True)
subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)], check=True)
print('ADHOC_SIGNATURE_OK macho_files='+str(count)+' notarized=false')

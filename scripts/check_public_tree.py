#!/usr/bin/env python3
"""Small publication hygiene check; not a general secret scanner."""
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
BLOCKED_PARTS={'acceptance','BridgeData','work','.claude','.codex','__pycache__'}
PATTERNS={
    'machine-specific home path':re.compile(r'/(?:Users|home)/[^/\s]+/'),
    'token-shaped string':re.compile(r'\b(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{20,}\b'),
    'literal bearer credential':re.compile(r'Authorization:\s*Bearer\s+[A-Za-z0-9_.-]{12,}',re.I),
}

def check():
    result=subprocess.run(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT,capture_output=True,check=True)
    paths=sorted(set(x for x in result.stdout.decode().split('\0') if x))
    issues=[]
    for name in paths:
        path=ROOT/name
        if not path.is_file() or path.is_symlink():
            issues.append(name+': missing/nonregular file');continue
        if set(Path(name).parts)&BLOCKED_PARTS or name.endswith(('.sqlite','.log','.db')) or Path(name).name=='.mcp.json':
            issues.append(name+': runtime/private artifact');continue
        try:content=path.read_text()
        except UnicodeError:issues.append(name+': binary content');continue
        for label,regex in PATTERNS.items():
            if regex.search(content):issues.append(name+': '+label)
    if issues:raise SystemExit('\n'.join(issues))
    print('PUBLIC_TREE_OK files='+str(len(paths))+' obvious_private_patterns=0')

if __name__=='__main__':check()

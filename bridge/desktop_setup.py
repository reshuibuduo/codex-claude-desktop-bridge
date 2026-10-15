#!/usr/bin/env python3
"""Local configuration and reversible project MCP installation for the menu app."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid
sys.dont_write_bytecode = True
from desktop_ipc import DesktopIPC
from live_service import atomic_json, validate_config

SERVER_NAME='codex-desktop-bridge'
PROMPT='''这是 Codex → Claude 桌面自动接续待命会话。请调用 codex-desktop-bridge 的 await_codex_failure(timeout_seconds=900)。只有返回 HANDOFF_READY 才接续 context.goal；先核对磁盘现状和项目指引，保留现有修改，避免重复外部操作。完成后调用 report_completion(handoff_id, summary, tests_result)，如实记录实际测试，然后继续等候下一次故障。WAIT_TIMEOUT 只继续等待；DISABLED、PAUSED、ERROR、REVIEW_PREVIOUS_HANDOFF 或 COMPLETION_CONFLICT 停止并报告。不要将计划当作完成。使用中文。'''

def read(path): return json.loads(Path(path).read_text())
def write_config(path,value):
    validate_config(value)
    atomic_json(path,value)

def unresolved(config):
    db=Path(config['state_dir'])/'state.sqlite'
    if not db.exists():return False
    with contextlib.closing(sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)) as c:
        return bool(c.execute("SELECT 1 FROM handoffs WHERE state NOT IN ('completed','abandoned') LIMIT 1").fetchone())

def resolve(config_path, handoff_id, outcome, note):
    """Explicit local reconciliation after the user checked an uncertain target session."""
    cfg=validate_config(read(config_path))
    if cfg.get('enabled'):raise ValueError('pause before reconciling a previous handoff')
    if not note.strip() or len(note)>12000:raise ValueError('a bounded nonempty inspection note is required')
    if outcome not in ('completed','abandoned'):raise ValueError('invalid resolution')
    root=Path(cfg['state_dir'])
    with contextlib.closing(sqlite3.connect(str(root/'state.sqlite'))) as db,db:
        row=db.execute('SELECT thread_id,workspace,state FROM handoffs WHERE session_id=?',(handoff_id,)).fetchone()
        if not row or row[0]!=cfg['thread_id'] or row[1]!=cfg['cwd']:
            raise ValueError('handoff does not match configured binding')
        atomic_json(root/'handoffs'/handoff_id/'manual-resolution.json',{
            'outcome':outcome,'note':note,'evidence_kind':'explicit_user_reconciliation','time':time.time()})
        db.execute('UPDATE handoffs SET state=? WHERE session_id=?',(outcome,handoff_id))
        db.execute('DELETE FROM leases WHERE session_id=?',(handoff_id,))
    return {'phase':'PREVIOUS_HANDOFF_RECONCILED','outcome':outcome,'handoff_id':handoff_id}

def install_mcp(cwd, config_path, script, audit_dir, thread_id, previous_server=None):
    cwd,config_path,script,audit_dir=map(lambda p:Path(p).resolve(),(cwd,config_path,script,audit_dir))
    path=cwd/'.mcp.json'
    if path.is_symlink():raise ValueError('project MCP file is a symbolic link')
    original=path.read_bytes() if path.exists() else None
    value=json.loads(original) if original else {'mcpServers':{}}
    if not isinstance(value,dict) or not isinstance(value.get('mcpServers',{}),dict):
        raise ValueError('unexpected project MCP configuration')
    servers=value.setdefault('mcpServers',{})
    entry={'type':'stdio','command':str(Path(sys.executable).resolve()),'args':['-E','-s','-B',str(script),'--config',str(config_path),
           '--expected-cwd',str(cwd),'--expected-thread',thread_id], 'timeout':1000000}
    prior=servers.get(SERVER_NAME)
    if prior is not None:
        old_args=prior.get('args',[]) if isinstance(prior,dict) else []
        owned_paths=[str(script)] + ([str(Path(previous_server).resolve())] if previous_server else [])
        old_script = old_args[3] if old_args[:3] == ['-E','-s','-B'] and len(old_args)>3 else (old_args[0] if old_args else None)
        if old_script not in owned_paths:
            raise ValueError('existing connector name belongs to another installation')
    audit_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    stamp=str(time.time_ns());backup=audit_dir/('mcp-before-'+stamp+'.json')
    if original is not None:backup.write_bytes(original);backup.chmod(0o600)
    servers[SERVER_NAME]=entry
    atomic_json(path,value)
    record={'path':str(path),'entry':entry,'previous_entry':prior,
            'before_existed':original is not None,'backup':str(backup) if original is not None else None,
            'after_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest=audit_dir/('mcp-install-'+stamp+'.json');atomic_json(manifest,record)
    return {'mcp_file':str(path),'manifest':str(manifest)}

def uninstall_mcp(manifest):
    record=read(manifest);path=Path(record['path']);value=read(path)
    if value.get('mcpServers',{}).get(SERVER_NAME)!=record['entry']:
        raise ValueError('connector changed since installation; preserved')
    if record['previous_entry'] is None:del value['mcpServers'][SERVER_NAME]
    else:value['mcpServers'][SERVER_NAME]=record['previous_entry']
    # Preserve any later edits to other connectors. Empty files are retained.
    atomic_json(path,value)
    return {'phase':'MCP_ENTRY_RESTORED','path':str(path)}

def bind(config_path,thread_id,cwd,server,previous_server=None,ipc_factory=DesktopIPC):
    uuid.UUID(thread_id)
    path=Path(config_path).resolve();cwd=Path(cwd).resolve(strict=True)
    old=read(path) if path.exists() else None
    if old and (old.get('enabled') or unresolved(old)):
        raise ValueError('pause and finish the current handoff before changing the binding')
    ipc=ipc_factory()
    try:
        v=ipc.fresh_snapshot(thread_id,ipc.owner(thread_id))
        if Path(v.state['cwd']).resolve()!=cwd:raise ValueError('workspace does not match selected Codex conversation')
    finally:ipc.close()
    config={'enabled':False,'thread_id':thread_id,'cwd':str(cwd),
            'state_dir':str(path.parent/'sessions'/thread_id),'target':'claude-desktop-code'}
    audit=path.parent/'installation-records'
    result=install_mcp(cwd,path,server,audit,thread_id,previous_server)
    write_config(path,config)
    return dict(result,phase='BOUND_PAUSED',thread_id=thread_id,cwd=str(cwd))

def status(config_path):
    cfg=read(config_path);p=Path(cfg['state_dir'])/'desktop-status.json'
    current=read(p) if p.exists() else {'phase':'NO_STANDBY'}
    current.update(enabled=cfg.get('enabled') is True,thread_id=cfg['thread_id'],cwd=cfg['cwd'])
    if not current['enabled']:current['display_phase']='PAUSED'
    elif current.get('phase')=='WAITING_FOR_NEW_FAILURE' and time.time()-current.get('time',0)>20:
        current['display_phase']='STANDBY_STALE'
    else:current['display_phase']=current['phase']
    return current

DEFAULT_CONFIG=Path.home()/'Library/Application Support/CodexClaudeBridge/config.json'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    sub=p.add_subparsers(dest='action',required=True)
    b=sub.add_parser('bind');b.add_argument('--thread',required=True);b.add_argument('--cwd',required=True)
    b.add_argument('--server',type=Path,default=Path(__file__).with_name('desktop_mcp.py'));b.add_argument('--previous-server',type=Path)
    for name in ['enable','pause','status','prompt']:sub.add_parser(name)
    u=sub.add_parser('uninstall');u.add_argument('--manifest',required=True)
    r=sub.add_parser('resolve');r.add_argument('--handoff-id',required=True);r.add_argument('--outcome',choices=['completed','abandoned'],required=True);r.add_argument('--note',required=True)
    a=p.parse_args();os.umask(0o077)
    if a.action=='bind':result=bind(a.config,a.thread,a.cwd,a.server,a.previous_server)
    elif a.action in ('enable','pause'):
        cfg=read(a.config)
        if a.action=='enable' and cfg.get('enabled') is not True:cfg['arm_generation']=str(uuid.uuid4())
        cfg['enabled']=a.action=='enable';write_config(a.config,cfg)
        result={'phase':'ENABLED_WAITING_FOR_CLAUDE_STANDBY' if cfg['enabled'] else 'PAUSED'}
    elif a.action=='status':result=status(a.config)
    elif a.action=='prompt':result={'prompt':PROMPT}
    elif a.action=='resolve':result=resolve(a.config,a.handoff_id,a.outcome,a.note)
    else:result=uninstall_mcp(a.manifest)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()

#!/usr/bin/env python3
"""Project-scoped MCP bridge used by an already authenticated Claude Desktop Code session.
No standalone Claude process, credentials, GUI injection or synthetic failure notifications.
"""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

sys.dont_write_bytecode = True
from desktop_ipc import DesktopIPC, ProtocolError
from live_service import atomic_json, build_context, validate_config, NewFailureGate, source_signature
import bridge_core as core


class DesktopBridge:
    def __init__(self, config_path, ipc_factory=DesktopIPC):
        self.path = Path(config_path).resolve()
        self.config = validate_config(json.loads(self.path.read_text()))
        self.root = Path(self.config['state_dir'])
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.core = core.HandoffCore(self.root/'state.sqlite', self.root/'handoffs')
        self.ipc_factory = ipc_factory
        self.current_handoff = None
        self.cancel = threading.Event()
        self.guard = threading.Lock()

    def enabled(self):
        current = json.loads(self.path.read_text())
        return (core.AUTO_HANDOFF_ENABLED and current.get('enabled') is True and
                current.get('thread_id') == self.config['thread_id'] and
                isinstance(current.get('cwd'), str) and
                str(Path(current['cwd']).resolve()) == self.config['cwd'])

    def record(self, phase, **data):
        result = {'phase': phase, 'time': time.time(), 'pid': os.getpid(),
                  'target': 'claude-desktop-code', 'thread_id': self.config['thread_id'], **data}
        atomic_json(self.root/'desktop-status.json', result)
        return result

    def probe(self):
        if not self.enabled():
            return self.record('DISABLED')
        ipc = self.ipc_factory()
        try:
            owner = ipc.owner(self.config['thread_id'])
            v = ipc.fresh_snapshot(self.config['thread_id'], owner)
            e,s = v.normalized()
            return self.record('CONNECTED', owner=owner, source_turn=source_signature(v)[0],
                               source_status=source_signature(v)[1], decision=core.evaluate(e,s),
                               standalone_cli_required=False)
        finally:
            ipc.close()

    def allowed_test_errors(self, view):
        # Acceptance-only model fault, bound to this dedicated thread, exact model and nonce.
        # Never relabel it as overload. Production config omits this entire object.
        fault = self.config.get('acceptance_fault')
        if not isinstance(fault, dict):
            return ()
        turn = view.latest() or {}
        params = turn.get('params') or {}
        model = params.get('model') or (params.get('collaborationMode') or {}).get('settings',{}).get('model')
        nonce = fault.get('nonce')
        if (not isinstance(nonce, str) or not nonce or
            self.config['thread_id'] != fault.get('thread_id') or model != fault.get('model') or
            not str(model).startswith('handoff-acceptance-unavailable-') or
            nonce not in build_context(view, self.config)['goal']):
            return ()
        code = (turn.get('error') or {}).get('codexErrorInfo')
        return (code,) if isinstance(code,str) and code in ('badRequest','other','modelNotFound') else ()

    def failure_gate(self, view):
        """Retain the armed boundary across MCP timeouts/restarts, not across explicit re-enable."""
        path = self.root/'armed-cursor.json'
        generation = json.loads(self.path.read_text()).get('arm_generation')
        saved = json.loads(path.read_text()) if path.exists() else {}
        gate = NewFailureGate(view)
        if saved.get('thread_id') == self.config['thread_id'] and saved.get('generation') == generation:
            gate.initial_turn = saved['initial_turn']
            gate.skip_initial = saved['skip_initial']
        else:
            atomic_json(path, {'thread_id':self.config['thread_id'], 'generation':generation,
                              'initial_turn':gate.initial_turn, 'skip_initial':gate.skip_initial})
        return gate

    def remember_delivered(self, turn_id):
        generation = json.loads(self.path.read_text()).get('arm_generation')
        atomic_json(self.root/'armed-cursor.json', {'thread_id':self.config['thread_id'],
                    'generation':generation, 'initial_turn':turn_id, 'skip_initial':True})

    def await_failure(self, timeout_seconds=900, _cancel=None):
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 86400:
            raise ValueError('timeout_seconds must be an integer from 1 to 86400')
        if not self.guard.acquire(False):
            return {'phase':'ALREADY_WAITING'}
        cancel = _cancel if _cancel is not None else self.cancel
        if _cancel is None:
            cancel.clear()
        try:
            with (self.root/'desktop-wait.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return {'phase':'ALREADY_WAITING'}
                if not self.enabled():
                    return self.record('DISABLED')
                with contextlib.closing(self.core.connect()) as db:
                    rows = db.execute("SELECT session_id,state FROM handoffs WHERE state NOT IN ('completed','abandoned')").fetchall()
                if rows:
                    return self.record('REVIEW_PREVIOUS_HANDOFF', handoffs=rows)
                ipc = self.ipc_factory()
                try:
                    owner = ipc.owner(self.config['thread_id'])
                    view = ipc.fresh_snapshot(self.config['thread_id'], owner)
                    if str(Path(view.state['cwd']).resolve()) != self.config['cwd']:
                        raise ValueError('selected workspace mismatch')
                    gate = self.failure_gate(view)
                    generation = json.loads(self.path.read_text()).get('arm_generation')
                    self.record('WAITING_FOR_NEW_FAILURE', owner=owner, initial_turn=gate.initial_turn,
                                historical_terminal_skipped=gate.skip_initial)
                    deadline = time.monotonic()+timeout_seconds
                    heartbeat = time.monotonic()
                    last_decision = None
                    while time.monotonic() < deadline:
                        if cancel.is_set() or not self.enabled() or json.loads(self.path.read_text()).get('arm_generation') != generation:
                            return self.record('PAUSED')
                        if gate.candidate(view):
                            event,snapshot=view.normalized()
                            allowed=self.allowed_test_errors(view)
                            decision=core.evaluate(event,snapshot,allowed_errors=allowed)
                            if decision == 'PREPARE':
                                # Recheck identity, turn and terminal state immediately before delivery.
                                if ipc.owner(self.config['thread_id']) != owner:
                                    raise ProtocolError('owner changed')
                                fresh=ipc.fresh_snapshot(self.config['thread_id'],owner)
                                if source_signature(fresh)!=source_signature(view):
                                    raise ProtocolError('source changed before handoff')
                                event,snapshot=fresh.normalized()
                                allowed=self.allowed_test_errors(fresh)
                                context=build_context(fresh,self.config)
                                context['constraints']=['仅操作已绑定的项目；保留现有修改，遵循用户当前任务约束。',
                                                        '历史信息作为证据；不要重复已完成的外部操作。']
                                acceptance = isinstance(self.config.get('acceptance_verification'), dict)
                                if acceptance:
                                    context['constraints'].append('这是隔离验收；只修改 work/project/clamp.py，不改测试文件。')
                                if cancel.is_set() or not self.enabled() or json.loads(self.path.read_text()).get('arm_generation') != generation:
                                    return self.record('PAUSED')
                                bound_core=core.HandoffCore(self.root/'state.sqlite',self.root/'handoffs',allowed_errors=allowed)
                                result=bound_core.prepare(event,snapshot,context)
                                if result['action']!='PREPARED':
                                    return self.record(result['action'],details=result)
                                self.current_handoff=result['session_id']
                                package=Path(result['package'])
                                atomic_json(package/'launch.json', {
                                    'status':'delivered_as_mcp_tool_result', 'target':'claude-desktop-code',
                                    'source_thread_id':self.config['thread_id'],
                                    'source_turn_id':source_signature(fresh)[0],
                                    'handoff_id':self.current_handoff, 'cwd':self.config['cwd'],
                                    'standalone_cli_spawned':False})
                                atomic_json(package/'desktop-delivery.json',{
                                    'source_event':event,'source_snapshot':snapshot,'owner':owner,
                                    'target':'authenticated-claude-desktop-code','acceptance_fault':bool(allowed),
                                    'label':'real controlled invalid-model failure' if allowed else 'terminal service failure'})
                                with contextlib.closing(self.core.connect()) as db,db:
                                    db.execute("UPDATE handoffs SET state='desktop_delivered' WHERE session_id=?",(self.current_handoff,))
                                self.remember_delivered(source_signature(fresh)[0])
                                self.record('HANDOFF_DELIVERED',handoff_id=self.current_handoff,
                                            source_turn=source_signature(fresh)[0],actual_error=event['params']['turn']['error'],
                                            acceptance_fault=bool(allowed))
                                return {'phase':'HANDOFF_READY','handoff_id':self.current_handoff,
                                        'source_thread_id':self.config['thread_id'],
                                        'source_turn_id':source_signature(fresh)[0],
                                        'actual_source_error':event['params']['turn']['error'],
                                        'context':context,
                                        'instruction': ('现在接续 context.goal，先读现有文件，完成后调用 verify_acceptance；不要修改测试文件。'
                                            if acceptance else '现在接续 context.goal；先核对磁盘现状和项目指引，完成后调用 report_completion，填写真实测试结果。')}
                            if decision != last_decision:
                                self.record('SOURCE_FAILURE_NOT_ELIGIBLE',decision=decision,
                                            source_turn=source_signature(view)[0])
                                last_decision = decision
                        elif time.monotonic()-heartbeat >= 5:
                            self.record('WAITING_FOR_NEW_FAILURE', owner=owner,
                                        initial_turn=gate.initial_turn, historical_terminal_skipped=gate.skip_initial)
                            heartbeat = time.monotonic()
                        if cancel.wait(0.5):
                            return self.record('PAUSED')
                        if ipc.owner(self.config['thread_id'])!=owner:
                            raise ProtocolError('source owner changed')
                        view=ipc.fresh_snapshot(self.config['thread_id'],owner)
                    return self.record('WAIT_TIMEOUT',handoffs_delivered=0)
                finally:
                    ipc.close()
        finally:
            self.guard.release()

    def report_completion(self, handoff_id, summary, tests_result):
        """Record the target agent's report; never mislabel it as independent verification."""
        if handoff_id != self.current_handoff or not handoff_id:
            raise ValueError('handoff identity mismatch')
        if not all(isinstance(x,str) and 0 < len(x) <= 12000 for x in (summary,tests_result)):
            raise ValueError('bounded nonempty summary and tests_result required')
        if self.config.get('acceptance_verification'):
            raise ValueError('acceptance requires the fixed independent verifier')
        ipc = self.ipc_factory()
        try:
            view=ipc.fresh_snapshot(self.config['thread_id'],ipc.owner(self.config['thread_id']))
            with contextlib.closing(self.core.connect()) as db:
                row=db.execute('SELECT turn_id FROM handoffs WHERE session_id=?',(handoff_id,)).fetchone()
            if not row or source_signature(view)!=(row[0],'failed'):
                return self.record('COMPLETION_CONFLICT',reason='source_resumed_or_changed')
        finally:
            ipc.close()
        atomic_json(self.root/'handoffs'/handoff_id/'completion.json',{
            'handoff_id':handoff_id,'summary':summary,'tests_result':tests_result,
            'evidence_kind':'target_agent_report_not_independent_verification','time':time.time()})
        with contextlib.closing(self.core.connect()) as db,db:
            db.execute("UPDATE handoffs SET state='completed' WHERE session_id=?",(handoff_id,))
            db.execute('DELETE FROM leases WHERE session_id=?',(handoff_id,))
        return self.record('COMPLETED_REPORTED',handoff_id=handoff_id)

    def verify_acceptance(self, handoff_id):
        # This test-only verifier never accepts caller-supplied shell/code/paths.
        if handoff_id != self.current_handoff or not handoff_id:
            raise ValueError('handoff identity mismatch')
        import hashlib
        verification=self.config.get('acceptance_verification')
        if not isinstance(verification,dict):
            return {'phase':'REQUIRES_PROJECT_VERIFICATION','handoff_id':handoff_id}
        cwd=Path(self.config['cwd'])/'work/project'
        tests=cwd/'test_clamp.py'
        if hashlib.sha256(tests.read_bytes()).hexdigest()!=verification['test_sha256']:
            return self.record('VERIFY_FAILED',reason='test_file_changed')
        ipc=self.ipc_factory()
        try:
            view=ipc.fresh_snapshot(self.config['thread_id'],ipc.owner(self.config['thread_id']))
            with contextlib.closing(self.core.connect()) as db:
                row=db.execute('SELECT turn_id FROM handoffs WHERE session_id=?',(handoff_id,)).fetchone()
            if not row or source_signature(view)!=(row[0],'failed'):
                return self.record('VERIFY_FAILED',reason='source_resumed_or_changed')
        finally:ipc.close()
        result=subprocess.run([sys.executable,'-m','unittest','-v'],cwd=cwd,capture_output=True,text=True,timeout=30)
        report={'phase':'ACCEPTANCE_PASSED' if result.returncode==0 else 'VERIFY_FAILED',
                'handoff_id':handoff_id,'command':[sys.executable,'-m','unittest','-v'],'cwd':str(cwd),
                'stdout':result.stdout,'stderr':result.stderr,'exit_status':result.returncode,
                'test_sha256':hashlib.sha256(tests.read_bytes()).hexdigest(),
                'changed_file_sha256':hashlib.sha256((cwd/'clamp.py').read_bytes()).hexdigest()}
        atomic_json(self.root/'acceptance-result.json',report)
        if result.returncode==0:
            with contextlib.closing(self.core.connect()) as db,db:
                db.execute("UPDATE handoffs SET state='completed' WHERE session_id=?",(handoff_id,))
                db.execute('DELETE FROM leases WHERE session_id=?',(handoff_id,))
        self.record(report['phase'],handoff_id=handoff_id,exit_status=result.returncode)
        return report

TOOLS=[
 {'name':'bridge_status','description':'Read connection to the one configured Codex Desktop conversation. No standalone Claude login.',
  'inputSchema':{'type':'object','properties':{},'additionalProperties':False},'annotations':{'readOnlyHint':True}},
 {'name':'await_codex_failure','description':'Wait for a NEW final failure of the selected Codex Desktop conversation and return its user goal. This may wait many minutes. Do not edit files before HANDOFF_READY.',
  'inputSchema':{'type':'object','properties':{'timeout_seconds':{'type':'integer','minimum':1,'maximum':86400,'default':900}},'additionalProperties':False},
  'annotations':{'readOnlyHint':False,'idempotentHint':False}},
 {'name':'verify_acceptance','description':'After completing the handed-off isolated clamp task, run the fixed independent tests; caller cannot supply commands or file paths.',
  'inputSchema':{'type':'object','properties':{'handoff_id':{'type':'string'}},'required':['handoff_id'],'additionalProperties':False},
  'annotations':{'readOnlyHint':False}},
 {'name':'report_completion','description':'Record actual work and test results after a handoff. This records an agent report, not an independent test run. Then await the next failure.',
  'inputSchema':{'type':'object','properties':{'handoff_id':{'type':'string'},'summary':{'type':'string'},'tests_result':{'type':'string'}},
                 'required':['handoff_id','summary','tests_result'],'additionalProperties':False},
  'annotations':{'readOnlyHint':False}}
]


def serve(config):
    bridge=DesktopBridge(config)
    output_lock=threading.Lock()
    wait_lock=threading.Lock()
    active_wait={'id':None, 'event':None}
    def send(value):
        with output_lock:
            sys.stdout.write(json.dumps(value,ensure_ascii=False)+'\n');sys.stdout.flush()
    def respond(request):
        rid,method=request.get('id'),request.get('method')
        try:
            params=request.get('params') or {}
            if method=='initialize':
                atomic_json(bridge.root/'mcp-client.json',{'clientInfo':params.get('clientInfo'),
                            'requestedProtocol':params.get('protocolVersion'),'server_pid':os.getpid()})
                result={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},
                        'serverInfo':{'name':'codex-desktop-bridge','version':'0.2.0'},
                        'instructions':'This bridge reads one configured Codex Desktop thread. Never treat WAITING or TIMEOUT as a handed-off task.'}
            elif method=='ping':result={}
            elif method=='tools/list':result={'tools':TOOLS}
            elif method=='tools/call':
                name,args=params.get('name'),params.get('arguments') or {}
                if name=='bridge_status':value=bridge.probe()
                elif name=='await_codex_failure':
                    if set(args)-{'timeout_seconds'}:raise ValueError('unknown wait arguments')
                    with wait_lock:cancel=active_wait['event']
                    value=bridge.await_failure(**args,_cancel=cancel)
                elif name=='verify_acceptance':value=bridge.verify_acceptance(**args)
                elif name=='report_completion':value=bridge.report_completion(**args)
                else:raise ValueError('unknown tool')
                result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],
                        'isError':value.get('phase') in ('VERIFY_FAILED','REVIEW_PREVIOUS_HANDOFF','SOURCE_FAILURE_NOT_ELIGIBLE')}
            elif method=='notifications/cancelled':
                with wait_lock:
                    if active_wait['id'] is not None and params.get('requestId') == active_wait['id']:
                        active_wait['event'].set()
                return
            elif method.startswith('notifications/'):
                return
            else:
                send({'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'method not found'}});return
            if rid is not None:send({'jsonrpc':'2.0','id':rid,'result':result})
        except Exception as exc:
            if method=='tools/call':
                bridge.record('ERROR',error_type=type(exc).__name__,error=str(exc))
                send({'jsonrpc':'2.0','id':rid,'result':{'content':[{'type':'text','text':str(exc)}],'isError':True}})
            elif rid is not None:send({'jsonrpc':'2.0','id':rid,'error':{'code':-32602,'message':str(exc)}})
        finally:
            if method=='tools/call' and (request.get('params') or {}).get('name')=='await_codex_failure':
                with wait_lock:
                    if active_wait['id']==rid:active_wait.update(id=None,event=None)
    workers=[]
    try:
        for line in sys.stdin:
            if not line.strip():continue
            try:request=json.loads(line)
            except ValueError:
                send({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'invalid JSON'}});continue
            if not isinstance(request,dict) or not isinstance(request.get('method'),str):
                send({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'invalid request'}});continue
            if request.get('method')=='tools/call':
                if (request.get('params') or {}).get('name')=='await_codex_failure':
                    with wait_lock:
                        if active_wait['id'] is not None:
                            send({'jsonrpc':'2.0','id':request.get('id'),'result':{'content':[{'type':'text','text':'{"phase":"ALREADY_WAITING"}'}]}})
                            continue
                        active_wait.update(id=request.get('id'),event=threading.Event())
                workers=[worker for worker in workers if worker.is_alive()]
                worker=threading.Thread(target=respond,args=(request,),daemon=True);worker.start();workers.append(worker)
            else:respond(request)
    finally:
        bridge.cancel.set()
        with wait_lock:
            if active_wait['event'] is not None:active_wait['event'].set()
        for worker in workers:worker.join(timeout=10)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--expected-cwd'); parser.add_argument('--expected-thread')
    args=parser.parse_args();os.umask(0o077)
    config=json.loads(args.config.read_text())
    if args.expected_cwd and config.get('cwd') != args.expected_cwd:
        raise SystemExit('project binding changed; open a new configured standby session')
    if args.expected_cwd and str(Path.cwd().resolve()) != str(Path(args.expected_cwd).resolve()):
        raise SystemExit('Claude actual working directory differs from the bound project; select it in the Environment panel')
    if args.expected_thread and config.get('thread_id') != args.expected_thread:
        raise SystemExit('thread binding changed; open a new configured standby session')
    serve(args.config)

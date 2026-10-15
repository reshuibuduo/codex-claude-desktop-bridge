import copy
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'bridge')]
import bridge_core as core
from desktop_ipc import DesktopIPC, ThreadView, ProtocolError, apply_patches, ordered_turns, MAX_FRAME
from live_service import NewFailureGate, build_context, validate_config, parse_claude_result, claude_argv, Service


def message(status='inProgress', runtime='active', turn_id='turn-1', revision=1):
    return {'type': 'broadcast', 'method': 'thread-stream-state-changed', 'version': 11,
            'sourceClientId': 'real-owner', 'params': {'hostId': 'local', 'conversationId': 'test-thread',
            'change': {'type': 'snapshot', 'revision': revision, 'conversationState': {
                'id': 'test-thread', 'cwd': '/tmp', 'resumeState': 'resumed', 'requests': [],
                'threadRuntimeStatus': {'type': runtime},
                'turns': [{'turnId': turn_id, 'status': status,
                           'params': {'input': [{'type': 'text', 'text': 'Fix this toy file'}],
                                      'additionalContext': 'HIDDEN_DO_NOT_TRANSFER'},
                           'error': {'codexErrorInfo': 'serverOverloaded'},
                           'items': [{'type': 'reasoning', 'content': 'SECRET_THOUGHT'}]}]}}}}


def view(m=None):
    v = ThreadView('test-thread', 'real-owner'); v.accept(m or message()); return v


class AdapterTests(unittest.TestCase):
    def test_active_is_not_quiescent(self):
        v = view(); e,s=v.normalized()
        self.assertFalse(s['writers_quiesced']); self.assertEqual(core.evaluate(e,s),'IGNORE_NOT_FAILED')

    def test_terminal_failed_idle(self):
        v=view(message('failed','idle'));e,s=v.normalized()
        self.assertTrue(s['writers_quiesced']);self.assertEqual(core.evaluate(e,s),'PREPARE')

    def test_real_desktop_system_error_is_terminal_not_active(self):
        v=view(message('failed','systemError')); e,s=v.normalized()
        self.assertEqual(s['thread_status'],'systemError')
        self.assertTrue(s['writers_quiesced']); self.assertEqual(core.evaluate(e,s),'PREPARE')
        v.latest()['status']='inProgress'; e,s=v.normalized()
        self.assertFalse(s['writers_quiesced']); self.assertEqual(core.evaluate(e,s),'IGNORE_NOT_FAILED')

    def test_pending_tools_and_requests(self):
        for value in ('request', 'tool', 'unconfirmed', 'not_resumed'):
            v=view(message('failed','idle'))
            if value=='request':v.state['requests']=[{'id':'r'}]
            if value=='tool':v.latest()['items'].append({'type':'commandExecution','status':'inProgress'})
            if value=='unconfirmed':v.state['unconfirmedTurnSubmissions']=[{'terminal':False}]
            if value=='not_resumed':v.state['resumeState']='notLoaded'
            e,s=v.normalized();self.assertEqual(core.evaluate(e,s),'WAIT_SOURCE',value)

    def test_non_owner_and_wrong_thread_ignored(self):
        v=view();old=copy.deepcopy(v.state)
        for field,value in [('sourceClientId','wrong'),('version',10)]:
            m=message();m[field]=value
            if field=='version':
                with self.assertRaises(ProtocolError):v.accept(m)
                self.assertIsNone(v.state)
            else:self.assertFalse(v.accept(m));self.assertEqual(v.state,old)
        m=message();m['params']['conversationId']='other';self.assertFalse(v.accept(m))

    def test_identity_fail_closed(self):
        m=message();m['params']['change']['conversationState']['id']='wrong'
        v=ThreadView('test-thread','real-owner')
        with self.assertRaises(ProtocolError):v.accept(m)
        self.assertIsNone(v.state)

    def test_canonical_order(self):
        state={'turns':[{'turnId':'ignored'}], 'turnHistory':{'kind':'canonical','history':{
            'entitiesByKey':{'x':{'turnId':'b'},'y':{'turnId':'a'}},
            'islands':[{'entries':[{'value':'y'},{'value':'x'},{'value':'x'}]}]}}}
        self.assertEqual([x['turnId'] for x in ordered_turns(state)],['a','b'])

    def test_patches_apply_no_mutation(self):
        state={'x':[{'v':1}], 'old':True}
        changed=apply_patches(state,[{'op':'replace','path':['x',0,'v'],'value':2},
                                   {'op':'add','path':['x',1],'value':3},
                                   {'op':'remove','path':['old']}])
        self.assertEqual(changed,{'x':[{'v':2},3]});self.assertEqual(state['x'][0]['v'],1)
        for patch_value in ({'op':'replace','path':['missing'],'value':3},
                            {'op':'add','path':['x',99],'value':3},
                            {'op':'remove','path':[]}):
            with self.assertRaises(ProtocolError):apply_patches(state,[patch_value])

    def test_revision_gaps_invalidate(self):
        v=view();m=message();m['params']['change']={'type':'patches','baseRevision':0,'revision':2,'patches':[]}
        with self.assertRaises(ProtocolError):v.accept(m)
        self.assertIsNone(v.state)
        v=view();m['params']['change']['baseRevision']=1
        self.assertTrue(v.accept(m));self.assertEqual(v.revision,2)

    def test_framing_partial_timeout(self):
        a,b=socket.socketpair()
        client=DesktopIPC.__new__(DesktopIPC);client.sock=a;client.buffer=bytearray()
        try:
            raw=json.dumps({'type':'broadcast','example':'中文'}).encode()
            frame=struct.pack('<I',len(raw))+raw
            b.sendall(frame[:2])
            with self.assertRaises(socket.timeout):client.receive(0.01)
            b.sendall(frame[2:7])
            with self.assertRaises(socket.timeout):client.receive(0.01)
            b.sendall(frame[7:]);self.assertEqual(client.receive(.1)['example'],'中文')
        finally:a.close();b.close()

    def test_oversize_frame(self):
        a,b=socket.socketpair();client=DesktopIPC.__new__(DesktopIPC);client.sock=a;client.buffer=bytearray()
        try:
            b.sendall(struct.pack('<I',MAX_FRAME+1))
            with self.assertRaises(ProtocolError):client.receive(.1)
        finally:a.close();b.close()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.config=validate_config({'thread_id':'test-thread','cwd':str(self.root),
                                    'state_dir':str(self.root/'state'),'enabled':True})

    def tearDown(self):self.temp.cleanup()

    def test_gate_ignores_historical_failure(self):
        failed=view(message('failed','idle'));g=NewFailureGate(failed)
        self.assertFalse(g.candidate(failed))
        self.assertTrue(g.candidate(view(message('failed','idle','turn-2'))))
        active=view();self.assertTrue(NewFailureGate(active).candidate(failed))

    def test_context_excludes_hidden_reasoning_and_tool_output(self):
        v=view(message('failed','idle'));v.state['cwd']=str(self.root)
        v.latest()['items'].append({'type':'commandExecution','aggregatedOutput':'PRIVATE_TOOL_DATA'})
        context=build_context(v,self.config);text=json.dumps(context)
        self.assertIn('Fix this toy file',text)
        for hidden in ['HIDDEN_DO_NOT_TRANSFER','SECRET_THOUGHT','PRIVATE_TOOL_DATA']:
            self.assertNotIn(hidden,text)
        v.state['cwd']='/';
        with self.assertRaises(ValueError):build_context(v,self.config)

    def test_scope_requires_actual_workspace(self):
        for change in ({'cwd':'relative'},{'max_budget_usd':float('nan')},
                       {'claude_timeout_seconds':True},{'thread_id':''}):
            with self.assertRaises(ValueError):validate_config(dict(self.config,**change))

    def test_command_profile(self):
        argv=claude_argv('/path with spaces/claude','a-session',self.config)
        for token in ['--restricted','--safe-mode','--strict-mcp-config','acceptEdits']:
            self.assertIn(token,argv)
        for token in ['--dangerously-skip-permissions','Bash','--resume','--bare']:
            self.assertNotIn(token,argv)
        self.assertEqual(argv[0],'/path with spaces/claude')

    def test_result_checks_error_denial_and_exit(self):
        path=self.root/'stream.jsonl'
        good={'type':'result','subtype':'success','is_error':False,'session_id':'s','result':'done'}
        for change,code,wanted in [({},0,True),({'is_error':True},0,False),
                                   ({'subtype':'error_max_budget_usd'},0,False),
                                   ({'permission_denials':[{'tool_name':'Write'}]},0,False),({},1,False)]:
            path.write_text(json.dumps(dict(good,**change))+'\n')
            self.assertEqual(parse_claude_result(path,code)['passed'],wanted)
        for body in ['', 'not-json\n',json.dumps(good)+'\n'+json.dumps(good)+'\n']:
            path.write_text(body);self.assertFalse(parse_claude_result(path,0)['passed'])

    def test_disabled_never_invokes_external(self):
        service=Service(dict(self.config,enabled=False))
        with patch('live_service.subprocess.run') as run,patch('live_service.subprocess.Popen') as popen:
            self.assertEqual(service.watch(0)['phase'],'DISABLED')
            run.assert_not_called();popen.assert_not_called()

    def test_auth_missing_never_launches(self):
        service=Service(self.config)
        with patch('live_service.discover_claude',return_value='/test/claude'), \
             patch('live_service.auth_status',return_value={'loggedIn':False}), \
             patch('live_service.subprocess.Popen') as popen:
            self.assertEqual(service.watch(0)['phase'],'AUTH_REQUIRED');popen.assert_not_called()

    def test_uncertain_previous_execution_not_resubmitted(self):
        service=Service(self.config)
        e,s,c=core.fixture(self.root,time.time());r=service.core.prepare(e,s,c)
        service.set_run_state(r['session_id'],'running')
        with patch('live_service.subprocess.run') as run,patch('live_service.subprocess.Popen') as popen:
            self.assertEqual(service.watch(0)['phase'],'REVIEW_PREVIOUS_RUN')
            run.assert_not_called();popen.assert_not_called()




class LocalProcessFixtureTests(unittest.TestCase):
    """Real local child processes + synthetic IPC, NOT a model or E2E test."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cli = self.root/'fake_claude'
        self.config = {'enabled': True, 'thread_id': 'test-thread', 'cwd': str(self.root),
                       'state_dir': str(self.root/'state'), 'claude_path': str(self.cli),
                       'claude_timeout_seconds': 10}

    def tearDown(self): self.temp.cleanup()

    def executable(self, body):
        self.cli.write_text('#!' + sys.executable + '\n' +
            'import sys,json,time\nfrom pathlib import Path\n' +
            "if sys.argv[1:]==['auth','status']:\n print(json.dumps({'loggedIn':True}));sys.exit(0)\n" + body)
        self.cli.chmod(0o700)

    def ipc(self, historical=False, race=False):
        outer = self
        class FixtureIPC:
            calls = 0
            def owner(self, thread): return 'real-owner'
            def fresh_snapshot(self, thread, owner):
                self.calls += 1
                active = (self.calls == 1 and not historical) or (race and self.calls >= 7)
                v = view(message('inProgress' if active else 'failed', 'active' if active else 'idle'))
                v.state['cwd'] = str(outer.root)
                return v
            def close(self): pass
        return FixtureIPC

    def test_real_local_subprocess_not_model_success(self):
        self.executable("prompt=sys.stdin.read()\nassert 'Fix this toy file' in prompt\n"
                        "Path('local_fixture_received.txt').write_text('LOCAL_PROCESS_ONLY')\n"
                        "session=sys.argv[sys.argv.index('--session-id')+1]\n"
                        "print(json.dumps({'type':'result','is_error':False,'subtype':'success','session_id':session,'result':'fixture only'}))\n")
        with contextlib.redirect_stdout(io.StringIO()):
            service = Service(self.config, self.ipc())
            result = service.watch(5)
        self.assertEqual(result['phase'], 'COMPLETED')
        self.assertEqual((self.root/'local_fixture_received.txt').read_text(),'LOCAL_PROCESS_ONLY')
        with contextlib.closing(service.core.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM handoffs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM leases').fetchone()[0],0)

    def test_nonzero_local_child_retains_lease(self):
        self.executable('sys.stdin.read()\nsys.exit(3)\n')
        with contextlib.redirect_stdout(io.StringIO()):
            service=Service(self.config,self.ipc());result=service.watch(5)
        self.assertEqual(result['phase'],'NEEDS_ATTENTION')
        self.assertEqual(result['result']['exit_status'],3)
        with contextlib.closing(service.core.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM leases').fetchone()[0],1)

    def test_source_restarted_terminates_owned_child(self):
        self.executable('sys.stdin.read()\ntime.sleep(30)\n')
        with contextlib.redirect_stdout(io.StringIO()):
            service=Service(self.config,self.ipc(race=True));result=service.watch(5)
        self.assertEqual(result['phase'],'NEEDS_ATTENTION')
        self.assertEqual(result['result']['reason'],'source_changed_or_disconnected')
        self.assertLess(result['result']['exit_status'],0)
        self.assertIsNone(service.process)

    def test_historical_failure_does_not_spawn(self):
        self.executable("raise RuntimeError('must not execute model branch')\n")
        with contextlib.redirect_stdout(io.StringIO()):
            service=Service(self.config,self.ipc(historical=True));result=service.watch(0)
        self.assertEqual(result['phase'],'WATCH_TIMEOUT')
        with contextlib.closing(service.core.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM handoffs').fetchone()[0],0)


if __name__=='__main__':unittest.main()

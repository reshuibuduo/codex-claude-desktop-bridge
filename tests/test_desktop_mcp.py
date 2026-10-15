import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'bridge')]
import desktop_mcp as mcp
import desktop_setup as setup
from desktop_ipc import ThreadView
from test_live_bridge import message

class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'config.json'
        self.cfg={'enabled':True,'thread_id':'test-thread','cwd':str(self.root),'state_dir':str(self.root/'state')}
        self.save()
    def save(self):self.path.write_text(json.dumps(self.cfg))
    def view(self,status='inProgress',turn='turn-1',error='serverOverloaded',model=None,goal='Fix toy'):
        msg=message(status,'systemError' if status=='failed' else 'idle',turn_id=turn)
        state=msg['params']['change']['conversationState'];state['cwd']=str(self.root)
        state['turns'][0]['error']={'codexErrorInfo':error}
        state['turns'][0]['params']={'input':[{'type':'text','text':goal}], 'model':model}
        v=ThreadView('test-thread','real-owner');v.accept(msg);return v
    def bridge(self,views=None):
        views=list(views or [self.view()])
        class IPC:
            def owner(self,t):return 'real-owner'
            def fresh_snapshot(self,t,o):
                if len(views)>1:return views.pop(0)
                return views[0]
            def close(self):pass
        return mcp.DesktopBridge(self.path,ipc_factory=IPC)
    def test_disabled_does_not_touch_ipc(self):
        self.cfg['enabled']=False;self.save()
        b=mcp.DesktopBridge(self.path,ipc_factory=lambda: self.fail('IPC must not start'))
        self.assertEqual(b.await_failure(1)['phase'],'DISABLED')
    def test_scoped_real_acceptance_error_only(self):
        model='handoff-acceptance-unavailable-abc'
        self.cfg['acceptance_fault']={'thread_id':'test-thread','model':model,'nonce':'abc'};self.save()
        b=self.bridge()
        self.assertEqual(b.allowed_test_errors(self.view('failed',error='other',model=model,goal='fix abc')),('other',))
        for model_arg,goal,code in [('wrong','fix abc','other'),(model,'fix xyz','other'),(model,'fix abc','unauthorized')]:
            self.assertEqual(b.allowed_test_errors(self.view('failed',error=code,model=model_arg,goal=goal)),())
    def test_bad_nonce_is_not_accepted(self):
        self.cfg['acceptance_fault']={'thread_id':'test-thread','model':'handoff-acceptance-unavailable-abc'};self.save()
        self.assertEqual(self.bridge().allowed_test_errors(self.view('failed')),())
    def test_production_has_no_acceptance_override(self):
        self.assertEqual(self.bridge().allowed_test_errors(self.view('failed',error='other')),())
    def test_delivery_uses_mcp_not_standalone_cli(self):
        b=self.bridge([self.view(),self.view('failed')])
        with patch('desktop_mcp.subprocess.run',side_effect=AssertionError('standalone process forbidden')):
            result=b.await_failure(2)
        self.assertEqual(result['phase'],'HANDOFF_READY')
        entry=json.loads((b.root/'handoffs'/result['handoff_id']/'launch.json').read_text())
        self.assertFalse(entry['standalone_cli_spawned']);self.assertNotIn('argv',entry)
        self.assertIn('report_completion',result['instruction'])
        self.assertNotIn('测试',result['context']['constraints'][0])
    def test_historical_failed_turn_skipped(self):
        b=self.bridge([self.view('failed')]);self.assertEqual(b.await_failure(1)['phase'],'WAIT_TIMEOUT')
        self.assertIsNone(b.current_handoff)
    def test_persistent_cursor_catches_failure_between_wait_calls(self):
        b=self.bridge();old=self.view('completed',turn='old');b.failure_gate(old)
        new=self.view('failed',turn='new')
        b2=self.bridge();self.assertTrue(b2.failure_gate(new).candidate(new))
    def test_new_generation_skips_disabled_history(self):
        b=self.bridge();b.failure_gate(self.view('completed',turn='old'))
        self.cfg['arm_generation']='re-enabled';self.save()
        new=self.view('failed',turn='new')
        self.assertFalse(b.failure_gate(new).candidate(new))
    def test_delivered_turn_not_replayed(self):
        b=self.bridge();b.remember_delivered('delivered')
        latest=self.view('failed',turn='delivered')
        self.assertFalse(self.bridge().failure_gate(latest).candidate(latest))
    def test_hot_rebinding_disables_old_server(self):
        b=self.bridge();self.cfg['thread_id']='different';self.save();self.assertFalse(b.enabled())
    def test_cancel_before_call_does_not_deliver(self):
        b=self.bridge([self.view(),self.view('failed')]);cancel=threading.Event();cancel.set()
        self.assertEqual(b.await_failure(2,_cancel=cancel)['phase'],'PAUSED')
    def test_completion_preserves_report_vs_verification(self):
        b=self.bridge([self.view(),self.view('failed')]);result=b.await_failure(2);sid=result['handoff_id']
        done=b.report_completion(sid,'Changed toy','0 tests run; not verified')
        self.assertEqual(done['phase'],'COMPLETED_REPORTED')
        saved=json.loads((b.root/'handoffs'/sid/'completion.json').read_text())
        self.assertEqual(saved['evidence_kind'],'target_agent_report_not_independent_verification')
        with contextlib.closing(b.core.connect()) as db:self.assertEqual(db.execute('SELECT count(*) FROM leases').fetchone()[0],0)
    def test_completion_wrong_id(self):
        with self.assertRaises(ValueError):self.bridge().report_completion('invented','done','passed')
    def test_pending_record_requires_explicit_reconciliation(self):
        b=self.bridge([self.view(),self.view('failed')]);sid=b.await_failure(2)['handoff_id']
        self.assertEqual(self.bridge().await_failure(1)['phase'],'REVIEW_PREVIOUS_HANDOFF')
        self.cfg['enabled']=False;self.save()
        result=setup.resolve(self.path,sid,'abandoned','Inspected target session: no remaining work; do not replay')
        self.assertEqual(result['outcome'],'abandoned');self.assertFalse(setup.unresolved(self.cfg))
    def test_reconciliation_requires_pause(self):
        with self.assertRaises(ValueError):setup.resolve(self.path,'id','abandoned','inspected')
    def test_unknown_cancel_does_not_cancel_active_wait(self):
        start=threading.Event();observed={};parent=self
        class Fake:
            def __init__(self,path):self.cancel=threading.Event()
            def await_failure(self,timeout_seconds,_cancel):
                observed['event']=_cancel;start.set();_cancel.wait(2)
                return {'phase':'PAUSED' if _cancel.is_set() else 'WAIT_TIMEOUT'}
            def record(self,*a,**kw):return {}
        def lines():
            yield json.dumps({'id':'A','method':'tools/call','params':{'name':'await_codex_failure','arguments':{'timeout_seconds':2}}})
            parent.assertTrue(start.wait(1))
            yield json.dumps({'method':'notifications/cancelled','params':{'requestId':'B'}})
            parent.assertFalse(observed['event'].is_set())
            yield json.dumps({'method':'notifications/cancelled','params':{'requestId':'A'}})
        out=io.StringIO()
        with patch.object(mcp,'DesktopBridge',Fake),patch.object(sys,'stdin',lines()),patch.object(sys,'stdout',out):mcp.serve(self.path)
        self.assertIn('PAUSED',out.getvalue());self.assertTrue(observed['event'].is_set())
    def test_eof_cancels_wait(self):
        started=threading.Event();finished=threading.Event();parent=self
        class Fake:
            def __init__(self,path):self.cancel=threading.Event()
            def await_failure(self,timeout_seconds,_cancel):
                started.set();_cancel.wait(2)
                if _cancel.is_set():finished.set()
                return {'phase':'PAUSED'}
            def record(self,*a,**kw):return {}
        def lines():
            yield json.dumps({'id':'A','method':'tools/call','params':{'name':'await_codex_failure','arguments':{'timeout_seconds':2}}})
            parent.assertTrue(started.wait(1))
        with patch.object(mcp,'DesktopBridge',Fake),patch.object(sys,'stdin',lines()),contextlib.redirect_stdout(io.StringIO()):mcp.serve(self.path)
        self.assertTrue(finished.is_set())

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.project=self.root/'project';self.project.mkdir();self.cfg=self.root/'config.json';self.script=self.root/'desktop_mcp.py';self.script.write_text('fixture')
        self.audit=self.root/'audit'
    def install(self):return setup.install_mcp(self.project,self.cfg,self.script,self.audit,'thread')
    def test_install_and_restore_preserves_other_connectors(self):
        path=self.project/'.mcp.json';path.write_text(json.dumps({'otherField':True,'mcpServers':{'existing':{'url':'https://example.invalid'}}}))
        before=path.read_bytes();result=self.install();value=json.loads(path.read_text())
        self.assertIn('existing',value['mcpServers']);self.assertTrue(value['otherField'])
        entry=value['mcpServers']['codex-desktop-bridge'];self.assertIn('--expected-thread',entry['args'])
        manifest=json.loads(Path(result['manifest']).read_text());self.assertEqual(Path(manifest['backup']).read_bytes(),before)
        value['mcpServers']['later']={'url':'local'};path.write_text(json.dumps(value))
        setup.uninstall_mcp(result['manifest']);restored=json.loads(path.read_text())
        self.assertNotIn('codex-desktop-bridge',restored['mcpServers']);self.assertIn('later',restored['mcpServers'])
    def test_unknown_existing_connector_preserved(self):
        path=self.project/'.mcp.json';text=json.dumps({'mcpServers':{'codex-desktop-bridge':{'command':'other'}}});path.write_text(text)
        with self.assertRaises(ValueError):self.install()
        self.assertEqual(path.read_text(),text)
    def test_changed_connector_not_uninstalled(self):
        result=self.install();path=self.project/'.mcp.json';value=json.loads(path.read_text());value['mcpServers']['codex-desktop-bridge']['command']='changed';path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):setup.uninstall_mcp(result['manifest'])
    def test_symlink_not_overwritten(self):
        target=self.root/'target';target.write_text('{}');(self.project/'.mcp.json').symlink_to(target)
        with self.assertRaises(ValueError):self.install()
        self.assertEqual(target.read_text(),'{}')
    def test_stale_standby_not_shown_ready(self):
        state=self.root/'state';state.mkdir();(state/'desktop-status.json').write_text(json.dumps({'phase':'WAITING_FOR_NEW_FAILURE','time':0}))
        self.cfg.write_text(json.dumps({'enabled':True,'state_dir':str(state),'thread_id':'test','cwd':str(self.project)}))
        self.assertEqual(setup.status(self.cfg)['display_phase'],'STANDBY_STALE')
    def test_pause_precedes_old_status(self):
        state=self.root/'state';state.mkdir();(state/'desktop-status.json').write_text(json.dumps({'phase':'HANDOFF_DELIVERED'}))
        self.cfg.write_text(json.dumps({'enabled':False,'state_dir':str(state),'thread_id':'test','cwd':str(self.project)}))
        self.assertEqual(setup.status(self.cfg)['display_phase'],'PAUSED')

if __name__=='__main__':unittest.main()

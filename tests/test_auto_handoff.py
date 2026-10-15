"""An armed real MCP subprocess hands off on fault, with no post-fault client input.
Source/target are fixtures, not a claim of vendor desktop/model E2E acceptance.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'bridge')]
from live_service import atomic_json
from test_live_bridge import message
ROOT = Path(__file__).resolve().parents[1]

WRAPPER = '''import json, sys
from pathlib import Path
sys.path[:0] = [sys.argv[1], str(Path(sys.argv[1])/'bridge')]
import desktop_mcp as mcp
from desktop_ipc import ThreadView
class FixtureIPC:
    def owner(self, thread): return 'real-owner'
    def fresh_snapshot(self, thread, owner):
        value=json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
        view=ThreadView(thread,owner);view.accept(value);return view
    def close(self): pass
original=mcp.DesktopBridge
mcp.DesktopBridge=lambda path: original(path,ipc_factory=FixtureIPC)
mcp.serve(Path(sys.argv[2]))
'''


class AutomaticHandoffTests(unittest.TestCase):
    def test_fault_after_arming_needs_no_new_client_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();config=root/'config.json';source=root/'source.json'
            atomic_json(config,{'enabled':True,'thread_id':'test-thread','cwd':str(root),'state_dir':str(root/'state')})
            def snapshot(status):
                value=message(status,'active' if status=='inProgress' else 'systemError')
                value['params']['change']['conversationState']['cwd']=str(root)
                return value
            atomic_json(source,snapshot('inProgress'))
            process=subprocess.Popen([sys.executable,'-u','-c',WRAPPER,str(ROOT),str(config),str(source)],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',cwd=root)
            replies=queue.Queue()
            def reader():
                for line in process.stdout: replies.put(json.loads(line))
            thread=threading.Thread(target=reader,daemon=True);thread.start()
            try:
                process.stdin.write(json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}})+'\n');process.stdin.flush()
                self.assertIn('result',replies.get(timeout=5))
                process.stdin.write(json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'await_codex_failure','arguments':{'timeout_seconds':10}}})+'\n');process.stdin.flush()
                deadline=time.monotonic()+5; status=root/'state/desktop-status.json'
                while time.monotonic()<deadline:
                    if status.exists() and json.loads(status.read_text(encoding='utf-8'))['phase']=='WAITING_FOR_NEW_FAILURE': break
                    time.sleep(0.05)
                else: self.fail('MCP never armed')
                before=config.read_bytes()
                # No stdin writes, UI clicks, prompts, enable calls or config edits after this fault.
                atomic_json(source,snapshot('failed'))
                reply=replies.get(timeout=5)
                self.assertEqual(reply['id'],2)
                handoff=json.loads(reply['result']['content'][0]['text'])
                self.assertEqual(handoff['phase'],'HANDOFF_READY')
                self.assertEqual(handoff['context']['goal'],'Fix this toy file')
                self.assertEqual(config.read_bytes(),before)
                self.assertEqual(len(list((root/'state/handoffs').iterdir())),1)
                print('AUTO_HANDOFF_FIXTURE_OK armed=true post_fault_client_inputs=0 deliveries=1 model_requests=0')
            finally:
                process.stdin.close()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill();process.wait()
                thread.join(2);errors=process.stderr.read();process.stdout.close();process.stderr.close()
            self.assertEqual(process.returncode,0,errors)


if __name__=='__main__':unittest.main()

"""Real Win32 transport fixtures, never a vendor app or a model request."""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'bridge'))
from windows_pipe import WindowsPipe, DEFAULT_PIPE, api
from desktop_ipc import DesktopIPC


class PipeFixture:
    def __init__(self, body):
        self.name = '\\\\.\\pipe\\bridge-fixture-' + str(uuid.uuid4())
        self.k = api(); self.errors = []; self.body = body
        self.k.CreateNamedPipeW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_void_p]
        self.k.CreateNamedPipeW.restype = W.HANDLE
        self.k.ConnectNamedPipe.argtypes = [W.HANDLE, C.c_void_p]; self.k.ConnectNamedPipe.restype = W.BOOL
        self.k.DisconnectNamedPipe.argtypes = [W.HANDLE]; self.k.DisconnectNamedPipe.restype = W.BOOL
        self.handle = self.k.CreateNamedPipeW(self.name, 3, 8, 1, 65536, 65536, 0, None)
        if self.handle == W.HANDLE(-1).value: raise C.WinError(C.get_last_error())
        self.thread = threading.Thread(target=self.serve, daemon=True)
    def serve(self):
        try:
            if not self.k.ConnectNamedPipe(self.handle, None) and C.get_last_error() != 535:
                raise C.WinError(C.get_last_error())
            self.body(self)
        except BaseException as exc: self.errors.append(exc)
        finally:
            self.k.DisconnectNamedPipe(self.handle); self.k.CloseHandle(self.handle)
    def read(self, count):
        result = b''
        while len(result) < count:
            data = C.create_string_buffer(count-len(result)); n = W.DWORD()
            if not self.k.ReadFile(self.handle, data, len(data), C.byref(n), None):
                raise C.WinError(C.get_last_error())
            if not n.value: raise EOFError()
            result += data.raw[:n.value]
        return result
    def write(self, data):
        buffer = C.create_string_buffer(data); n = W.DWORD()
        if not self.k.WriteFile(self.handle, buffer, len(data), C.byref(n), None): raise C.WinError(C.get_last_error())
        assert n.value == len(data)
    def frame(self): return json.loads(self.read(struct.unpack('<I', self.read(4))[0]))
    def __enter__(self): self.thread.start(); return self
    def __exit__(self, *args):
        self.thread.join(5)
        if self.thread.is_alive(): raise AssertionError('pipe fixture did not finish')
        if self.errors and args[0] is None: raise self.errors[0]


def frame(value):
    raw = json.dumps(value).encode('utf-8')
    return struct.pack('<I', len(raw))+raw


class PipeContractTests(unittest.TestCase):
    def test_endpoint_is_local_named_pipe(self):
        self.assertEqual(DEFAULT_PIPE, '\\\\.\\pipe\\codex-ipc')
        for path in ['\\\\remote\\pipe\\codex-ipc', '/tmp/sock']:
            with self.assertRaises(ValueError): WindowsPipe(path)


@unittest.skipUnless(os.name == 'nt', 'native Windows named-pipe fixtures')
class NativePipeTests(unittest.TestCase):
    def test_initialize_partial_frame_timeout_and_disconnect(self):
        sent_partial = threading.Event(); continue_frame = threading.Event()
        def server(p):
            req = p.frame(); assert req['method'] == 'initialize'
            p.write(frame({'type':'response','requestId':req['requestId'],'resultType':'success','result':{'clientId':'fixture'}}))
            raw = frame({'type':'fixture','text':'中文'})
            p.write(raw[:6]); sent_partial.set(); assert continue_frame.wait(3)
            p.write(raw[6:])
            # Wait for the client's acknowledgement before closing the server end.
            assert p.read(1) == b'!'
        with PipeFixture(server) as p:
            client = DesktopIPC(p.name)
            try:
                self.assertEqual(client.client_id, 'fixture')
                self.assertTrue(sent_partial.wait(2))
                with self.assertRaises(socket.timeout): client.receive(0.03)
                self.assertGreater(len(client.buffer), 0)
                continue_frame.set()
                self.assertEqual(client.receive(2)['text'], '中文')
                client.sock.sendall(b'!')
                with self.assertRaises(EOFError): client.receive(2)
            finally: continue_frame.set(); client.close()

    def test_read_timeout_does_not_break_next_read(self):
        ready = threading.Event()
        def server(p):
            assert ready.wait(3); p.write(b'ok'); assert p.read(1) == b'!'
        with PipeFixture(server) as p:
            client = WindowsPipe(p.name, 0.03)
            try:
                with self.assertRaises(socket.timeout): client.recv(2)
                ready.set(); client.settimeout(2)
                self.assertEqual(client.recv(2), b'ok'); client.sendall(b'!')
            finally: ready.set(); client.close()

    def test_untrusted_peer_rejected_before_sending(self):
        # Inject the identity failure, not the transport; real connection must close without bytes.
        observed = []
        def server(p):
            try: observed.append(p.read(1))
            except (OSError, EOFError): observed.append(b'')
        with PipeFixture(server) as p, patch('windows_pipe.verify_server', side_effect=PermissionError('fixture identity mismatch')):
            with self.assertRaises(PermissionError): WindowsPipe(p.name)
        self.assertEqual(observed, [b''])

    def test_missing_pipe_errors(self):
        with self.assertRaises(OSError): WindowsPipe('\\\\.\\pipe\\missing-bridge-'+str(uuid.uuid4()), 0.1)


if __name__ == '__main__': unittest.main()

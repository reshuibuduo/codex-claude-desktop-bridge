"""Socket-like, timeout-bounded Win32 named-pipe client (Python stdlib only).

The endpoint is from the shipped cross-platform desktop transport. Native tests
use a separate local pipe fixture; they do not establish Windows vendor-app E2E.
"""
import ctypes as C
from ctypes import wintypes as W
import math
import os
import socket
import time

DEFAULT_PIPE = r'\\.\pipe\codex-ipc'


class OVERLAPPED(C.Structure):
    _fields_ = [('Internal', C.c_size_t), ('InternalHigh', C.c_size_t),
                ('Offset', W.DWORD), ('OffsetHigh', W.DWORD), ('hEvent', W.HANDLE)]


def api():
    if os.name != 'nt':
        raise OSError('Windows named-pipe transport requires Windows')
    k = C.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateFileW': (W.HANDLE, [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]),
        'CloseHandle': (W.BOOL, [W.HANDLE]),
        'WaitNamedPipeW': (W.BOOL, [W.LPCWSTR, W.DWORD]),
        'CreateEventW': (W.HANDLE, [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]),
        'ReadFile': (W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.POINTER(OVERLAPPED)]),
        'WriteFile': (W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.POINTER(OVERLAPPED)]),
        'GetOverlappedResult': (W.BOOL, [W.HANDLE, C.POINTER(OVERLAPPED), C.POINTER(W.DWORD), W.BOOL]),
        'CancelIoEx': (W.BOOL, [W.HANDLE, C.POINTER(OVERLAPPED)]),
        'WaitForSingleObject': (W.DWORD, [W.HANDLE, W.DWORD]),
        'GetNamedPipeServerProcessId': (W.BOOL, [W.HANDLE, C.POINTER(W.ULONG)]),
        'OpenProcess': (W.HANDLE, [W.DWORD, W.BOOL, W.DWORD]),
        'GetCurrentProcess': (W.HANDLE, []),
        'GetCurrentProcessId': (W.DWORD, []),
        'ProcessIdToSessionId': (W.BOOL, [W.DWORD, C.POINTER(W.DWORD)]),
    }
    for name, (restype, argtypes) in signatures.items():
        fn = getattr(k, name); fn.restype = restype; fn.argtypes = argtypes
    return k


def verify_server(k, pipe):
    """Match Unix same-user semantics and reject cross-session pipe servers."""
    pid = W.ULONG()
    if not k.GetNamedPipeServerProcessId(pipe, C.byref(pid)):
        raise C.WinError(C.get_last_error())
    ours, theirs = W.DWORD(), W.DWORD()
    if not (k.ProcessIdToSessionId(k.GetCurrentProcessId(), C.byref(ours)) and
            k.ProcessIdToSessionId(pid.value, C.byref(theirs))):
        raise C.WinError(C.get_last_error())
    if ours.value != theirs.value:
        raise PermissionError('desktop pipe belongs to a different Windows session')
    server = k.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not server:
        raise C.WinError(C.get_last_error())
    a = C.WinDLL('advapi32', use_last_error=True)
    a.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    a.OpenProcessToken.restype = W.BOOL
    a.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    a.GetTokenInformation.restype = W.BOOL
    a.EqualSid.argtypes = [C.c_void_p, C.c_void_p]; a.EqualSid.restype = W.BOOL

    def token_user(process):
        token = W.HANDLE()
        if not a.OpenProcessToken(process, 8, C.byref(token)):  # TOKEN_QUERY
            raise C.WinError(C.get_last_error())
        try:
            size = W.DWORD()
            a.GetTokenInformation(token, 1, None, 0, C.byref(size))
            if not size.value:
                raise C.WinError(C.get_last_error())
            buffer = C.create_string_buffer(size.value)
            if not a.GetTokenInformation(token, 1, buffer, size, C.byref(size)):
                raise C.WinError(C.get_last_error())
            return buffer
        finally:
            k.CloseHandle(token)
    try:
        own = token_user(k.GetCurrentProcess()); peer = token_user(server)
        # TOKEN_USER begins with SID_AND_ATTRIBUTES, whose first member is PSID.
        if not a.EqualSid(C.c_void_p.from_buffer(own), C.c_void_p.from_buffer(peer)):
            raise PermissionError('desktop pipe belongs to a different Windows user')
    finally:
        k.CloseHandle(server)


class WindowsPipe:
    def __init__(self, path=DEFAULT_PIPE, timeout=8):
        if not str(path).startswith('\\\\.\\pipe\\') or '/' in str(path):
            raise ValueError('only local Windows named pipes are supported')
        self.k = api(); self.handle = None; self.timeout = timeout
        deadline = time.monotonic() + timeout
        while True:
            # Identification only: the server cannot impersonate this client's token.
            handle = self.k.CreateFileW(str(path), 0xC0000000, 0, None, 3,
                                       0x40000000 | 0x100000 | 0x10000, None)
            if handle != W.HANDLE(-1).value:
                self.handle = handle
                break
            error = C.get_last_error()
            if error != 231:  # ERROR_PIPE_BUSY
                raise C.WinError(error)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout('desktop pipe connection timed out')
            self.k.WaitNamedPipeW(str(path), max(1, math.ceil(remaining * 1000)))
        try:
            verify_server(self.k, self.handle)
        except BaseException:
            self.close()
            raise

    def settimeout(self, timeout):
        if timeout is None or timeout <= 0:
            raise ValueError('a positive bounded timeout is required')
        self.timeout = timeout

    def _io(self, buffer, size, writing):
        if self.handle is None:
            raise OSError('pipe is closed')
        event = self.k.CreateEventW(None, True, False, None)
        if not event:
            raise C.WinError(C.get_last_error())
        overlapped = OVERLAPPED(); overlapped.hEvent = event
        count = W.DWORD()
        try:
            fn = self.k.WriteFile if writing else self.k.ReadFile
            if fn(self.handle, buffer, size, C.byref(count), C.byref(overlapped)):
                return count.value
            error = C.get_last_error()
            if error in (109, 232) and not writing:  # broken/disconnected pipe
                return 0
            if error != 997:  # ERROR_IO_PENDING
                raise C.WinError(error)
            wait = self.k.WaitForSingleObject(event, max(1, math.ceil(self.timeout * 1000)))
            if wait != 0:
                # Always finish cancellation before releasing the overlapped/buffer memory.
                self.k.CancelIoEx(self.handle, C.byref(overlapped))
                completed = self.k.GetOverlappedResult(self.handle, C.byref(overlapped), C.byref(count), True)
                if completed:  # completion raced the deadline; do not discard consumed bytes
                    return count.value
                if wait == 258:
                    raise socket.timeout('desktop pipe I/O timed out')
                raise OSError('desktop pipe event wait failed')
            if not self.k.GetOverlappedResult(self.handle, C.byref(overlapped), C.byref(count), False):
                error = C.get_last_error()
                if error in (109, 232) and not writing:
                    return 0
                raise C.WinError(error)
            return count.value
        finally:
            self.k.CloseHandle(event)

    def recv(self, size):
        buffer = C.create_string_buffer(size)
        count = self._io(buffer, size, False)
        return buffer.raw[:count]

    def sendall(self, value):
        deadline = time.monotonic() + self.timeout
        previous = self.timeout
        try:
            while value:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise socket.timeout('desktop pipe write timed out')
                self.timeout = remaining
                buffer = C.create_string_buffer(value)
                count = self._io(buffer, len(value), True)
                if not count:
                    raise BrokenPipeError('desktop pipe write returned zero bytes')
                value = value[count:]
        finally:
            self.timeout = previous

    def close(self):
        if self.handle is not None:
            self.k.CloseHandle(self.handle)
            self.handle = None

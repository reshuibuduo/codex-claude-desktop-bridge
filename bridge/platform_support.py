"""Small OS boundaries shared by desktop UI, MCP and the earlier CLI experiment."""
import errno
import os
from pathlib import Path


def data_directory():
    override = os.environ.get('CODEX_CLAUDE_BRIDGE_DATA')
    if override:
        return Path(override).expanduser().resolve()
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'CodexClaudeBridge'
    return Path.home()/'Library/Application Support/CodexClaudeBridge'


def lock_exclusive(stream):
    """Nonblocking, cross-process lock held until the caller closes its file."""
    if os.name == 'nt':
        import msvcrt
        # Windows byte-range locks need a stable byte and a known cursor.
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write('\0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BlockingIOError('another bridge process holds the lock') from exc
            raise
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _security_api():
    import ctypes as c
    from ctypes import wintypes as w
    a = c.WinDLL('advapi32', use_last_error=True); k = c.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.LocalFree.argtypes = [c.c_void_p]; k.LocalFree.restype = c.c_void_p
    a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    a.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    a.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(w.LPWSTR)]
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.c_void_p]
    a.GetSecurityDescriptorDacl.argtypes = [c.c_void_p, c.POINTER(w.BOOL), c.POINTER(c.c_void_p), c.POINTER(w.BOOL)]
    a.SetNamedSecurityInfoW.argtypes = [w.LPWSTR, c.c_int, w.DWORD, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p]
    a.SetNamedSecurityInfoW.restype = w.DWORD
    a.GetNamedSecurityInfoW.argtypes = [w.LPCWSTR, c.c_int, w.DWORD, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p)]
    a.GetNamedSecurityInfoW.restype = w.DWORD
    a.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(w.LPWSTR), c.c_void_p]
    return c, w, a, k


def _private_sddl():
    c, w, a, k = _security_api(); token = w.HANDLE()
    if not a.OpenProcessToken(k.GetCurrentProcess(), 8, c.byref(token)): raise c.WinError(c.get_last_error())
    sid = w.LPWSTR()
    try:
        size = w.DWORD(); a.GetTokenInformation(token, 1, None, 0, c.byref(size))
        if not size.value: raise c.WinError(c.get_last_error())
        buffer = c.create_string_buffer(size.value)
        if not a.GetTokenInformation(token, 1, buffer, size, c.byref(size)): raise c.WinError(c.get_last_error())
        if not a.ConvertSidToStringSidW(c.c_void_p.from_buffer(buffer), c.byref(sid)): raise c.WinError(c.get_last_error())
        return 'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;'+sid.value+')'
    finally:
        if sid: k.LocalFree(sid)
        k.CloseHandle(token)


def restrict_windows_path(path):
    """Protect newly written state/context; never apply this to the project directory."""
    if os.name != 'nt': return
    c, w, a, k = _security_api(); descriptor = c.c_void_p()
    if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(_private_sddl(), 1, c.byref(descriptor), None):
        raise c.WinError(c.get_last_error())
    try:
        present, defaulted, acl = w.BOOL(), w.BOOL(), c.c_void_p()
        if not a.GetSecurityDescriptorDacl(descriptor, c.byref(present), c.byref(acl), c.byref(defaulted)):
            raise c.WinError(c.get_last_error())
        error = a.SetNamedSecurityInfoW(str(path), 1, 4 | 0x80000000, None, None, acl, None)
        if error: raise c.WinError(error)
    finally: k.LocalFree(descriptor)


def windows_path_is_private(path):
    """Read back the actual protected DACL, not Unix mode emulation."""
    c, w, a, k = _security_api(); descriptor = c.c_void_p(); text = w.LPWSTR()
    error = a.GetNamedSecurityInfoW(str(path), 1, 4, None, None, None, None, c.byref(descriptor))
    if error: raise c.WinError(error)
    try:
        if not a.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, c.byref(text), None):
            raise c.WinError(c.get_last_error())
        import re
        actual = text.value
        expected_sids = set(re.findall(r';;;([^;)]+)', _private_sddl()))
        return actual.startswith('D:P') and set(re.findall(r';;;([^;)]+)', actual)) == expected_sids
    finally:
        if text: k.LocalFree(text)
        k.LocalFree(descriptor)

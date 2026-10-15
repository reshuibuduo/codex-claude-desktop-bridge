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

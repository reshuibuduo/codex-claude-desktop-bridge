"""One selected local Desktop conversation -> an authenticated Claude CLI.

Default file-tool-only profile; no app patching, global settings changes or shell
permissions. This module does not create chats or inject source failures.
"""
import argparse
import contextlib
from platform_support import lock_exclusive
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

from desktop_ipc import DesktopIPC, ProtocolError, ordered_turns
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge_core as core


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def discover_claude(explicit=None):
    if explicit:
        candidates = [Path(explicit).expanduser()]
    else:
        folder = Path.home() / 'Library/Application Support/Claude/claude-code'
        candidates = sorted(folder.glob('*/*/claude.app/Contents/MacOS/claude'),
                            key=lambda x: x.stat().st_mtime, reverse=True)
        for candidate in (Path.home()/'.local/bin/claude', Path('/opt/homebrew/bin/claude')):
            if candidate.is_file():
                candidates.append(candidate)
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    raise FileNotFoundError('Claude Code executable not found')


def auth_status(cli, cwd):
    result = subprocess.run([cli, 'auth', 'status'], cwd=str(cwd), capture_output=True,
                            text=True, timeout=20)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        data = {}
    return {'loggedIn': data.get('loggedIn') is True, 'authMethod': data.get('authMethod'),
            'exit_status': result.returncode}


def validate_config(value):
    if not isinstance(value, dict):
        raise ValueError('config must be an object')
    thread_id = value.get('thread_id')
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError('one explicit thread_id required')
    cwd = Path(value['cwd']).expanduser()
    if not cwd.is_absolute() or not cwd.is_dir():
        raise ValueError('cwd must be an existing absolute directory')
    state_dir = Path(value['state_dir']).expanduser()
    if not state_dir.is_absolute():
        raise ValueError('state_dir must be absolute')
    timeout = value.get('claude_timeout_seconds', 300)
    if type(timeout) is not int or not 10 <= timeout <= 1800:
        raise ValueError('claude_timeout_seconds must be 10..1800')
    budget = value.get('max_budget_usd', 2.0)
    if type(budget) not in (float, int) or not 0 < budget <= 20:
        raise ValueError('max_budget_usd must be >0 and <=20')
    return dict(value, thread_id=thread_id, cwd=str(cwd.resolve()),
                state_dir=str(state_dir.resolve()), claude_timeout_seconds=timeout,
                max_budget_usd=budget)


def input_text(turn):
    values = (turn.get('params') or {}).get('input') or []
    return '\n'.join(x['text'] for x in values if isinstance(x, dict) and
                     x.get('type') == 'text' and isinstance(x.get('text'), str))


def build_context(view, config):
    state, turn = view.state, view.latest()
    actual_cwd = Path(state.get('cwd', '')).resolve()
    if str(actual_cwd) != config['cwd']:
        raise ValueError('source workspace differs from selected workspace')
    goal = input_text(turn)
    if not goal.strip() or len(goal) > 20000:
        raise ValueError('latest user objective missing or too large')
    history = []
    for previous in ordered_turns(state)[-4:]:
        if previous.get('turnId') == turn.get('turnId'):
            continue
        text = input_text(previous)
        if text:
            history.append('前序用户消息（上下文；最新目标优先）: ' + text[:4000])
        for item in previous.get('items', []):
            if item.get('type') == 'agentMessage' and item.get('phase') == 'final_answer':
                history.append('前序助手结论（未独立验证）: ' + str(item.get('text', ''))[:4000])
    # Never export additionalContext, reasoning, auth settings or raw tool results.
    # Selected visible prose may itself contain sensitive information; no secret-scanner claim.
    context = {'goal': goal, 'cwd': config['cwd'],
               'constraints': ['本接续轮只读写当前项目文件；不执行 shell 或外部工具。',
                               '不要重复外部操作。先检查磁盘现状，明确区分计划与完成。'],
               'completed_verified': [], 'pending': ['核对已改文件后继续最新用户目标'],
               'uncertainties': history[-6:] + ['历史结论未独立验证；系统提示、推理、原始工具输出未转移。']}
    return core.normalize_context(context)


def source_signature(view):
    turn = view.latest() or {}
    return turn.get('turnId'), turn.get('status')


class NewFailureGate:
    """Skip already-terminal history on enable/restart; observe transitions only."""
    def __init__(self, initial_view):
        self.initial_turn, status = source_signature(initial_view)
        self.skip_initial = status != 'inProgress'

    def candidate(self, view):
        turn, status = source_signature(view)
        return bool(turn) and status == 'failed' and not (
            self.skip_initial and turn == self.initial_turn)


def claude_argv(cli, session, config):
    # --restricted confines file tools to cwd; no Bash, MCP or WebFetch tool.
    return [cli, '-p', '--output-format', 'stream-json', '--verbose',
            '--session-id', session, '--permission-mode', 'acceptEdits',
            '--restricted', '--safe-mode', '--strict-mcp-config',
            '--tools', 'Read,Edit,Write,Glob,Grep', '--model', config.get('model', 'sonnet'),
            '--effort', 'low', '--max-budget-usd', str(config['max_budget_usd'])]


def parse_claude_result(stdout_path, exit_status):
    last, count, invalid = None, 0, 0
    with Path(stdout_path).open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except ValueError:
                invalid += 1
                continue
            if isinstance(value, dict) and value.get('type') == 'result':
                last, count = value, count + 1
    if exit_status != 0 or count != 1 or invalid or not last:
        return {'passed': False, 'reason': 'process_or_stream_failed', 'exit_status': exit_status,
                'result_count': count, 'invalid_lines': invalid}
    ok = last.get('is_error') is False and last.get('subtype') == 'success' and not last.get('permission_denials')
    return {'passed': ok, 'reason': 'claude_completed' if ok else 'claude_reported_error_or_denial',
            'exit_status': exit_status, 'result_count': count, 'invalid_lines': invalid,
            'session_id': last.get('session_id'), 'subtype': last.get('subtype'),
            'is_error': last.get('is_error'), 'permission_denial_count': len(last.get('permission_denials') or []),
            'result': last.get('result', '')}


def ensure_same_failed_turn(ipc, thread_id, owner, turn_id):
    actual_owner = ipc.owner(thread_id)
    if actual_owner != owner:
        raise ProtocolError('source owner changed')
    view = ipc.fresh_snapshot(thread_id, owner)
    event, snapshot = view.normalized()
    if source_signature(view) != (turn_id, 'failed') or core.evaluate(event, snapshot) != 'PREPARE':
        raise ProtocolError('source changed or is not quiescent')
    return view


def terminate_owned(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        process.terminate()  # Legacy CLI only; desktop MCP never launches this child.
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


class Service:
    def __init__(self, config, ipc_factory=DesktopIPC):
        self.config = validate_config(config)
        self.folder = Path(self.config['state_dir'])
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.folder, 0o700)
        self.ipc_factory, self.process = ipc_factory, None
        self.core = core.HandoffCore(self.folder/'state.sqlite', self.folder/'handoffs')
        os.chmod(self.folder/'state.sqlite', 0o600)

    def status(self, phase, **fields):
        data = {'phase': phase, 'time': time.time(), 'pid': os.getpid(),
                'thread_id': self.config['thread_id'], **fields}
        atomic_json(self.folder/'status.json', data)
        print(json.dumps(data, ensure_ascii=False), flush=True)
        return data

    def set_run_state(self, session, state, release=False):
        with contextlib.closing(self.core.connect()) as db, db:
            db.execute('UPDATE handoffs SET state=? WHERE session_id=?', (state, session))
            if release:
                db.execute('DELETE FROM leases WHERE session_id=?', (session,))

    def launch(self, ipc, owner, prepared, event):
        if os.name == 'nt':
            raise OSError("legacy CLI execution is POSIX-only; use the Windows desktop MCP app")
        session, package = prepared['session_id'], Path(prepared['package'])
        thread_id, turn_id = self.config['thread_id'], event['params']['turn']['id']
        ensure_same_failed_turn(ipc, thread_id, owner, turn_id)
        cli = discover_claude(self.config.get('claude_path'))
        auth = auth_status(cli, self.config['cwd'])
        if not auth['loggedIn']:
            self.set_run_state(session, 'auth_required')
            return self.status('AUTH_REQUIRED', auth=auth, session_id=session)
        # Check again after the auth process, not just before it.
        ensure_same_failed_turn(ipc, thread_id, owner, turn_id)
        argv = claude_argv(cli, session, self.config)
        atomic_json(package/'execution.json', {'argv': argv, 'cwd': self.config['cwd'],
                    'stdin_file': str(package/'handoff.txt'), 'session_id': session,
                    'source_thread_id': thread_id, 'source_turn_id': turn_id,
                    'source_owner': owner, 'source_event': event,
                    'state': 'launching', 'file_tool_only': True})
        self.set_run_state(session, 'launching')
        reason = None
        with (package/'handoff.txt').open('rb') as stdin, \
                (package/'claude.stdout.jsonl').open('wb') as stdout, \
                (package/'claude.stderr.txt').open('wb') as stderr:
            self.process = subprocess.Popen(argv, cwd=self.config['cwd'], stdin=stdin,
                                            stdout=stdout, stderr=stderr, start_new_session=True)
            self.set_run_state(session, 'running')
            self.status('CLAUDE_RUNNING', session_id=session, child_pid=self.process.pid)
            deadline = time.monotonic() + self.config['claude_timeout_seconds']
            try:
                while self.process.poll() is None:
                    if time.monotonic() > deadline:
                        reason = 'claude_timeout'
                        break
                    try:
                        ensure_same_failed_turn(ipc, thread_id, owner, turn_id)
                    except (OSError, EOFError, TimeoutError, ProtocolError):
                        reason = 'source_changed_or_disconnected'
                        break
                    time.sleep(0.5)
            finally:
                terminate_owned(self.process)
        if not reason:
            try:
                ensure_same_failed_turn(ipc, thread_id, owner, turn_id)
            except (OSError, EOFError, TimeoutError, ProtocolError):
                reason = 'source_changed_or_disconnected'
        result = parse_claude_result(package/'claude.stdout.jsonl', self.process.returncode)
        if reason:
            result.update(passed=False, reason=reason)
        if result.get('session_id') != session:
            result.update(passed=False, reason=result.get('reason') if not result.get('passed') else 'session_id_mismatch')
        result.update(package=str(package), source_turn_id=turn_id)
        atomic_json(package/'result.json', result)
        self.process = None
        state = 'completed' if result['passed'] else 'needs_attention'
        self.set_run_state(session, state, release=result['passed'])
        return self.status(state.upper(), session_id=session, result=result)

    def watch(self, duration=1800):
        # One daemon per state directory, including across GUI restarts.
        with (self.folder/'service.lock').open('a') as lock:
            try:
                lock_exclusive(lock)
            except BlockingIOError:
                return self.status('ALREADY_RUNNING')
            if not core.AUTO_HANDOFF_ENABLED or self.config.get('enabled') is not True:
                return self.status('DISABLED')
            with contextlib.closing(self.core.connect()) as db:
                uncertain = db.execute("SELECT session_id,state FROM handoffs WHERE state NOT IN ('completed')").fetchall()
            if uncertain:
                return self.status('REVIEW_PREVIOUS_RUN', runs=uncertain)
            cli = discover_claude(self.config.get('claude_path'))
            auth = auth_status(cli, self.config['cwd'])
            if not auth['loggedIn']:
                return self.status('AUTH_REQUIRED', auth=auth)
            ipc, deadline = self.ipc_factory(), time.monotonic() + duration
            try:
                owner = ipc.owner(self.config['thread_id'])
                view = ipc.fresh_snapshot(self.config['thread_id'], owner)
                if str(Path(view.state.get('cwd', '')).resolve()) != self.config['cwd']:
                    raise ValueError('selected thread/workspace mismatch')
                gate = NewFailureGate(view)
                self.status('ARMED', source_owner=owner, initial_turn=gate.initial_turn,
                            historical_failure_skipped=gate.skip_initial)
                previous_decision = None
                while time.monotonic() < deadline:
                    if gate.candidate(view):
                        event, snapshot = view.normalized()
                        decision = core.evaluate(event, snapshot)
                        if decision != previous_decision:
                            self.status('SOURCE_FAILURE', decision=decision,
                                        source_turn_id=event['params']['turn']['id'])
                            previous_decision = decision
                        if decision == 'PREPARE':
                            current = ensure_same_failed_turn(ipc, self.config['thread_id'], owner,
                                                              event['params']['turn']['id'])
                            event, snapshot = current.normalized()
                            prepared = self.core.prepare(event, snapshot, build_context(current, self.config))
                            if prepared['action'] == 'PREPARED':
                                return self.launch(ipc, owner, prepared, event)
                            return self.status(prepared['action'], details=prepared)
                    time.sleep(0.5)
                    new_owner = ipc.owner(self.config['thread_id'])
                    if new_owner != owner:
                        raise ProtocolError('source owner changed; re-arm explicitly')
                    view = ipc.fresh_snapshot(self.config['thread_id'], owner)
                return self.status('WATCH_TIMEOUT', external_runs=0)
            finally:
                if self.process:
                    terminate_owned(self.process)
                ipc.close()


def probe(thread_id, destination=None):
    ipc = DesktopIPC()
    try:
        owner = ipc.owner(thread_id)
        view = ipc.fresh_snapshot(thread_id, owner)
        event, snapshot = view.normalized()
        result = {'connected': True, 'source': 'running_codex_desktop_ipc', 'owner': owner,
                  'revision': view.revision, 'thread_id': thread_id,
                  'source_turn_id': source_signature(view)[0], 'turn_status': source_signature(view)[1],
                  'runtime_status': snapshot['thread_status'] if snapshot else None,
                  'quiesced': snapshot['writers_quiesced'] if snapshot else False,
                  'decision': core.evaluate(event, snapshot), 'external_runs': 0}
        if destination:
            atomic_json(destination, result)
        print(json.dumps(result, ensure_ascii=False))
        return result
    finally:
        ipc.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('probe'); p.add_argument('--thread', required=True); p.add_argument('--out', type=Path)
    w = sub.add_parser('watch'); w.add_argument('--config', type=Path, required=True)
    w.add_argument('--duration', type=int, default=1800)
    a = sub.add_parser('auth-status'); a.add_argument('--claude-path')
    args = parser.parse_args(argv)
    if args.command == 'probe':
        probe(args.thread, args.out)
        return 0
    if args.command == 'auth-status':
        status = auth_status(discover_claude(args.claude_path), Path.cwd())
        print(json.dumps(status))
        return 0 if status['loggedIn'] else 2
    os.umask(0o077)
    service = Service(json.loads(args.config.read_text(encoding='utf-8')))
    def stop(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    try:
        result = service.watch(args.duration)
        return 0 if result['phase'] in ('COMPLETED', 'DISABLED', 'WATCH_TIMEOUT') else 2
    except KeyboardInterrupt:
        service.status('STOPPED')
        return 130
    except Exception as exc:
        service.status('ERROR', error_type=type(exc).__name__, error=str(exc))
        return 1


if __name__ == '__main__':
    sys.exit(main())

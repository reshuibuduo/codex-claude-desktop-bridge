"""Read-only stream adapter for the observed Codex Desktop IPC v11.

Private, versioned desktop protocol; no app patching, credentials, or daemon startup.
Unknown frames/revisions invalidate the view rather than implying an idle source.
"""
import copy
import json
import os
from pathlib import Path
import socket
import stat
import struct
import time
import uuid

MAX_FRAME = 32 * 1024 * 1024
STREAM_VERSION = 11


class ProtocolError(RuntimeError):
    pass


def ordered_turns(state):
    history = state.get("turnHistory") or {}
    if history.get("kind") == "canonical":
        value = history.get("history") or {}
        entities = value.get("entitiesByKey") or {}
        result, seen = [], set()
        for island in value.get("islands", []):
            for entry in island.get("entries", []):
                key = entry.get("value")
                if key in entities and key not in seen:
                    result.append(entities[key])
                    seen.add(key)
        return result
    return state.get("turns", [])


def apply_patches(state, patches):
    value = copy.deepcopy(state)
    for patch in patches:
        op, path = patch.get("op"), patch.get("path")
        if op not in ("add", "replace", "remove") or not isinstance(path, list):
            raise ProtocolError("unsupported patch")
        if not path:
            if op == "remove":
                raise ProtocolError("root removed")
            value = copy.deepcopy(patch["value"])
            continue
        parent = value
        for key in path[:-1]:
            parent = parent[key]
        key = path[-1]
        if isinstance(parent, list):
            if type(key) is not int or key < 0:
                raise ProtocolError("invalid list index")
            if op == "add":
                if key > len(parent):
                    raise ProtocolError("non-contiguous list insertion")
                parent.insert(key, copy.deepcopy(patch["value"]))
            elif op == "replace":
                parent[key] = copy.deepcopy(patch["value"])
            else:
                del parent[key]
        elif isinstance(parent, dict):
            if op != "add" and key not in parent:
                raise ProtocolError("missing patch key")
            if op == "remove":
                del parent[key]
            else:
                parent[key] = copy.deepcopy(patch["value"])
        else:
            raise ProtocolError("patch parent is not a container")
    if not isinstance(value, dict):
        raise ProtocolError("snapshot root must be an object")
    return value


class DesktopIPC:
    def __init__(self, path=None, timeout=8):
        self.path = Path(path or Path.home() / ".codex/ipc/ipc.sock")
        info = self.path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise ProtocolError("unexpected socket owner or file type")
        if info.st_mode & 0o077:
            raise ProtocolError("desktop socket is not private")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(str(self.path))
        self.client_id = "initializing-client"
        self.pending = []
        self.buffer = bytearray()
        self.followed = set()
        try:
            answer = self.request("initialize", {"clientType": "codex-claude-bridge"}, 0)
            self.client_id = answer["result"]["clientId"]
        except BaseException:
            self.sock.close()
            raise

    def send(self, message):
        raw = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()
        if len(raw) > MAX_FRAME:
            raise ProtocolError("outgoing frame exceeds cap")
        self.sock.sendall(struct.pack("<I", len(raw)) + raw)

    def receive(self, timeout=None):
        if timeout is not None:
            self.sock.settimeout(timeout)
        # Preserve partial frames across socket timeouts.
        while True:
            if len(self.buffer) >= 4:
                size = struct.unpack("<I", self.buffer[:4])[0]
                if not 0 < size <= MAX_FRAME:
                    raise ProtocolError("incoming frame exceeds cap")
                if len(self.buffer) >= size + 4:
                    message = json.loads(self.buffer[4:4+size])
                    del self.buffer[:4+size]
                    if message.get("type") == "client-discovery-request":
                        self.send({"type": "client-discovery-response", "requestId": message["requestId"],
                                   "response": {"canHandle": False}})
                    elif message.get("type") == "request":
                        self.send({"type": "response", "requestId": message["requestId"],
                                   "resultType": "error", "error": "no-handler-for-request"})
                    return message
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError("desktop IPC disconnected")
            self.buffer.extend(chunk)

    def request(self, method, params, version, target=None, timeout=8):
        message = {"type": "request", "requestId": str(uuid.uuid4()), "sourceClientId": self.client_id,
                   "version": version, "method": method, "params": params, "timeoutMs": int(timeout*1000)}
        if target:
            message["targetClientId"] = target
        self.send(message)
        deadline = time.monotonic() + timeout + 1
        while time.monotonic() < deadline:
            reply = self.receive(max(0.1, deadline-time.monotonic()))
            if reply.get("type") == "response" and reply.get("requestId") == message["requestId"]:
                if reply.get("resultType") != "success":
                    raise ProtocolError(str(reply.get("error", "IPC request failed")))
                return reply
            self.pending.append(reply)
        raise TimeoutError(method)

    def owner(self, thread_id):
        reply = self.request("thread-owner-discovery", {"hostId": "local", "conversationId": thread_id}, 1)
        return reply["handledByClientId"]

    def follow(self, thread_id, following=True, target=None):
        message = {"type": "broadcast", "method": "thread-stream-following-changed", "version": 1,
                   "sourceClientId": self.client_id,
                   "params": {"hostId": "local", "conversationId": thread_id, "following": following}}
        if target:
            message["targetClientIds"] = [target]
        self.send(message)
        if following:
            self.followed.add(thread_id)
        else:
            self.followed.discard(thread_id)

    def fresh_snapshot(self, thread_id, owner, timeout=8):
        # Drain already queued frames before asking the confirmed owner for a new snapshot.
        self.pending = []
        drain_deadline = time.monotonic() + 0.2
        while time.monotonic() < drain_deadline:
            try:
                self.receive(0.001)
            except socket.timeout:
                break
        self.follow(thread_id, target=owner)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.receive(max(0.1, deadline-time.monotonic()))
            p = message.get("params") or {}
            if (message.get("method") == "thread-stream-state-changed" and
                    message.get("sourceClientId") == owner and p.get("conversationId") == thread_id and
                    p.get("change", {}).get("type") == "snapshot"):
                view = ThreadView(thread_id, owner)
                view.accept(message)
                return view
        raise TimeoutError("fresh desktop snapshot")

    def close(self):
        for thread_id in list(self.followed):
            try:
                self.follow(thread_id, False)
            except (OSError, EOFError):
                pass
        self.sock.close()


class ThreadView:
    def __init__(self, thread_id, owner):
        self.thread_id, self.owner = thread_id, owner
        self.state, self.revision, self.observed_at = None, None, None

    def accept(self, message):
        params = message.get("params") or {}
        if (message.get("method") != "thread-stream-state-changed" or
                params.get("conversationId") != self.thread_id):
            return False
        if message.get("version") != STREAM_VERSION:
            self.state = None
            raise ProtocolError("Desktop stream version changed; adapter revalidation required")
        if message.get("sourceClientId") != self.owner or params.get("hostId") != "local":
            return False
        change = params.get("change") or {}
        if change.get("type") == "snapshot":
            self.state = copy.deepcopy(change["conversationState"])
        elif change.get("type") == "patches":
            if self.state is None or change.get("baseRevision") != self.revision:
                self.state = None
                raise ProtocolError("stream revision gap")
            try:
                self.state = apply_patches(self.state, change["patches"])
            except (KeyError, IndexError, TypeError, ValueError, ProtocolError) as exc:
                self.state = None
                raise ProtocolError("invalid desktop patch") from exc
        else:
            self.state = None
            raise ProtocolError("unknown stream update")
        if self.state.get("id") != self.thread_id:
            self.state = None
            raise ProtocolError("snapshot identity mismatch")
        self.revision = change["revision"]
        self.observed_at = time.time()
        return True

    def latest(self):
        turns = ordered_turns(self.state or {})
        return turns[-1] if turns else None

    def normalized(self):
        state, turn = self.state, self.latest()
        if state is None or not turn or not turn.get("turnId"):
            return None, None
        pending = len(state.get("requests") or [])
        for item in turn.get("items", []):
            if item.get("status") in ("inProgress", "running", "pending"):
                pending += 1
        unconfirmed = any(x.get("terminal") is not True for x in state.get("unconfirmedTurnSubmissions", []))
        runtime = (state.get("threadRuntimeStatus") or {}).get("type")
        event = {"method": "turn/completed", "params": {"threadId": self.thread_id, "turn": {
            "id": turn["turnId"], "status": turn.get("status"), "error": turn.get("error")}}}
        snapshot = {"authority": "same-runtime", "thread_id": self.thread_id,
                    "latest_turn_id": turn["turnId"], "observed_at": self.observed_at,
                    "thread_status": runtime, "pending_tools": pending,
                    "writers_quiesced": runtime in ("idle", "systemError") and pending == 0 and not unconfirmed and
                        state.get("resumeState") == "resumed" and turn.get("status") == "failed"}
        return event, snapshot

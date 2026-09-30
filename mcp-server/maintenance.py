"""Cooperative restart lease and cross-process native-publication gate.

The lease and unfinished-publication records live outside IPC and never expire.
This coordinates current MCP servers; it is not a sandbox for old clients or
manual Vectorworks use. All functions are local file operations, not host calls.
"""
from contextlib import contextmanager
import hashlib
import hmac
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace


# Also works when maintenance is loaded by an absolute path from a standalone
# controller; it does not depend on the caller's cwd or sys.path.
_DIAGNOSTIC_SPEC = importlib.util.spec_from_file_location(
    'maintenance_diagnostic_io', Path(__file__).with_name('diagnostic_io.py'))
_DIAGNOSTIC_IO = importlib.util.module_from_spec(_DIAGNOSTIC_SPEC)
_DIAGNOSTIC_SPEC.loader.exec_module(_DIAGNOSTIC_IO)
read_diagnostic_text = _DIAGNOSTIC_IO.read_diagnostic_text


LEASE_FILE = 'bridge.maintenance.json'
GATE_FILE = 'bridge.publish.lock'
PUBLICATIONS_DIR = 'bridge.publications'
NATIVE_ACTIONS = frozenset({'status', 'save', 'quit'})
_THREAD_LOCKS = {}
_LOCKS_LOCK = threading.Lock()
_PROJECT_MODULE = None


def project_module():
    """Load the same contract when called by the server or a standalone tool."""
    global _PROJECT_MODULE
    if _PROJECT_MODULE is None:
        spec = importlib.util.spec_from_file_location(
            'maintenance_project_session', Path(__file__).with_name('project_session.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _PROJECT_MODULE = module
    return _PROJECT_MODULE


class MaintenanceError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

    def response(self):
        return {'error': str(self), 'code': self.code, 'dispatched': False}


def _token_hash(token):
    if type(token) is not str or not re.fullmatch('[0-9a-f]{64}', token):
        raise MaintenanceError('VWX_MAINTENANCE_TOKEN', 'A caller-generated 64-character lowercase hexadecimal token is required')
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def _base(plugin_dir):
    base = Path(plugin_dir).resolve(strict=True)
    if not base.is_dir():
        raise MaintenanceError('VWX_MAINTENANCE_STATE', 'Bridge installation directory is unavailable')
    return base


@contextmanager
def publish_gate(plugin_dir, *, timeout=2.0):
    """Never delete this OS-locked file: deletion would split the lock domain."""
    base = _base(plugin_dir)
    key = os.path.normcase(str(base))
    with _LOCKS_LOCK:
        local = _THREAD_LOCKS.setdefault(key, threading.Lock())
    if not local.acquire(timeout=timeout):
        raise MaintenanceError('VWX_MAINTENANCE_BUSY', 'Native publication gate is busy')
    stream = None
    locked = False
    try:
        stream = open(base / GATE_FILE, 'a+b')
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise MaintenanceError('VWX_MAINTENANCE_BUSY', 'Native publication gate is held by another process')
                time.sleep(0.02)
        yield base
    finally:
        if stream is not None:
            if locked:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()
        local.release()


def _read_lease(base):
    path = base / LEASE_FILE
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError('Invalid lease file')
        value = json.loads(path.read_text(encoding='utf-8'))
        if (type(value) is not dict or set(value) != {'schema_version', 'token_sha256', 'created_epoch', 'owner_server_pid', 'host_process_id'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or type(value['token_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', value['token_sha256'])
                or type(value['created_epoch']) not in (int, float) or not math.isfinite(value['created_epoch']) or value['created_epoch'] < 0
                or any(type(value[key]) is not int or value[key] <= 0 for key in ('owner_server_pid', 'host_process_id'))):
            raise ValueError('Malformed lease')
        return value
    except (OSError, ValueError, TypeError) as error:
        raise MaintenanceError('VWX_MAINTENANCE_STATE', 'Maintenance lease is unreadable or malformed; it was not changed') from error


def _owned(lease, token):
    supplied = _token_hash(token)
    return lease is not None and hmac.compare_digest(lease['token_sha256'], supplied)


def _public(lease, token=''):
    return ({'status': 'ok', 'active': False, 'owned': False} if lease is None else
            {'status': 'ok', 'active': True, 'owned': _owned(lease, token) if token else False,
             'created_epoch': lease['created_epoch'], 'owner_server_pid': lease['owner_server_pid'],
             'host_process_id': lease['host_process_id']})


def _write_exclusive(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def _filetime(path):
    # Native ReadRunnerStamp uses Windows FILETIME (100ns since1601).
    return path.stat().st_mtime_ns // 100 + 116444736000000000 if path.exists() else 0


def _readiness(base, *, now=None, max_age=8.0):
    now = time.time() if now is None else now
    ipc = base / 'ipc'
    try:
        alive = read_diagnostic_text(ipc / 'native.alive').split()
        state = json.loads(read_diagnostic_text(ipc / 'native.scheduler.json'))
        if (len(alive) != 2 or not alive[0].isdigit() or alive[1] != '0'
                or not -2 <= now - int(alive[0]) <= max_age
                or type(state) is not dict or type(state.get('updated_epoch')) is not int
                or not -2 <= now - state['updated_epoch'] <= max_age
                or state.get('scheduler') != 'sdk-named-menu-broker-ack-v4'
                or type(state.get('schema_version')) is not int or state['schema_version'] != 1
                or type(state.get('sdk_version')) is not int or state['sdk_version'] != 3200
                or type(state.get('process_id')) is not int or state['process_id'] <= 0
                or any(state.get(key) is not False for key in ('paused', 'pending', 'broker_message_pending', 'menu_invocation_active'))
                or any(state.get(key) is not True for key in ('timer_active', 'frame_available', 'broker_window_available'))):
            raise ValueError('Fresh idle scheduler required')
        for key in ('queued_jobs', 'posts', 'runner_completions_observed', 'menu_invocations', 'menu_returns', 'runner_stamp', 'completion_stamp'):
            if type(state.get(key)) is not int or state[key] < 0:
                raise ValueError('Malformed scheduler counter')
        if (state['queued_jobs'] != 0 or len({state[key] for key in ('posts', 'runner_completions_observed', 'menu_invocations', 'menu_returns')}) != 1
                or (state['posts'] > 0 and (state['runner_stamp'] == 0 or state['completion_stamp'] == 0))
                or state['runner_stamp'] > state['completion_stamp']
                or state['runner_stamp'] != _filetime(ipc / 'pump.stamp')
                or state['completion_stamp'] != _filetime(ipc / 'pump.complete.stamp')):
            raise ValueError('An outer invocation or acknowledgment is pending')
        jobs = ipc / 'jobs'
        if not jobs.is_dir() or any(jobs.iterdir()):
            raise ValueError('Queue contains a job, orphan working file or incomplete publication')
        publications = base / PUBLICATIONS_DIR
        if publications.exists() and (not publications.is_dir() or any(publications.iterdir())):
            raise ValueError('A publication is outstanding or has an uncertain outcome')
        return state['process_id']
    except (OSError, ValueError, TypeError) as error:
        raise MaintenanceError('VWX_MAINTENANCE_NOT_IDLE', 'Cannot acquire maintenance: ' + str(error)) from error


def acquire(plugin_dir, token):
    digest = _token_hash(token)
    with publish_gate(plugin_dir) as base:
        project = project_module()
        try:
            if project.guard.read_lease(base) is not None:
                raise MaintenanceError('VWX_PROJECT_HELD', 'A project lease owns native access; maintenance cannot acquire it')
        except project.ProjectError as error:
            raise MaintenanceError(error.code, str(error)) from error
        if _read_lease(base) is not None:
            raise MaintenanceError('VWX_MAINTENANCE_HELD', 'A maintenance lease already exists; never replay or steal it')
        process_id = _readiness(base)
        lease = dict(schema_version=1, token_sha256=digest, created_epoch=time.time(),
                     owner_server_pid=os.getpid(), host_process_id=process_id)
        _write_exclusive(base / LEASE_FILE, lease)
        return dict(_public(lease, token), action='acquire')


def release(plugin_dir, token):
    _token_hash(token)
    with publish_gate(plugin_dir) as base:
        lease = _read_lease(base)
        if not _owned(lease, token):
            raise MaintenanceError('VWX_MAINTENANCE_TOKEN', 'No matching maintenance lease; nothing was released')
        (base / LEASE_FILE).unlink()
        return {'status': 'ok', 'action': 'release', 'active': False, 'owned': False}


def lease_status(plugin_dir, token=''):
    if token:
        _token_hash(token)
    with publish_gate(plugin_dir) as base:
        return dict(_public(_read_lease(base), token), action='lease_status')


def reject_nested_maintenance(command, params, depth=0):
    """This invariant also applies in attended mode, before any batch member."""
    if command == 'bridge_maintenance' and depth:
        raise MaintenanceError('VWX_MAINTENANCE_CONTEXT', 'Maintenance actions must be separate top-level typed requests')
    if command in {'project_session', 'project_execute'} and depth:
        raise MaintenanceError('VWX_PROJECT_CONTEXT', 'Project coordination must be a separate top-level typed request')
    if command == '_batch':
        if depth > 20 or type(params) is not dict or type(params.get('calls')) is not list:
            raise MaintenanceError('VWX_MAINTENANCE_CONTEXT', 'Cannot validate nested maintenance in this batch')
        for call in params['calls']:
            if type(call) is not dict:
                raise MaintenanceError('VWX_MAINTENANCE_CONTEXT', 'Cannot validate nested maintenance in this batch')
            reject_nested_maintenance(call.get('command'), call.get('params', {}), depth + 1)


def _cid(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{12}', value):
        raise MaintenanceError('VWX_MAINTENANCE_STATE', 'Invalid publication identity')
    return value


@contextmanager
def publication_guard(plugin_dir, command, params, cid):
    reject_nested_maintenance(command, params)
    _cid(cid)
    with publish_gate(plugin_dir) as base:
        project = project_module()
        try:
            params = project.authorize_publication(base, command, params,
                coordinator=SimpleNamespace(_readiness=_readiness, MaintenanceError=MaintenanceError))
        except project.ProjectError as error:
            raise MaintenanceError(error.code, str(error)) from error
        lease = _read_lease(base)
        maintenance = command == 'bridge_maintenance'
        if maintenance:
            if (type(params) is not dict or set(params) - {'action', 'token', 'expected_path'}
                    or params.get('action') not in NATIVE_ACTIONS or type(params.get('expected_path', '')) is not str):
                raise MaintenanceError('VWX_MAINTENANCE_CONTEXT', 'Only typed status/save/quit may reach the host')
            if not _owned(lease, params.get('token', '')):
                raise MaintenanceError('VWX_MAINTENANCE_TOKEN', 'A matching maintenance lease is required')
        elif lease is not None:
            raise MaintenanceError('VWX_MAINTENANCE_HELD', 'Native publications are blocked by an active maintenance lease')
        if not maintenance:
            folder = base / PUBLICATIONS_DIR
            folder.mkdir(exist_ok=True)
            _write_exclusive(folder / (cid + '.json'), {'schema_version': 1, 'cid': cid,
                             'command': command, 'created_epoch': time.time(), 'owner_server_pid': os.getpid()})
        # No marker is removed on an exception: the caller must prove that
        # publication failed before dispatch, or preserve the uncertain record.
        yield params


def finish_publication(plugin_dir, cid):
    _cid(cid)
    with publish_gate(plugin_dir) as base:
        path = base / PUBLICATIONS_DIR / (cid + '.json')
        try:
            path.unlink()
        except FileNotFoundError:
            pass

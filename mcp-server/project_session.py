"""Persistent drawing ownership, sharing maintenance's OS publication gate."""
import hashlib
import hmac
import importlib.util
import os
from pathlib import Path
import re
import time
import uuid

_SPEC = importlib.util.spec_from_file_location(
    'vwx_project_guard', Path(__file__).resolve().parents[1] / 'vwx-plugin/project_guard.py')
guard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guard)
ProjectError = guard.ProjectError
LEASE_FILE = guard.LEASE_FILE


def _token_hash(token):
    if type(token) is not str or not re.fullmatch('[0-9a-f]{64}', token):
        raise ProjectError('VWX_PROJECT_TOKEN', 'A caller-generated 64-character lowercase hexadecimal token is required')
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def _owned(lease, token):
    digest = _token_hash(token)
    return lease is not None and hmac.compare_digest(lease['token_sha256'], digest)


def _public(lease, token=''):
    if lease is None:
        return {'status': 'ok', 'active': False, 'owned': False}
    return {'status': 'ok', 'active': True, 'owned': _owned(lease, token) if token else False,
            'owner': lease['owner'], 'expected_path': lease['expected_path'],
            'created_epoch': lease['created_epoch'], 'host_process_id': lease['host_process_id'],
            'owner_server_pid': lease['owner_server_pid']}


def _idle(coordinator, base):
    try:
        return coordinator._readiness(base)
    except coordinator.MaintenanceError as error:
        raise ProjectError('VWX_PROJECT_NOT_IDLE', 'Project coordination requires a fresh idle bridge with no queued, running or uncertain publication') from error


def acquire(plugin_dir, token, expected_path, owner, *, coordinator):
    digest = _token_hash(token)
    path = guard.canonical_path(expected_path)
    if not guard.valid_owner(owner):
        raise ProjectError('VWX_PROJECT_OWNER', 'A printable owner label of 1 to 160 characters is required')
    with coordinator.publish_gate(plugin_dir) as base:
        if coordinator._read_lease(base) is not None:
            raise ProjectError('VWX_MAINTENANCE_HELD', 'Maintenance owns native access; a project lease cannot be acquired')
        if guard.read_lease(base) is not None:
            raise ProjectError('VWX_PROJECT_HELD', 'A project lease already exists; never expire, replay or steal it')
        lease = dict(schema_version=1, lease_id=uuid.uuid4().hex, token_sha256=digest,
                     created_epoch=time.time(), owner_server_pid=os.getpid(),
                     host_process_id=_idle(coordinator, base), expected_path=path, owner=owner.strip())
        coordinator._write_exclusive(base / LEASE_FILE, lease)
        return dict(_public(lease, token), action='acquire',
                    note='Ownership is reserved locally; project_execute verifies the active drawing inside every native job.')


def release(plugin_dir, token, *, coordinator):
    _token_hash(token)
    with coordinator.publish_gate(plugin_dir) as base:
        lease = guard.read_lease(base)
        if not _owned(lease, token):
            raise ProjectError('VWX_PROJECT_TOKEN', 'No matching project lease; nothing was released')
        _idle(coordinator, base)
        (base / LEASE_FILE).unlink()
        return {'status': 'ok', 'action': 'release', 'active': False, 'owned': False}


def status(plugin_dir, token='', *, coordinator):
    if token:
        _token_hash(token)
    with coordinator.publish_gate(plugin_dir) as base:
        return dict(_public(guard.read_lease(base), token), action='status')


def authorize_publication(base, command, params, *, coordinator):
    """Called with the shared publication gate held; returns token-free params."""
    lease = guard.read_lease(base)
    if command == 'project_session':
        raise ProjectError('VWX_PROJECT_CONTEXT', 'Project session management is local and cannot be queued')
    if command != 'project_execute':
        if lease is not None:
            raise ProjectError('VWX_PROJECT_HELD', 'Native publications require the project owner token through project_execute')
        return params
    if (type(params) is not dict or set(params) != {'token', 'command', 'params'}
            or not _owned(lease, params.get('token', ''))):
        raise ProjectError('VWX_PROJECT_TOKEN', 'A matching active project lease is required')
    guard.validate_operation(params['command'], params['params'], lease['expected_path'])
    if _idle(coordinator, base) != lease['host_process_id']:
        raise ProjectError('VWX_PROJECT_HOST', 'The Vectorworks process changed; the project lease was preserved')
    return {'lease_id': lease['lease_id'], 'expected_path': lease['expected_path'],
            'command': params['command'], 'params': params['params']}

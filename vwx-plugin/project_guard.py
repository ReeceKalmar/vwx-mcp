"""Shared, host-independent contract for cooperative drawing ownership.

This is coordination, not a security boundary against direct file access or
manual edits. Tokens are checked only by the server; jobs carry a nonsecret
lease identity so a delayed job cannot run under a replacement lease.
"""
import json
import math
import os
from pathlib import Path
import re
import stat

LEASE_FILE = 'bridge.project.json'
LEASE_KEYS = {'schema_version', 'lease_id', 'token_sha256', 'created_epoch',
              'owner_server_pid', 'host_process_id', 'expected_path', 'owner'}
BLOCKED_COMMANDS = frozenset({
    'project_session', 'project_execute', 'bridge_maintenance', 'execute_script',
    'run_menu_command', 'marionette_recalc', 'switch_document', 'save_document',
    'save_document_as',
})


class ProjectError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

    def response(self):
        return {'error': str(self), 'code': self.code, 'dispatched': False}


def canonical_path(value, *, require_exists=True):
    if (type(value) is not str or not value or len(value) > 4096
            or any(ord(char) < 32 for char in value) or not os.path.isabs(value)
            or Path(value).suffix.lower() != '.vwx'):
        raise ProjectError('VWX_PROJECT_DOCUMENT', 'An exact absolute saved .vwx path is required')
    try:
        path = os.path.realpath(value)
        if require_exists and not os.path.isfile(path):
            raise ValueError('Drawing does not exist')
        return os.path.normcase(path)
    except (OSError, ValueError) as error:
        raise ProjectError('VWX_PROJECT_DOCUMENT', 'The saved drawing path is unavailable') from error


def valid_owner(value):
    return (type(value) is str and 1 <= len(value.strip()) <= 160
            and all(char.isprintable() for char in value))


def read_lease(base):
    path = Path(base) / LEASE_FILE
    try:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return None
        # exists()/is_symlink() can suppress access errors on some Python
        # versions. Only confirmed absence releases the ownership restriction.
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 65536:
            raise ValueError('Invalid lease file')
        value = json.loads(path.read_text(encoding='utf-8'))
        if (type(value) is not dict or set(value) != LEASE_KEYS
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or type(value['lease_id']) is not str or not re.fullmatch('[0-9a-f]{32}', value['lease_id'])
                or type(value['token_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', value['token_sha256'])
                or type(value['created_epoch']) not in (int, float)
                or not math.isfinite(value['created_epoch']) or value['created_epoch'] < 0
                or any(type(value[key]) is not int or value[key] <= 0
                       for key in ('owner_server_pid', 'host_process_id'))
                or not valid_owner(value['owner'])
                or canonical_path(value['expected_path'], require_exists=False) != value['expected_path']):
            raise ValueError('Malformed lease')
        return value
    except (OSError, ValueError, TypeError, OverflowError, ProjectError) as error:
        raise ProjectError('VWX_PROJECT_STATE', 'Project lease is unreadable or malformed; it was not changed') from error


def validate_operation(command, params, expected_path, depth=0):
    """Reject context escapes recursively, including inside batches/sequences."""
    if (depth > 20 or type(command) is not str or not command or type(params) is not dict
            or command in BLOCKED_COMMANDS or (command.startswith('_') and command != '_batch')):
        raise ProjectError('VWX_PROJECT_CONTEXT', 'Project jobs require typed drawing operations without nested coordination or document/script escapes')
    if command == '_batch':
        calls = params.get('calls')
        if type(calls) is not list or len(calls) > 200:
            raise ProjectError('VWX_PROJECT_CONTEXT', 'Project batches require at most 200 typed calls')
        for call in calls:
            if type(call) is not dict or set(call) - {'command', 'params'}:
                raise ProjectError('VWX_PROJECT_CONTEXT', 'Malformed project batch member')
            validate_operation(call.get('command'), call.get('params', {}), expected_path, depth + 1)
    elif command == 'sdk_sequence':
        calls = params.get('calls')
        if type(calls) is not list or len(calls) > 200:
            raise ProjectError('VWX_PROJECT_CONTEXT', 'Project SDK sequences require at most 200 calls')
        for call in calls:
            if type(call) is not dict:
                raise ProjectError('VWX_PROJECT_CONTEXT', 'Malformed project SDK sequence member')
            validate_operation('sdk_call', call, expected_path, depth + 1)
    elif command == 'sdk_call' or command.startswith('sdk_'):
        name = params.get('name') if command == 'sdk_call' else command[4:]
        if type(name) is not str:
            raise ProjectError('VWX_PROJECT_CONTEXT', 'An exact SDK name is required')
        # These routes can escape the bound document or run unchecked code.
        if (name.startswith(('Python', 'Run', 'CallTool', 'DoMenu', 'SetTool'))
                or name in {'OpenURL', 'OpenDocument', 'OpenDocumentN', 'CloseDocument',
                            'NewDocument', 'SetActiveDocument', 'Quit', 'QuitApplication'}):
            raise ProjectError('VWX_PROJECT_CONTEXT', 'SDK document switching and script/menu/tool execution are unavailable inside a project job')
        if name == 'SaveActiveDocument':
            args = params.get('arguments')
            if (type(args) is not dict
                    or canonical_path(args.get('filePath')) != expected_path):
                raise ProjectError('VWX_PROJECT_DOCUMENT', 'Project save must use the literal bound drawing path; Save As is unavailable')


def host_operation(base, command, params, *, process_id, get_active_path):
    """Check drawing identity inside the same menu job as the eventual call."""
    lease = read_lease(base)
    if command != 'project_execute':
        if lease is not None:
            raise ProjectError('VWX_PROJECT_HELD', 'Native work requires the active project owner and project_execute')
        return command, params
    if lease is None:
        raise ProjectError('VWX_PROJECT_TOKEN', 'The project lease is no longer active; this job was not dispatched')
    if (type(params) is not dict or set(params) != {'lease_id', 'expected_path', 'command', 'params'}
            or params.get('lease_id') != lease['lease_id']
            or params.get('expected_path') != lease['expected_path']):
        raise ProjectError('VWX_PROJECT_STATE', 'Project job does not match the active lease')
    if process_id != lease['host_process_id']:
        raise ProjectError('VWX_PROJECT_HOST', 'The Vectorworks process changed; project jobs cannot resume automatically')
    validate_operation(params['command'], params['params'], lease['expected_path'])
    try:
        actual = canonical_path(get_active_path())
    except Exception as error:
        raise ProjectError('VWX_PROJECT_DOCUMENT', 'The active saved drawing could not be verified') from error
    if actual != lease['expected_path']:
        raise ProjectError('VWX_PROJECT_DOCUMENT', 'The active drawing differs from the bound project; nothing was dispatched')
    return params['command'], params['params']

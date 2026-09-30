"""Read-only landscape installation check; no host connection or deployment.

Run with the Python interpreter that will launch the MCP server. Source-only
checks work without an installed or open Vectorworks process. Installation
checks inspect only the named runtime files and native artifacts, never queues,
ownership leases, documents, credentials or arbitrary environment settings.
"""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILES = ('commands.py', 'vwx_pump.py', 'BridgeStart_MenuCommand.py',
                'vs_index.json', 'vs_index_meta.json', 'sdk_catalog.json',
                'sdk_generated.py', 'sdk_runtime.py', 'sdk_sequences.py',
                'project_guard.py', 'landscape_takeoff.py')
SERVER_FILES = ('vwx_mcp_server.py', 'sdk_tools.py', 'tool_tags.py',
                'background_policy.py', 'maintenance.py', 'diagnostic_io.py',
                'discovery.py', 'project_session.py')
NATIVE_FILES = ('VwxBridge.vlb', 'VwxBridge.vwr')
SDK_IDENTITY = {'vectorworks_year': 2027, 'sdk_version': 3200,
                'sdk_build': 882699, 'function_count': 3098}


def _read(path):
    """Read one exact file without following a symlink/reparse redirect."""
    for candidate in (path, *path.parents):
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise OSError('reparse path')
    data = path.read_bytes()
    if not data:
        raise OSError('empty required file')
    return data


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _package_version(name, lookup):
    try:
        value = lookup(name)
    except metadata.PackageNotFoundError:
        return None
    except Exception:
        return 'unavailable'
    if not isinstance(value, str) or re.fullmatch(r'[0-9A-Za-z.+_-]{1,80}', value) is None:
        return 'invalid metadata'
    return value


def _pillow_supported(version):
    if not version or re.fullmatch(r'\d+(?:\.\d+){1,3}(?:\.post\d+)?', version) is None:
        return False
    numbers = version.split('.post', 1)[0].split('.')
    return tuple(int(value) for value in numbers[:2]) >= (11, 0)


def check_installation(repo=ROOT, plugin_dir=None, source_only=False, *,
                       environment=None, python_version=None, package_version=None):
    """Return reproducible file/runtime diagnostics without executing host code.

    Dependency injection is for offline tests; the CLI uses the current Python
    process and distribution metadata. Missing local native build output is an
    explicit verification limit, not a requirement to rebuild an installation.
    """
    repo = Path(repo).absolute()
    environment = os.environ if environment is None else environment
    python_version = sys.version_info[:3] if python_version is None else python_version
    package_version = metadata.version if package_version is None else package_version
    errors, warnings, checks = [], [], []

    def error(code, component, message):
        errors.append({'code': code, 'component': component, 'message': message})

    actual_python = '.'.join(str(part) for part in python_version[:3])
    fastmcp = _package_version('fastmcp', package_version)
    pillow = _package_version('Pillow', package_version)
    runtime = {
        'python': {'required': '3.12', 'actual': actual_python,
                   'ok': tuple(python_version[:2]) == (3, 12)},
        'fastmcp': {'required': '4.0.3', 'actual': fastmcp, 'ok': fastmcp == '4.0.3'},
        'pillow': {'required': '>=11.0', 'actual': pillow, 'ok': _pillow_supported(pillow)},
    }
    for name, result in runtime.items():
        if not result['ok']:
            error('RUNTIME_DEPENDENCY', name, 'Use the documented Python environment and mcp-server/requirements.txt.')

    source_bytes = {}
    for relative in [*('vwx-plugin/' + name for name in PYTHON_FILES),
                     *('mcp-server/' + name for name in SERVER_FILES), 'mcp-server/requirements.txt']:
        try:
            data = _read(repo / relative)
        except FileNotFoundError:
            checks.append({'component': relative, 'status': 'missing'})
            error('SOURCE_MISSING', relative, 'Required repository source file is missing.')
        except OSError:
            checks.append({'component': relative, 'status': 'unreadable'})
            error('SOURCE_UNREADABLE', relative, 'Required source must be a nonempty readable file without reparse paths.')
        else:
            source_bytes[relative] = data
            checks.append({'component': relative, 'status': 'ok', 'source_sha256': _sha256(data)})

    requirements = source_bytes.get('mcp-server/requirements.txt', b'')
    try:
        requirement_lines = [line.strip() for line in requirements.decode('utf-8-sig').splitlines()
                             if line.strip() and not line.lstrip().startswith('#')]
        pins_valid = ('fastmcp==4.0.3' in requirement_lines and 'pillow>=11.0' in requirement_lines
                      and sum(line.lower().startswith('fastmcp') for line in requirement_lines) == 1
                      and sum(line.lower().startswith('pillow') for line in requirement_lines) == 1)
    except UnicodeError:
        pins_valid = False
    if not pins_valid:
        error('REQUIREMENTS_PIN', 'mcp-server/requirements.txt', 'Expected FastMCP 4.0.3 and Pillow >=11.0 requirements.')

    sdk = None
    try:
        sdk_meta = json.loads(source_bytes.get('vwx-plugin/vs_index_meta.json', b''))
        if not isinstance(sdk_meta, dict) or any(type(sdk_meta.get(key)) is not int or sdk_meta[key] != value
                                                for key, value in SDK_IDENTITY.items()):
            raise ValueError('wrong SDK identity')
        if sdk_meta.get('index_sha256') != _sha256(source_bytes['vwx-plugin/vs_index.json']):
            raise ValueError('index hash mismatch')
        sdk = dict(SDK_IDENTITY)
    except (ValueError, KeyError, UnicodeError):
        error('SDK_METADATA', 'vwx-plugin/vs_index_meta.json',
              'SDK 3200/build 882699 metadata and the matching 2027 source index are required.')

    selected = None
    origin = 'not_checked_source_only' if source_only else None
    if not source_only:
        raw = plugin_dir
        origin = 'argument'
        if raw is None:
            raw = environment.get('VWX_PLUGIN_DIR')
            origin = 'VWX_PLUGIN_DIR'
        if not raw:
            appdata = environment.get('APPDATA')
            raw = Path(appdata) / 'Nemetschek/Vectorworks/2027/Plug-ins/VWX-MCP' if appdata else None
            origin = 'APPDATA_2027'
        if raw is None:
            error('PLUGIN_DIR_UNRESOLVED', 'plugin_dir', 'Pass --plugin-dir when neither VWX_PLUGIN_DIR nor APPDATA identifies the installation.')
        else:
            try:
                candidate = Path(raw).absolute()
                # Inspect the supplied path before resolving: a symlink should
                # not make a different installation appear to be this one.
                for ancestor in (candidate, *candidate.parents):
                    try:
                        info = ancestor.lstat()
                    except FileNotFoundError:
                        continue
                    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                        raise OSError('reparse path')
                selected = candidate.resolve()
            except (OSError, ValueError, TypeError):
                error('PLUGIN_DIR_INVALID', 'plugin_dir', 'Installation path must be readable and must not traverse reparse points.')

        if selected is not None:
            for name in PYTHON_FILES:
                component = 'installed/' + name
                try:
                    data = _read(selected / name)
                except FileNotFoundError:
                    checks.append({'component': component, 'status': 'missing'})
                    error('INSTALLED_MISSING', component, 'Required installed companion file is missing; run the documented deployment workflow.')
                    continue
                except OSError:
                    checks.append({'component': component, 'status': 'unreadable'})
                    error('INSTALLED_UNREADABLE', component, 'Installed companion must be a nonempty readable file without reparse paths.')
                    continue
                expected = source_bytes.get('vwx-plugin/' + name)
                matches = expected is not None and data == expected
                checks.append({'component': component, 'status': 'ok' if matches else 'mismatch',
                               'installed_sha256': _sha256(data),
                               'source_sha256': _sha256(expected) if expected is not None else None})
                if not matches:
                    error('INSTALLED_MISMATCH', component, 'Installed file differs from this checkout; do not mix bridge revisions.')

            for name in NATIVE_FILES:
                component = 'installed/' + name
                try:
                    installed = _read(selected.parent / name)
                except FileNotFoundError:
                    checks.append({'component': component, 'status': 'missing'})
                    error('NATIVE_MISSING', component, 'Native library and resource archive must both exist beside VWX-MCP.')
                    continue
                except OSError:
                    checks.append({'component': component, 'status': 'unreadable'})
                    error('NATIVE_UNREADABLE', component, 'Native artifact must be a nonempty readable file without reparse paths.')
                    continue
                local = repo / 'native/Output/2027/Release' / name
                result = {'component': component, 'installed_sha256': _sha256(installed)}
                try:
                    built = _read(local)
                except FileNotFoundError:
                    result['status'] = 'present_without_local_build'
                    warnings.append({'code': 'NATIVE_BUILD_UNAVAILABLE', 'component': component,
                                     'message': 'Artifact exists; binary identity is unverified because no local Release build is available.'})
                except OSError:
                    result['status'] = 'local_build_unreadable'
                    error('NATIVE_BUILD_UNREADABLE', component, 'Local Release artifact exists but cannot be compared safely.')
                else:
                    result.update(source_sha256=_sha256(built), status='ok' if installed == built else 'mismatch')
                    if installed != built:
                        error('NATIVE_MISMATCH', component, 'Installed native artifact differs from the local 2027 Release build.')
                checks.append(result)

    return {
        'schema_version': 1, 'ok': not errors,
        'mode': 'source_only' if source_only else 'installation',
        'source_root': str(repo.resolve()),
        'plugin_dir': str(selected) if selected is not None else None,
        'plugin_dir_origin': origin, 'runtime': runtime, 'sdk': sdk,
        'checks': checks, 'errors': errors, 'warnings': warnings,
        'host_readiness': {'checked': False,
                           'reason': 'No Vectorworks connection or process inspection; an open host is not required.'},
        'modified_installation': False,
        'next_steps': [
            'Configure every MCP client and the Vectorworks bridge with the same resolved VWX_PLUGIN_DIR.',
            'Keep background mode enabled and coordinate drawing ownership with the project lease.',
            'Live readiness, native menu setup, security approval and drawing behavior require separate verification.',
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-dir', type=Path, help='Shared Vectorworks 2027 VWX-MCP folder.')
    parser.add_argument('--source-only', action='store_true', help='Check checkout and Python dependencies without inspecting an installation.')
    parser.add_argument('--json', action='store_true', help='Print structured diagnostics with no file contents or secrets.')
    args = parser.parse_args(argv)
    report = check_installation(repo=ROOT, plugin_dir=args.plugin_dir, source_only=args.source_only)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print('Landscape %s check: %s' % (report['mode'], 'PASS' if report['ok'] else 'FAIL'))
        if report['plugin_dir']:
            print('Shared VWX_PLUGIN_DIR: ' + report['plugin_dir'])
        for name, value in report['runtime'].items():
            print('%s: %s (required %s)' % (name, value['actual'] or 'not installed', value['required']))
        for issue in report['errors']:
            print('ERROR %s [%s]: %s' % (issue['code'], issue['component'], issue['message']))
        for issue in report['warnings']:
            print('LIMIT %s [%s]: %s' % (issue['code'], issue['component'], issue['message']))
        print('Host readiness was not checked. No installation or host state was changed.')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

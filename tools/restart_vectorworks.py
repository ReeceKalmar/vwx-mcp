"""Controlled Vectorworks maintenance via typed MCP, never desktop input.

The default creates a reviewable plan. --execute reserves the bridge, verifies
one saved drawing, saves once, requests normal quit once, observes actual exit,
deploys, relaunches and verifies the new session. Failed runs are never resumed.
The lease stays held on failure so uncertain work cannot silently continue.
"""
import argparse
import asyncio
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILES = ('commands.py', 'vwx_pump.py', 'BridgeStart_MenuCommand.py',
                'vs_index.json', 'vs_index_meta.json', 'sdk_catalog.json',
                'sdk_generated.py', 'sdk_runtime.py', 'sdk_sequences.py')


def normalized(path):
    return ntpath.normcase(ntpath.normpath(str(path)))


def inventory(response, expected_path, expected_pid=None):
    if (type(response) is not dict or response.get('status') != 'ok' or 'error' in response
            or type(response.get('helper_revision')) is not int or response['helper_revision'] != 1
            or type(response.get('process_id')) is not int or response['process_id'] <= 0
            or (expected_pid is not None and response['process_id'] != expected_pid)
            or type(response.get('count')) is not int or response['count'] != 1
            or type(response.get('open_documents')) is not list or len(response['open_documents']) != 1):
        raise ValueError('Maintenance requires the measured host and exactly one saved drawing')
    doc = response['open_documents'][0]
    if (type(doc) is not dict or doc.get('active') is not True or doc.get('in_memory_only') is not False
            or type(doc.get('file_ref')) is not int or type(doc.get('path')) is not str
            or normalized(doc['path']) != normalized(expected_path)):
        raise ValueError('The sole active document does not match the exact saved drawing')
    return response['process_id']


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


class Journal:
    def __init__(self, path):
        self.stream = Path(path).open('x', encoding='utf-8')

    def __call__(self, event, **values):
        json.dump(dict(event=event, utc=datetime.now(timezone.utc).isoformat(), **values),
                  self.stream, ensure_ascii=False, allow_nan=False)
        self.stream.write('\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        print(event, flush=True)

    def close(self):
        self.stream.close()


async def restart(send, host, *, document, token, journal, timeout=120, sleep=asyncio.sleep):
    """Injectable state machine. No mutation, quit, deployment or launch retries."""
    if type(timeout) not in (int, float) or not 1 <= timeout <= 600:
        raise ValueError('Timeout must be 1..600 seconds')
    held, phase, process = 'unknown', 'acquire', None
    async def call(action):
        journal('intent', action=action)
        value = await send({'action': action, 'token': token, 'expected_path': document})
        journal('response', action=action, response=value)
        return value
    def ok(value):
        if type(value) is not dict or value.get('status') != 'ok' or 'error' in value:
            raise ValueError('Maintenance operation failed: ' + str(value))
        return value
    async def wait_until(check, description):
        # Bounded polling permits progress messages and does not issue host jobs.
        for attempt in range(int(timeout * 2) + 1):
            if check():
                return
            if attempt % 30 == 0:
                journal('waiting', for_state=description)
            if attempt < int(timeout * 2):
                await sleep(.5)
        raise TimeoutError(description + ' was not confirmed; no forced recovery attempted')
    try:
        acquired = ok(await call('acquire'))
        held = True
        if acquired.get('action') != 'acquire' or acquired.get('active') is not True or acquired.get('owned') is not True:
            raise ValueError('Acquisition did not prove an active owned lease')
        pid = acquired.get('host_process_id')
        if type(pid) is not int or pid <= 0:
            raise ValueError('Lease did not identify the original Vectorworks process')
        phase = 'inventory'
        measured = inventory(await call('status'), document, pid)
        # A retained kernel handle binds all exit checks to this process instance,
        # even if Windows later reuses its PID. It also verifies the executable.
        process = host.open_process(measured)
        journal('process_bound', process_id=measured)
        phase = 'save'
        saved = ok(await call('save'))
        if (saved.get('action') != 'save' or type(saved.get('process_id')) is not int or saved['process_id'] != pid
                or saved.get('dispatched') is not True or type(saved.get('native_status')) is not int
                or saved['native_status'] != 1 or normalized(saved.get('path', '')) != normalized(document)):
            raise ValueError('Exact native save confirmation is missing')
        inventory(await call('status'), document, pid)
        phase = 'quit'
        # A quit may terminate Vectorworks before it can return an MCP result.
        # Durable intent is written first; process exit, not a response, gates deploy.
        try:
            quit_result = await call('quit')
        except Exception as error:
            journal('quit_response_unavailable', error=str(error))
            quit_result = None
        if isinstance(quit_result, dict) and quit_result.get('dispatched') is False:
            raise ValueError('Quit was refused before native dispatch')
        phase = 'exit'
        await wait_until(process.exited, 'original process exit')
        # CloseAllFilesAndQuitVectorworks leaves Chromium children briefly alive.
        await wait_until(host.all_exited, 'all Vectorworks processes exiting')
        journal('exit_confirmed', process_id=pid)
        phase = 'deploy'
        host.verify_sources()
        journal('deployment_intent')
        deployment = host.deploy()
        journal('deployment_complete', result=deployment)
        host.verify_installed()
        phase = 'launch'
        journal('launch_intent')
        launched = host.launch(document)
        journal('launch_started', process_id=launched)
        phase = 'startup'
        await wait_until(host.ready, 'fresh idle bridge heartbeat after restart')
        actual = inventory(await call('status'), document)
        if actual != launched:
            raise ValueError('The fresh bridge belongs to a different process than the launched host')
        host.verify_installed()
        phase = 'release'
        released = ok(await call('release'))
        if released.get('action') != 'release' or released.get('active') is not False or released.get('owned') is not False:
            raise ValueError('Release did not prove that maintenance ended')
        held = False
        journal('complete', process_id=actual)
        return {'status': 'passed', 'old_process_id': pid, 'new_process_id': actual,
                'lease_retained': False, 'document_path': document}
    except asyncio.CancelledError:
        journal('cancelled', phase=phase, lease_retained=held, retry_safe=False)
        raise
    except Exception as error:
        result = {'status': 'stopped', 'phase': phase, 'error': str(error), 'lease_retained': held,
                  'document_path': document, 'retry_safe': False}
        journal('stopped', **result)
        return result
    finally:
        if process is not None:
            process.close()


class WindowsProcess:
    def __init__(self, pid, executable):
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                       ctypes.POINTER(wintypes.DWORD)]
        self.handle = self.api.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            if not self.api.QueryFullProcessImageNameW(self.handle, 0, path, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            if normalized(path.value) != normalized(executable) or self.exited():
                raise ValueError('Original process is not the expected running Vectorworks executable')
        except Exception:
            self.close()
            raise

    def exited(self):
        result = self.api.WaitForSingleObject(self.handle, 0)
        if result not in (0, 258):
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class WindowsHost:
    def __init__(self, plugin_dir, executable):
        self.plugin_dir, self.executable = Path(plugin_dir), Path(executable)
        self.pairs = [(ROOT / 'vwx-plugin' / name, self.plugin_dir / name) for name in PYTHON_FILES]
        self.pairs += [(ROOT / 'native/Output/2027/Release' / name, self.plugin_dir.parent / name)
                       for name in ('VwxBridge.vlb', 'VwxBridge.vwr')]
        self.expected = {src.name: self.hash(src) for src, _ in self.pairs}
        metadata = json.loads((ROOT / 'vwx-plugin/vs_index_meta.json').read_text(encoding='utf-8'))
        if metadata.get('sdk_version') != 3200:
            raise ValueError('Only the SDK3200 build can be deployed')
        self.launched = None

    @staticmethod
    def hash(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def open_process(self, pid):
        return WindowsProcess(pid, self.executable)

    @staticmethod
    def powershell(args):
        return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', *args],
                              check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)

    def all_exited(self):
        output = self.powershell(['-Command', "@(Get-Process -Name Vectorworks2027 -ErrorAction SilentlyContinue).Count"])
        return output.stdout.strip() == '0'

    def verify_sources(self):
        if any(self.hash(src) != self.expected[src.name] for src, _ in self.pairs):
            raise ValueError('Build/source files changed after the restart plan was recorded')

    def verify_installed(self):
        if any(self.hash(dst) != self.expected[src.name] for src, dst in self.pairs):
            raise ValueError('The installed files do not match all eleven planned hashes')

    def deploy(self):
        if not self.all_exited():
            raise ValueError('Vectorworks is still running')
        self.verify_sources()
        backups = self.plugin_dir.parent.parent / 'MCP-Backups'
        backup = backups / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-maintenance')
        backup.mkdir(parents=True, exist_ok=False)
        queue = self.plugin_dir / 'ipc'
        destination = backup / 'ipc'
        # Resolve and constrain both directories before any recursive move.
        if (normalized(backup.resolve()) != normalized(backup.absolute())
                or not backup.resolve().is_relative_to(backups.resolve())):
            raise ValueError('Unexpected backup directory resolution')
        if queue.exists():
            if (normalized(queue.resolve()) != normalized(queue.absolute())
                    or not queue.resolve().is_relative_to(self.plugin_dir.resolve())
                    or not destination.resolve().is_relative_to(backup.resolve())):
                raise ValueError('Unexpected IPC archive path')
            queue.rename(destination)
        for source, installed in self.pairs:
            if installed.exists():
                shutil.copy2(installed, backup / installed.name)
            shutil.copy2(source, installed)
            if self.hash(installed) != self.expected[source.name]:
                raise ValueError('Deployment hash mismatch: ' + str(installed))
        (queue / 'jobs').mkdir(parents=True, exist_ok=False)
        (queue / 'results').mkdir(exist_ok=False)
        self.verify_sources()
        self.verify_installed()
        return {'backup': str(backup), 'installed_sha256': dict(self.expected)}

    def launch(self, document):
        if not self.all_exited():
            raise ValueError('A Vectorworks process appeared before launch')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        self.launched = subprocess.Popen([str(self.executable), document], cwd=self.executable.parent,
                                         startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW)
        return self.launched.pid

    def ready(self):
        from run_sdk_regression_batch import bridge_readiness
        if self.launched is None or self.launched.poll() is not None:
            raise ValueError('The newly launched process exited during startup')
        state = bridge_readiness(self.plugin_dir)
        return state.get('ready') is True and state['scheduler']['process_id'] == self.launched.pid

    def quiescent(self):
        # Use the acquisition gate's exact stamp/counter checks. A weak heartbeat
        # can still show the previous idle tick just after a result is returned.
        import importlib.util
        spec = importlib.util.spec_from_file_location('restart_lease_readiness', ROOT / 'mcp-server/maintenance.py')
        lease = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lease)
        try:
            lease._readiness(self.plugin_dir)
            return True
        except lease.MaintenanceError:
            return False


async def execute(args, host, token, journal):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    env = dict(os.environ, VWX_PLUGIN_DIR=str(args.plugin_dir), VWX_TRANSPORT='file',
               VWX_VW_VERSION='2027', VWX_BACKGROUND_MODE='1', VWX_SDK_TOOLS='0',
               VWX_CACHE_TTL='0', VWX_SOCKET_TIMEOUT='25', VWX_ALIVE_GRACE='5')
    transport = StdioTransport(sys.executable, [str(ROOT / 'mcp-server/vwx_mcp_server.py')],
                               env=env, cwd=str(ROOT))
    async with Client(transport, init_timeout=60, timeout=35) as client:
        async def send(params):
            result = await client.call_tool('bridge_maintenance', params)
            return json.loads(result.content[0].text)
        for _ in range(20):
            if host.quiescent():
                break
            await asyncio.sleep(.25)
        return await restart(send, host, document=str(args.document), token=token, journal=journal,
                             timeout=args.timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document', type=Path, required=True)
    parser.add_argument('--plugin-dir', type=Path, required=True)
    parser.add_argument('--executable', type=Path, default=Path('C:/Program Files/Vectorworks 2027/Vectorworks2027.exe'))
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt' or not 1 <= args.timeout <= 600:
        parser.error('Requires Windows and timeout1..600')
    args.document = args.document.resolve(strict=True)
    args.plugin_dir = args.plugin_dir.resolve(strict=True)
    args.executable = args.executable.resolve(strict=True)
    default_plugin = Path(os.environ['APPDATA']) / 'Nemetschek/Vectorworks/2027/Plug-ins/VWX-MCP'
    if normalized(args.plugin_dir) != normalized(default_plugin):
        parser.error('The deployment script targets the default 2027 VWX-MCP installation only')
    if args.document.suffix.lower() != '.vwx' or args.executable.name.lower() != 'vectorworks2027.exe':
        parser.error('An existing ordinary .vwx drawing and Vectorworks2027.exe are required')
    host = WindowsHost(args.plugin_dir, args.executable)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    token = secrets.token_hex(32)
    write_new(args.output_dir / 'plan.json', dict(document=str(args.document), plugin_dir=str(args.plugin_dir),
              executable=str(args.executable), source_sha256=host.expected, execute=args.execute))
    if not args.execute:
        print('Planned only; no Vectorworks actions performed.')
        return 0
    # Local recovery credential: excluded from console and response journals.
    write_new(args.output_dir / 'lease-token.json', {'token': token})
    journal = Journal(args.output_dir / 'journal.jsonl')
    try:
        result = asyncio.run(execute(args, host, token, journal))
        write_new(args.output_dir / 'result.json', result)
        return 0 if result['status'] == 'passed' else 2
    finally:
        journal.close()


if __name__ == '__main__':
    raise SystemExit(main())

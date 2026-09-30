#!/usr/bin/env python3
"""Vectorworks 2027 file IPC: one job per Python menu-command invocation.

All reads and writes use VW's script-plugin runner. Notification callbacks
never execute Python. Returning after each job allows deferred PIO resets to
complete before a later inspection job. This is not a crash-safety guarantee:
invalid handles, API calls and third-party plug-ins can still fail natively.
Claimed jobs are never retried automatically, including after a host crash.
"""
import os, sys, json, time, traceback

def _vw_roots():
    """Only the target major version; never choose another installed host."""
    if os.environ.get('VWX_VW_VERSION', '2027') != '2027':
        raise RuntimeError('This bridge requires Vectorworks 2027')
    return [os.path.join(os.environ.get('APPDATA', ''), 'Nemetschek',
                         'Vectorworks', '2027', 'Plug-ins')]


try:
    _DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:                      # VW runs scripts as <string>
    _DIR = os.environ.get('VWX_PLUGIN_DIR') or None
    if _DIR:
        _DIR = os.path.abspath(_DIR)
        if not all(os.path.isfile(os.path.join(_DIR, name))
                   for name in ('vwx_pump.py', 'commands.py')):
            raise RuntimeError('VWX_PLUGIN_DIR is not a complete bridge installation: ' + _DIR)
    else:
        for _base in _vw_roots():
            for _name in ('VWX-MCP', 'VW-MCP'):
                _cand = os.path.join(_base, _name)
                if all(os.path.isfile(os.path.join(_cand, name))
                       for name in ('vwx_pump.py', 'commands.py')):
                    _DIR = _cand
                    break
            if _DIR:
                break
    if _DIR is None:
        raise RuntimeError('The 2027 bridge Python files are not installed')
if _DIR in sys.path:
    sys.path.remove(_DIR)
sys.path.insert(0, _DIR)

_IPC     = os.path.join(_DIR, 'ipc')
_JOBS    = os.path.join(_IPC, 'jobs')
_RESULTS = os.path.join(_IPC, 'results')
_STAMP   = os.path.join(_IPC, 'pump.stamp')
_LOG     = os.path.join(_DIR, 'bridge.log')

# Shared pure validation, loaded from this installation without importing vs.
import importlib.util
_project_spec = importlib.util.spec_from_file_location(
    'pump_project_guard', os.path.join(_DIR, 'project_guard.py'))
_project_guard = importlib.util.module_from_spec(_project_spec)
_project_spec.loader.exec_module(_project_guard)

RESULT_TTL = 3600.0          # orphaned result files are removed after this

# Marionette executions may tear down THIS Python context on frame return:
# their ack is written BEFORE dispatch.
_FIRE_AND_FORGET = frozenset({'marionette_recalc'})


def _log(msg):
    try:
        with open(_LOG, 'a', encoding='utf-8') as f:
            f.write("[%s] pump: %s\n" % (time.strftime('%H:%M:%S'), msg))
    except Exception:
        pass


def _write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)      # atomic: the reader never sees a partial file


def _get_commands():
    """Import commands.py once; reload ONLY when the file changed on disk.
    The old code reloaded the ~2500-line module on EVERY dispatch — tens of ms
    per call, seconds across a sweep. The mtime marker lives on the commands
    module object (persists in sys.modules across vwx_pump reloads), so warm
    calls are near-free yet an edited/redeployed commands.py hot-reloads at
    once."""
    import importlib, commands
    loaded_dir = os.path.normcase(os.path.dirname(os.path.abspath(commands.__file__)))
    if loaded_dir != os.path.normcase(os.path.abspath(_DIR)):
        raise RuntimeError('A different commands module is already loaded; restart Vectorworks')
    try:
        mt = os.path.getmtime(os.path.join(_DIR, 'commands.py'))
    except Exception:
        mt = 0.0
    if getattr(commands, '_vwx_loaded_mtime', None) != mt:
        importlib.reload(commands)
        commands._vwx_loaded_mtime = mt
    return commands

def _dispatch(cmd, params):
    try:
        commands = _get_commands()
        cmd, params = _project_guard.host_operation(
            _DIR, cmd, params, process_id=os.getpid(),
            get_active_path=lambda: commands.vs.GetFPathName())
        fn = getattr(commands, cmd, None)
        if fn is None:
            return {'error': 'Unknown command: %s' % cmd}
        return fn(params)
    except _project_guard.ProjectError as e:
        return e.response()
    except Exception as e:
        return {'error': str(e), 'traceback': traceback.format_exc()}


def _list_jobs():
    try:
        return sorted(fn for fn in os.listdir(_JOBS) if fn.endswith('.json'))
    except Exception:
        return []


def _claim_and_run(fn):
    src  = os.path.join(_JOBS, fn)
    work = src + '.working'
    try:
        os.replace(src, work)           # atomic claim
    except Exception:
        return False                    # another invocation grabbed it
    try:
        with open(work, 'r', encoding='utf-8') as f:
            msg = json.load(f)
    except Exception as e:
        _log("bad job %s: %s" % (fn, e))
        try: os.remove(work)
        except Exception: pass
        return False
    try: os.remove(work)                # claim consumed; a crash loses the job
    except Exception: pass              # (visible timeout) instead of re-running
    cid    = str(msg.get('_cid', fn))
    cmd    = msg.get('type', '')
    params = msg.get('params', {}) or {}
    rpath  = os.path.join(_RESULTS, cid + '.json')
    _log('START cid=%s cmd=%s' % (cid, cmd))
    try:
        early_ack = (cmd in _FIRE_AND_FORGET and not params.get('_sync')
                     and _project_guard.read_lease(_DIR) is None)
    except _project_guard.ProjectError as error:
        # An unreadable lease must not become an early success acknowledgment.
        _write_json(rpath, error.response())
        return True
    if early_ack:
        _write_json(rpath, {'status': 'triggered',
                            'note': 'Marionette execution — ack before dispatch.'})
        _log("fire-and-forget cid=%s cmd=%s" % (cid, cmd))
        _dispatch(cmd, params)
        return True
    t0 = time.time()
    result = _dispatch(cmd, params)
    try:
        _write_json(rpath, result)
    except Exception as e:
        _write_json(rpath, {'error': 'result not serializable: %s' % e})
    _log("cid=%s cmd=%s ms=%d %s"
         % (cid, cmd, (time.time() - t0) * 1000,
            'ERR' if isinstance(result, dict) and result.get('error') else 'ok'))
    return True


SWEEP_EVERY = 60.0           # how often the TTL sweep is allowed to run
_last_sweep = 0.0
_dirs_ready = False


def _housekeep():
    """Cheap per-drain work only. The expensive sweep runs on a timer.

    This used to stat every file in the results directory on EVERY pump call —
    an O(n) scan paying full price on each trigger cycle even though the TTL
    cleanup only needs to happen rarely. On a long session with orphaned
    results that scan grew without bound and was charged to the latency of
    every single tool call.
    """
    global _last_sweep, _dirs_ready
    if not _dirs_ready:
        for d in (_JOBS, _RESULTS):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass
        _dirs_ready = True
    try:
        with open(_STAMP, 'w') as f:
            f.write(str(time.time()))
    except Exception:
        pass
    now = time.time()
    if now - _last_sweep < SWEEP_EVERY:
        return
    _last_sweep = now
    try:
        for fn in os.listdir(_RESULTS):
            p = os.path.join(_RESULTS, fn)
            if now - os.path.getmtime(p) > RESULT_TTL:
                os.remove(p)
    except Exception:
        pass


def pump_readonly():
    """Compatibility no-op: notification contexts must not run VW jobs."""
    return 0


_pumping = False


def _mark_menu_complete():
    """Acknowledge an outer menu invocation after its reentry guard is reset.

    The native scheduler uses this separate stamp instead of pump.stamp (entry)
    so a nested host message loop cannot schedule another job mid-execution.
    Completion does not imply success; the job result remains authoritative.
    """
    try:
        _write_json(os.path.join(_IPC, 'pump.complete.stamp'),
                    {'schema_version': 1, 'completed_ns': time.time_ns()})
    except Exception as error:
        # Never replace a job's result or original exception with telemetry I/O.
        _log('could not write menu completion stamp: %s' % error)


def pump_all():
    """Run at most ONE job from VW's Python menu-command runner, then return."""
    global _pumping
    if _pumping:
        return 0
    _pumping = True
    try:
        _housekeep()
        for fn in _list_jobs():
            if _claim_and_run(fn):
                return 1
        return 0
    finally:
        _pumping = False
        _mark_menu_complete()

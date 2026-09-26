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
    _DIR = None
    for _base in _vw_roots():
        for _name in ('VW-MCP', 'VWX-MCP'):
            _cand = os.path.join(_base, _name)
            if os.path.isdir(_cand):
                _DIR = _cand
                break
        if _DIR:
            break
    if _DIR is None:
        _roots = _vw_roots()
        _DIR = os.path.join(_roots[0] if _roots else '', 'VW-MCP')
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

_IPC     = os.path.join(_DIR, 'ipc')
_JOBS    = os.path.join(_IPC, 'jobs')
_RESULTS = os.path.join(_IPC, 'results')
_STAMP   = os.path.join(_IPC, 'pump.stamp')
_LOG     = os.path.join(_DIR, 'bridge.log')

RESULT_TTL = 3600.0          # orphaned result files are removed after this

# Read-only commands: safe in ANY context (no document mutation, no dialog).
# A job is read-only if its command is in this set OR starts with one of the
# read-only prefixes. Everything else is treated as a mutation and waits for
# genuine dispatch.
_RO_NAMES = frozenset({
    'ping', 'distance', 'distance_3d', 'polygon_centroid',
    'get_document_info', 'get_document_preferences', 'get_georeferencing',
})
_RO_PREFIXES = ('get_', 'list_', 'count_', 'find_')

# Marionette executions may tear down THIS Python context on frame return:
# their ack is written BEFORE dispatch.
_FIRE_AND_FORGET = frozenset({'marionette_recalc'})


def _log(msg):
    try:
        with open(_LOG, 'a', encoding='utf-8') as f:
            f.write("[%s] pump: %s\n" % (time.strftime('%H:%M:%S'), msg))
    except Exception:
        pass


_MANIFEST = os.path.join(_IPC, 'readonly.json')
_manifest_names = None
_manifest_mtime = None


def _readonly_manifest():
    """Read-only command names as classified by the MCP server, if it said.

    The prefix rule below is a convention with nothing enforcing it: a command
    named get_or_create_layer would mutate the document from the OnIdle
    notification context, which is verified to crash Vectorworks. The server
    knows the real classification (it annotates every tool with readOnlyHint)
    and writes it here at startup, so the two sides stop guessing separately.
    Absent or unreadable manifest falls back to the prefixes — the pump must
    keep working when only the plugin has been redeployed.
    """
    global _manifest_names, _manifest_mtime
    try:
        mt = os.path.getmtime(_MANIFEST)
    except Exception:
        return None
    if mt != _manifest_mtime:
        try:
            with open(_MANIFEST, 'r', encoding='utf-8') as f:
                _manifest_names = frozenset(json.load(f))
            _manifest_mtime = mt
            _log("readonly manifest: %d names" % len(_manifest_names))
        except Exception as e:
            _log("readonly manifest unreadable (%s) — using prefixes" % e)
            return None
    return _manifest_names


def _is_readonly(cmd):
    names = _readonly_manifest()
    if names is not None:
        return cmd in names
    return cmd in _RO_NAMES or cmd.startswith(_RO_PREFIXES)


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
        fn = getattr(commands, cmd, None)
        if fn is None:
            return {'error': 'Unknown command: %s' % cmd}
        return fn(params)
    except Exception as e:
        return {'error': str(e), 'traceback': traceback.format_exc()}


def _list_jobs():
    try:
        return sorted(fn for fn in os.listdir(_JOBS) if fn.endswith('.json'))
    except Exception:
        return []


_peek_cache = {}


def _peek_cmd(fn):
    """Read a job's command name WITHOUT claiming it.

    Cached by filename. Job files are written once under a unique
    <timestamp>-<cid> name and never rewritten, so the answer cannot go stale.
    Without the cache the read-only drain re-read every queued mutation job
    from disk on every OnIdle notification — many times a second while a write
    waits for the accelerator hop.
    """
    hit = _peek_cache.get(fn)
    if hit is not None:
        return hit
    try:
        with open(os.path.join(_JOBS, fn), 'r', encoding='utf-8') as f:
            cmd = json.load(f).get('type', '')
    except Exception:
        return None
    if len(_peek_cache) > 512:          # bounded: a stuck queue must not grow it forever
        _peek_cache.clear()
    _peek_cache[fn] = cmd
    return cmd


def _claim_and_run(fn):
    src  = os.path.join(_JOBS, fn)
    work = src + '.working'
    _peek_cache.pop(fn, None)
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
    if cmd in _FIRE_AND_FORGET and not params.get('_sync'):
        _write_json(rpath, {'status': 'triggered',
                            'note': 'Marionette execution — ack before dispatch.'})
        _log("fire-and-forget cid=%s cmd=%s" % (cid, cmd))
        _dispatch(cmd, params)
        return True
    t0 = time.time()
    _log('START cid=%s cmd=%s' % (cid, cmd))
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

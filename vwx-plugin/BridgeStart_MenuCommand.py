# This file runs ONLY as a Vectorworks Python menu command (Ctrl+Shift+B).
# One invocation executes one queued job and returns to the host event loop.
import os
import sys
import importlib
import vs

_year = str(vs.GetVersion()[0] + 1995)
if _year != '2027':
    raise RuntimeError('This bridge requires Vectorworks 2027; host is ' + _year)
if os.environ.get('VWX_VW_VERSION', _year) != _year:
    raise RuntimeError('VWX_VW_VERSION does not match the running Vectorworks')

def _installed(path):
    return all(os.path.isfile(os.path.join(path, name))
               for name in ('vwx_pump.py', 'commands.py'))


_dir = os.environ.get('VWX_PLUGIN_DIR')
if _dir:
    _dir = os.path.abspath(_dir)
    if not _installed(_dir):
        raise RuntimeError('VWX_PLUGIN_DIR is not a complete bridge installation: ' + _dir)
else:
    _base = os.path.join(os.environ['APPDATA'], 'Nemetschek', 'Vectorworks',
                         _year, 'Plug-ins')
    _dir = next((os.path.join(_base, n) for n in ('VWX-MCP', 'VW-MCP')
                 if _installed(os.path.join(_base, n))), None)
if _dir is None:
    raise RuntimeError('The 2027 bridge Python files are not installed')
if _dir in sys.path:
    sys.path.remove(_dir)
sys.path.insert(0, _dir)

import vwx_pump
if os.path.normcase(os.path.dirname(os.path.abspath(vwx_pump.__file__))) != os.path.normcase(_dir):
    raise RuntimeError('A different bridge is already loaded; restart Vectorworks')
_mt = os.path.getmtime(os.path.join(_dir, 'vwx_pump.py'))
# Do not reset the pump's reentry guard by reloading during a nested invocation.
if not getattr(vwx_pump, '_pumping', False) and getattr(vwx_pump, '_vwx_loaded_mtime', None) != _mt:
    importlib.reload(vwx_pump)
    vwx_pump._vwx_loaded_mtime = _mt
vwx_pump.pump_all()

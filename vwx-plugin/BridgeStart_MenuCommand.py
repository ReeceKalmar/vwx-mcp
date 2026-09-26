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

_base = os.path.join(os.environ['APPDATA'], 'Nemetschek', 'Vectorworks',
                     _year, 'Plug-ins')
_dir = next((os.path.join(_base, n) for n in ('VWX-MCP', 'VW-MCP')
             if os.path.isfile(os.path.join(_base, n, 'vwx_pump.py'))), None)
if _dir is None:
    raise RuntimeError('The 2027 bridge Python files are not installed')
if _dir not in sys.path:
    sys.path.insert(0, _dir)

import vwx_pump
if os.path.normcase(os.path.dirname(os.path.abspath(vwx_pump.__file__))) != os.path.normcase(_dir):
    raise RuntimeError('A different bridge is already loaded; restart Vectorworks')
_mt = os.path.getmtime(os.path.join(_dir, 'vwx_pump.py'))
if getattr(vwx_pump, '_vwx_loaded_mtime', None) != _mt:
    importlib.reload(vwx_pump)
    vwx_pump._vwx_loaded_mtime = _mt
vwx_pump.pump_all()

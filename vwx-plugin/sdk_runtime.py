"""JSON transport adapter for the generated Vectorworks 2027 SDK calls.

This module validates transport contracts, not the geometry or host semantics of
all SDK functions. It runs only within the existing Python menu-command job.
Document HANDLE values cross the transport as UUIDs. Native pointers, transient
handles and asynchronous callbacks are deliberately not converted to strings.
"""
import importlib
import json
import math
from pathlib import Path
import uuid


SDK_VERSION = 3200
VECTORWORKS_YEAR = 2027
_CATALOG = None
_CATALOG_MTIME = None

# VectorScript INTEGER and LONGINT are signed 16- and 32-bit values. Text style
# flags are the SDK's kTextStylePlain/Bold/Italic/Underline/Outline/Shadow bits.
_INTEGER_RANGES = {'INTEGER': (-32768, 32767),
                   'LONGINT': (-2147483648, 2147483647), 'TEXTSTYLE': (0, 31)}
_STRINGS = {'STRING', 'DYNARRAY[] OF CHAR', 'DYNARRAY OF CHAR', 'CRITERIA'}
_POINTS = {'POINT': 2, 'POINT3D': 3, 'VECTOR': 3}
_NULLABLE_HANDLES = {('BeginGroupN', 'groupHandle')}
_STRING_ARRAYS = {('SetObjectTags', 'arrTags'), ('SetResourceTags', 'tags'),
                  ('PopupSetChoices', 'popUpValues')}
# SetResourceTags references SetObjectTags's documented Python tuple ABI.
# Keep JSON arrays at the transport boundary; convert only these native inputs.
_TUPLE_ARRAYS = {('SetObjectTags', 'arrTags'), ('SetResourceTags', 'tags')}
_DIALOG_OPTION_ARRAYS = {'AlertInformDontShowAgain', 'AlertInformHLinkN',
                        'AlertQuestionDontShowAgain'}
_CALLBACKS = {
    # These callback conventions are explicit in the shipped vs.py docstrings.
    'ForEachObject': ('callback', None, None),
    'ForEachObjectInLayer': ('actionFunc', False, True),
    'ForEachObjectAtPoint': ('actionFunc', True, False),
    'ForEachMaterial': ('callback', None, None),
    'ForEachObjectInList': ('actionFunc', False, True),
}
_DIALOG_CALLBACKS = {'RunLayoutDialog', 'RunLayoutDialogN', 'RunNamedDialog', 'RunNamedDialogN'}
_SPECIAL_CALLBACKS = {name: 'callback' for name in _DIALOG_CALLBACKS | {
    'TrackObject', 'TrackObjectN', 'ImportResToCurFileN'}}
_QUARANTINED = {'Layer', 'CombineIntoSurface'}
_UPRSTRING_COMPATIBILITY = {
    'native_function': 'UprString', 'replacement_function': 'python.str.upper',
    'reason': 'native_uncertain_outcome', 'scope': 'ASCII only',
    'source': 'https://github.com/Vectorworks/developer-scripting/blob/main/Function%20Reference/Functions/UprString.md',
    'note': 'The host exited after an UprString job was claimed; causation is unproven. The native call is not retried.',
}


class SDKError(ValueError):
    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details


class _HandleRef:
    def __init__(self, value):
        self.value = value


def load_catalog():
    """Read the deployed SDK catalog; reload it only after its file changes."""
    global _CATALOG, _CATALOG_MTIME
    path = Path(__file__).with_name('sdk_catalog.json')
    stamp = path.stat().st_mtime_ns
    if _CATALOG is None or _CATALOG_MTIME != stamp:
        with path.open(encoding='utf-8') as stream:
            candidate = json.load(stream)
        _check_catalog(candidate)
        _CATALOG, _CATALOG_MTIME = candidate, stamp
    return _CATALOG


def _check_catalog(catalog):
    if not isinstance(catalog, dict) or catalog.get('schema_version') != 1:
        raise SDKError('SDK_VERSION', 'Unsupported SDK catalog schema')
    if catalog.get('sdk_version') != SDK_VERSION or catalog.get('vectorworks_year') != VECTORWORKS_YEAR:
        raise SDKError('SDK_VERSION', 'This adapter requires the Vectorworks 2027 SDK 3200 catalog')
    if not isinstance(catalog.get('functions'), dict):
        raise SDKError('SDK_VERSION', 'SDK catalog has no function definitions')


def _type_name(value):
    return ' '.join(str(value).replace('in/out ', '').upper().split())


def _integer(value, minimum, maximum, label, code='SDK_TYPE'):
    if type(value) is not int:
        raise SDKError(code, label + ' must be an integer (booleans are not integers)')
    if not minimum <= value <= maximum:
        raise SDKError('SDK_RANGE' if code == 'SDK_TYPE' else code,
                       '%s must be between %d and %d' % (label, minimum, maximum))
    return value


def _number(value, label, code='SDK_TYPE'):
    if type(value) not in (int, float):
        raise SDKError(code, label + ' must be a finite number (booleans are not numbers)')
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise SDKError(code, label + ' must be a finite number')
    if not math.isfinite(number):
        raise SDKError('SDK_RANGE' if code == 'SDK_TYPE' else code, label + ' must be finite')
    return number


def _json_value(value, label, code, seen=None):
    """Copy finite JSON data; never stringify a native or arbitrary Python value."""
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is float:
        return _number(value, label, code)
    if type(value) not in (list, tuple, dict):
        raise SDKError(code, label + ' contains an opaque native or non-JSON value')
    seen = set() if seen is None else seen
    identity = id(value)
    if identity in seen:
        raise SDKError(code, label + ' contains a cyclic value')
    seen.add(identity)
    try:
        if isinstance(value, dict):
            if any(type(key) is not str for key in value):
                raise SDKError(code, label + ' requires string JSON object keys')
            return {key: _json_value(item, label + '.' + key, code, seen)
                    for key, item in value.items()}
        return [_json_value(item, '%s[%d]' % (label, index), code, seen)
                for index, item in enumerate(value)]
    finally:
        seen.remove(identity)


def _uuid(value, label, code):
    if type(value) is not str:
        raise SDKError(code, label + ' must be an object UUID string')
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise SDKError(code, label + ' must be a valid object UUID string')
    if parsed.int == 0:
        raise SDKError(code, label + ' must not be the nil UUID')
    return str(parsed)


def _input(value, parameter, function):
    label = parameter['name']
    typename = _type_name(parameter.get('type', 'UNKNOWN'))
    if typename == 'HANDLE':
        if value is None and ((function, label) in _NULLABLE_HANDLES or parameter.get('nullable') is True):
            return _HandleRef(None)
        return _HandleRef(_uuid(value, label, 'SDK_HANDLE'))
    if typename == 'BOOLEAN':
        if type(value) is not bool:
            raise SDKError('SDK_TYPE', label + ' must be a boolean')
        return value
    if typename in _INTEGER_RANGES:
        return _integer(value, *_INTEGER_RANGES[typename], label)
    if typename.startswith('REAL'):
        return _number(value, label)
    if typename in _STRINGS or typename == 'CHAR':
        if type(value) is not str:
            raise SDKError('SDK_TYPE', label + ' must be a string')
        if typename == 'CHAR' and len(value) != 1:
            raise SDKError('SDK_RANGE', label + ' must contain exactly one character')
        return value
    if typename in _POINTS or typename in ('COLOR', 'RGBCOLOR'):
        size = _POINTS.get(typename, 3)
        if type(value) not in (list, tuple) or len(value) != size:
            raise SDKError('SDK_TYPE', '%s must contain exactly %d components' % (label, size))
        if typename in ('COLOR', 'RGBCOLOR'):
            return tuple(_integer(part, 0, 65535, label + ' color component') for part in value)
        return tuple(_number(part, label + ' coordinate') for part in value)
    if typename == 'ARRAY':
        if type(value) not in (list, tuple):
            raise SDKError('SDK_TYPE', label + ' must be a JSON array')
        if (function, label) in _STRING_ARRAYS or function in _DIALOG_OPTION_ARRAYS:
            if any(type(item) is not str for item in value):
                raise SDKError('SDK_TYPE', label + ' must contain strings')
        if function in _DIALOG_OPTION_ARRAYS and len(value) != 3:
            raise SDKError('SDK_RANGE', label + ' must contain exactly three option strings')
        copied = _json_value(value, label, 'SDK_TYPE')
        return tuple(copied) if (function, label) in _TUPLE_ARRAYS else copied
    if typename == 'ANY':
        if any(token in label.lower() for token in ('ptr', 'pointer', 'cstr')):
            raise SDKError('SDK_UNSUPPORTED', label + ' is a native pointer, not a transportable JSON value')
        return _json_value(value, label, 'SDK_TYPE')
    if typename == 'PROCEDURE':
        if function in _SPECIAL_CALLBACKS and _SPECIAL_CALLBACKS[function] == label:
            return _callback_descriptor(value, function, label)
        spec = _CALLBACKS.get(function)
        if spec is None or spec[0] != label:
            raise SDKError('SDK_UNSUPPORTED', function + '.' + label +
                           ' requires a host callback or native pointer with no supported JSON descriptor')
        if type(value) is not dict or set(value) - {'mode', 'limit'} or value.get('mode') != 'collect':
            raise SDKError('SDK_TYPE', label + ' requires {"mode":"collect","limit":positive integer}')
        return {'mode': 'collect', 'limit': _integer(value.get('limit', 500), 1, 100000, label + '.limit')}
    raise SDKError('SDK_UNSUPPORTED', 'Unsupported SDK parameter type: ' + typename)


def _callback_descriptor(value, function, label):
    if type(value) is not dict:
        raise SDKError('SDK_TYPE', label + ' must be a supported callback descriptor')
    limit = _integer(value.get('limit', 500), 1, 100000, label + '.limit')
    if function in _DIALOG_CALLBACKS:
        if set(value) - {'mode', 'limit', 'events'} or value.get('mode') != 'dialog':
            raise SDKError('SDK_TYPE', label + ' requires mode=dialog, optional limit and events')
        events = value.get('events', {})
        if type(events) is not dict or len(events) > 100:
            raise SDKError('SDK_TYPE', label + '.events must map at most 100 event IDs to SDK calls')
        for event, calls in events.items():
            if type(event) is not str or not event.lstrip('-').isdigit() or str(int(event)) != event:
                raise SDKError('SDK_TYPE', 'Dialog event keys must be canonical integer strings')
            _integer(int(event), -2147483648, 2147483647, 'event ID')
            if type(calls) is not list or len(calls) > 100:
                raise SDKError('SDK_RANGE', 'Each dialog event accepts at most 100 SDK calls')
        return {'mode': 'dialog', 'limit': limit, 'events': _json_value(events, label, 'SDK_TYPE')}
    if function == 'ImportResToCurFileN':
        if set(value) - {'mode', 'action', 'limit'} or value.get('mode') != 'conflict' or value.get('action') not in ('skip', 'replace'):
            raise SDKError('SDK_TYPE', label + ' requires mode=conflict and action=skip or replace; rename VAR ABI is unsupported')
        return {'mode': 'conflict', 'action': value['action'], 'limit': limit}
    if set(value) - {'mode', 'object_types', 'limit'} or value.get('mode') != 'filter':
        raise SDKError('SDK_TYPE', label + ' requires mode=filter and object_types')
    kinds = value.get('object_types')
    if type(kinds) is not list or not kinds or len(kinds) > 256:
        raise SDKError('SDK_TYPE', 'object_types must contain between 1 and 256 object type numbers')
    return {'mode': 'filter', 'limit': limit,
            'object_types': [_integer(kind, 1, 32767, 'object type') for kind in kinds]}


def _host_version(vs_module):
    try:
        version = vs_module.GetVersion()
    except Exception as error:
        raise SDKError('SDK_VERSION', 'Cannot verify running Vectorworks version: ' + str(error))
    if type(version) not in (list, tuple) or not version or type(version[0]) is not int or version[0] != 32:
        raise SDKError('SDK_VERSION', 'Generated SDK calls require a running Vectorworks 2027 host')


def _windows_build(vs_module, build):
    """Only measured, complete host identity enables build-specific repairs."""
    getter = getattr(vs_module, 'GetVersionEx', None)
    if not hasattr(getter, '__call__'):
        return False
    version = getter()
    return (type(version) in (tuple, list) and len(version) == 5
            and all(type(item) is int for item in version)
            and tuple(version) == (32, 0, 0, 2, build))


def _gradient_opacity_writer(vs_module, converted):
    """Prepare a measured native-binding replacement without changing anything.

    The dedicated setter on build 882075 changed a stop's position instead of
    its opacity. A separate 79-job native fixture verified SetGradientDataN
    with every other field preserved. Never invoke the broken setter first.
    The returned closure performs one write; any later mismatch is a dispatched
    error, with no retry, rollback or invented successful result.
    """
    gradient, index, opacity = converted
    if not 0 <= opacity <= 100:
        raise SDKError('SDK_ARGUMENT', 'Gradient opacity must be between 0 and 100')
    kind = vs_module.GetTypeN(gradient)
    if type(kind) is not int or kind != 120:
        raise SDKError('SDK_HANDLE', 'Gradient opacity requires a gradient resource')
    helpers = {}
    for name in ('GetNumGradientSegments', 'GetGradientDataN', 'GetGradientOpacity', 'SetGradientDataN'):
        helper = getattr(vs_module, name, None)
        if not hasattr(helper, '__call__'):
            raise SDKError('SDK_UNSUPPORTED', 'Gradient opacity replacement requires ' + name)
        helpers[name] = helper
    count = helpers['GetNumGradientSegments'](gradient)
    if type(count) is not int or not 2 <= count <= 32767:
        raise SDKError('SDK_RESULT', 'Invalid gradient segment count')
    if not 1 <= index <= count:
        raise SDKError('SDK_ARGUMENT', 'Gradient segment index is out of bounds')
    identifier = _uuid(vs_module.GetObjectUuid(gradient), 'gradient verification', 'SDK_HANDLE')

    def read_data():
        data = helpers['GetGradientDataN'](gradient, index)
        if (type(data) not in (tuple, list) or len(data) != 6
                or any(type(value) not in (int, float) or not 0 <= value <= 1
                       or not math.isfinite(value) for value in data[:2])
                or any(type(value) is not int or not 0 <= value <= 255 for value in data[2:5])
                or type(data[5]) is not int or not 0 <= data[5] <= 100):
            raise SDKError('SDK_RESULT', 'Invalid gradient data for opacity replacement')
        independently_read = helpers['GetGradientOpacity'](gradient, index)
        if type(independently_read) is not int or independently_read != data[5]:
            raise SDKError('SDK_RESULT', 'Independent gradient opacity getters disagree')
        return tuple(data)

    original = read_data()

    def write(*arguments):
        result = helpers['SetGradientDataN'](gradient, index, *original[:5], opacity)
        if type(result) is not int or result != index:
            raise SDKError('SDK_RESULT', 'Gradient opacity replacement changed the segment index')
        after_kind = vs_module.GetTypeN(gradient)
        after_count = helpers['GetNumGradientSegments'](gradient) if type(after_kind) is int and after_kind == 120 else None
        if (type(after_count) is not int or after_count != count
                or _uuid(vs_module.GetObjectUuid(gradient), 'gradient identity', 'SDK_RESULT') != identifier):
            raise SDKError('SDK_RESULT', 'Gradient opacity replacement did not preserve the resource')
        if read_data() != original[:5] + (opacity,):
            raise SDKError('SDK_RESULT', 'Gradient opacity replacement failed its independent readback')
        return None

    return write, {'native_function': 'SetGradientOpacity', 'replacement_function': 'SetGradientDataN',
                   'reason': 'native_setter_changes_spot_position', 'host_build': 882075,
                   'native_dispatched': False, 'preserved_fields_verified_on_success': True}


def _arc_angle_writer(vs_module, converted):
    """Use the guarded SDK extension for the measured Python SetArc no-op.

    The helper changes the existing arc through GS_SetArcAnglesN. Its status
    only acknowledges dispatch; angle and identity readbacks remain necessary.
    Geometry is verified separately by retained arc/NURBS fixture controls.
    """
    handle, start, sweep = converted
    kind = vs_module.GetTypeN(handle)
    if type(kind) is not int or kind != 6:
        raise SDKError('SDK_HANDLE', 'Arc angles require an arc object')
    revision = getattr(vs_module, 'VWXBridgeRevision', None)
    setter = getattr(vs_module, 'VWXBridgeSetArc', None)
    getter = getattr(vs_module, 'GetArc', None)
    if not all(hasattr(helper, '__call__') for helper in (revision, setter, getter)):
        raise SDKError('SDK_UNSUPPORTED', 'SetArc requires the native VwxBridge arc helper loaded in Vectorworks')
    abi = revision()
    if type(abi) is not int or abi != 1:
        raise SDKError('SDK_UNSUPPORTED', 'Unsupported native VwxBridge arc helper revision')
    identifier = _uuid(vs_module.GetObjectUuid(handle), 'arc verification', 'SDK_HANDLE')
    compatibility = {'native_function': 'SetArc', 'replacement_function': 'VWXBridgeSetArc',
                     'reason': 'python_setarc_binding_noop', 'host_build': 882075,
                     'native_dispatched': False, 'helper_revision': abi}

    def write(*arguments):
        status = setter(handle, float(start), float(sweep))
        if type(status) is not int or status != 1:
            raise SDKError('SDK_RESULT', 'Native arc helper did not acknowledge a completed SDK call',
                           details={'helper_status': status} if type(status) in (int, bool) else None)
        after_kind = vs_module.GetTypeN(handle)
        if (type(after_kind) is not int or after_kind != 6
                or _uuid(vs_module.GetObjectUuid(handle), 'arc identity', 'SDK_RESULT') != identifier):
            raise SDKError('SDK_RESULT', 'Native arc helper did not preserve object identity')
        angles = getter(handle)
        if type(angles) not in (tuple, list) or len(angles) != 2:
            raise SDKError('SDK_RESULT', 'Invalid independent arc-angle readback')
        angles = [_number(value, 'arc angle readback', 'SDK_RESULT') for value in angles]
        delta = (angles[0] % 360 - start % 360 + 180) % 360 - 180
        if not math.isclose(delta, 0, rel_tol=0, abs_tol=1e-8) or not math.isclose(angles[1], sweep, rel_tol=0, abs_tol=1e-8):
            raise SDKError('SDK_RESULT', 'Native arc helper failed its independent angle readback')
        return None

    return write, compatibility


def _resolve_handle(reference, vs_module, label):
    if reference.value is None:
        return None
    try:
        handle = vs_module.GetObjectByUuid(reference.value)
        if handle is None or (type(handle) is int and handle == 0) or vs_module.GetTypeN(handle) == 0:
            raise SDKError('SDK_HANDLE', label + ' does not identify a valid document object')
        # Read-back prevents resolving a UUID to an unexpected or transient handle.
        actual = _uuid(vs_module.GetObjectUuid(handle), label, 'SDK_HANDLE')
        if actual != reference.value:
            raise SDKError('SDK_HANDLE', label + ' resolved to a different object UUID')
        return handle
    except SDKError:
        raise
    except Exception as error:
        raise SDKError('SDK_HANDLE', label + ' could not resolve its UUID: ' + str(error))


def _output_handle(value, vs_module, label):
    if value is None or (type(value) is int and value == 0):
        return None
    try:
        if vs_module.GetTypeN(value) == 0:
            # The Python binding can return vs.Handle() instead of None for
            # NIL (documented by WSScript_GetObject in the SDK stub). Accept
            # only equality with an independently constructed native null of
            # exactly the same type. Falsy, stale and dummy type-0 objects do
            # not otherwise become successful null results.
            constructor = getattr(vs_module, 'Handle', None)
            if hasattr(constructor, '__call__'):
                native_null = constructor()
                if type(value) is type(native_null) and (value == native_null) is True:
                    return None
            raise SDKError('SDK_RESULT', label + ' returned a non-object or invalid HANDLE')
        return _uuid(vs_module.GetObjectUuid(value), label, 'SDK_RESULT')
    except SDKError:
        raise
    except Exception as error:
        raise SDKError('SDK_RESULT', label + ' returned a HANDLE that cannot be represented as an object UUID: ' + str(error))


def _output(value, description, vs_module, label):
    typename = _type_name(description.get('type', 'UNKNOWN'))
    if typename == 'HANDLE':
        return _output_handle(value, vs_module, label)
    if typename == 'BOOLEAN':
        if type(value) is not bool:
            raise SDKError('SDK_RESULT', label + ' did not return a boolean')
        return value
    if typename in _INTEGER_RANGES:
        return _integer(value, *_INTEGER_RANGES[typename], label, code='SDK_RESULT')
    if typename.startswith('REAL'):
        return _number(value, label, 'SDK_RESULT')
    if typename in _STRINGS or typename == 'CHAR':
        if type(value) is not str or (typename == 'CHAR' and len(value) != 1):
            raise SDKError('SDK_RESULT', label + ' did not return the declared string type')
        return value
    if typename in _POINTS or typename in ('COLOR', 'RGBCOLOR'):
        size = _POINTS.get(typename, 3)
        if type(value) not in (list, tuple) or len(value) != size:
            raise SDKError('SDK_RESULT', label + ' did not return the declared component count')
        if typename in ('COLOR', 'RGBCOLOR'):
            return [_integer(part, 0, 65535, label, code='SDK_RESULT') for part in value]
        return [_number(part, label, 'SDK_RESULT') for part in value]
    if typename in ('ANY', 'ARRAY'):
        if typename == 'ARRAY' and type(value) not in (list, tuple):
            raise SDKError('SDK_RESULT', label + ' did not return an array')
        return _json_value(value, label, 'SDK_RESULT')
    raise SDKError('SDK_RESULT', label + ' has an unsupported declared return type: ' + typename)


def _return_shape_diagnostic(value, expected_count):
    # Diagnostic evidence only: never coerce a malformed native result into
    # success or stringify opaque handles/pointers. A small, flat numeric tuple
    # is safe to preserve exactly; other output values receive shape only.
    container = 'tuple' if type(value) is tuple else 'list' if type(value) is list else 'other'
    diagnostic = {'container': container, 'expected_count': expected_count}
    if container != 'other':
        diagnostic['actual_count'] = len(value)
        if len(value) <= 32 and all(type(part) is bool
                or (type(part) is int and -(2 ** 53) <= part <= 2 ** 53)
                or (type(part) is float and math.isfinite(part)) for part in value):
            diagnostic['numeric_outputs'] = list(value)
    return {'native_return': diagnostic}


def _serialize_result(value, returns, vs_module):
    kind = returns.get('kind')
    if kind == 'void':
        if value is not None:
            raise SDKError('SDK_RESULT', 'SDK procedure unexpectedly returned a value; it was not discarded')
        return None, None
    if kind == 'scalar':
        return _output(value, returns, vs_module, 'result'), None
    if kind != 'tuple':
        raise SDKError('SDK_RESULT', 'SDK catalog has an unsupported return shape')
    items = returns.get('items', [])
    if type(value) not in (tuple, list) or len(value) != len(items):
        raise SDKError('SDK_RESULT', 'SDK returned a different number of outputs than declared in its catalog',
                       details=_return_shape_diagnostic(value, len(items)))
    result = [_output(part, descriptor, vs_module, 'result[%d]' % index)
              for index, (part, descriptor) in enumerate(zip(value, items))]
    names = [item.get('name') for item in items]
    outputs = dict(zip(names, result)) if all(names) and len(set(names)) == len(names) else None
    return result, outputs


def _check_return_contract(returns):
    kind = returns.get('kind')
    if kind == 'void':
        return
    if kind not in ('scalar', 'tuple'):
        raise SDKError('SDK_UNSUPPORTED', 'SDK catalog has an unsupported return shape')
    descriptors = [returns] if kind == 'scalar' else returns.get('items', [])
    supported = _STRINGS | set(_INTEGER_RANGES) | set(_POINTS) | {
        'BOOLEAN', 'HANDLE', 'CHAR', 'COLOR', 'RGBCOLOR', 'ANY', 'ARRAY'}
    for description in descriptors:
        typename = _type_name(description.get('type', 'UNKNOWN'))
        if typename not in supported and not typename.startswith('REAL'):
            raise SDKError('SDK_UNSUPPORTED', 'Return type requires an explicit adapter: ' + typename)


def _dialog_reference(value, parameter):
    if not isinstance(value, dict) or not ({'$event', '$dialog'} & set(value)):
        return False
    is_dialog = set(value) == {'$dialog'} and value['$dialog'] is True
    if not is_dialog and value not in ({'$event': 'item'}, {'$event': 'data'}):
        raise SDKError('SDK_ARGUMENTS', 'Dialog reference must be $dialog:true or $event:item/data')
    if _type_name(parameter['type']) not in {'LONGINT', 'INTEGER', 'REAL', 'ANY'}:
        raise SDKError('SDK_TYPE', 'Dialog numeric reference is incompatible with ' + parameter['type'])
    return True


def _validate_dialog_calls(descriptor, catalog):
    for calls in descriptor['events'].values():
        for call in calls:
            if type(call) is not dict or set(call) - {'name', 'arguments'} or type(call.get('name')) is not str:
                raise SDKError('SDK_ARGUMENTS', 'Dialog event calls accept only name and arguments')
            entry = catalog['functions'].get(call['name'])
            if (entry is None or entry.get('category') != 'Dialogs - Modern'
                    or call['name'] in _DIALOG_CALLBACKS
                    or any(_type_name(p['type']) == 'PROCEDURE' for p in entry['parameters'])):
                raise SDKError('SDK_CONTEXT', 'Dialog handlers accept only noninteractive modern-dialog control APIs')
            if entry.get('context', {}).get('interactive'):
                raise SDKError('SDK_CONTEXT', 'Nested interactive dialogs are unsupported')
            _prepare(call['name'], {'arguments': call.get('arguments', {})}, catalog,
                     {'host_context': 'dialog_event'}, _dialog_reference)


def _callback(function, parameter, descriptor, vs_module, captures, catalog, arguments, lifetime):
    limit = descriptor['limit']
    data = {'items': [], 'count': 0, 'truncated': False}
    captures[parameter] = data
    missing = object()

    def record(value):
        data['count'] += 1
        if len(data['items']) >= limit:
            data['truncated'] = True
            return False
        data['items'].append(value)
        return True

    def failure(error):
        # A host can swallow Python callback exceptions. Keep the first error so
        # invoke cannot report success after the synchronous native call returns.
        data.setdefault('error', {'code': getattr(error, 'code', 'SDK_EXECUTION'), 'message': str(error)})

    def valid_arguments(values, extra, keywords):
        # Native code can swallow Python TypeError. Catch a callback ABI mismatch
        # inside the function so the outer call cannot then report success.
        # Keep the named positional parameters (and their co_argcount) because
        # APIs such as TrackObject distinguish callback forms by their arity.
        if extra or keywords or any(value is missing for value in values):
            failure(SDKError('SDK_RESULT', function + '.' + parameter +
                             ' received an unexpected callback argument shape'))
            return False
        return True

    if function in _DIALOG_CALLBACKS:
        def dialog(item=missing, event_data=missing, *extra, **keywords):
            if not lifetime['active']:
                return 0 if item is missing else item
            if not valid_arguments((item, event_data), extra, keywords):
                # Zero means no event; never synthesize accept/cancel when the
                # host did not supply an item to preserve.
                return 0 if item is missing else item
            try:
                _integer(item, -2147483648, 2147483647, 'dialog item', 'SDK_RESULT')
                _integer(event_data, -2147483648, 2147483647, 'dialog data', 'SDK_RESULT')
                record_item = {'item': item, 'data': event_data, 'results': []}
                recorded = record(record_item)
                calls = descriptor['events'].get(str(item), [])
                if not recorded and calls:
                    raise SDKError('SDK_RANGE', 'Dialog callback event limit reached before executing control calls')
                if recorded and 'error' not in data:
                    for call in calls:
                        values = {}
                        for key, value in call.get('arguments', {}).items():
                            values[key] = (arguments['dialogID'] if value == {'$dialog': True} else
                                           item if value == {'$event': 'item'} else
                                           event_data if value == {'$event': 'data'} else value)
                        response = invoke(call['name'], {'arguments': values}, vs_module=vs_module,
                                          catalog=catalog, invocation_context={'host_context': 'dialog_event'})
                        record_item['results'].append(response)
                        if 'error' in response:
                            raise SDKError(response['code'], response['error'])
            except Exception as error:
                failure(error)
            # Preserve the event. The caller/user determines when to accept or
            # cancel; this adapter never closes or dismisses a dialog itself.
            return item
        return dialog

    if function == 'ImportResToCurFileN':
        def conflict(resource_name=missing, *extra, **keywords):
            if not lifetime['active']:
                return 0
            if not valid_arguments((resource_name,), extra, keywords):
                return 0
            try:
                name = _output(resource_name, {'type': 'STRING'}, vs_module, 'resource name')
                if not record(name):
                    raise SDKError('SDK_RANGE', 'Resource conflict callback limit reached; remaining conflicts skipped')
                if 'error' not in data:
                    return 1 if descriptor['action'] == 'replace' else 0
            except Exception as error:
                failure(error)
            return 0
        return conflict

    if function in {'TrackObject', 'TrackObjectN'}:
        def filter_object(handle=missing, *extra, **keywords):
            if not lifetime['active']:
                return False
            if not valid_arguments((handle,), extra, keywords):
                return False
            try:
                identifier = _output_handle(handle, vs_module, 'tracked handle')
                record(identifier)
                if identifier is not None and 'error' not in data:
                    return vs_module.GetTypeN(handle) in descriptor['object_types']
            except Exception as error:
                failure(error)
            return False
        return filter_object

    _, continue_value, stop_value = _CALLBACKS[function]

    def collect(handle=missing, *extra, **keywords):
        if not lifetime['active']:
            return stop_value
        if not valid_arguments((handle,), extra, keywords):
            return stop_value
        try:
            if record(_output_handle(handle, vs_module, 'callback handle')) and 'error' not in data:
                return continue_value
        except Exception as error:
            failure(error)
        return stop_value

    return collect


def _prepare(name, params, catalog, invocation_context, reference_validator=None):
    if type(params) is not dict or set(params) - {'arguments', 'options'}:
        raise SDKError('SDK_ARGUMENTS', 'Expected {"arguments":{...},"options":{...}}')
    arguments, options = params.get('arguments', {}), params.get('options', {})
    if type(arguments) is not dict or type(options) is not dict:
        raise SDKError('SDK_ARGUMENTS', 'arguments and options must be JSON objects')
    if set(options) - {'force'} or ('force' in options and type(options['force']) is not bool):
        raise SDKError('SDK_ARGUMENTS', 'Only the boolean options.force is supported')
    catalog = load_catalog() if catalog is None else catalog
    _check_catalog(catalog)
    if type(name) is not str or name not in catalog['functions']:
        raise SDKError('SDK_ARGUMENTS', 'Unknown SDK function')
    entry = catalog['functions'][name]
    parameters = entry['parameters']
    expected = {parameter['name'] for parameter in parameters}
    extra = set(arguments) - expected
    missing = {p['name'] for p in parameters if p.get('required', True)} - set(arguments)
    if extra or missing:
        raise SDKError('SDK_ARGUMENTS', 'SDK arguments mismatch; missing=%s extra=%s' %
                       (sorted(missing), sorted(extra, key=str)))
    context = entry.get('context', {})
    if context.get('unsupported_reason'):
        raise SDKError('SDK_UNSUPPORTED', context['unsupported_reason'])
    if context.get('required_host_context') and context['required_host_context'] != (invocation_context or {}).get('host_context'):
        raise SDKError('SDK_CONTEXT', 'Requires host context: ' + context['required_host_context'])
    if context.get('requires_sequence') and not (invocation_context or {}).get('sequence'):
        raise SDKError('SDK_CONTEXT', 'This API requires a validated same-job SDK sequence')
    if (name in _QUARANTINED or context.get('quarantined')) and not options.get('force', False):
        raise SDKError('SDK_CONTEXT', 'This API is quarantined; explicit options.force is required')
    _check_return_contract(entry['returns'])
    converted = []
    for parameter in parameters:
        value = arguments[parameter['name']]
        typename = _type_name(parameter['type'])
        if typename == 'PROCEDURE' and (_CALLBACKS.get(name, (None,))[0] != parameter['name']
                                       and _SPECIAL_CALLBACKS.get(name) != parameter['name']):
            raise SDKError('SDK_UNSUPPORTED', name + '.' + parameter['name'] +
                           ' requires an unsupported host callback or native pointer')
        if reference_validator is not None and reference_validator(value, parameter):
            converted.append(None)  # Preflight only; invocation resolves and validates the actual value.
        else:
            decoded = _input(value, parameter, name)
            if typename == 'PROCEDURE' and name in _DIALOG_CALLBACKS:
                _validate_dialog_calls(decoded, catalog)
            converted.append(decoded)
    if name == 'UprString' and type(arguments['str']) is str and not arguments['str'].isascii():
        raise SDKError('SDK_UNSUPPORTED', 'UprString compatibility supports ASCII only; native execution is blocked '
                       'after an uncertain host exit, and Unicode/locale casing equivalence is not established')
    return entry, parameters, converted


def validate(name, params, *, catalog=None, invocation_context=None, reference_validator=None):
    """Validate a call before a sequence starts, without importing/calling ``vs``.

    The trusted sequence runner may provide ``reference_validator(value, param)``.
    It must validate the reference's structure and destination before returning
    True; only that value skips literal decoding. ``invoke`` never skips decoding.
    """
    try:
        _prepare(name, params, catalog, invocation_context, reference_validator)
        return {'status': 'ok', 'function': name}
    except SDKError as error:
        return {'error': str(error), 'code': error.code, 'function': name, 'dispatched': False}
    except Exception as error:
        return {'error': str(error), 'code': 'SDK_ADAPTER', 'function': name, 'dispatched': False}


def invoke(name, params, callable=None, *, vs_module=None, catalog=None, invocation_context=None):
    """Invoke one generated API call with ``{arguments: {...}, options: {...}}``.

    ``callable`` is supplied by the generated named wrapper. The keyword-only
    injection points support offline tests and the trusted same-job sequence
    runner; they are not accepted from user JSON. ``dispatched`` on errors tells
    callers whether the native operation may already have changed the document.
    """
    dispatched = False
    compatibility = None
    captures = {}
    callback_lifetime = {'active': True}
    try:
        catalog = load_catalog() if catalog is None else catalog
        entry, parameters, converted = _prepare(name, params, catalog, invocation_context)
        vs_module = importlib.import_module('vs') if vs_module is None else vs_module
        _host_version(vs_module)
        if name == 'UprString':
            # Do not resolve or invoke vs.UprString: the last measured native job
            # ended with an application exit. The documented ASCII conversion
            # has a local implementation; native Unicode casing is not assumed.
            compatibility = dict(_UPRSTRING_COMPATIBILITY)
            result, outputs = _serialize_result(converted[0].upper(), entry['returns'], vs_module)
            return {'status': 'ok', 'function': name, 'result': result,
                    'compatibility': compatibility, 'native_dispatched': False}
        for index, (parameter, value) in enumerate(zip(parameters, converted)):
            if isinstance(value, _HandleRef):
                converted[index] = _resolve_handle(value, vs_module, parameter['name'])
            elif _type_name(parameter['type']) == 'PROCEDURE':
                converted[index] = _callback(name, parameter['name'], value, vs_module, captures,
                                              catalog, params.get('arguments', {}), callback_lifetime)
        if name == 'SetGradientOpacity' and _windows_build(vs_module, 882075):
            target, compatibility = _gradient_opacity_writer(vs_module, converted)
        elif name == 'SetArc' and _windows_build(vs_module, 882075):
            target, compatibility = _arc_angle_writer(vs_module, converted)
        else:
            target = callable if callable is not None else getattr(vs_module, name, None)
        if not hasattr(target, '__call__'):
            raise SDKError('SDK_UNSUPPORTED', 'The running host has no callable vs.' + name)
        dispatched = True
        try:
            raw = target(*converted)
        finally:
            callback_lifetime['active'] = False
        for captured in captures.values():
            if 'error' in captured:
                raise SDKError(captured['error']['code'], captured['error']['message'])
        if name == 'HArea' and raw is None:
            # SDK 3200 documents HArea as obsolete and HAreaN as the same area
            # operation with improved polyline accuracy. Preserve the native
            # call and disclose the fallback; other malformed returns still fail.
            compatibility = {'native_function': 'HArea', 'replacement_function': 'HAreaN',
                             'reason': 'obsolete_native_returned_none'}
            replacement = getattr(vs_module, 'HAreaN', None)
            if not hasattr(replacement, '__call__'):
                raise SDKError('SDK_RESULT', 'HArea returned None and the host has no callable HAreaN')
            raw = replacement(*converted)
        if (name == 'GetTextLength' and type(raw) is int and -32768 <= raw <= 32767
                and _windows_build(vs_module, 882075)):
            object_type = vs_module.GetTypeN(converted[0])
            if type(object_type) is int and object_type == 10:
                if raw < 0:
                    raise SDKError('SDK_RESULT', 'Native text length cannot be negative')
                # This binding counts UTF-8 bytes, but independently measured
                # formatting positions use the SDK's UCChar (UTF-16) units.
                # Verify both lengths from the same object's actual text before
                # correcting only the known byte-count defect on this host.
                text_getter = getattr(vs_module, 'GetText', None)
                if not hasattr(text_getter, '__call__'):
                    raise SDKError('SDK_RESULT', 'Cannot independently verify text length without GetText')
                text = text_getter(converted[0])
                if type(text) is not str:
                    raise SDKError('SDK_RESULT', 'GetText returned an invalid text value')
                utf16_units = len(text.encode('utf-16-le')) // 2
                utf8_bytes = len(text.encode('utf-8'))
                if raw != utf16_units:
                    if raw != utf8_bytes:
                        raise SDKError('SDK_RESULT', 'Native text length matches neither text units nor UTF-8 bytes')
                    compatibility = {'native_function': name, 'replacement_function': 'GetText',
                                     'reason': 'python_binding_counts_utf8_bytes_instead_of_utf16_units',
                                     'native_result': raw, 'host_build': 882075,
                                     'result_unit': 'utf16_code_units'}
                    raw = utf16_units
        if name == 'GetTextLeading' and type(raw) in (int, float) and raw == 0:
            # SDK 3200 specifies -1 when spacing is not custom. The Python
            # binding on build 882075 returns its untouched output value 0.
            # Confirm the mode through the independent spacing getter before
            # correcting only this documented sentinel; custom zero is valid.
            spacing_getter = getattr(vs_module, 'GetTextSpace', None)
            if not hasattr(spacing_getter, '__call__'):
                raise SDKError('SDK_RESULT', 'Cannot verify zero text leading without GetTextSpace')
            spacing = spacing_getter(converted[0])
            if type(spacing) is not int:
                raise SDKError('SDK_RESULT', 'GetTextSpace returned an invalid spacing mode')
            if spacing in (2, 3, 4):
                compatibility = {'native_function': name, 'replacement_function': 'GetTextSpace',
                                 'reason': 'documented_noncustom_leading_sentinel',
                                 'native_result': raw, 'spacing_mode': spacing}
                raw = -1.0
        if (name == 'GetOpacityByClassN' and type(raw) in (tuple, list)
                and len(raw) == 2 and all(type(value) is bool for value in raw)
                and _windows_build(vs_module, 882075)):
            # Four flag combinations, checked against independent effective
            # pen/fill opacities, isolate this binding's reversed output order.
            # The setter and the SDK's declared pen-then-fill contract are right.
            compatibility = {'native_function': name, 'replacement_function': name,
                             'reason': 'python_binding_reversed_pen_fill_outputs',
                             'native_result': list(raw), 'host_build': 882075}
            raw = (raw[1], raw[0])
        if (name == 'GetObjMaterialName' and type(raw) in (tuple, list)
                and len(raw) == 2 and raw[0] is False and type(raw[1]) is str and raw[1]):
            # Do not turn a nonempty string alone into success. An independently
            # resolved material resource must have the exact same name and type.
            material_getter = getattr(vs_module, 'GetObjMaterialHandle', None)
            name_getter = getattr(vs_module, 'GetName', None)
            if not hasattr(material_getter, '__call__') or not hasattr(name_getter, '__call__'):
                raise SDKError('SDK_RESULT', 'Cannot independently verify material name status')
            material = material_getter(converted[0])
            if (material is not None and vs_module.GetTypeN(material) == 19
                    and name_getter(material) == raw[1]):
                identifier = _output_handle(material, vs_module, 'material verification')
                compatibility = {'native_function': name, 'replacement_function': 'GetObjMaterialHandle/GetName',
                                 'reason': 'material_name_verified_independently',
                                 'native_result': list(raw), 'material_id': identifier}
                raw = (True, raw[1])
        result, outputs = _serialize_result(raw, entry['returns'], vs_module)
        response = {'status': 'ok', 'function': name, 'result': result}
        if compatibility is not None:
            response['compatibility'] = compatibility
        if outputs is not None:
            response['outputs'] = outputs
        if captures:
            response['callbacks'] = captures
        return response
    except SDKError as error:
        response = {'error': str(error), 'code': error.code, 'function': name, 'dispatched': dispatched}
        if error.details is not None:
            response['details'] = error.details
    except Exception as error:
        response = {'error': str(error), 'code': 'SDK_EXECUTION' if dispatched else 'SDK_ADAPTER',
                    'function': name, 'dispatched': dispatched}
    if compatibility is not None:
        response['compatibility'] = compatibility
    if captures:
        response['callbacks'] = captures
    return response

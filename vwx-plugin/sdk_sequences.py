"""Bounded same-menu-job SDK calls, with validated construction scopes.

This is not a transaction. Earlier native operations may survive a failed step.
Regeneration-dependent reads must use a later menu-command job.
"""
import sdk_runtime


MAX_STEPS = 200


def _native_entered(result):
    return bool(result.get('native_dispatched',
                           'error' not in result or result.get('dispatched', False)))


def _reference(value, step):
    if not isinstance(value, dict) or '$ref' not in value:
        return False
    if set(value) - {'$ref', 'path'}:
        raise ValueError('Reference accepts only $ref and path')
    index, path = value['$ref'], value.get('path', ['result'])
    if type(index) is not int or not 0 <= index < step:
        raise ValueError('Reference must point to an earlier step')
    if not isinstance(path, list) or len(path) > 16 or any(type(part) not in (str, int) for part in path):
        raise ValueError('Reference path must be a list of string keys or integer indices')
    if any(type(part) is int and part < 0 for part in path):
        raise ValueError('Reference indices must be nonnegative')
    return True


def _resolve(value, results):
    if isinstance(value, dict) and '$ref' in value:
        target = results[value['$ref']]
        for part in value.get('path', ['result']):
            if type(part) is int and not isinstance(target, list):
                raise ValueError('Integer reference path requires a list')
            if type(part) is str and not isinstance(target, dict):
                raise ValueError('String reference path requires an object')
            target = target[part]
        return target
    return value


def _reference_contract(value, parameter, step, calls, functions):
    if not _reference(value, step):
        return False
    returns = functions[calls[value['$ref']]['name']]['returns']
    path = list(value.get('path', ['result']))
    if not path:
        raise ValueError('Reference must select result or outputs')
    root = path.pop(0)
    if root == 'result':
        descriptor = returns
        if returns['kind'] == 'void':
            raise ValueError('Cannot reference a void SDK result')
        if returns['kind'] == 'tuple':
            if not path or type(path[0]) is not int or not 0 <= path[0] < len(returns['items']):
                raise ValueError('Tuple result reference requires a valid item index')
            descriptor = returns['items'][path.pop(0)]
    elif root == 'outputs':
        if returns['kind'] != 'tuple' or not path or type(path[0]) is not str:
            raise ValueError('Named outputs require a tuple return and output name')
        output_name = path.pop(0)
        items = [item for item in returns['items'] if item['name'] == output_name]
        if len(items) != 1:
            raise ValueError('Unknown named SDK output: ' + output_name)
        descriptor = items[0]
    else:
        raise ValueError('Only statically typed result/outputs references are supported')
    source = sdk_runtime._type_name(descriptor.get('type', 'UNKNOWN'))
    destination = sdk_runtime._type_name(parameter['type'])
    if path:
        size = {'POINT': 2, 'POINT3D': 3, 'VECTOR': 3, 'COLOR': 3}.get(source)
        if len(path) != 1 or size is None or type(path[0]) is not int or not 0 <= path[0] < size:
            raise ValueError('Reference path does not match the declared SDK output shape')
        source = 'INTEGER' if source == 'COLOR' else 'REAL'
    number_types = {'REAL', 'INTEGER', 'LONGINT', 'TEXTSTYLE'}
    strings = {'STRING', 'DYNARRAY[] OF CHAR', 'CRITERIA', 'CHAR'}
    compatible = (source == destination or destination == 'ANY'
                  or source in number_types and destination == 'REAL'
                  or source in strings and destination in strings - {'CHAR'}
                  or {source, destination} <= {'POINT3D', 'VECTOR'})
    if not compatible:
        raise ValueError('Reference type %s is incompatible with %s' % (source, destination))
    return True


def run(params, *, vs_module=None, catalog=None):
    """Validate the complete plan, then execute serially in the current job."""
    results, active, cleanup = [], [], []
    step = None
    try:
        if type(params) is not dict or set(params) - {'calls', 'options'}:
            raise ValueError('Expected calls and optional options')
        calls, options = params.get('calls'), params.get('options', {})
        if not isinstance(calls, list) or not 1 <= len(calls) <= MAX_STEPS:
            raise ValueError('calls must contain 1..%d steps' % MAX_STEPS)
        catalog = sdk_runtime.load_catalog() if catalog is None else catalog
        functions = catalog['functions']
        matching, closing = [], {}
        for step, call in enumerate(calls):
            if type(call) is not dict or set(call) - {'name', 'arguments'}:
                raise ValueError('Each step accepts name and arguments')
            name = call.get('name')
            if type(name) is not str or name not in functions:
                raise ValueError('Unknown SDK function at step %d' % step)
            valid = sdk_runtime.validate(
                name, {'arguments': call.get('arguments', {}), 'options': options},
                catalog=catalog, invocation_context={'sequence': True},
                reference_validator=lambda value, parameter, index=step: _reference_contract(
                    value, parameter, index, calls, functions))
            if 'error' in valid:
                return dict(valid, failed_step=step, results=[], cleanup=[])
            context = functions[name].get('context', {})
            role, family = context.get('scope_role'), context.get('scope_family')
            if role == 'begin':
                matching.append((family, step))
            elif role == 'member':
                if not matching or matching[-1][0] != family:
                    raise ValueError('Scope member requires an active %s scope at step %d' % (family, step))
            elif role == 'end':
                if not matching or matching[-1][0] != family:
                    raise ValueError('Mismatched scope end at step %d' % step)
                _, opener = matching.pop()
                closing[opener] = name
        if matching:
            raise ValueError('Every Begin scope must have its matching End in this sequence')

        for step, call in enumerate(calls):
            name = call['name']
            arguments = {key: _resolve(value, results) for key, value in call.get('arguments', {}).items()}
            context = functions[name].get('context', {})
            result = sdk_runtime.invoke(name, {'arguments': arguments, 'options': options},
                                        vs_module=vs_module, catalog=catalog,
                                        invocation_context={'sequence': True})
            results.append(result)
            # An entered native Begin that fails during serialization may still
            # leave a scope open. Attempt one matching End; never retry Begin.
            entered = _native_entered(result)
            if context.get('scope_role') == 'begin' and entered:
                active.append(closing[step])
            elif context.get('scope_role') == 'end' and entered:
                active.pop()
            if 'error' in result:
                return {'error': 'SDK sequence stopped at step %d' % step, 'code': 'SDK_SEQUENCE',
                        'failed_step': step, 'results': results, 'cleanup': cleanup,
                        'dispatched': any(_native_entered(r) for r in results)}
        return {'status': 'ok', 'results': results, 'count': len(results), 'cleanup': cleanup,
                'regeneration_boundary': 'after this menu-command job returns'}
    except Exception as error:
        return {'error': str(error), 'code': 'SDK_SEQUENCE', 'failed_step': step,
                'results': results, 'cleanup': cleanup,
                'dispatched': any(_native_entered(r) for r in results)}
    finally:
        for name in reversed(active):
            arguments = {'acceptOrReject': 0} if name == 'EndContext' else {}
            cleanup.append(sdk_runtime.invoke(name, {'arguments': arguments, 'options': {}},
                           vs_module=vs_module, catalog=catalog,
                           invocation_context={'sequence': True}))

"""Build guarded live SDK probe plans; this CLI never connects to Vectorworks.

An authorized caller may inject send_job into run_plan. Every step is a distinct
menu-command job, and native inspection follows creation/reset in a later job.
The small document suite leaves its objects and worksheet available for review.
Its pass results apply only to the tested inputs, not to the other SDK APIs.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import uuid


DOCUMENT_PREFIX = 'VWX-MCP-SDK-TEST-'


def _call(api_name, **arguments):
    return {'name': api_name, 'arguments': arguments}


def _capture(name):
    return {'$capture': name}


def build_plan(suite='pure', run_id=None):
    if suite not in ('pure', 'document'):
        raise ValueError('suite must be pure or document')
    run_id = run_id or uuid.uuid4().hex[:10]
    if not isinstance(run_id, str) or not run_id or not all(c.isalnum() or c in '-_' for c in run_id):
        raise ValueError('run_id must contain only letters, digits, hyphens or underscores')
    steps = [
        {'id': 'version', 'call': _call('GetVersion'),
         'expect': {'path': ['result', 0], 'equals': 32}},
        {'id': 'absolute', 'call': _call('Abs', v=-12.5),
         'expect': {'path': ['result'], 'equals': 12.5}},
        {'id': 'square_root', 'call': _call('Sqrt', v=81.0),
         'expect': {'path': ['result'], 'equals': 9.0}},
        {'id': 'sine_zero', 'call': _call('Sin', v=0.0),
         'expect': {'path': ['result'], 'equals': 0.0}},
    ]
    if suite == 'document':
        document_steps = [
            {'id': 'create_rectangle', 'calls': [
                _call('Rect', p1=[0, 20], p2=[30, 0]), _call('LNewObj')],
             'capture': {'name': 'rectangle', 'path': ['results', 1, 'result']}},
            {'id': 'inspect_rectangle_bbox', 'call': _call('GetBBox', h=_capture('rectangle'))},
            {'id': 'inspect_rectangle_area', 'call': _call('HAreaN', ObjectHandle=_capture('rectangle')),
             'expect': {'path': ['result'], 'equals': 600.0}},
            {'id': 'create_polygon', 'calls': [
                _call('BeginPoly'), _call('AddPoint', p=[50, 0]),
                _call('AddPoint', p=[80, 0]), _call('AddPoint', p=[50, 20]),
                _call('EndPoly'), _call('LNewObj'),
                _call('SetPolyClosed', polyHandle={'$ref': 5}, isClosed=True)],
             'capture': {'name': 'polygon', 'path': ['results', 5, 'result']}},
            {'id': 'inspect_polygon_vertices', 'call': _call('GetVertNum', PolyHd=_capture('polygon')),
             'expect': {'path': ['result'], 'equals': 3}},
            {'id': 'inspect_polygon_area', 'call': _call('HAreaN', ObjectHandle=_capture('polygon')),
             'expect': {'path': ['result'], 'equals': 300.0}},
            {'id': 'create_text', 'calls': [
                _call('TextOrigin', p=[0, -30]),
                _call('CreateText', theText='SDK probe before'), _call('LNewObj')],
             'capture': {'name': 'text', 'path': ['results', 2, 'result']}},
            {'id': 'inspect_text_before', 'call': _call('GetText', objectHd=_capture('text')),
             'expect': {'path': ['result'], 'equals': 'SDK probe before'}},
            {'id': 'update_text', 'call': _call('SetText', objectHd=_capture('text'), text='SDK probe after')},
            {'id': 'inspect_text_after', 'call': _call('GetText', objectHd=_capture('text')),
             'expect': {'path': ['result'], 'equals': 'SDK probe after'}},
            {'id': 'create_worksheet', 'call': _call('CreateWS', name='SDK-Probe-' + run_id, rows=3, columns=2),
             'capture': {'name': 'worksheet', 'path': ['result']}},
            {'id': 'update_worksheet', 'calls': [
                _call('SetWSCellFormula', worksheet=_capture('worksheet'), topRow=1,
                      leftColumn=1, bottomRow=1, rightColumn=1, formula='=6*7'),
                _call('RecalculateWS', worksheet=_capture('worksheet'))]},
            {'id': 'inspect_worksheet', 'call': _call('GetWSCellValue', worksheet=_capture('worksheet'), row=1, column=1),
             'expect': {'path': ['result'], 'equals': 42.0}},
        ]
        for step in document_steps:
            step['requires_test_document'] = True
        steps.extend(document_steps)
    return {'schema_version': 1, 'suite': suite, 'run_id': run_id,
            'document_prefix': DOCUMENT_PREFIX, 'steps': steps,
            'prerequisites': ('A blank disposable document named with the required prefix, '
                              'using Top/Plan and a design layer.' if suite == 'document' else
                              'A running Vectorworks 2027 menu-command bridge.'),
            'verification_limit': 'Only these concrete inputs; no inference of all-API live correctness.',
            'cleanup': 'No deletion: retain fixtures and raw results for review.'}


def _substitute(value, captures):
    if isinstance(value, dict):
        if '$capture' in value:
            if set(value) != {'$capture'} or value['$capture'] not in captures:
                raise ValueError('Unknown or malformed capture reference')
            return captures[value['$capture']]
        return {key: _substitute(item, captures) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, captures) for item in value]
    return value


def render_job(step, captures=None, document_prefix=DOCUMENT_PREFIX):
    """Return one execute_script request without executing it or importing vs."""
    if document_prefix != DOCUMENT_PREFIX:
        raise ValueError('The live probe document prefix cannot be weakened')
    if ('call' in step) == ('calls' in step):
        raise ValueError('A step must specify exactly one call or calls list')
    sequence = 'calls' in step
    payload = {'calls': step['calls']} if sequence else step['call']
    payload = _substitute(payload, captures or {})
    # Quoting the JSON as a Python string prevents names/text becoming source.
    body = 'import json\nimport commands\n_probe_payload = json.loads(%r)\n' % json.dumps(payload, allow_nan=False)
    expression = 'commands.sdk_sequence(_probe_payload)' if sequence else 'commands.sdk_call(_probe_payload)'
    names = [call['name'] for call in payload['calls']] if sequence else [payload['name']]
    # Only this fixed read-only/pure set may omit the disposable-document guard.
    if step.get('requires_test_document') or any(name not in {'GetVersion', 'Abs', 'Sqrt', 'Sin'} for name in names):
        body += (
            '_probe_document = vs.GetFName()\n'
            'if not isinstance(_probe_document, str) or not _probe_document.startswith(%r):\n'
            '    __result__ = {"error":"A disposable test document with the required prefix must be active",'
            '"code":"SDK_PROBE_DOCUMENT","dispatched":False,"document":_probe_document}\n'
            'else:\n'
            '    __result__ = %s\n'
        ) % (DOCUMENT_PREFIX, expression)
    else:
        body += '__result__ = ' + expression + '\n'
    return {'command': 'execute_script', 'params': {'code': body}}


def _at_path(value, path):
    for component in path:
        value = value[component]
    return value


def run_plan(send_job, plan):
    """Use an explicitly injected sender; stop at the first failure, never retry.

    send_job(request) must return the execute_script result object (or its inner
    __result__ dict). The CLI does not provide any sender or network connection.
    """
    records, captures = [], {}
    evidence = {'suite': plan['suite'], 'run_id': plan['run_id'], 'records': records,
                'captures': captures, 'started_utc': datetime.now(timezone.utc).isoformat(),
                'verification_limit': plan['verification_limit']}
    for step in plan['steps']:
        try:
            request = render_job(step, captures, plan['document_prefix'])
            response = send_job(request)
            if isinstance(response, str):
                response = json.loads(response)
            if isinstance(response, dict) and 'output' in response and 'result' in response:
                if response.get('error'):
                    raise ValueError('execute_script error: ' + str(response['error']))
                response = response['result']
            record = {'step': step['id'], 'response': response}
            records.append(record)
            if not isinstance(response, dict) or response.get('error') or response.get('status') != 'ok':
                evidence.update(status='failed', failed_step=step['id'])
                break
            if 'capture' in step:
                capture = step['capture']
                value = _at_path(response, capture['path'])
                if not isinstance(value, str) or uuid.UUID(value).int == 0:
                    raise ValueError('Creation did not return a valid object UUID')
                captures[capture['name']] = value
            if 'expect' in step:
                expectation = step['expect']
                actual = _at_path(response, expectation['path'])
                expected = expectation['equals']
                equal = (type(actual) in (int, float) and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
                         if type(expected) in (int, float) else actual == expected)
                record['assertion'] = {'expected': expected, 'actual': actual, 'passed': equal}
                if not equal:
                    evidence.update(status='failed', failed_step=step['id'])
                    break
        except Exception as error:
            records.append({'step': step['id'], 'error': str(error)})
            evidence.update(status='failed', failed_step=step['id'])
            break
    else:
        evidence['status'] = 'passed'
    evidence['finished_utc'] = datetime.now(timezone.utc).isoformat()
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('pure', 'document'), default='pure')
    parser.add_argument('--run-id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    plan = json.dumps(build_plan(args.suite, args.run_id), indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.write_text(plan, encoding='utf-8')
    else:
        print(plan, end='')


if __name__ == '__main__':
    main()

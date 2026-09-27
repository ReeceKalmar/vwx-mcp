"""Generated SDK coverage and exact contracts; these tests never load native vs."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_sdk_wrappers', ROOT / 'tools/build_sdk_wrappers.py')
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)
CATALOG_BYTES = (ROOT / 'vwx-plugin/sdk_catalog.json').read_bytes()
CATALOG = json.loads(CATALOG_BYTES)
FUNCTIONS = CATALOG['functions']
INDEX = json.loads((ROOT / 'vwx-plugin/vs_index.json').read_text(encoding='utf-8'))
GENERATED = (ROOT / 'vwx-plugin/sdk_generated.py').read_text(encoding='utf-8')
GRADIENT_STUB = '''
def GetGradientDataN(
    gradient, # HANDLE - Gradient that contains the segment.
    segmentIndex, # INTEGER - Segment from which to get the data.
):
    """Python: (Boolean, spotPosition, midpointPosition, red, green, blue, opacity) = vs.GetGradientDataN(gradient, segmentIndex)
    VectorScript: PROCEDURE GetGradientDataN(gradient:HANDLE; segmentIndex:INTEGER; VAR spotPosition:REAL; VAR midpointPosition:REAL; VAR red:LONGINT; VAR green:LONGINT; VAR blue:LONGINT; VAR opacity:INTEGER);
    Category: Document Attributes
    """
    return (0.0, 0.0, 0, 0, 0, 0)
'''


class SDKGenerationTests(unittest.TestCase):
    def test_all_sdk_names_and_exact_parameter_order_are_covered(self):
        self.assertEqual(len(FUNCTIONS), 3098)
        self.assertEqual(set(FUNCTIONS), set(INDEX))
        for name, entry in FUNCTIONS.items():
            with self.subTest(function=name):
                self.assertEqual(entry['name'], name)
                self.assertEqual(entry['command'], 'sdk_' + name)
                self.assertEqual([p['name'] for p in entry['parameters']], INDEX[name]['args'])
                self.assertEqual(entry['required_count'], INDEX[name]['required'])
                self.assertTrue(all(p['required'] and not p['has_default'] for p in entry['parameters']))

    def test_every_parameter_and_output_has_a_resolved_type(self):
        for name, entry in FUNCTIONS.items():
            with self.subTest(function=name):
                self.assertIn(entry['returns']['kind'], {'void', 'scalar', 'tuple'})
                for parameter in entry['parameters']:
                    self.assertIn(parameter['type'], GENERATOR.SCALAR_TYPES)
                    self.assertIn(parameter['direction'], {'in', 'inout'})
                    self.assertEqual(parameter['type'], GENERATOR.normalize_type(parameter['raw_type']))
                for output in entry['returns']['items']:
                    self.assertIn(output['type'], GENERATOR.SCALAR_TYPES)
                    self.assertIn('source', output)

    def test_generated_text_and_provenance_are_current(self):
        self.assertEqual(GENERATED, GENERATOR.render_wrappers(CATALOG))
        metadata = json.loads((ROOT / 'vwx-plugin/vs_index_meta.json').read_text(encoding='utf-8'))
        self.assertEqual(CATALOG['source']['stub_sha256'], metadata['stub_sha256'])
        self.assertEqual(CATALOG['source']['index_sha256'], metadata['index_sha256'])
        self.assertEqual(CATALOG['source']['generator_sha256'],
                         hashlib.sha256((ROOT / 'tools/build_sdk_wrappers.py').read_bytes()).hexdigest())

    def test_all_wrappers_name_the_native_api_and_exact_lambda_arguments(self):
        tree = ast.parse(GENERATED)
        wrappers = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(set(wrappers), {'sdk_' + name for name in INDEX})
        for name, entry in FUNCTIONS.items():
            with self.subTest(function=name):
                wrapper = wrappers['sdk_' + name]
                self.assertEqual([a.arg for a in wrapper.args.args], ['p'])
                call = wrapper.body[-1].value
                self.assertEqual(ast.unparse(call.func), 'sdk_runtime.invoke')
                self.assertEqual(call.args[0].value, name)
                self.assertEqual(call.args[1].id, 'p')
                native = call.args[2]
                names = [p['name'] for p in entry['parameters']]
                self.assertIsInstance(native, ast.Lambda)
                self.assertEqual([a.arg for a in native.args.args], names)
                self.assertEqual(ast.unparse(native.body.func), 'vs.' + name)
                self.assertEqual([a.id for a in native.body.args], names)

    def test_named_registry_does_not_call_native_apis_at_import(self):
        fake_vs = ModuleType('vs')
        fake_runtime = ModuleType('sdk_runtime')
        spec = importlib.util.spec_from_file_location('sdk_generated_test',
                                                       ROOT / 'vwx-plugin/sdk_generated.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'vs': fake_vs, 'sdk_runtime': fake_runtime}):
            spec.loader.exec_module(module)
        self.assertEqual(set(module.WRAPPERS), set(INDEX))
        self.assertEqual(module.SDK_CATALOG_SHA256, hashlib.sha256(CATALOG_BYTES).hexdigest())
        for name, wrapper in module.WRAPPERS.items():
            self.assertEqual(wrapper.__name__, 'sdk_' + name)

    def test_return_point_grouping_uses_python_contract_not_flat_stub_placeholder(self):
        bbox = FUNCTIONS['GetBBox']['returns']
        self.assertEqual([item['type'] for item in bbox['items']], ['POINT', 'POINT'])
        self.assertEqual(len(bbox['stub_placeholder']), 4)
        self.assertEqual([item['type'] for item in FUNCTIONS['Centroid3D']['returns']['items']],
                         ['BOOLEAN', 'REAL', 'REAL', 'REAL'])
        self.assertEqual([item['type'] for item in FUNCTIONS['AddSolid']['returns']['items']],
                         ['INTEGER', 'HANDLE'])
        self.assertEqual(FUNCTIONS['GetPolyPt']['returns']['type'], 'POINT')

    def test_gradient_data_contract_returns_six_native_values_without_inventing_success(self):
        parsed = GENERATOR.parse_stub(GRADIENT_STUB)['GetGradientDataN']
        for entry in (parsed, FUNCTIONS['GetGradientDataN']):
            self.assertEqual([p['name'] for p in entry['returns']['items']],
                             ['spotPosition', 'midpointPosition', 'red', 'green', 'blue', 'opacity'])
            self.assertEqual([p['type'] for p in entry['returns']['items']],
                             ['REAL', 'REAL', 'LONGINT', 'LONGINT', 'LONGINT', 'INTEGER'])
            self.assertNotIn('Boolean', entry['python_signature'])
            audit = entry['return_contract_correction']
            self.assertIn('(Boolean,', audit['sdk_python_signature'])
            self.assertEqual(audit['observed_host'], [32, 0, 0, 2, 882075])
            self.assertEqual(audit['native_evidence'], 'docs/GRADIENT_RETURN_2027.json')

    def test_placeholder_mismatch_never_generically_drops_other_boolean_returns(self):
        for name in ('OtherGradientDataN', 'getGradientDataN', 'GetGradientData'):
            with self.subTest(function=name):
                entry = GENERATOR.parse_stub(GRADIENT_STUB.replace('GetGradientDataN', name))[name]
                self.assertEqual(entry['returns']['items'][0]['type'], 'BOOLEAN')
                self.assertEqual(len(entry['returns']['items']), 7)
                self.assertEqual(len(entry['returns']['stub_placeholder']), 6)
                self.assertNotIn('return_contract_correction', entry)

    def test_gradient_correction_evidence_hash_and_independent_readbacks_agree(self):
        audit = FUNCTIONS['GetGradientDataN']['return_contract_correction']
        evidence_bytes = (ROOT / audit['native_evidence']).read_bytes()
        self.assertEqual(hashlib.sha256(evidence_bytes).hexdigest(), audit['native_evidence_sha256'])
        evidence = json.loads(evidence_bytes)
        records = {r['request']['params']['name']: r for r in evidence['records']}
        self.assertEqual(records['GetVersionEx']['response']['result'], audit['observed_host'])
        observed = records['GetGradientDataN']['response']
        self.assertEqual(observed['code'], 'SDK_RESULT')  # Historical failure remains preserved.
        native = observed['details']['native_return']
        self.assertEqual(native['container'], 'tuple')
        self.assertEqual(native['actual_count'], 6)
        self.assertEqual(native['numeric_outputs'], audit['observed_result'])
        self.assertEqual(native['numeric_outputs'], records['GetGradientData']['response']['result']
                         + [records['GetGradientOpacity']['response']['result']])
        for name in ('GetGradientData', 'GetGradientOpacity'):
            self.assertEqual(records[name]['response']['function'], name)
            self.assertEqual(records[name]['response']['status'], 'ok')
            self.assertEqual(records[name]['request']['params']['arguments'],
                             records['GetGradientDataN']['request']['params']['arguments'])

    def test_gradient_correction_rejects_sdk_declaration_drift(self):
        changes = [
            ('(Boolean, spotPosition', '(spotPosition'),
            ('(Boolean, spotPosition', '(BOOLEAN, spotPosition'),
            ('PROCEDURE GetGradientDataN', 'FUNCTION GetGradientDataN'),
            ('opacity:INTEGER);', 'opacity:INTEGER): BOOLEAN;'),
            ('VAR opacity:INTEGER', 'VAR opacity:LONGINT'),
            ('VAR red:LONGINT', 'VAR red:REAL'),
            ('# HANDLE -', '# STRING -'),
            ('# INTEGER -', '# in/out INTEGER -'),
            ('segmentIndex', 'segmentNumber'),
            ('return (0.0, 0.0, 0, 0, 0, 0)', 'return (False, 0.0, 0.0, 0, 0, 0, 0)'),
            ('return (0.0, 0.0, 0, 0, 0, 0)', 'return [0.0, 0.0, 0, 0, 0, 0]'),
            ('return (0.0, 0.0, 0, 0, 0, 0)', 'return (0, 0, 0, 0, 0, 0)'),
            ('return (0.0, 0.0, 0, 0, 0, 0)', 'return (0.0, 0.0, False, 0, 0, 0)'),
            ('return (0.0, 0.0, 0, 0, 0, 0)', 'return (0.0, 0.0, 1, 0, 0, 0)'),
            ('return (0.0, 0.0, 0, 0, 0, 0)', 'return None'),
        ]
        for before, after in changes:
            with self.subTest(change=after):
                self.assertIn(before, GRADIENT_STUB)
                with self.assertRaisesRegex(ValueError, 'GetGradientDataN SDK declaration changed'):
                    GENERATOR.parse_stub(GRADIENT_STUB.replace(before, after))

    def test_gradient_correction_rejects_a_different_sdk_version_before_regeneration(self):
        for field, value in [('vectorworks_year', 2028), ('sdk_version', 3300), ('sdk_build', 999999)]:
            metadata = {'vectorworks_year': 2027, 'sdk_version': 3200, 'sdk_build': 882699}
            metadata[field] = value
            with self.subTest(field=field), \
                    patch.object(Path, 'read_bytes', side_effect=[GRADIENT_STUB.encode(), b'{}']), \
                    patch.object(Path, 'read_text', return_value=json.dumps(metadata)):
                with self.assertRaisesRegex(ValueError, 'SDK version changed'):
                    GENERATOR.build_catalog('unused-offline-sdk-stub.py')

    def test_scope_and_non_document_handles_are_not_advertised_as_unrestricted(self):
        self.assertTrue(FUNCTIONS['BeginGroupN']['context']['requires_sequence'])
        self.assertTrue(FUNCTIONS['BeginGroupN']['parameters'][0]['nullable'])
        self.assertTrue(FUNCTIONS['EndGroup']['context']['requires_sequence'])
        self.assertEqual(FUNCTIONS['vsoGetEventInfo']['context']['required_host_context'], 'object_event')
        self.assertIn('transient', FUNCTIONS['CreateHLHandle']['context']['unsupported_reason'])
        for name in GENERATOR.VARIADIC_READS:
            self.assertEqual(FUNCTIONS[name]['returns']['type'], 'ANY')
            self.assertTrue(FUNCTIONS[name]['context']['unsupported_reason'])

    def test_documented_callback_and_scope_expansions_keep_context_requirements(self):
        self.assertEqual(FUNCTIONS['BeginRoof']['context']['scope_family'], 'group')
        self.assertEqual(FUNCTIONS['BeginRoof']['context']['scope_role'], 'begin')
        self.assertIsNone(FUNCTIONS['BeginRoof']['context']['unsupported_reason'])
        self.assertIsNone(FUNCTIONS['vsoParamName2Index']['context']['required_host_context'])
        self.assertEqual(FUNCTIONS['SetControlData']['context']['required_host_context'], 'dialog_event')
        self.assertIsNone(FUNCTIONS['SetControlData']['context']['unsupported_reason'])
        for name, mode in [('ForEachMaterial', 'collect'), ('ForEachObjectInList', 'collect'),
                           ('TrackObject', 'filter'), ('ImportResToCurFileN', 'conflict'),
                           ('RunLayoutDialog', 'dialog'), ('RunNamedDialogN', 'dialog')]:
            self.assertEqual(FUNCTIONS[name]['callback_contract']['mode'], mode)
            self.assertEqual(FUNCTIONS[name]['callback_contract']['lifetime'], 'synchronous')

    def test_parser_preserves_inout_types_and_semantic_return_names(self):
        source = '''
def TestShape(
    shape, # in/out HANDLE - Shape may be replaced.
    p, # POINT - Input coordinate.
):
    """Python: (BOOLEAN, shape, output) = vs.TestShape(shape, p)
    VectorScript: FUNCTION TestShape(VAR shape:HANDLE; pX,pY:REAL; VAR outputX,outputY:REAL) : BOOLEAN;
    Category: Test
    Test description.
    """
    return (False, 0, 0, 0)
'''
        entry = GENERATOR.parse_stub(source)['TestShape']
        self.assertEqual(entry['parameters'][0]['direction'], 'inout')
        self.assertEqual([item['type'] for item in entry['returns']['items']],
                         ['BOOLEAN', 'HANDLE', 'POINT'])
        self.assertEqual(entry['returns']['items'][2]['components'], ['outputX', 'outputY'])


if __name__ == '__main__':
    unittest.main()

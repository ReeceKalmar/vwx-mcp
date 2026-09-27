"""Coverage must count implementations, not index entries or arbitrary scripts."""
import importlib.util
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('api_coverage', ROOT / 'tools/api_coverage.py')
COVERAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COVERAGE)


class CoverageAnalysisTests(unittest.TestCase):
    def test_private_registered_extensions_do_not_expand_the_sdk_catalog(self):
        source = '''const SFunctionDef kFunctions[] = {
            { "VWXMaintSave", "VWX Bridge", "save" },
            { "VWXBridgeSetArc", "VWX Bridge", "arc" },
            {}
        };
        { "VWXMaintTypo", "outside the declaration table" }
        '''
        self.assertEqual(COVERAGE.declared_bridge_extensions(source), {'VWXMaintSave', 'VWXBridgeSetArc'})
        self.assertEqual(COVERAGE.declared_bridge_extensions('getattr(vs, "VWXMaintSave")'), set())
        report = COVERAGE.build_report(ROOT)
        self.assertEqual(report['counts']['sdk_indexed_functions'], 3098)
        self.assertEqual(report['private_bridge_extension_functions_invoked'],
                         ['VWXMaintQuit', 'VWXMaintRevision', 'VWXMaintSave', 'VWXMaintSnapshot'])
        self.assertFalse(set(report['private_bridge_extension_functions_invoked']) & set(report['handwritten_sdk_functions']))
        self.assertEqual(report['unknown_invoked_sdk_names'], [])

    def analyze(self, source, roots=('command',)):
        return COVERAGE.Analysis(source, roots)

    def test_transitive_helpers_callbacks_and_unreferenced_private_code(self):
        result = self.analyze('''
import vs
def _unused():
    vs.NeverUsed()
def _inner():
    vs.GetName(None)
def _outer():
    _inner()
def command(p):
    def callback(h):
        _outer()
    def unused_nested():
        vs.AlsoUnused()
    vs.ForEachObject(callback, "ALL")
''')
        self.assertEqual(result.sdk_functions, {'GetName', 'ForEachObject'})
        self.assertNotIn('_unused', result.reachable)
        self.assertNotIn('command.unused_nested', result.reachable)

    def test_literal_helper_arguments_resolve_dynamic_sdk_calls(self):
        result = self.analyze('''
import vs
def _call(name):
    fn = getattr(vs, name, None)
    return fn()
def command(p):
    _call('AddSolid')
    _call('SubtractSolid')
''')
        self.assertEqual(result.sdk_functions, {'AddSolid', 'SubtractSolid'})
        self.assertEqual(result.dynamic_lookups[0]['candidates'], ['AddSolid', 'SubtractSolid'])

    def test_literal_loop_columns_do_not_count_output_keys_as_functions(self):
        result = self.analyze('''
import vs
def command(p):
    for name, key in (('ActiveClass', 'class'), ('GetVersion', 'version')):
        fn = getattr(vs, name)
        p[key] = fn()
''')
        self.assertEqual(result.sdk_functions, {'ActiveClass', 'GetVersion'})

    def test_callable_aliases_dict_dispatch_and_callback_arguments(self):
        result = self.analyze('''
import vs as api
from vs import GetFName as filename
def _safe(callback):
    return callback()
def command(p):
    aliases = {'a': api.AddSolid, 'b': api.SubtractSolid}
    fn = aliases.get(p['op'])
    fn()
    _safe(filename)
    second = api.GetVersion if p else api.GetUnits
    second()
''')
        self.assertEqual(result.sdk_functions,
                         {'AddSolid', 'SubtractSolid', 'GetFName', 'GetVersion', 'GetUnits'})

    def test_arbitrary_script_and_index_lookup_do_not_count_as_implementations(self):
        result = self.analyze('''
import vs
INDEX = {'SecretApi': {'arity': 1}}
def command(p):
    namespace = {'vs': vs}
    exec(p['code'], namespace)
    return namespace.get('__result__'), INDEX.get(p['name'])
''')
        self.assertEqual(result.sdk_functions, set())

    def test_unknown_dynamic_name_is_reported_without_inventing_coverage(self):
        result = self.analyze('''
import vs
def command(p):
    fn = getattr(vs, p['name'])
    fn()
''')
        self.assertEqual(result.sdk_functions, set())
        self.assertFalse(result.dynamic_lookups[0]['resolved'])

    def test_marker_callable_pairs_remain_resolved_in_later_application_loop(self):
        result = self.analyze('''
import vs
def command(p):
    changes = []
    for key, getter, setter in (
        ('start', vs.GetObjBeginningMarker, vs.SetObjBeginningMarker),
        ('end', vs.GetObjEndMarker, vs.SetObjEndMarker)):
        current = getter(p['h'])
        changes.append((setter, current))
    for setter, current in changes:
        setter(p['h'], current)
''')
        self.assertEqual(result.sdk_functions, {'GetObjBeginningMarker', 'GetObjEndMarker',
                                               'SetObjBeginningMarker', 'SetObjEndMarker'})

    def test_helper_cycles_terminate_and_container_values_stay_finite(self):
        result = self.analyze('''
import vs
def _a():
    _b()
def _b():
    _a()
    vs.GetVersion()
def command(p):
    _a()
    choices = {'a': vs.GetUnits}
    choices = {'nested': choices}
    choices.get('nested')()
''')
        self.assertEqual(result.sdk_functions, {'GetVersion', 'GetUnits'})

    def test_vtool_count_includes_server_only_tools_and_decorator_calls(self):
        tree = COVERAGE.ast.parse('''
@vtool
def server_only(): pass
@vtool()
async def async_tool(): pass
def helper(): pass
''')
        self.assertEqual([node.name for node in tree.body if COVERAGE.is_vtool(node)],
                         ['server_only', 'async_tool'])

    def test_catalog_or_arbitrary_dispatch_is_not_a_generated_binding(self):
        bindings, invalid = COVERAGE.generated_bindings('''
CATALOG = {'Abs': {'command': 'sdk_Abs'}}
def sdk_Abs(p):
    return invoke(p)
''', {'Abs'})
        self.assertEqual(bindings, {})
        self.assertEqual(invalid, [{'wrapper': 'sdk_Abs', 'sdk_targets': []}])

    def test_generated_binding_must_match_exact_api_name(self):
        bindings, invalid = COVERAGE.generated_bindings('''
def sdk_Abs(p):
    return invoke('Abs', p, lambda v: vs.Abs(v))
def sdk_Absolute(p):
    return invoke('Absolute', p, lambda: vs.WrongName())
''', {'Abs', 'Absolute'})
        self.assertEqual(set(bindings), {'Abs'})
        self.assertEqual(invalid[0]['wrapper'], 'sdk_Absolute')

    def test_repository_counts_keep_handwritten_generated_and_mock_units_separate(self):
        report = COVERAGE.build_report(ROOT)
        counts = report['counts']
        self.assertEqual(counts['sdk_indexed_functions'], 3098)
        self.assertEqual(counts['generated_sdk_adapters'], 3098)
        self.assertEqual(counts['generated_mock_dispatched'] + counts['generated_mock_rejected'] +
                         counts['generated_mock_compatibility'], 3098)
        self.assertLess(counts['handwritten_sdk_functions'], counts['generated_sdk_adapters'])
        self.assertGreater(counts['generated_mock_rejected'], 0)
        self.assertEqual(counts['total_mcp_tools_default'],
                         counts['handwritten_mcp_tools'] + counts['generated_mcp_tools_default'])
        self.assertEqual(counts['total_public_dispatcher_commands'],
                         counts['handwritten_public_dispatcher_verbs'] + counts['generated_public_dispatcher_commands'])
        self.assertEqual(counts['live_fixtures_pending'] + counts['sdk_functions_observed_live'], 3098)
        self.assertEqual(counts['full_semantics_verified_functions'], 0)
        self.assertEqual(report['invalid_generated_bindings'], [])
        self.assertEqual(report['missing_tool_targets'], [])
        dispatched = set(report['generated_mock_dispatched_functions'])
        rejected = set(report['generated_mock_rejected_functions'])
        compatibility = set(report['generated_mock_compatibility_functions'])
        self.assertFalse(dispatched & rejected)
        self.assertFalse(compatibility & (dispatched | rejected))
        self.assertEqual(dispatched | rejected | compatibility, set(report['generated_sdk_bindings']))

    def test_report_keeps_unknown_and_compatibility_results_out_of_native_counts(self):
        matrix = COVERAGE.mock_matrix(ROOT)
        # Inject a small evidence view while preserving the actual SDK inventory.
        for entry in matrix['functions'].values():
            entry['live'].update(native_outcome_observed=False, uncertain_case_count=0,
                                 compatibility_case_counts={'passed': 0, 'failed': 0, 'uncertain': 0})
        matrix['functions']['Abs']['live']['native_outcome_observed'] = True
        upper = matrix['functions']['UprString']['live']
        upper.update(uncertain_case_count=1, compatibility_case_counts={'passed': 1, 'failed': 0, 'uncertain': 0})
        matrix['summary'].update(functions_observed_live=1, pending_live_fixtures=3097,
                                 live_cases_passed=1, live_cases_failed=0, live_cases_uncertain=1,
                                 functions_with_passed_case=1, functions_with_failed_case=0,
                                 functions_with_uncertain_case=1, functions_with_only_uncertain_native_cases=1,
                                 functions_attempted_native=2, compatibility_cases_passed=1,
                                 compatibility_cases_failed=0, compatibility_cases_uncertain=0,
                                 functions_with_compatibility_case=1, functions_with_passed_compatibility_case=1)
        with patch.object(COVERAGE, 'mock_matrix', return_value=matrix):
            report = COVERAGE.build_report(ROOT)
        self.assertEqual(set(report['sdk_functions_observed_live']), {'Abs'})
        self.assertEqual(set(report['sdk_functions_with_uncertain_native_attempts']), {'UprString'})
        self.assertEqual(set(report['sdk_functions_with_compatibility_evidence']), {'UprString'})
        self.assertEqual(report['counts']['sdk_functions_observed_live'], 1)
        self.assertEqual(report['counts']['live_cases_uncertain'], 1)
        self.assertEqual(report['counts']['compatibility_cases_passed'], 1)

    def test_sequence_runner_changes_invalidate_report_provenance(self):
        source = 'vwx-plugin/sdk_sequences.py'
        path = ROOT / source
        original_read = Path.read_bytes
        contents = original_read(path)
        report = COVERAGE.build_report(ROOT)
        self.assertEqual(report['source_sha256'][source], hashlib.sha256(contents).hexdigest())
        self.assertNotIn('vwx-plugin/sdk_sequence.py', report['source_sha256'])

        changed_contents = contents + b'\n# simulated sequence-runner change\n'
        def changed_read(candidate):
            return changed_contents if candidate == path else original_read(candidate)

        # Simulate a changed runner without modifying the shared working tree.
        with patch.object(Path, 'read_bytes', changed_read):
            changed_report = COVERAGE.build_report(ROOT)
        self.assertEqual(changed_report['source_sha256'][source],
                         hashlib.sha256(changed_contents).hexdigest())
        self.assertNotEqual(report['source_sha256'], changed_report['source_sha256'])
        self.assertEqual(report['counts'], changed_report['counts'])


if __name__ == '__main__':
    unittest.main()

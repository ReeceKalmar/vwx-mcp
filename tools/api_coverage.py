#!/usr/bin/env python3
"""Separate handwritten SDK use, generated adapters and injected mock coverage.

This never imports vs, the server, or commands.py. Handwritten analysis follows
callback references, aliases, finite literal getattr targets and literal helper
arguments to a fixed point. Reachability is conservative (all branches), not a
claim that any command has executed successfully inside Vectorworks.
"""
import argparse
import ast
from collections import Counter
import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = 'vwx-plugin/commands.py'
SERVER = 'mcp-server/vwx_mcp_server.py'
FRAMEWORK = ('vwx-plugin/BridgeStart_MenuCommand.py', 'vwx-plugin/vwx_pump.py')
INDEX = 'vwx-plugin/vs_index.json'
META = 'vwx-plugin/vs_index_meta.json'
REPORT = 'docs/API_COVERAGE_2027.json'
GENERATED = 'vwx-plugin/sdk_generated.py'
CATALOG = 'vwx-plugin/sdk_catalog.json'
PRIVATE_EXTENSIONS = 'native/Source/Bridge/BridgeVSFunctions.cpp'


def declared_bridge_extensions(source):
    """Only the private scripting registration table supplies extension names.

    These routines are reported separately, never added to the SDK denominator
    or its implementation/pass counts. A typo outside the table stays unknown.
    """
    table = re.search(r'const\s+SFunctionDef\s+kFunctions\[\]\s*=\s*\{(.*?)\n\s*\};', source, re.S)
    if table is None:
        return set()
    return set(re.findall(r'^\s*\{\s*"(VWX(?:Bridge|Maint|Doc)[A-Za-z0-9_]*)"\s*,', table.group(1), re.M))


def local_nodes(body):
    """Walk a lexical scope, excluding bodies of separately analyzed functions."""
    for node in body:
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from local_nodes(ast.iter_child_nodes(node))


class Analysis:
    """Finite-set propagation of strings, SDK functions, and local callables.

    Containers are conservatively collapsed to their possible values. Literal
    tuples in for loops retain columns, so ('SDKName', 'output_key') does not
    accidentally count the output key as an API. Arbitrary computed strings,
    external imports, eval and exec are intentionally not inferred.
    """
    def __init__(self, source, roots=None):
        self.tree = ast.parse(source)
        self.scopes = {}
        self.parents = {}
        self.envs = {}
        self._add_scope('<module>', self.tree, None)
        self.top_functions = {n.name for n in self.tree.body
                              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.reachable = {'<module>'} | set(roots if roots is not None else self.top_functions)
        self.changed = True
        while self.changed:
            self.changed = False
            for key in sorted(self.reachable):
                self._propagate(key)
        self.sites = []
        self.dynamic_lookups = []
        for key in sorted(self.reachable):
            self._record(key)

    def _add_scope(self, key, node, parent):
        self.scopes[key] = node
        self.parents[key] = parent
        self.envs[key] = {}
        for child in local_nodes(node.body):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_key = child.name if key == '<module>' else key + '.' + child.name
                self.envs[key][child.name] = {('local', child_key)}
                self._add_scope(child_key, child, key)
            elif isinstance(child, ast.Import):
                for alias in child.names:
                    if alias.name == 'vs':
                        self.envs[key][alias.asname or 'vs'] = {('module', 'vs')}
            elif isinstance(child, ast.ImportFrom) and child.module == 'vs':
                for alias in child.names:
                    self.envs[key][alias.asname or alias.name] = {('sdk', alias.name)}

    def lookup(self, key, name):
        while key is not None:
            if name in self.envs[key]:
                return self.envs[key][name]
            key = self.parents[key]
        return set()

    def values(self, key, node):
        if node is None:
            return set()
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {('str', node.value)}
        if isinstance(node, ast.Name):
            return self.lookup(key, node.id)
        if isinstance(node, ast.Attribute):
            if ('module', 'vs') in self.values(key, node.value):
                return {('sdk', node.attr)}
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            items = self._flatten(set().union(*(self.values(key, value) for value in node.elts)))
            return {('container', frozenset(items))}
        if isinstance(node, ast.Dict):
            items = self._flatten(set().union(*(self.values(key, value) for value in node.values)))
            return {('container', frozenset(items))}
        if isinstance(node, ast.IfExp):
            return self.values(key, node.body) | self.values(key, node.orelse)
        if isinstance(node, ast.BoolOp):
            return set().union(*(self.values(key, value) for value in node.values))
        if isinstance(node, ast.Subscript):
            return self._items(self.values(key, node.value))
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Name) and node.func.id == 'getattr'
                    and len(node.args) >= 2
                    and ('module', 'vs') in self.values(key, node.args[0])):
                return {('sdk', name) for kind, name in self.values(key, node.args[1])
                        if kind == 'str'}
            if isinstance(node.func, ast.Attribute) and node.func.attr in ('get', 'values'):
                return self._items(self.values(key, node.func.value))
        return set()

    @staticmethod
    def _items(values):
        return set().union(*(items for kind, items in values if kind == 'container'))

    @staticmethod
    def _flatten(values):
        out = set()
        for kind, value in values:
            out.update(value if kind == 'container' else {(kind, value)})
        return out

    def _merge(self, key, name, values):
        old = self.envs[key].setdefault(name, set())
        if not values <= old:
            old.update(values)
            self.changed = True

    def _assign(self, key, target, value):
        if isinstance(target, ast.Name):
            self._merge(key, target.id, self.values(key, value))
        elif isinstance(target, (ast.Tuple, ast.List)):
            if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts):
                for t, v in zip(target.elts, value.elts):
                    self._assign(key, t, v)

    def _reach(self, target):
        if target in self.scopes and target not in self.reachable:
            self.reachable.add(target)
            self.changed = True

    def _propagate(self, key):
        scope = self.scopes[key]
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = scope.args.posonlyargs + scope.args.args
            for arg, default in zip(args[-len(scope.args.defaults):], scope.args.defaults):
                self._merge(key, arg.arg, self.values(key, default))
        for node in local_nodes(scope.body):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    self._assign(key, target, node.value)
            elif isinstance(node, ast.AnnAssign):
                self._assign(key, node.target, node.value)
            elif isinstance(node, (ast.For, ast.comprehension)):
                if isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
                    for item in node.iter.elts:
                        self._assign(key, node.target, item)
                else:
                    if isinstance(node.target, ast.Name):
                        self._merge(key, node.target.id, self._items(self.values(key, node.iter)))
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                for kind, target in self.values(key, node):
                    if kind == 'local':
                        self._reach(target)
            elif isinstance(node, ast.Call):
                for kind, target in self.values(key, node.func):
                    if kind != 'local' or target not in self.scopes:
                        continue
                    self._reach(target)
                    fn = self.scopes[target]
                    params = fn.args.posonlyargs + fn.args.args
                    for param, arg in zip(params, node.args):
                        self._merge(target, param.arg, self.values(key, arg))
                    for kw in node.keywords:
                        if kw.arg:
                            self._merge(target, kw.arg, self.values(key, kw.value))

    def _record(self, key):
        for node in local_nodes(self.scopes[key].body):
            if not isinstance(node, ast.Call):
                continue
            names = sorted(name for kind, name in self.values(key, node.func) if kind == 'sdk')
            if names:
                direct = (isinstance(node.func, ast.Attribute)
                          and ('module', 'vs') in self.values(key, node.func.value))
                self.sites.append({'line': node.lineno, 'column': node.col_offset,
                                   'function': key, 'kind': 'direct' if direct else 'resolved_alias',
                                   'sdk_functions': names})
            if (isinstance(node.func, ast.Name) and node.func.id == 'getattr'
                    and len(node.args) >= 2
                    and ('module', 'vs') in self.values(key, node.args[0])):
                candidates = sorted(name for kind, name in self.values(key, node)
                                    if kind == 'sdk')
                self.dynamic_lookups.append({'line': node.lineno, 'function': key,
                                             'expression': ast.unparse(node.args[1]),
                                             'candidates': candidates,
                                             'resolved': bool(candidates)})

    @property
    def sdk_functions(self):
        return {name for site in self.sites for name in site['sdk_functions']}


def is_vtool(node):
    for decorator in node.decorator_list:
        callee = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(callee, ast.Name) and callee.id == 'vtool':
            return True
    return False


def generated_bindings(source, sdk_names):
    """Count actual direct generated bindings, never a signature catalog alone."""
    expected = set(sdk_names)
    bindings, invalid = {}, []
    for function in ast.parse(source).body:
        if not isinstance(function, ast.FunctionDef) or not function.name.startswith('sdk_'):
            continue
        name = function.name[4:]
        calls = {node.func.attr for node in ast.walk(function)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == 'vs'}
        if name not in expected or calls != {name}:
            invalid.append({'wrapper': function.name, 'sdk_targets': sorted(calls)})
        else:
            bindings[name] = {'command': function.name, 'line': function.lineno}
    return bindings, invalid


def mock_matrix(repo):
    """Run the reproducible fake-host baseline; this cannot connect to a host."""
    spec = importlib.util.spec_from_file_location('coverage_sdk_matrix', repo / 'tools/sdk_test_matrix.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_matrix(repo)


def build_report(repo=ROOT):
    repo = Path(repo)
    read = lambda path: (repo / path).read_text(encoding='utf-8-sig')
    index = json.loads(read(INDEX))
    metadata = json.loads(read(META))
    server = Analysis(read(SERVER))
    tools = sorted(node.name for node in server.tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_vtool(node))
    tool_targets = {}
    for tool in tools:
        targets = set()
        for node in local_nodes(server.scopes[tool].body):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'cmd' and node.args:
                targets.update(name for kind, name in server.values(tool, node.args[0]) if kind == 'str')
        tool_targets[tool] = sorted(targets)
    command_tree = ast.parse(read(COMMANDS))
    verbs = sorted(node.name for node in command_tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith('_'))
    roots = set(verbs) | {target for values in tool_targets.values() for target in values}
    defined = {node.name for node in command_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing_targets = sorted(roots - defined)
    commands = Analysis(read(COMMANDS), roots & defined)
    all_commands = Analysis(read(COMMANDS))
    framework = {path: Analysis(read(path)) for path in FRAMEWORK}
    built_in = commands.sdk_functions & set(index)
    extensions = declared_bridge_extensions((repo / PRIVATE_EXTENSIONS).read_text(encoding='utf-8'))
    generated, invalid_generated = generated_bindings(read(GENERATED), index)
    matrix = mock_matrix(repo)
    mock_dispatched = sorted(name for name, entry in matrix['functions'].items()
                             if entry['offline_baseline']['status'] == 'mock_dispatched')
    mock_rejected = {name: entry['offline_baseline'] for name, entry in matrix['functions'].items()
                     if entry['offline_baseline']['status'] == 'rejected_before_dispatch'}
    mock_compatibility = {name: entry['offline_baseline'] for name, entry in matrix['functions'].items()
                          if entry['offline_baseline']['status'] == 'compatibility_executed'}
    framework_api = set().union(*(a.sdk_functions for a in framework.values())) & set(index)
    source_files = (COMMANDS, SERVER, *FRAMEWORK, INDEX, META, GENERATED, CATALOG, PRIVATE_EXTENSIONS,
                    'vwx-plugin/sdk_runtime.py', 'vwx-plugin/sdk_sequences.py',
                    'mcp-server/sdk_tools.py',
                    'tools/sdk_test_matrix.py', 'tools/api_coverage.py')
    if (repo / 'docs/LIVE_SDK_2027.json').is_file():
        source_files += ('docs/LIVE_SDK_2027.json',)
    sources = {path: hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in source_files}
    categories = Counter(index[name].get('cat', '') or '(none)' for name in built_in)
    sites = [dict(path=COMMANDS, **site) for site in commands.sites]
    by_api = {name: [site for site in sites if name in site['sdk_functions']] for name in sorted(built_in)}
    raw_calls = lambda tree: sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'vs'
                                for node in ast.walk(tree))
    return {
        'schema_version': 2,
        'verification': 'handwritten/generated source analysis and injected fake-host baseline; no native semantic certification',
        'sdk': metadata,
        'method': [
            'Denominator: top-level Python API functions indexed from the official SDK vs.py; excludes C++ interfaces and Handle methods.',
            'Numerator: distinct SDK names invoked from public commands or explicit wrapper targets and transitively referenced local helpers/callbacks.',
            'Branches are conservatively included; direct calls, callable aliases, finite literal getattr names and literal helper arguments are resolved.',
            'Dead private functions, legacy bridge scripts, tests, examples and arbitrary execute_script input are excluded from built-in coverage.',
            'Index lookup and arbitrary script execution expose API knowledge/capability but do not implement all indexed functions.',
            'This is a finite, context-insensitive source analysis; it does not prove runtime availability, argument correctness or successful geometry.',
            'Generated adapters are counted only when a named sdk_Name function directly binds vs.Name; catalogs alone do not qualify.',
            'Mock-dispatched/rejected counts execute the actual runtime with injected version/UUID resolvers and signature-bound fake native calls.',
            'The mock baseline uses one menu job, no sequence context, no force override; rejection includes contextual prerequisites, not only missing implementation.',
            'Default MCP totals include generated registrations; VWX_SDK_TOOLS=0 and visibility presets change the exposed list.',
            'Native input/result cases are imported only from normalized LIVE_SDK_2027.json evidence; untested APIs stay pending and full semantic coverage is not claimed.',
            'Uncertain native attempts and compatibility replacement outputs remain separate from confirmed native results; neither earns native API pass coverage.',
        ],
        'source_sha256': sources,
        'counts': {
            'sdk_indexed_functions': len(index),
            'handwritten_sdk_functions': len(built_in),
            'handwritten_sdk_percent': round(100 * len(built_in) / len(index), 2),
            'sdk_functions_without_handwritten_workflow': len(set(index) - built_in),
            'generated_sdk_adapters': len(generated),
            'generated_adapter_percent': round(100 * len(generated) / len(index), 2),
            'sdk_functions_without_generated_adapter': len(set(index) - set(generated)),
            'generated_mock_dispatched': len(mock_dispatched),
            'generated_mock_rejected': len(mock_rejected),
            'generated_mock_compatibility': len(mock_compatibility),
            'handwritten_mcp_tools': len(tools),
            'generated_mcp_tools_default': len(generated),
            'total_mcp_tools_default': len(tools) + len(generated),
            'handwritten_public_dispatcher_verbs': len(verbs),
            'generated_public_dispatcher_commands': len(generated),
            'total_public_dispatcher_commands': len(verbs) + len(generated),
            'live_fixtures_pending': matrix['summary']['pending_live_fixtures'],
            'sdk_functions_observed_live': matrix['summary']['functions_observed_live'],
            'live_cases_passed': matrix['summary']['live_cases_passed'],
            'live_cases_failed': matrix['summary']['live_cases_failed'],
            'live_cases_uncertain': matrix['summary']['live_cases_uncertain'],
            'sdk_functions_with_passed_case': matrix['summary']['functions_with_passed_case'],
            'sdk_functions_with_failed_case': matrix['summary']['functions_with_failed_case'],
            'sdk_functions_with_uncertain_case': matrix['summary']['functions_with_uncertain_case'],
            'sdk_functions_with_only_uncertain_native_cases': matrix['summary']['functions_with_only_uncertain_native_cases'],
            'sdk_functions_attempted_native': matrix['summary']['functions_attempted_native'],
            'compatibility_cases_passed': matrix['summary']['compatibility_cases_passed'],
            'compatibility_cases_failed': matrix['summary']['compatibility_cases_failed'],
            'compatibility_cases_uncertain': matrix['summary']['compatibility_cases_uncertain'],
            'sdk_functions_with_compatibility_case': matrix['summary']['functions_with_compatibility_case'],
            'sdk_functions_with_passed_compatibility_case': matrix['summary']['functions_with_passed_compatibility_case'],
            'full_semantics_verified_functions': 0,
            'live_adapter_edge_cases': matrix['summary']['live_adapter_edge_cases'],
            'live_adapter_edge_cases_passed': matrix['summary']['live_adapter_edge_cases_passed'],
            'private_explicit_dispatcher_targets': len((roots & defined) - set(verbs)),
            'raw_direct_sdk_calls_in_commands': raw_calls(command_tree),
            'reachable_sdk_invocation_sites_in_commands': sum(bool(set(site['sdk_functions']) & set(index)) for site in commands.sites),
            'private_bridge_extension_functions_invoked': len(commands.sdk_functions & extensions),
            'framework_sdk_functions': len(framework_api),
            'framework_only_sdk_functions': len(framework_api - built_in),
            'raw_direct_sdk_calls_in_framework': sum(raw_calls(a.tree) for a in framework.values()),
            'unreferenced_top_level_command_helpers': len(commands.top_functions - commands.reachable),
        },
        'handwritten_explicit_tools': tool_targets,
        'handwritten_public_dispatcher_verbs': verbs,
        'missing_tool_targets': missing_targets,
        'handwritten_sdk_functions': sorted(built_in),
        'sdk_functions_without_handwritten_workflow': sorted(set(index) - built_in),
        'generated_sdk_bindings': generated,
        'invalid_generated_bindings': invalid_generated,
        'generated_mock_dispatched_functions': mock_dispatched,
        'generated_mock_rejected_functions': mock_rejected,
        'generated_mock_compatibility_functions': mock_compatibility,
        'mock_baseline_context': matrix['summary']['mock_baseline_context'],
        'live_evidence_source': matrix['live_evidence_source'],
        'sdk_functions_observed_live': {name: entry['live'] for name, entry in matrix['functions'].items()
                                        if entry['live']['native_outcome_observed']},
        'sdk_functions_with_uncertain_native_attempts': {name: entry['live'] for name, entry in matrix['functions'].items()
                                                        if entry['live']['uncertain_case_count']},
        'sdk_functions_with_compatibility_evidence': {name: entry['live'] for name, entry in matrix['functions'].items()
                                                     if any(entry['live']['compatibility_case_counts'].values())},
        'implemented_by_sdk_category': dict(sorted(categories.items())),
        'implementation_sites_by_sdk_function': by_api,
        'framework_sdk_functions': sorted(framework_api),
        'framework_only_sdk_functions': sorted(framework_api - built_in),
        'private_bridge_extension_functions_declared': sorted(extensions),
        'private_bridge_extension_functions_invoked': sorted(commands.sdk_functions & extensions),
        'unknown_invoked_sdk_names': sorted(commands.sdk_functions - set(index) - extensions),
        'dynamic_sdk_lookups': commands.dynamic_lookups,
        'unreferenced_top_level_helpers': sorted(commands.top_functions - commands.reachable),
        'sdk_names_only_in_unreferenced_helpers': sorted((all_commands.sdk_functions - commands.sdk_functions) & set(index)),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--output', default=REPORT)
    parser.add_argument('--check', action='store_true', help='Fail if the saved report is stale; do not write it.')
    args = parser.parse_args(argv)
    report = build_report(args.repo)
    output = args.repo / args.output
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.check:
        if not output.is_file() or output.read_text(encoding='utf-8') != rendered:
            print('Coverage report is stale. Run: python tools/api_coverage.py')
            return 1
    else:
        output.write_text(rendered, encoding='utf-8', newline='\n')
    print(json.dumps(report['counts'], indent=2))
    if report['unknown_invoked_sdk_names'] or report['missing_tool_targets'] or report['invalid_generated_bindings']:
        print('Unknown SDK names:', report['unknown_invoked_sdk_names'])
        print('Missing command targets:', report['missing_tool_targets'])
        print('Invalid generated bindings:', report['invalid_generated_bindings'])
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

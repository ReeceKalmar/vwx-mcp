"""Check MCP wrappers, command parameters and tool tags without loading Vectorworks.

Usage: python tools/pruefe_konsistenz.py [repo]
Exit 0 when clean; exit 1 when findings exist.

The pump resolves module functions by getattr, including explicitly requested
private commands such as _batch. Public discovery and dispatcher availability
are therefore counted separately. Every @vtool (sync/async and server-only)
participates in tag checks.

Only literal payload keys and a small set of local literal bindings are
resolved: dictionary keys/items and list/tuple loop or comprehension values.
Unknown expressions never stand for "all keys". A p.get(...) read may be
optional even without an explicit default, so only unguarded p[...] reads are
classified as required. This is a static contract check, not live API validation.
"""
import ast
import io
import os
import sys

_UNKNOWN = object()
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
# Transport envelopes handled by the pump before commands.py dispatch. Keep
# their public input contracts explicit; they are not handwritten native verbs.
PUMP_ENVELOPES = {'project_execute': ({'token', 'command', 'params'}, {'token', 'command'})}


def _dict_keys(node):
    if not isinstance(node, ast.Dict):
        return set()
    return {key.value for key in node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)}


def _dict_schluessel(function, payload=None):
    """Only keys belonging to the dictionary actually passed to cmd()."""
    if isinstance(payload, ast.Dict):
        return _dict_keys(payload)
    if not isinstance(payload, ast.Name):
        return set()
    visitor = _PayloadWrites(payload.id)
    for statement in function.body:
        visitor.visit(statement)
    return visitor.keys


def vtools(source):
    """{tool: (literal command or None, payload keys, line)} for every @vtool."""
    result = {}
    for function in ast.parse(source).body:
        if not isinstance(function, _FUNCTIONS):
            continue
        if not any((isinstance(d, ast.Name) and d.id == "vtool") or
                   (isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                    and d.func.id == "vtool") for d in function.decorator_list):
            continue
        result[function.name] = (None, set(), function.lineno)
        for node in ast.walk(function):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "cmd" and node.args):
                continue
            target = (node.args[0].value if isinstance(node.args[0], ast.Constant)
                      and isinstance(node.args[0].value, str) else None)
            payload = node.args[1] if len(node.args) > 1 else None
            result[function.name] = (
                target, _dict_schluessel(function, payload), function.lineno)
            break
    return result


class _ParameterReads(ast.NodeVisitor):
    """Small, bounded literal propagation; no imported code is executed."""

    def __init__(self, parameter):
        self.parameter = parameter
        self.env = {}
        self.read = set()
        self.required = set()
        self.helpers = set()
        self.guarded = set()

    def literal(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self.env.get(node.id, _UNKNOWN)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return tuple(self.literal(item) for item in node.elts)
        if isinstance(node, ast.Dict):
            result = {}
            for key, value in zip(node.keys, node.values):
                key = self.literal(key)
                if not isinstance(key, (str, int, float, bool, type(None))):
                    return _UNKNOWN
                result[key] = self.literal(value)
            return result
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and not node.args and not node.keywords):
            value = self.literal(node.func.value)
            if isinstance(value, dict):
                if node.func.attr == "items":
                    return tuple(value.items())
                if node.func.attr == "keys":
                    return tuple(value)
                if node.func.attr == "values":
                    return tuple(value.values())
        return _UNKNOWN

    def bind(self, target, value):
        if isinstance(target, ast.Name):
            self.env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            values = value if isinstance(value, tuple) and len(value) == len(target.elts) else None
            for index, item in enumerate(target.elts):
                self.bind(item, values[index] if values is not None else _UNKNOWN)

    def key(self, node):
        value = self.literal(node)
        return {value} if isinstance(value, str) else set()

    def is_params(self, node):
        return isinstance(node, ast.Name) and node.id == self.parameter

    def get_key(self, node):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and self.is_params(node.func.value)
                and node.func.attr == "get" and node.args):
            return self.key(node.args[0])
        return set()

    def guards(self, node):
        direct = self.get_key(node)
        if direct:
            return direct
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            return set().union(*(self.guards(value) for value in node.values))
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            if isinstance(node.ops[0], ast.In) and self.is_params(node.comparators[0]):
                return self.key(node.left)
            if (isinstance(node.ops[0], (ast.IsNot, ast.NotEq))
                    and isinstance(node.comparators[0], ast.Constant)
                    and node.comparators[0].value is None):
                return self.get_key(node.left)
        return set()

    def visit_Assign(self, node):
        self.visit(node.value)
        for target in node.targets:
            self.bind(target, self.literal(node.value))
            if isinstance(target, ast.Subscript):
                # Unknown mutation invalidates a local literal container.
                if isinstance(target.value, ast.Name):
                    self.env[target.value.id] = _UNKNOWN

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit(node.value)
            self.bind(node.target, self.literal(node.value))

    def visit_AugAssign(self, node):
        self.visit(node.value)
        self.bind(node.target, _UNKNOWN)

    def visit_Call(self, node):
        self.read |= self.get_key(node)
        if (isinstance(node.func, ast.Name)
                and any(self.is_params(arg) for arg in node.args)):
            self.helpers.add(node.func.id)
        self.generic_visit(node)
        if (isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.attr not in ("keys", "items", "values", "get")):
            self.env[node.func.value.id] = _UNKNOWN

    def visit_Subscript(self, node):
        if self.is_params(node.value):
            keys = self.key(node.slice)
            self.read |= keys
            if isinstance(node.ctx, ast.Load):
                self.required |= keys - self.guarded
        self.generic_visit(node)

    def visit_If(self, node):
        self.visit(node.test)
        original_env, original_guards = dict(self.env), set(self.guarded)
        self.guarded |= self.guards(node.test)
        for statement in node.body:
            self.visit(statement)
        body_env = dict(self.env)
        self.env, self.guarded = dict(original_env), set(original_guards)
        for statement in node.orelse:
            self.visit(statement)
        # Keep a binding only when both paths agree; never guess a branch.
        self.env = {key: value for key, value in body_env.items()
                    if key in self.env and value == self.env[key]}
        self.guarded = original_guards

    def visit_IfExp(self, node):
        self.visit(node.test)
        saved = set(self.guarded)
        self.guarded |= self.guards(node.test)
        self.visit(node.body)
        self.guarded = saved
        self.visit(node.orelse)

    def visit_BoolOp(self, node):
        saved = set(self.guarded)
        for value in node.values:
            self.visit(value)
            if isinstance(node.op, ast.And):
                self.guarded |= self.guards(value)
        self.guarded = saved

    def visit_For(self, node):
        self.visit(node.iter)
        values = self.literal(node.iter)
        saved = dict(self.env)
        if isinstance(values, dict):
            values = tuple(values)
        if not isinstance(values, tuple) or len(values) > 128:
            values = (_UNKNOWN,)
        for value in values:
            self.env = dict(saved)
            self.bind(node.target, value)
            for statement in node.body:
                self.visit(statement)
        self.env = saved
        # The loop variable cannot retain an earlier unrelated literal value.
        self.bind(node.target, _UNKNOWN)
        for statement in node.orelse:
            self.visit(statement)

    visit_AsyncFor = visit_For

    def comprehension(self, node):
        saved, guards = dict(self.env), set(self.guarded)

        def walk(index):
            if index == len(node.generators):
                if isinstance(node, ast.DictComp):
                    self.visit(node.key)
                    self.visit(node.value)
                else:
                    self.visit(node.elt)
                return
            generator = node.generators[index]
            self.visit(generator.iter)
            values = self.literal(generator.iter)
            if isinstance(values, dict):
                values = tuple(values)
            if not isinstance(values, tuple) or len(values) > 128:
                values = (_UNKNOWN,)
            before = dict(self.env)
            before_guards = set(self.guarded)
            for value in values:
                self.env, self.guarded = dict(before), set(before_guards)
                self.bind(generator.target, value)
                for condition in generator.ifs:
                    self.visit(condition)
                    self.guarded |= self.guards(condition)
                walk(index + 1)

        walk(0)
        self.env, self.guarded = saved, guards

    visit_GeneratorExp = comprehension
    visit_ListComp = comprehension
    visit_SetComp = comprehension
    visit_DictComp = comprehension


class _PayloadWrites(_ParameterReads):
    """Resolve literal writes to the outgoing parameter dictionary as well."""

    def __init__(self, parameter):
        super().__init__(parameter)
        self.keys = set()

    def visit_Assign(self, node):
        for target in node.targets:
            if self.is_params(target):
                self.keys |= _dict_keys(node.value)
            elif isinstance(target, ast.Subscript) and self.is_params(target.value):
                self.keys |= self.key(target.slice)
        super().visit_Assign(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and self.is_params(node.func.value):
            if node.func.attr == "update":
                if node.args:
                    self.keys |= _dict_keys(node.args[0])
                self.keys |= {keyword.arg for keyword in node.keywords if keyword.arg}
            elif node.func.attr == "setdefault" and node.args:
                self.keys |= self.key(node.args[0])
        super().visit_Call(node)


def _schluessel_in(function):
    """Return read keys, mandatory subscript keys and payload-sharing helpers."""
    if not function.args.args:
        return set(), set(), set()
    visitor = _ParameterReads(function.args.args[0].arg)
    for statement in function.body:
        visitor.visit(statement)
    return visitor.read, visitor.required, visitor.helpers


def kommandos(source):
    """All module functions the real pump can resolve, including private ones."""
    raw, lines = {}, {}
    for function in ast.parse(source).body:
        # The current synchronous pump cannot await an async command.
        if isinstance(function, ast.FunctionDef):
            raw[function.name] = _schluessel_in(function)
            lines[function.name] = function.lineno

    def resolve(name, seen):
        if name in seen or name not in raw:
            return set(), set()
        seen.add(name)
        read, required, helpers = raw[name]
        read, required = set(read), set(required)
        for helper in helpers:
            helper_read, _ = resolve(helper, seen)
            read |= helper_read
            # Helpers may be conditional; their requirements are not inferred.
        return read, required

    return {name: (*resolve(name, set()), lines[name]) for name in raw}


def doppelte(source):
    seen = {}
    for function in ast.parse(source).body:
        if isinstance(function, _FUNCTIONS):
            seen.setdefault(function.name, []).append(function.lineno)
    return [(name, lines) for name, lines in seen.items() if len(lines) > 1]


def tags(source):
    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "TOOL_TAGS"
                        for target in node.targets)):
            return _dict_keys(node.value)
    return set()


def findings(server_source, command_source, tag_source):
    """Structured findings keep the CLI and regression tests on the same path."""
    tools = vtools(server_source)
    commands = kommandos(command_source)
    tool_tags = tags(tag_source)
    result = []
    for tool, (target, keys, line) in sorted(tools.items()):
        if target in PUMP_ENVELOPES:
            allowed, mandatory = PUMP_ENVELOPES[target]
            if keys - allowed:
                result.append(('unused_keys', tool, sorted(keys - allowed)))
            if mandatory - keys:
                result.append(('missing_required_keys', tool, sorted(mandatory - keys)))
        elif target is not None and target not in commands:
            result.append(("unknown_command", tool, target))
        elif target is not None:
            unused = keys - commands[target][0]
            required = commands[target][1] - keys
            if unused:
                result.append(("unused_keys", tool, sorted(unused)))
            if required:
                result.append(("missing_required_keys", tool, sorted(required)))
        if tool not in tool_tags:
            result.append(("missing_tag", tool, line))
    for name in sorted(tool_tags - tools.keys()):
        result.append(("orphan_tag", name, None))
    for filename, source in (("commands.py", command_source),
                             ("vwx_mcp_server.py", server_source)):
        for name, lines in doppelte(source):
            result.append(("duplicate_function", filename + ":" + name, lines))
    return result


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    def read(*parts):
        with io.open(os.path.join(repo, *parts), encoding="utf-8-sig") as stream:
            return stream.read()
    server = read("mcp-server", "vwx_mcp_server.py")
    commands = read("vwx-plugin", "commands.py")
    tool_tags = read("mcp-server", "tool_tags.py")
    command_index = kommandos(commands)
    public = sum(not name.startswith("_") for name in command_index)
    print(f"{len(vtools(server))} @vtool; {public} public commands; "
          f"{len(command_index) - public} private module functions; "
          f"{len(tags(tool_tags))} tags")
    problems = findings(server, commands, tool_tags)
    for kind, name, detail in problems:
        print(f"  {kind}: {name}" + (f" -> {detail}" if detail is not None else ""))
    print(f"Findings: {len(problems)}")
    print("Static literal contracts only; optional get() reads are not mandatory.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

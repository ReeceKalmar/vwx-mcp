"""Regression checks for static MCP/command contracts; no live Vectorworks calls."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "consistency_check", ROOT / "tools/pruefe_konsistenz.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class ConsistencyTests(unittest.TestCase):
    def findings(self, server, commands, names=("tool",)):
        return CHECK.findings(server, commands,
                              "TOOL_TAGS = " + repr(dict.fromkeys(names, "query")))

    def test_private_batch_matches_real_pump_dispatch(self):
        result = self.findings(
            '@vtool\ndef tool():\n    return cmd("_batch", {"calls": []})',
            'def _batch(p):\n    return p.get("calls", [])')
        self.assertEqual(result, [])
        self.assertIn("_batch", CHECK.kommandos('def _batch(p):\n    return p'))

    def test_all_decorated_tools_count_including_async_server_only(self):
        server = (
            '@vtool\nasync def tool():\n    return "server-only"\n'
            '@vtool()\ndef screenshot():\n    return capture()\n'
            '@vtool\ndef set_toolset():\n    return "changed"\n')
        self.assertEqual(set(CHECK.vtools(server)), {"tool", "screenshot", "set_toolset"})
        result = self.findings(server, "")
        self.assertEqual({(kind, name) for kind, name, _ in result},
                         {("missing_tag", "screenshot"), ("missing_tag", "set_toolset")})

    def test_mapping_items_and_tuple_loops_resolve_only_literal_keys(self):
        source = (
            'def command(p):\n'
            '    mapping = {"height": "Height", "spread": "Spread"}\n'
            '    for key, value in mapping.items():\n'
            '        if p.get(key) is not None:\n'
            '            apply(value, p[key])\n'
            '    for key, setter in (("start", vs.Start), ("end", vs.End)):\n'
            '        setter(p.get(key))\n')
        read, required, _ = CHECK.kommandos(source)["command"]
        self.assertEqual(read, {"height", "spread", "start", "end"})
        self.assertEqual(required, set())

    def test_literal_generator_reads_export_options(self):
        source = (
            'def command(p):\n'
            '    return any(p.get(key) is not None '
            'for key in ("width", "height", "dpi", "format"))\n')
        read, required, _ = CHECK.kommandos(source)["command"]
        self.assertEqual(read, {"width", "height", "dpi", "format"})
        self.assertEqual(required, set())

    def test_unknown_dynamic_keys_do_not_hide_unused_arguments(self):
        result = self.findings(
            '@vtool\ndef tool():\n    return cmd("command", {"misspelled": 1})',
            'def command(p):\n'
            '    mapping = load_mapping()\n'
            '    for key in mapping:\n'
            '        consume(p.get(key))\n')
        self.assertIn(("unused_keys", "tool", ["misspelled"]), result)

    def test_reassignment_invalidates_literal_keys(self):
        source = (
            'def command(p):\n'
            '    keys = ("old",)\n'
            '    keys = load_keys()\n'
            '    for key in keys:\n'
            '        consume(p.get(key))\n')
        self.assertEqual(CHECK.kommandos(source)["command"][0], set())

    def test_matching_one_key_does_not_hide_missing_mandatory_key(self):
        result = self.findings(
            '@vtool\ndef tool():\n    return cmd("command", {"first": 1})',
            'def command(p):\n    return p["first"] + p["required"]')
        self.assertIn(("missing_required_keys", "tool", ["required"]), result)

    def test_optional_get_does_not_imply_mandatory_key(self):
        result = self.findings(
            '@vtool\ndef tool():\n    return cmd("command", {"id": 1})',
            'def command(p):\n'
            '    if p.get("optional") is not None:\n'
            '        consume(p["optional"])\n'
            '    return p["id"]\n')
        self.assertEqual(result, [])

    def test_unknown_command_and_orphan_tag_remain_findings(self):
        result = self.findings(
            '@vtool\ndef tool():\n    return cmd("typo", {})', "",
            names=("tool", "removed_tool"))
        self.assertIn(("unknown_command", "tool", "typo"), result)
        self.assertIn(("orphan_tag", "removed_tool", None), result)

    def test_payload_keys_are_scoped_and_literal_loop_writes_are_seen(self):
        server = (
            '@vtool\ndef tool():\n'
            '    unrelated = {"not_a_parameter": 1}\n'
            '    p = {"id": 1}\n'
            '    for key, value in {"font": font, "size": size}.items():\n'
            '        if value is not None:\n'
            '            p[key] = value\n'
            '    return cmd("command", p)\n')
        self.assertEqual(CHECK.vtools(server)["tool"][1], {"id", "font", "size"})

    def test_helper_keys_propagate_but_nested_payload_keys_do_not(self):
        result = self.findings(
            '@vtool\ndef tool():\n'
            '    return cmd("command", {"options": {"nested": 1}, "layer": "A"})',
            'def _helper(params):\n    return params.get("layer")\n'
            'def command(p):\n    _helper(p)\n    return p["options"]')
        self.assertEqual(result, [])

    def test_async_commands_are_not_available_to_synchronous_pump(self):
        result = self.findings(
            '@vtool\ndef tool():\n    return cmd("command", {})',
            'async def command(p):\n    return p')
        self.assertIn(("unknown_command", "tool", "command"), result)

    def test_repository_contracts_have_no_findings(self):
        def read(path):
            return (ROOT / path).read_text(encoding="utf-8-sig")
        self.assertEqual(CHECK.findings(
            read("mcp-server/vwx_mcp_server.py"),
            read("vwx-plugin/commands.py"),
            read("mcp-server/tool_tags.py")), [])

    def test_project_envelope_is_checked_without_inventing_a_native_verb(self):
        source = '@vtool\ndef tool():\n    return cmd("project_execute", {"token": token, "command": command, "params": {}})'
        self.assertEqual(self.findings(source, ''), [])
        invalid = '@vtool\ndef tool():\n    return cmd("project_execute", {"unexpected": 1})'
        result = self.findings(invalid, '')
        self.assertIn(('unused_keys', 'tool', ['unexpected']), result)
        self.assertIn(('missing_required_keys', 'tool', ['command', 'token']), result)


if __name__ == "__main__":
    unittest.main()

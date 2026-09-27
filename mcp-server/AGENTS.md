# MCP server context

Read [root guidance](../AGENTS.md) and [the 2027 contract](../docs/VECTORWORKS_2027.md).
This directory owns client-facing tools and transport; native `vs.*` work belongs
in `vwx-plugin`, not in the server process.

## Map and invariants

- `vwx_mcp_server.py`: standalone **FastMCP 4.0.3**, wrappers, file transport,
  timeouts, logs and optional MCP HTTP. Do not import `mcp.server.fastmcp`.
  Register handwritten tools with `vtool` and tags from `tool_tags.py`; keep
  `output_schema=None`, annotations, timeout and the final entry-point guard
  after all registrations. Do not restore `structured_output=False`.
- `sdk_tools.py`: exact generated SDK schemas, shared `sdk` tag and the same
  output-schema suppression. Presets must retain discovery/escape tools.
- `background_policy.py`: recursively preflight the entire request before
  connection/publication. Raw scripts and interactive routes stay blocked by
  default; `options.force` is not a policy override.
- `maintenance.py`: persistent owner-token lease, OS publication gate and durable
  publication markers outside IPC. Never expire/steal an unknown lease or clear
  consumed uncertain work. Reject nested maintenance. Validate twelve lowercase
  hexadecimal CID characters before any result-path read or removal.
- `diagnostic_io.py`: four reads/30 ms maximum delay only for `PermissionError`
  on diagnostic snapshots. Never apply it to jobs, results or lease records.

One process-wide queue serializes jobs, not whole workflows or documents. Keep
claimed-timeout uncertainty distinct from proven unclaimed removal. Never replay
a mutation, use global input, take focus or dismiss application dialogs.
Local discovery may work without Vectorworks; native results require the host.

MCP stdio/HTTP is separate from Vectorworks file IPC. Pass HTTP host/port to
`mcp.run`, not the FastMCP constructor. Cache only the allowlist; use TTL zero
for verification. Task extensions are opt-in and do not make native work concurrent.
Do not publish tokens or credentials in logs or reports.

## Checks from repository root

```text
python -m unittest discover -s tests -p "test_server_2027.py" -v
python -m unittest discover -s tests -p "test_background_policy.py" -v
python -m unittest discover -s tests -p "test_bridge_maintenance.py" -v
python -m unittest discover -s tests -p "test_diagnostic_io.py" -v
python tools/pruefe_konsistenz.py .
```

After dependency/registration changes inspect real `tools/list` without host
calls: no `outputSchema`, correct tags/annotations and preserved discovery tools.
After changing source-hashed inputs, regenerate the matrix/coverage reports as
described in [TESTING_2027.md](../docs/TESTING_2027.md). Offline checks are not
native verification. See [BUILD_SETUP.md](../docs/BUILD_SETUP.md) for installation.

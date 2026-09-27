# Python host bridge context

Read [root guidance](../AGENTS.md) and [the 2027 contract](../docs/VECTORWORKS_2027.md).
These files load inside Vectorworks' Python menu-command context.

| File | Responsibility |
|---|---|
| `BridgeStart_MenuCommand.py` | Host/install checks and one outer pump invocation |
| `vwx_pump.py` | Reentry guard, atomic claim/consume, one job, result and completion stamps |
| `commands.py` | Handwritten workflow verbs and UUID/native object helpers |
| `sdk_runtime.py` | Argument/handle/context/result validation and disclosed compatibility repairs |
| `sdk_sequences.py` | Up to 200 balanced same-job calls, references and scope cleanup |
| `sdk_catalog.json`, `sdk_generated.py` | Generated SDK bindings; regenerate, never hand-edit |
| `vs_index.json`, `vs_index_meta.json` | SDK reference and provenance; regenerate together |

Every `vs.*` call must stay on the authorized menu runner. Never add Python
threads, notification/timer execution, reentrant pumping or automatic retries.
Consume a claimed job before dispatch; only the outer invocation may stamp
completion. Creation/reset and regeneration-dependent inspection need separate
requests. Sequences have no rollback or regeneration break.

Resolve UUIDs and validate object types; type-zero lookup handles are invalid.
Collect iterator results before mutation, bound traversal and verify nested
parentage. Use replacement handles returned by conversion/import/booleans.
Preserve exact tuple/in-out SDK conventions and use catalog names, not guessed
selectors. Expected values must come from documented contracts or independent
measurements, not from the implementation being tested.

Preserve compatibility metadata, original values, exact-build guards and
pre/post-write dispatch state. A compatibility success never becomes a native
pass. Do not call the broken gradient-opacity binding before its replacement,
retry native `UprString`, or weaken the private arc/maintenance ABI checks.
Maintenance save/quit rechecks the sole expected saved drawing and owner lease;
no discard, force-kill or dialog dismissal fallback is permitted.

## Checks from repository root

```text
python -m unittest discover -s tests -p "test_menu_runner.py" -v
python -m unittest discover -s tests -p "test_command_contracts_2027.py" -v
python -m unittest discover -s tests -p "test_sdk_runtime.py" -v
python -m unittest discover -s tests -p "test_sdk_sequences.py" -v
python -m unittest discover -s tests -p "test_sdk_*repair*.py" -v
python tools/pruefe_vs_aufrufe.py vwx-plugin/vs_index.json vwx-plugin/commands.py vwx-plugin/BridgeStart_MenuCommand.py
```

Check a script's `--help` before supplying alternate roots/SDK paths. Follow
[BUILD_SETUP.md](../docs/BUILD_SETUP.md) for deployment and
[TESTING_2027.md](../docs/TESTING_2027.md) for independent typed native fixtures.
Changing generated-contract inputs requires wrapper/index and report freshness
checks; never rewrite empirical evidence merely to match new source.

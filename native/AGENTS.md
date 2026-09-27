# Native bridge context

Read [root guidance](../AGENTS.md), [the 2027 contract](../docs/VECTORWORKS_2027.md),
and [build setup](../docs/BUILD_SETUP.md). Build only `VwxBridge2027.vcxproj` via
`tools/build_2027.py`: SDK 3200/build 882699, x64 MSVC v143 14.42, C++20 and
native `wchar_t`. Keep compile-time SDK and callback argument-tag assertions.

`Source/Bridge/VwxBridgePalette.cpp` owns the private UI-thread SDK menu broker,
timer/palette lifecycle, heartbeat and scheduler telemetry. The timer posts a
one-use event; the broker calls the fixed `VWX Bridge Start` menu selector.
Never execute Python from timers, notifications or web callbacks. Never add
global input, key injection, focus changes or dialog dismissal.

`PumpScheduleState.h` holds scheduling/acknowledgment policy. Permit at most one
outstanding trigger; acknowledge only changed outer completion after the
synchronous menu call returns. Preserve an unknown completion fence during
close/reopen, invalidate canceled queued tokens, and never repost uncertain work.
`AtomicStatusFile.h` closes full temporary content before atomic replacement;
failed publication must preserve the previous complete destination.

`BridgeVSFunctions.cpp` implements private arc and maintenance callbacks.
`ArcAnglesPolicy.h` and `MaintenancePolicy.h` validate SDK types and inputs.
These callbacks run in the existing menu invocation; do not start another
runner. Arc repair preserves object identity. Maintenance saves and rechecks
the sole expected saved ordinary drawing before normal quit; it never discards
changes, bypasses a prompt or force-kills the process. Private bridge functions
are not additions to the official Python SDK API inventory.

`VwxBridge.vwr/html` and `Strings` contain the English palette resources. Keep
the public Python menu name `VWX Bridge Start` exact. UI status callbacks do not
execute the pump. Resources and binary must be deployed together only after
Vectorworks closes; never commit generated binaries or SDK material.

## Checks from repository root

```text
python tools/build_2027.py --sdk "C:\path\to\SDKVW(882699)"
python -m unittest discover -s tests -p "test_native_*.py" -v
```

The Windows C++ harnesses compile production policy/callback code against
independent models and real file-sharing tests. A skip for missing MSVC is not
native verification. Build and offline success need separate source-pinned
host results; see [NATIVE_REPAIRS_2027.md](../docs/NATIVE_REPAIRS_2027.md).

# Test suite context

Read [root guidance](../AGENTS.md) and [TESTING_2027.md](../docs/TESTING_2027.md).
Unittest discovery is offline. It must not launch, quit, control or call an
installed Vectorworks process. Live checks belong to explicitly executed typed
runners under `tools`, with a disposable drawing and fresh journal directory.

Tests cover SDK generation/contracts, command wrappers, menu scheduling,
maintenance races, fixture/oracle models, evidence import and report freshness.
`native_*.cpp` harnesses test production C++ policies and callbacks independently;
the Windows status-file harness exercises real temporary-file concurrency.
They need the configured MSVC toolchain and may skip elsewhere; report skips.

Use independent expected geometry/data. Include no-op setters, wrong-object or
aliased copies, incorrect index shifts and later preservation readbacks where
relevant. Do not mirror production logic as an oracle or change a valid expected
value solely to match a host failure. Preserve exact response identity/count,
finite-number validation, expected declarations and dispatch provenance.
Partial/uncertain sequences must never credit unexecuted calls. Compatibility
and characterization observations are separate from native semantic passes.

## Run from repository root

```text
python -m pip install -r mcp-server/requirements.txt
python -m unittest discover -s tests -v
python tools/pruefe_konsistenz.py .
python tools/sdk_test_matrix.py --check
python tools/api_coverage.py --check
```

Use `-p "test_<area>.py"` for focused discovery. Do not weaken assertions when
temporary-directory ACL restrictions block filesystem tests: diagnose the
environment, run the same suite with authorized normal temporary-file access,
and retain both outcomes. Avoid modifying source-hashed fixture files during
registry tests or live runs. Generated reports need regeneration after their
source inputs change; empirical records never need rewriting to make tests pass.

The 793-test/57-family checkpoint is evidence for its recorded revision, not a
permanent expected test count. Consult current logs and generated reports after
changes. A local pass does not assert that hosted CI or every native API passed.

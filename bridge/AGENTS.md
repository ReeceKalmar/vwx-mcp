# Installation and launcher context

Read [root guidance](../AGENTS.md) and [build/setup](../docs/BUILD_SETUP.md).

- `deploy_2027.ps1` installs exactly the 2027 Release binary/resources and nine
  Python/data files into the user plug-in folder. It requires a closed host,
  complete sources, SDK 3200 metadata and paths without reparse points. Keep
  preflight before mutations, unique backups, queue quarantine and hash checks.
- `deploy_native_bridge.bat` forwards to that installer with a child-process
  RemoteSigned policy. It is not an older native target.
- `vwx-mcp.bat` runs the optional **localhost** HTTP server using the repository
  `.venv`; it does not launch Vectorworks or install the native bridge. It pins
  year 2027, file IPC, background mode and disabled cache. Preserve localhost
  binding unless the user explicitly configures another deployment.

Initial installation and later maintenance are different workflows. Automatic
save/quit/deploy/reopen belongs to `tools/restart_vectorworks.py` and its
persistent lease protocol. Do not bolt force-kill, prompt dismissal or unknown
queue replay into these launchers. Vectorworks security approval remains a
user action; the credentials example is not an issued credential.

Validate installer changes with `test_deploy_2027.py` and build preflight with
`test_build_2027.py`. These use temporary fake installations; a passing installer
test is not authorization to modify an active Vectorworks installation.

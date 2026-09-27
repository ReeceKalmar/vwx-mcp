# Vectorworks 2027 plug-in developer credentials

The local native build of this fork does not have Vectorworks-issued developer
credentials. Vectorworks may identify or block `VwxBridge` as an unknown
developer at startup. The user must review that application prompt; do not
disable plug-in security checks.

The 2027 deployment places `VwxBridge.vlb` and `VwxBridge.vwr` in:

```text
%APPDATA%\Nemetschek\Vectorworks\2027\Plug-ins
```

A successful compiler build or acceptance of a developer prompt does not verify
that the bridge loads, the menu runner executes, or native-object workflows work.
Those require the separate checks in [VECTORWORKS_2027.md](VECTORWORKS_2027.md).

## Requesting credentials

`native/CredentialsVwxMcp.example.json` is a request template, not an issued
credential. Replace its placeholders with this fork's actual developer
information in a private request copy before any submission. Do not reuse
credentials issued to another developer.

Ask Vectorworks developer support for the current **2027** credential request
process and the required output filename, placement and version coverage.
Follow the instructions supplied with the issued credential. The historical
upstream notes referred to a `Credentials*.vst` file beside the native plug-in;
do not assume an older host's issued file covers this fork or this host version.

`bridge/deploy_2027.ps1` deploys the native binary/resources and Python bridge
files. It does not automatically request, issue or install a credentials file.
Keep developer credential files and personal submission details out of Git.

The 2027 palette supplies scheduling, heartbeat and status UI. Automatic error
dialog dismissal was removed; credentials do not change that behavior.

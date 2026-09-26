"""Build the Windows bridge against the official 2027 SDK, without deploying it."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', default=os.environ.get('VWSDK2027'))
    args = parser.parse_args()
    if not args.sdk:
        parser.error('Set VWSDK2027 or supply --sdk (folder containing SDKLib)')
    sdk = Path(args.sdk).resolve()
    header = (sdk / 'SDKLib/Include/VectorworksSDK.h').read_text()
    if not re.search(r'^#define\s+SDK_VERSION\b[^\n]*\b3200\b', header, re.M):
        parser.error('SDK_VERSION must be 3200 (Vectorworks 2027)')
    for relative in ('SDKLib/LibWin/Release/VWSDK.lib', 'SDKLib/Include/vs.py'):
        if not (sdk / relative).is_file():
            parser.error('Incomplete SDK: missing ' + relative)
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    instances = json.loads(subprocess.check_output([
        str(vswhere), '-all', '-products', '*', '-format', 'json'], text=True))
    for instance in sorted(instances, key=lambda i: i['installationVersion'], reverse=True):
        vs = Path(instance['installationPath'])
        targets = vs / 'MSBuild/Microsoft/VC/v170'
        compiler = vs / 'VC/Tools/MSVC/14.42.34433/bin/Hostx64/x64/cl.exe'
        if compiler.exists() and (targets / 'Platforms/x64/PlatformToolsets/v143').exists():
            break
    else:
        parser.error('Install MSVC v143 14.42 (VS2022 17.12) C++ x64 build tools')
    root = Path(__file__).resolve().parents[1]
    # Windows can inherit both Path and PATH from a launcher. MSBuild rejects
    # that ambiguous environment; normalize keys for this child process only.
    env = {k.upper(): v for k, v in os.environ.items()}
    command = [str(vs / 'MSBuild/Current/Bin/MSBuild.exe'),
               str(root / 'native/VwxBridge2027.vcxproj'), '/t:Rebuild',
               '/p:Configuration=Release', '/p:Platform=x64',
               '/p:VWSDK2027=' + str(sdk),
               '/p:VCTargetsPath=' + str(targets) + '\\', '/v:minimal', '/nologo']
    return subprocess.call(command, cwd=root, env=env)


if __name__ == '__main__':
    sys.exit(main())

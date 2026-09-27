"""Build the Windows bridge against the official 2027 SDK, without deploying it."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


TOOLSET_VERSION = '14.42.34433'
SDK_FILES = (
    'SDKLib/Include/VectorworksSDK.h',
    'SDKLib/Include/vs.py',
    'SDKLib/Include/OnlyWin/NNA_PluginBuild_RELEASE.props',
    'SDKLib/LibWin/Release/VWSDK.lib',
    'SDKLib/ToolsWin/BuildVWR/buildvwr.exe',
    'SDKLib/ToolsWin/BuildVWR/7z.exe',
    'SDKLib/ToolsWin/BuildVWR/7z.dll',
)


def validate_sdk(path):
    sdk = Path(path).expanduser().resolve()
    for relative in SDK_FILES:
        if not (sdk / relative).is_file():
            raise ValueError('Incomplete SDK: missing ' + str(sdk / relative))
    header = (sdk / SDK_FILES[0]).read_text(encoding='utf-8-sig')
    header = re.sub(r'/\*.*?\*/|//[^\n]*', '', header, flags=re.S)
    versions = re.findall(r'^\s*#\s*define\s+SDK_VERSION\s+(\d+)\s*$', header, re.M)
    if versions != ['3200']:
        raise ValueError('SDK_VERSION must be 3200 (Vectorworks 2027)')
    return sdk


def discover_toolchain(environment):
    program_files = environment.get('ProgramFiles(x86)')
    if not program_files:
        raise ValueError('Windows ProgramFiles(x86) is missing; install Visual Studio C++ build tools')
    vswhere = Path(program_files) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if not vswhere.is_file():
        raise ValueError('Visual Studio Installer/vswhere.exe is missing; install Visual Studio C++ build tools')
    try:
        instances = json.loads(subprocess.check_output([
            str(vswhere), '-all', '-products', '*', '-format', 'json'], text=True))
        if type(instances) is not list:
            raise ValueError('Expected a list of Visual Studio installations')
        candidates = [(tuple(int(part) for part in item['installationVersion'].split('.')),
                       Path(item['installationPath'])) for item in instances]
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Unable to discover Visual Studio installations: ' + str(exc)) from exc
    for _, vs in sorted(candidates, key=lambda candidate: candidate[0], reverse=True):
        targets = vs / 'MSBuild/Microsoft/VC/v170'
        compiler = vs / ('VC/Tools/MSVC/' + TOOLSET_VERSION + '/bin/Hostx64/x64/cl.exe')
        msbuild = vs / 'MSBuild/Current/Bin/MSBuild.exe'
        if (compiler.is_file() and msbuild.is_file()
                and (targets / 'Microsoft.Cpp.Default.props').is_file()
                and (targets / 'Microsoft.Cpp.targets').is_file()
                and (targets / 'Platforms/x64/PlatformToolsets/v143').is_dir()):
            return msbuild, targets
    raise ValueError('Install MSVC v143 ' + TOOLSET_VERSION
                     + ' (VS2022 17.12) C++ x64 build tools and a Windows 10/11 SDK')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', default=os.environ.get('VWSDK2027'))
    args = parser.parse_args(argv)
    if sys.platform != 'win32':
        parser.error('This native build requires Windows; offline Python tests can run on other platforms')
    if not args.sdk:
        parser.error('Set VWSDK2027 or supply --sdk (folder containing SDKLib)')
    try:
        sdk = validate_sdk(args.sdk)
        msbuild, targets = discover_toolchain(os.environ)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    root = Path(__file__).resolve().parents[1]
    # Windows can inherit both Path and PATH from a launcher. MSBuild rejects
    # that ambiguous environment; normalize keys for this child process only.
    env = {k.upper(): v for k, v in os.environ.items()}
    command = [str(msbuild),
               str(root / 'native/VwxBridge2027.vcxproj'), '/t:Rebuild',
               '/p:Configuration=Release', '/p:Platform=x64',
               '/p:VWSDK2027=' + str(sdk),
               '/p:VCTargetsPath=' + str(targets) + '\\', '/v:minimal', '/nologo']
    return subprocess.call(command, cwd=root, env=env)


if __name__ == '__main__':
    sys.exit(main())
